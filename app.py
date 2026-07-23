
import io
import re
import hmac
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="PDP Control Center",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_SHEET = "https://docs.google.com/spreadsheets/d/1a2fKpBWiJjW0BGeLPuPlb1cmPIzo_q0b/edit?gid=27782394#gid=27782394"

# ----------------------- AUTENTICACIÓN -----------------------
def check_password():
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <style>
      .login-box {
        max-width:430px; margin:70px auto 0 auto; padding:30px;
        background:#ffffff; border-radius:16px;
        box-shadow:0 8px 30px rgba(0,0,0,.12);
        border-top:7px solid #f5b700;
      }
      .login-title {text-align:center;color:#082d55;font-size:30px;font-weight:800;}
      .login-sub {text-align:center;color:#667085;margin-bottom:20px;}
    </style>
    <div class="login-box">
      <div class="login-title">PDP CONTROL CENTER</div>
      <div class="login-sub">Control y seguimiento de órdenes de trabajo</div>
    </div>
    """, unsafe_allow_html=True)

    try:
        valid_user = st.secrets["auth"]["username"]
        valid_password = st.secrets["auth"]["password"]
    except Exception:
        valid_user = "admin"
        valid_password = "Mainin2026"

    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        with st.form("login"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            login = st.form_submit_button("INGRESAR", type="primary", use_container_width=True)
        if login:
            if hmac.compare_digest(username, valid_user) and hmac.compare_digest(password, valid_password):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")
    return False

if not check_password():
    st.stop()

# ----------------------- DATOS -----------------------
def sheet_export_url(url):
    sid = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not sid:
        raise ValueError("El enlace de Google Sheets no es válido.")
    gid = re.search(r"(?:gid=)(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{sid.group(1)}/export?format=csv&gid={(gid.group(1) if gid else '0')}"

def norm_text(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def norm_col(v):
    v = norm_text(v).upper()
    replacements = {"Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U","Ñ":"N"}
    for a,b in replacements.items():
        v = v.replace(a,b)
    v = re.sub(r"\s+", " ", v)
    aliases = {
        "DESCRIPCION ORDEN DE TRABAJO":"DESCRIPCION_OT",
        "DESCRIPCION OPERACIONES":"DESCRIPCION_OPERACIONES",
        "% AVANCE REAL":"AVANCE_REAL",
        "AVANCE REAL":"AVANCE_REAL",
        "AVANCE PLAN":"AVANCE_PLAN",
        "DUR (HR)":"DURACION_H",
        "DUR (Hr)":"DURACION_H",
        "CANT":"CANT_PERSONAS",
        "CANT PERS":"CANT_PERSONAS",
    }
    return aliases.get(v, v.replace(" ","_"))

def pct(v):
    if pd.isna(v) or v == "":
        return 0.0
    if isinstance(v, (int,float)):
        return float(v)*100 if 0 <= float(v) <= 1 else float(v)
    s = str(v).strip().replace("%","").replace(",",".")
    try:
        x = float(s)
        return x*100 if 0 <= x <= 1 else x
    except:
        return 0.0

@st.cache_data(ttl=60)
def load_sheet(url):
    raw = pd.read_csv(sheet_export_url(url), header=None, dtype=str)
    header = None
    for i in range(min(35, len(raw))):
        vals = [norm_col(x) for x in raw.iloc[i].tolist()]
        if "OT" in vals and ("EQUIPO" in vals or "GRUPO" in vals):
            header = i
            break
    if header is None:
        raise ValueError("No se encontró la fila de encabezados con la columna OT.")

    cols, used = [], {}
    for j,x in enumerate(raw.iloc[header].tolist()):
        name = norm_col(x) or f"COLUMNA_{j+1}"
        used[name] = used.get(name,0)+1
        if used[name] > 1:
            name = f"{name}_{used[name]}"
        cols.append(name)

    df = raw.iloc[header+1:].copy()
    df.columns = cols
    df = df.dropna(how="all")

    if "OT" not in df.columns:
        raise ValueError("La hoja no contiene una columna OT.")
    df["OT"] = df["OT"].map(norm_text)
    df = df[df["OT"].str.match(r"^\d+", na=False)].copy()

    text_cols = ["GRUPO","EQUIPO","DESCRIPCION_OT","DESCRIPCION_OPERACIONES","SUPERVISOR","OBSERVACIONES"]
    for c in text_cols:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].map(norm_text)

    for c in list(df.columns):
        if "AVANCE" in c or "CUMPLIMIENTO" in c:
            df[c] = df[c].map(pct).clip(0,100)

    if "AVANCE_REAL" not in df.columns:
        candidates = [c for c in df.columns if "AVANCE" in c]
        df["AVANCE_REAL"] = df[candidates[0]] if candidates else 0
    if "AVANCE_PLAN" not in df.columns:
        df["AVANCE_PLAN"] = 100
    if "CUMPLIMIENTO" not in df.columns:
        df["CUMPLIMIENTO"] = df["AVANCE_REAL"]

    for c in ["DURACION_H","CANT_PERSONAS","HH"]:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",","."), errors="coerce").fillna(0)

    def estado(x):
        if x >= 100: return "CULMINADO"
        if x <= 0: return "NO EJECUTADO"
        return "CUMPLIMIENTO PARCIAL"
    df["ESTADO"] = df["CUMPLIMIENTO"].map(estado)
    return df.reset_index(drop=True)

# ----------------------- ESTILO -----------------------
st.markdown("""
<style>
[data-testid="stSidebar"] {background:#07294d;}
[data-testid="stSidebar"] * {color:white;}
[data-testid="stMetric"] {
  background:white;border:1px solid #e5e7eb;padding:14px;border-radius:12px;
  box-shadow:0 2px 10px rgba(0,0,0,.05);
}
.block-container {padding-top:1.2rem;}
h1,h2,h3 {color:#082d55;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## MAININ")
    st.caption("Maintenance Ingenuity")
    st.markdown("---")
    menu = st.radio("Menú", ["Dashboard","Detalle de OTs","Exportar reporte"])
    st.markdown("---")
    st.write(f"Usuario: **{st.session_state.get('username','admin')}**")
    if st.button("Cerrar sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.markdown("### Fuente de datos")
    sheet_url = st.text_area("Google Sheets", DEFAULT_SHEET, height=115)
    if st.button("Actualizar datos", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

try:
    df = load_sheet(sheet_url)
except Exception as e:
    st.error(f"No fue posible leer Google Sheets: {e}")
    st.info("Verifique que el documento tenga acceso 'Cualquier persona con el enlace – Lector'.")
    st.stop()

with st.sidebar:
    st.markdown("### Filtros")
    ots = sorted(df["OT"].unique().tolist())
    supervisors = sorted([x for x in df["SUPERVISOR"].unique() if x])
    groups = sorted([x for x in df["GRUPO"].unique() if x])
    sel_ot = st.multiselect("OT", ots)
    sel_sup = st.multiselect("Supervisor", supervisors)
    sel_group = st.multiselect("Grupo", groups)
    sel_state = st.multiselect("Estado", ["CULMINADO","CUMPLIMIENTO PARCIAL","NO EJECUTADO"])
    search = st.text_input("Buscar equipo o descripción")

filtered = df.copy()
if sel_ot: filtered = filtered[filtered["OT"].isin(sel_ot)]
if sel_sup: filtered = filtered[filtered["SUPERVISOR"].isin(sel_sup)]
if sel_group: filtered = filtered[filtered["GRUPO"].isin(sel_group)]
if sel_state: filtered = filtered[filtered["ESTADO"].isin(sel_state)]
if search:
    s = search.lower()
    mask = (
        filtered["EQUIPO"].str.lower().str.contains(s,na=False) |
        filtered["DESCRIPCION_OT"].str.lower().str.contains(s,na=False) |
        filtered["DESCRIPCION_OPERACIONES"].str.lower().str.contains(s,na=False)
    )
    filtered = filtered[mask]

st.title("APLICATIVO DE CONTROL Y SEGUIMIENTO DE OTs")
st.caption(f"Datos sincronizados con Google Sheets · Actualización: {datetime.now():%d/%m/%Y %H:%M}")

if filtered.empty:
    st.warning("No hay registros con los filtros seleccionados.")
    st.stop()

total = filtered["OT"].nunique()
avance = filtered["AVANCE_REAL"].mean()
cumpl = filtered["CUMPLIMIENTO"].mean()
culm = filtered.loc[filtered["ESTADO"]=="CULMINADO","OT"].nunique()
parc = filtered.loc[filtered["ESTADO"]=="CUMPLIMIENTO PARCIAL","OT"].nunique()
noej = filtered.loc[filtered["ESTADO"]=="NO EJECUTADO","OT"].nunique()

if menu == "Dashboard":
    a,b,c,d,e,f = st.columns(6)
    a.metric("OTs", total)
    b.metric("Avance real", f"{avance:.0f}%")
    c.metric("Cumplimiento", f"{cumpl:.0f}%")
    d.metric("Culminadas", culm)
    e.metric("Parciales", parc)
    f.metric("No ejecutadas", noej)

    left,right = st.columns([1.25,1])
    with left:
        sup = filtered.groupby("SUPERVISOR",as_index=False).agg(
            PLAN=("AVANCE_PLAN","mean"), REAL=("AVANCE_REAL","mean")
        ).sort_values("REAL")
        fig = go.Figure()
        fig.add_bar(y=sup["SUPERVISOR"],x=sup["PLAN"],name="PLAN",orientation="h",
                    text=sup["PLAN"].round().astype(int).astype(str)+"%")
        fig.add_bar(y=sup["SUPERVISOR"],x=sup["REAL"],name="REAL",orientation="h",
                    text=sup["REAL"].round().astype(int).astype(str)+"%")
        fig.update_layout(title="Plan vs. real por supervisor",barmode="group",
                          xaxis_range=[0,105],height=430,legend_orientation="h")
        st.plotly_chart(fig,use_container_width=True)
    with right:
        state = filtered.groupby("ESTADO")["OT"].nunique().reset_index(name="OTs")
        fig2 = px.bar(state,x="ESTADO",y="OTs",text_auto=True,title="Cumplimiento de OTs")
        fig2.update_layout(height=430,showlegend=False)
        st.plotly_chart(fig2,use_container_width=True)

    left,right = st.columns([.7,1.3])
    with left:
        donut = go.Figure(go.Pie(labels=["Cumplimiento","Pendiente"],
                                 values=[cumpl,max(100-cumpl,0)],hole=.64,textinfo="value"))
        donut.update_layout(title="Avance general",height=380,
                            annotations=[dict(text=f"<b>{cumpl:.0f}%</b>",x=.5,y=.5,
                                              showarrow=False,font_size=28)])
        st.plotly_chart(donut,use_container_width=True)
    with right:
        grp = filtered.groupby("GRUPO",as_index=False).agg(
            AVANCE_REAL=("AVANCE_REAL","mean"), OTs=("OT","nunique"), HH=("HH","sum")
        )
        fig3 = px.bar(grp,x="GRUPO",y="AVANCE_REAL",text_auto=".0f",
                      hover_data=["OTs","HH"],title="Avance real por grupo")
        fig3.update_layout(yaxis_range=[0,105],height=380)
        st.plotly_chart(fig3,use_container_width=True)

if menu in ["Dashboard","Detalle de OTs"]:
    st.subheader("Detalle de órdenes de trabajo")
    cols = ["OT","GRUPO","EQUIPO","DESCRIPCION_OT","DESCRIPCION_OPERACIONES",
            "SUPERVISOR","AVANCE_REAL","CUMPLIMIENTO","ESTADO",
            "OBSERVACIONES","DURACION_H","CANT_PERSONAS","HH"]
    st.dataframe(filtered[cols],use_container_width=True,hide_index=True,
        column_config={
            "AVANCE_REAL":st.column_config.ProgressColumn("Avance real", min_value=0, max_value=100, format="%.0f%%"),
            "CUMPLIMIENTO":st.column_config.ProgressColumn("Cumplimiento", min_value=0, max_value=100, format="%.0f%%"),
        })

if menu == "Exportar reporte":
    st.subheader("Exportación")
    output = io.BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        filtered.to_excel(writer,index=False,sheet_name="Reporte_OTs")
    st.download_button("Descargar reporte filtrado en Excel",output.getvalue(),
                       "reporte_ots_filtrado.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
