
import io
import hmac
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import Client, create_client

st.set_page_config(
    page_title="PDP Control Center",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BUCKET = "evidencias-ots"
MASTER_FILE = Path(__file__).with_name("maestro_ots_quellaveco.csv")

st.markdown("""
<style>
[data-testid="stSidebar"] {background:#082d55;}
[data-testid="stSidebar"] * {color:white;}
[data-testid="stMetric"] {
    background:#ffffff;border:1px solid #e5e7eb;padding:14px;
    border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,.05);
}
.block-container {padding-top:1.1rem;}
h1,h2,h3 {color:#082d55;}
.ot-card {
    background:#f8fafc;border:1px solid #dbe3ec;border-radius:12px;
    padding:16px;margin:8px 0 18px 0;
}
.label {font-size:12px;color:#667085;font-weight:700;text-transform:uppercase;}
.value {font-size:15px;color:#101828;margin-bottom:12px;}
</style>
""", unsafe_allow_html=True)


def authenticate() -> bool:
    if st.session_state.get("authenticated"):
        return True
    user_ok = st.secrets.get("auth", {}).get("username", "Jose")
    pass_ok = st.secrets.get("auth", {}).get("password", "Mainin2026")

    st.markdown("""
    <div style="max-width:540px;margin:70px auto 12px auto;padding:42px 35px;
    background:#fff;border-radius:18px;border-top:8px solid #f5b700;
    box-shadow:0 10px 35px rgba(0,0,0,.10);text-align:center;">
      <div style="font-size:34px;font-weight:800;color:#082d55;">PDP CONTROL CENTER</div>
      <div style="font-size:18px;color:#667085;margin-top:8px;">
        Control y seguimiento de órdenes de trabajo
      </div>
    </div>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        with st.form("login"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("INGRESAR", type="primary", use_container_width=True)
        if submit:
            if hmac.compare_digest(username, user_ok) and hmac.compare_digest(password, pass_ok):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")
    return False


if not authenticate():
    st.stop()


@st.cache_resource
def get_supabase() -> Client:
    try:
        return create_client(
            st.secrets["supabase"]["url"],
            st.secrets["supabase"]["key"],
        )
    except Exception:
        st.error("Falta configurar Supabase en los Secrets de Streamlit.")
        st.stop()


@st.cache_data
def load_master() -> pd.DataFrame:
    if not MASTER_FILE.exists():
        st.error("No se encontró maestro_ots_quellaveco.csv en el repositorio.")
        st.stop()
    df = pd.read_csv(MASTER_FILE, dtype={"OT": str})
    df["OT"] = df["OT"].astype(str).str.strip()
    return df


supabase = get_supabase()
master = load_master()


def upload_evidence(file, ot: str) -> str:
    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else "jpg"
    safe_ot = "".join(ch for ch in ot if ch.isalnum() or ch in "-_")
    filename = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:10]}.{ext}"
    path = f"{safe_ot}/{filename}"
    supabase.storage.from_(BUCKET).upload(
        path=path,
        file=file.getvalue(),
        file_options={"content-type": file.type or "image/jpeg", "upsert": "false"},
    )
    return supabase.storage.from_(BUCKET).get_public_url(path)


def save_record(record: dict) -> None:
    supabase.table("ot_avances").insert(record).execute()


@st.cache_data(ttl=20)
def load_records() -> pd.DataFrame:
    result = (
        supabase.table("ot_avances")
        .select("*")
        .order("fecha_registro", desc=True)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "avance" in df.columns:
        df["avance"] = pd.to_numeric(df["avance"], errors="coerce").fillna(0)
    if "fecha_registro" in df.columns:
        df["fecha_registro"] = pd.to_datetime(
            df["fecha_registro"], errors="coerce", utc=True
        ).dt.tz_convert("America/Lima")
    return df


with st.sidebar:
    st.markdown("## MAININ")
    st.caption("Maintenance Ingenuity")
    st.markdown("---")
    page = st.radio(
        "Menú",
        ["Dashboard ejecutivo", "Registrar avance", "Historial por OT",
         "Galería de evidencias", "Exportar reporte"],
    )
    st.markdown("---")
    st.write(f"Usuario: **{st.session_state.get('username', 'Jose')}**")
    if st.button("Cerrar sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()


st.title("APLICATIVO DE CONTROL Y SEGUIMIENTO DE OTs")
st.caption("La información técnica se completa automáticamente al seleccionar la OT.")


if page == "Registrar avance":
    st.subheader("Registrar avance")

    selected_ot = st.selectbox(
        "Escriba o seleccione el número de OT *",
        options=master["OT"].sort_values().tolist(),
        index=None,
        placeholder="Escriba el número de OT para buscar...",
    )

    if selected_ot:
        info = master.loc[master["OT"] == selected_ot].iloc[0]

        c1, c2, c3 = st.columns(3)
        c1.text_input("Equipo", value=str(info.get("EQUIPO", "")), disabled=True)
        c2.text_input("Grupo", value=str(info.get("GRUPO", "")), disabled=True)
        c3.text_input("Supervisor", value=str(info.get("SUPERVISOR", "")), disabled=True)

        c1, c2 = st.columns(2)
        c1.text_input(
            "Ubicación / descripción del equipo",
            value=str(info.get("UBICACION_EQUIPO", "")),
            disabled=True,
        )
        c2.text_input(
            "Especialidad",
            value=str(info.get("ESPECIALIDAD", "")),
            disabled=True,
        )

        st.text_area(
            "Descripción de la orden de trabajo",
            value=str(info.get("DESCRIPCION_OT", "")),
            disabled=True,
            height=90,
        )
        st.text_area(
            "Operaciones programadas",
            value=str(info.get("DESCRIPCION_OPERACIONES", "")),
            disabled=True,
            height=100,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.text_input("Inicio planificado", value=str(info.get("INICIO", "")), disabled=True)
        c2.text_input("Fin planificado", value=str(info.get("FIN", "")), disabled=True)
        c3.text_input(
            "Cantidad de personas",
            value=str(int(float(info.get("CANT_PERSONAS_MAX", 0) or 0))),
            disabled=True,
        )
        c4.text_input(
            "HH planificadas",
            value=f"{float(info.get('HH_TOTAL', 0) or 0):.0f}",
            disabled=True,
        )

        st.markdown("---")

        with st.form("registro_avance", clear_on_submit=True):
            avance = st.number_input(
                "Porcentaje de avance (%) *",
                min_value=0,
                max_value=100,
                value=0,
                step=5,
            )
            descripcion = st.text_area(
                "Descripción breve de la actividad realizada *",
                placeholder="Ejemplo: Se ejecutó la inspección, conexionado y pruebas preliminares.",
                height=110,
            )
            observaciones = st.text_area(
                "Observaciones de la OT",
                placeholder="Registre restricciones, pendientes, desviaciones o coordinaciones.",
                height=100,
            )
            evidencias = st.file_uploader(
                "Evidencias fotográficas",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help="Puede adjuntar hasta 10 fotografías.",
            )
            save = st.form_submit_button(
                "Guardar avance",
                type="primary",
                use_container_width=True,
            )

        if save:
            if not descripcion.strip():
                st.error("Debe ingresar una descripción breve de la actividad realizada.")
            elif len(evidencias or []) > 10:
                st.error("Puede adjuntar como máximo 10 fotografías.")
            else:
                try:
                    urls = [upload_evidence(photo, selected_ot) for photo in evidencias or []]
                    estado = (
                        "CULMINADO" if avance >= 100
                        else ("NO INICIADO" if avance <= 0 else "EN EJECUCIÓN")
                    )
                    save_record({
                        "ot": selected_ot,
                        "equipo": str(info.get("EQUIPO", "")),
                        "ubicacion_equipo": str(info.get("UBICACION_EQUIPO", "")),
                        "supervisor": str(info.get("SUPERVISOR", "")),
                        "especialidad": str(info.get("ESPECIALIDAD", "")),
                        "grupo": str(info.get("GRUPO", "")),
                        "descripcion_ot": str(info.get("DESCRIPCION_OT", "")),
                        "descripcion_operaciones": str(info.get("DESCRIPCION_OPERACIONES", "")),
                        "inicio_plan": str(info.get("INICIO", "")),
                        "fin_plan": str(info.get("FIN", "")),
                        "hh_plan": float(info.get("HH_TOTAL", 0) or 0),
                        "cant_personas": int(float(info.get("CANT_PERSONAS_MAX", 0) or 0)),
                        "avance": int(avance),
                        "estado": estado,
                        "descripcion": descripcion.strip(),
                        "observaciones": observaciones.strip(),
                        "evidencias": urls,
                        "usuario": st.session_state.get("username", "Jose"),
                        "fecha_registro": datetime.now(timezone.utc).isoformat(),
                    })
                    load_records.clear()
                    st.success(f"El avance de la OT {selected_ot} fue registrado correctamente.")
                except Exception as exc:
                    st.error(f"No fue posible guardar el registro: {exc}")
    else:
        st.info("Seleccione una OT para visualizar automáticamente toda su información.")


records = load_records()


if page == "Dashboard ejecutivo":
    if records.empty:
        st.info("Todavía no existen avances registrados.")
    else:
        latest = (
            records.sort_values("fecha_registro")
            .groupby("ot", as_index=False)
            .tail(1)
            .copy()
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("OTs registradas", latest["ot"].nunique())
        c2.metric("Avance promedio", f"{latest['avance'].mean():.0f}%")
        c3.metric("Culminadas", int((latest["avance"] >= 100).sum()))
        c4.metric("En ejecución", int(((latest["avance"] > 0) & (latest["avance"] < 100)).sum()))
        c5.metric("No iniciadas", int((latest["avance"] <= 0).sum()))

        left, right = st.columns([1.3, 1])
        with left:
            fig = px.bar(
                latest.sort_values("avance"),
                x="avance", y="ot", orientation="h", text="avance",
                color="especialidad", title="Último avance registrado por OT",
            )
            fig.update_traces(texttemplate="%{text}%")
            fig.update_layout(xaxis_range=[0,105], height=max(420, 34*len(latest)))
            st.plotly_chart(fig, use_container_width=True)
        with right:
            status = latest.groupby("estado").size().reset_index(name="OTs")
            fig2 = px.bar(status, x="estado", y="OTs", text_auto=True,
                          title="Estado de las OTs")
            fig2.update_layout(height=420, showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Últimas actualizaciones")
        cols = [c for c in [
            "fecha_registro","ot","equipo","supervisor","grupo",
            "avance","estado","descripcion","observaciones","usuario"
        ] if c in records.columns]
        st.dataframe(
            records[cols].sort_values("fecha_registro", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "fecha_registro": st.column_config.DatetimeColumn(
                    "Fecha y hora", format="DD/MM/YYYY HH:mm"
                ),
                "avance": st.column_config.ProgressColumn(
                    "Avance", min_value=0, max_value=100, format="%d%%"
                ),
            },
        )


if page == "Historial por OT":
    if records.empty:
        st.info("Todavía no existen avances registrados.")
    else:
        selected = st.selectbox(
            "Seleccione una OT",
            sorted(records["ot"].dropna().astype(str).unique().tolist()),
        )
        history = records[records["ot"].astype(str) == selected].sort_values("fecha_registro")
        fig = px.line(history, x="fecha_registro", y="avance",
                      markers=True, text="avance", title=f"Evolución OT {selected}")
        fig.update_traces(texttemplate="%{text}%", textposition="top center")
        fig.update_layout(yaxis_range=[0,105], height=420)
        st.plotly_chart(fig, use_container_width=True)

        for _, row in history.sort_values("fecha_registro", ascending=False).iterrows():
            st.markdown("---")
            date_text = row["fecha_registro"].strftime("%d/%m/%Y %H:%M")
            st.markdown(f"### {date_text} — {int(row['avance'])}%")
            st.write(f"**Actividad ejecutada:** {row.get('descripcion','')}")
            st.write(f"**Observaciones:** {row.get('observaciones','') or 'Sin observaciones'}")
            st.caption(f"Registrado por: {row.get('usuario','')}")
            urls = row.get("evidencias") or []
            if isinstance(urls, str):
                urls = [urls]
            if urls:
                image_cols = st.columns(min(3, len(urls)))
                for i, url in enumerate(urls):
                    image_cols[i % len(image_cols)].image(url, use_container_width=True)


if page == "Galería de evidencias":
    if records.empty:
        st.info("Todavía no existen evidencias.")
    else:
        evidence_rows = records[
            records["evidencias"].apply(lambda value: bool(value))
        ]
        if evidence_rows.empty:
            st.info("Todavía no existen evidencias fotográficas.")
        else:
            selected = st.selectbox(
                "Filtrar por OT",
                ["TODAS"] + sorted(evidence_rows["ot"].astype(str).unique().tolist()),
            )
            if selected != "TODAS":
                evidence_rows = evidence_rows[
                    evidence_rows["ot"].astype(str) == selected
                ]
            for _, row in evidence_rows.iterrows():
                st.markdown(f"### OT {row['ot']} — {int(row['avance'])}%")
                urls = row.get("evidencias") or []
                if isinstance(urls, str):
                    urls = [urls]
                cols = st.columns(min(3, len(urls)))
                for i, url in enumerate(urls):
                    cols[i % len(cols)].image(url, use_container_width=True)
                st.markdown("---")


if page == "Exportar reporte":
    if records.empty:
        st.info("No existen registros para exportar.")
    else:
        output_df = records.copy()
        if "evidencias" in output_df.columns:
            output_df["evidencias"] = output_df["evidencias"].apply(
                lambda value: "\n".join(value) if isinstance(value, list) else str(value or "")
            )
        if "fecha_registro" in output_df.columns:
            output_df["fecha_registro"] = output_df["fecha_registro"].dt.tz_localize(None)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            output_df.to_excel(writer, index=False, sheet_name="Avances_OT")
        st.download_button(
            "Descargar reporte en Excel",
            output.getvalue(),
            "reporte_avances_ots.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
