
import io
import hmac
import uuid
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from supabase import Client, create_client

st.set_page_config(
    page_title="PDP Control Center",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BUCKET = "evidencias-ots"

st.markdown("""
<style>
[data-testid="stSidebar"] {background:#082d55;}
[data-testid="stSidebar"] * {color:white;}
[data-testid="stMetric"] {
    background:#ffffff;
    border:1px solid #e5e7eb;
    padding:14px;
    border-radius:12px;
    box-shadow:0 2px 10px rgba(0,0,0,.05);
}
.block-container {padding-top:1.1rem;}
h1,h2,h3 {color:#082d55;}
div.stButton > button:first-child {
    border-radius:10px;
    font-weight:700;
}
</style>
""", unsafe_allow_html=True)


def authenticate() -> bool:
    if st.session_state.get("authenticated"):
        return True

    username_ok = st.secrets.get("auth", {}).get("username", "Jose")
    password_ok = st.secrets.get("auth", {}).get("password", "Mainin2026")

    st.markdown("""
    <div style="
        max-width:540px;margin:70px auto 12px auto;padding:42px 35px;
        background:#fff;border-radius:18px;border-top:8px solid #f5b700;
        box-shadow:0 10px 35px rgba(0,0,0,.10);text-align:center;">
        <div style="font-size:34px;font-weight:800;color:#082d55;">
            PDP CONTROL CENTER
        </div>
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
            submit = st.form_submit_button(
                "INGRESAR", type="primary", use_container_width=True
            )
        if submit:
            if (
                hmac.compare_digest(username, username_ok)
                and hmac.compare_digest(password, password_ok)
            ):
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
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
    except Exception:
        st.error("Falta configurar Supabase en los Secrets de Streamlit.")
        st.stop()
    return create_client(url, key)


supabase = get_supabase()


def upload_evidence(file, ot: str) -> str:
    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else "jpg"
    safe_ot = "".join(ch for ch in ot if ch.isalnum() or ch in "-_")
    filename = (
        f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_"
        f"{uuid.uuid4().hex[:10]}.{ext}"
    )
    path = f"{safe_ot}/{filename}"
    supabase.storage.from_(BUCKET).upload(
        path=path,
        file=file.getvalue(),
        file_options={
            "content-type": file.type or "image/jpeg",
            "upsert": "false",
        },
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
    columns = [
        "id", "ot", "equipo", "supervisor", "especialidad", "grupo",
        "avance", "estado", "descripcion", "observaciones",
        "evidencias", "usuario", "fecha_registro"
    ]
    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None

    df["avance"] = pd.to_numeric(df["avance"], errors="coerce").fillna(0)
    df["fecha_registro"] = pd.to_datetime(
        df["fecha_registro"], errors="coerce", utc=True
    ).dt.tz_convert("America/Lima")
    return df[columns]


with st.sidebar:
    st.markdown("## MAININ")
    st.caption("Maintenance Ingenuity")
    st.markdown("---")
    page = st.radio(
        "Menú",
        [
            "Dashboard ejecutivo",
            "Registrar avance",
            "Historial por OT",
            "Galería de evidencias",
            "Exportar reporte",
        ],
    )
    st.markdown("---")
    st.write(f"Usuario: **{st.session_state.get('username', 'Jose')}**")
    if st.button("Cerrar sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()


st.title("APLICATIVO DE CONTROL Y SEGUIMIENTO DE OTs")
st.caption("Registro en línea, trazabilidad por OT y evidencias fotográficas.")


if page == "Registrar avance":
    st.subheader("Registrar avance de una orden de trabajo")

    with st.form("registro_avance", clear_on_submit=True):
        c1, c2, c3 = st.columns([1.2, 1, 1])
        ot = c1.text_input("Número de OT *", placeholder="Ejemplo: 4016676669")
        equipo = c2.text_input("Equipo", placeholder="Ejemplo: 2630-ER-001")
        grupo = c3.text_input("Grupo", placeholder="Ejemplo: G1")

        c1, c2, c3 = st.columns([1, 1, 1])
        supervisor = c1.text_input("Supervisor")
        especialidad = c2.selectbox(
            "Especialidad",
            ["ELECTRICIDAD", "INSTRUMENTACIÓN", "MECÁNICA", "OTROS"],
        )
        avance = c3.number_input(
            "Porcentaje de avance (%) *",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
        )

        estado = st.selectbox(
            "Estado",
            ["NO INICIADO", "EN EJECUCIÓN", "CULMINADO"],
        )

        descripcion = st.text_area(
            "Descripción breve de lo avanzado *",
            placeholder="Describa las actividades ejecutadas.",
            height=120,
        )
        observaciones = st.text_area(
            "Observaciones de la OT",
            placeholder="Registre restricciones, pendientes o desviaciones.",
            height=110,
        )
        evidencias = st.file_uploader(
            "Evidencias fotográficas",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="Puede adjuntar hasta 10 fotografías por registro.",
        )

        save = st.form_submit_button(
            "Guardar avance",
            type="primary",
            use_container_width=True,
        )

    if save:
        ot_clean = ot.strip()
        if not ot_clean:
            st.error("Debe ingresar el número de OT.")
        elif not descripcion.strip():
            st.error("Debe ingresar una descripción de lo avanzado.")
        elif len(evidencias or []) > 10:
            st.error("Puede adjuntar como máximo 10 fotografías.")
        else:
            try:
                urls = [upload_evidence(photo, ot_clean) for photo in evidencias or []]
                save_record({
                    "ot": ot_clean,
                    "equipo": equipo.strip(),
                    "supervisor": supervisor.strip(),
                    "especialidad": especialidad,
                    "grupo": grupo.strip(),
                    "avance": int(avance),
                    "estado": estado,
                    "descripcion": descripcion.strip(),
                    "observaciones": observaciones.strip(),
                    "evidencias": urls,
                    "usuario": st.session_state.get("username", "Jose"),
                    "fecha_registro": datetime.now(timezone.utc).isoformat(),
                })
                load_records.clear()
                st.success(f"El avance de la OT {ot_clean} fue registrado correctamente.")
            except Exception as exc:
                st.error(f"No fue posible guardar el registro: {exc}")


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
        c4.metric("Parciales", int(((latest["avance"] > 0) & (latest["avance"] < 100)).sum()))
        c5.metric("No iniciadas", int((latest["avance"] <= 0).sum()))

        left, right = st.columns([1.35, 1])

        with left:
            fig_ot = px.bar(
                latest.sort_values("avance"),
                x="avance",
                y="ot",
                orientation="h",
                text="avance",
                color="especialidad",
                title="Último avance registrado por OT",
                labels={"avance": "Avance (%)", "ot": "OT"},
            )
            fig_ot.update_traces(texttemplate="%{text}%")
            fig_ot.update_layout(xaxis_range=[0, 105], height=max(420, 34 * len(latest)))
            st.plotly_chart(fig_ot, use_container_width=True)

        with right:
            state_df = latest.copy()
            state_df["estado_kpi"] = state_df["avance"].apply(
                lambda x: "CULMINADO" if x >= 100 else ("NO INICIADO" if x <= 0 else "EN EJECUCIÓN")
            )
            status = state_df.groupby("estado_kpi").size().reset_index(name="OTs")
            fig_status = px.bar(
                status,
                x="estado_kpi",
                y="OTs",
                text_auto=True,
                title="Estado de las OTs",
            )
            fig_status.update_layout(height=420, showlegend=False)
            st.plotly_chart(fig_status, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            by_specialty = latest.groupby("especialidad", as_index=False)["avance"].mean()
            fig_sp = px.bar(
                by_specialty, x="especialidad", y="avance",
                text_auto=".0f", title="Avance promedio por especialidad"
            )
            fig_sp.update_layout(yaxis_range=[0,105], height=380)
            st.plotly_chart(fig_sp, use_container_width=True)

        with c2:
            by_supervisor = (
                latest[latest["supervisor"].fillna("").str.strip() != ""]
                .groupby("supervisor", as_index=False)["avance"]
                .mean()
                .sort_values("avance")
            )
            fig_sup = px.bar(
                by_supervisor, x="avance", y="supervisor",
                orientation="h", text_auto=".0f",
                title="Avance promedio por supervisor"
            )
            fig_sup.update_layout(xaxis_range=[0,105], height=380)
            st.plotly_chart(fig_sup, use_container_width=True)

        st.subheader("Últimas actualizaciones")
        st.dataframe(
            records[
                [
                    "fecha_registro", "ot", "equipo", "supervisor",
                    "especialidad", "grupo", "avance", "estado",
                    "descripcion", "observaciones", "usuario"
                ]
            ].sort_values("fecha_registro", ascending=False),
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
        selected_ot = st.selectbox(
            "Seleccione una OT",
            sorted(records["ot"].dropna().unique().tolist()),
        )
        history = records[records["ot"] == selected_ot].sort_values("fecha_registro")

        st.subheader(f"Historial de la OT {selected_ot}")

        fig = px.line(
            history,
            x="fecha_registro",
            y="avance",
            markers=True,
            text="avance",
            title="Evolución del avance",
            labels={"fecha_registro": "Fecha", "avance": "Avance (%)"},
        )
        fig.update_traces(texttemplate="%{text}%", textposition="top center")
        fig.update_layout(yaxis_range=[0, 105], height=420)
        st.plotly_chart(fig, use_container_width=True)

        for _, row in history.sort_values("fecha_registro", ascending=False).iterrows():
            st.markdown("---")
            date_text = (
                row["fecha_registro"].strftime("%d/%m/%Y %H:%M")
                if pd.notna(row["fecha_registro"])
                else "Sin fecha"
            )
            st.markdown(f"### {date_text} — Avance: {int(row['avance'])}%")
            st.write(f"**Equipo:** {row['equipo'] or 'No registrado'}")
            st.write(f"**Supervisor:** {row['supervisor'] or 'No registrado'}")
            st.write(f"**Especialidad:** {row['especialidad'] or 'No registrada'}")
            st.write(f"**Descripción:** {row['descripcion']}")
            st.write(f"**Observaciones:** {row['observaciones'] or 'Sin observaciones'}")
            st.caption(f"Registrado por: {row['usuario']}")

            urls = row.get("evidencias") or []
            if isinstance(urls, str):
                urls = [urls]
            if urls:
                cols = st.columns(min(3, len(urls)))
                for i, url in enumerate(urls):
                    cols[i % len(cols)].image(url, use_container_width=True)


if page == "Galería de evidencias":
    if records.empty:
        st.info("Todavía no existen evidencias.")
    else:
        evidence_rows = records[records["evidencias"].apply(lambda x: bool(x))]
        if evidence_rows.empty:
            st.info("Todavía no existen evidencias fotográficas.")
        else:
            ot_filter = st.selectbox(
                "Filtrar por OT",
                ["TODAS"] + sorted(evidence_rows["ot"].unique().tolist())
            )
            if ot_filter != "TODAS":
                evidence_rows = evidence_rows[evidence_rows["ot"] == ot_filter]

            for _, row in evidence_rows.iterrows():
                urls = row["evidencias"] or []
                if isinstance(urls, str):
                    urls = [urls]
                if not urls:
                    continue
                st.markdown(f"### OT {row['ot']} — {int(row['avance'])}%")
                st.caption(
                    row["fecha_registro"].strftime("%d/%m/%Y %H:%M")
                    if pd.notna(row["fecha_registro"]) else ""
                )
                cols = st.columns(min(3, len(urls)))
                for i, url in enumerate(urls):
                    cols[i % len(cols)].image(url, use_container_width=True)
                st.markdown("---")


if page == "Exportar reporte":
    if records.empty:
        st.info("No existen registros para exportar.")
    else:
        output_df = records.copy()
        output_df["evidencias"] = output_df["evidencias"].apply(
            lambda v: "\n".join(v) if isinstance(v, list) else str(v or "")
        )
        output_df["fecha_registro"] = output_df["fecha_registro"].dt.tz_localize(None)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            output_df.to_excel(writer, index=False, sheet_name="Avances_OT")

        st.download_button(
            "Descargar reporte en Excel",
            data=output.getvalue(),
            file_name="reporte_avances_ots.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
