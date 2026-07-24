
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
    background:#fff;border:1px solid #e5e7eb;padding:14px;
    border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,.05);
}
.block-container {padding-top:1.15rem;}
h1,h2,h3 {color:#082d55;}
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
        Gestión de OTs, actividades y avances
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


supabase = get_supabase()


@st.cache_data(ttl=20)
def read_table(name: str) -> pd.DataFrame:
    result = supabase.table(name).select("*").execute()
    rows = result.data or []
    return pd.DataFrame(rows)


def upload_evidence(file, ot: str, activity_id: str) -> str:
    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else "jpg"
    safe_ot = "".join(ch for ch in ot if ch.isalnum() or ch in "-_")
    filename = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:10]}.{ext}"
    path = f"{safe_ot}/{activity_id}/{filename}"
    supabase.storage.from_(BUCKET).upload(
        path=path,
        file=file.getvalue(),
        file_options={"content-type": file.type or "image/jpeg", "upsert": "false"},
    )
    return supabase.storage.from_(BUCKET).get_public_url(path)


def invalidate():
    read_table.clear()


def load_model():
    ots = read_table("ots")
    activities = read_table("actividades")
    progress = read_table("avances_actividad")

    if not ots.empty and "ot" in ots.columns:
        ots["ot"] = ots["ot"].astype(str)
    if not activities.empty and "codigo_actividad" in activities.columns:
        activities["codigo_actividad"] = activities["codigo_actividad"].astype(str)

    if not progress.empty and "fecha_registro" in progress.columns:
        progress["fecha_registro"] = pd.to_datetime(
            progress["fecha_registro"], errors="coerce", utc=True
        ).dt.tz_convert("America/Lima")

    return ots, activities, progress


def latest_progress(progress: pd.DataFrame) -> pd.DataFrame:
    if progress.empty:
        return pd.DataFrame(columns=["actividad_id", "avance"])
    return (
        progress.sort_values("fecha_registro")
        .groupby("actividad_id", as_index=False)
        .tail(1)
    )


def build_activity_status(activities: pd.DataFrame, progress: pd.DataFrame) -> pd.DataFrame:
    if activities.empty:
        return activities.copy()

    latest = latest_progress(progress)
    if latest.empty:
        result = activities.copy()
        result["avance_real"] = 0.0
    else:
        result = activities.merge(
            latest[["actividad_id", "avance", "descripcion_avance", "observaciones", "fecha_registro"]],
            left_on="id",
            right_on="actividad_id",
            how="left",
        )
        result["avance_real"] = pd.to_numeric(result["avance"], errors="coerce").fillna(0)

    result["peso"] = pd.to_numeric(result.get("peso", 1), errors="coerce").fillna(1)
    return result


def weighted_progress(activity_status: pd.DataFrame) -> float:
    if activity_status.empty:
        return 0.0
    denominator = activity_status["peso"].sum()
    if denominator <= 0:
        return float(activity_status["avance_real"].mean())
    return float(
        (activity_status["avance_real"] * activity_status["peso"]).sum() / denominator
    )


def build_s_curve(activities: pd.DataFrame, progress: pd.DataFrame) -> pd.DataFrame:
    """Construye Curva S planificada y real ponderada por actividad."""
    if activities.empty:
        return pd.DataFrame(columns=["fecha", "PLAN", "REAL"])

    acts = activities.copy()
    acts["peso"] = pd.to_numeric(acts.get("peso", 1), errors="coerce").fillna(1)
    acts["inicio_plan"] = pd.to_datetime(acts.get("inicio_plan"), errors="coerce")
    acts["fin_plan"] = pd.to_datetime(acts.get("fin_plan"), errors="coerce")
    acts["fecha_plan"] = acts["fin_plan"].fillna(acts["inicio_plan"])

    total_weight = acts["peso"].sum()
    if total_weight <= 0:
        total_weight = len(acts)
        acts["peso"] = 1

    valid_plan = acts.dropna(subset=["fecha_plan"]).copy()

    if progress.empty or "fecha_registro" not in progress.columns:
        real_dates = pd.Series(dtype="datetime64[ns]")
    else:
        real_dates = pd.to_datetime(progress["fecha_registro"], errors="coerce").dropna()

    date_candidates = []
    if not valid_plan.empty:
        date_candidates.extend(valid_plan["fecha_plan"].tolist())
    if not real_dates.empty:
        date_candidates.extend(real_dates.dt.tz_localize(None).tolist())

    if not date_candidates:
        today = pd.Timestamp.today().normalize()
        date_index = pd.date_range(today, today, freq="D")
    else:
        start_date = pd.Timestamp(min(date_candidates)).normalize()
        end_date = pd.Timestamp(max(date_candidates)).normalize()
        if end_date < start_date:
            end_date = start_date
        date_index = pd.date_range(start_date, end_date, freq="D")

    # PLAN: peso acumulado de actividades cuya fecha plan ya ocurrió.
    plan_values = []
    for current_date in date_index:
        completed_weight = valid_plan.loc[
            valid_plan["fecha_plan"].dt.normalize() <= current_date, "peso"
        ].sum()
        plan_values.append(min(100.0, completed_weight / total_weight * 100))

    # REAL: para cada fecha, tomar el último avance reportado de cada actividad.
    real_values = []
    if progress.empty:
        real_values = [0.0] * len(date_index)
    else:
        prog = progress.copy()
        prog["fecha_registro"] = pd.to_datetime(
            prog["fecha_registro"], errors="coerce"
        )
        if getattr(prog["fecha_registro"].dt, "tz", None) is not None:
            prog["fecha_registro"] = prog["fecha_registro"].dt.tz_localize(None)
        prog["avance"] = pd.to_numeric(prog["avance"], errors="coerce").fillna(0)

        weight_map = acts.set_index("id")["peso"].to_dict()

        for current_date in date_index:
            cutoff = current_date + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            available = prog[prog["fecha_registro"] <= cutoff]
            if available.empty:
                real_values.append(0.0)
                continue

            latest_by_activity = (
                available.sort_values("fecha_registro")
                .groupby("actividad_id", as_index=False)
                .tail(1)
            )
            weighted_sum = 0.0
            for _, row in latest_by_activity.iterrows():
                weight = float(weight_map.get(row["actividad_id"], 0))
                weighted_sum += float(row["avance"]) * weight
            real_values.append(min(100.0, weighted_sum / total_weight))

    curve = pd.DataFrame({
        "fecha": date_index,
        "PLAN": plan_values,
        "REAL": real_values,
    })
    curve["PLAN"] = curve["PLAN"].cummax()
    curve["REAL"] = curve["REAL"].cummax()
    return curve


def compute_kpis(activities: pd.DataFrame, progress: pd.DataFrame) -> dict:
    status = build_activity_status(activities, progress)
    if status.empty:
        return {
            "avance_general": 0.0,
            "actividades": 0,
            "culminadas": 0,
            "parciales": 0,
            "no_iniciadas": 0,
            "spi": 0.0,
            "hh_plan": 0.0,
            "hh_ganadas": 0.0,
        }

    avance_general = weighted_progress(status)
    culminadas = int((status["avance_real"] >= 100).sum())
    parciales = int(((status["avance_real"] > 0) & (status["avance_real"] < 100)).sum())
    no_iniciadas = int((status["avance_real"] <= 0).sum())

    hh_plan_series = pd.to_numeric(status.get("hh_plan", 0), errors="coerce").fillna(0)
    hh_plan = float(hh_plan_series.sum())
    hh_ganadas = float((hh_plan_series * status["avance_real"] / 100).sum())

    today = pd.Timestamp.today().normalize()
    plan_dates = pd.to_datetime(status.get("fin_plan"), errors="coerce").fillna(
        pd.to_datetime(status.get("inicio_plan"), errors="coerce")
    )
    plan_due = status.loc[plan_dates <= today].copy()
    plan_due_pct = weighted_progress(
        plan_due.assign(avance_real=100)
    ) if not plan_due.empty else 0.0
    spi = (avance_general / plan_due_pct) if plan_due_pct > 0 else 0.0

    return {
        "avance_general": avance_general,
        "actividades": len(status),
        "culminadas": culminadas,
        "parciales": parciales,
        "no_iniciadas": no_iniciadas,
        "spi": spi,
        "hh_plan": hh_plan,
        "hh_ganadas": hh_ganadas,
    }


def traffic_light(value: float, green: float = 0.95, yellow: float = 0.80) -> str:
    if value >= green:
        return "🟢"
    if value >= yellow:
        return "🟡"
    return "🔴"


def build_daily_summary(ots: pd.DataFrame, activities: pd.DataFrame, progress: pd.DataFrame) -> str:
    if progress.empty:
        return "No existen avances registrados."

    today = pd.Timestamp.now(tz="America/Lima").date()
    daily = progress[
        pd.to_datetime(progress["fecha_registro"], errors="coerce").dt.date == today
    ].copy()

    if daily.empty:
        return "No se registraron avances durante el día."

    latest = latest_progress(progress)
    status = build_activity_status(activities, progress)
    kpis = compute_kpis(activities, progress)

    top_updates = daily.sort_values("fecha_registro", ascending=False).head(8)
    lines = [
        f"Resumen diario de control de OTs – {today.strftime('%d/%m/%Y')}",
        f"Avance general acumulado: {kpis['avance_general']:.1f}%.",
        f"Registros realizados hoy: {len(daily)}.",
        f"Actividades culminadas: {kpis['culminadas']}.",
        f"Actividades en ejecución: {kpis['parciales']}.",
        f"Actividades no iniciadas: {kpis['no_iniciadas']}.",
        "",
        "Principales actualizaciones:"
    ]

    activity_lookup = activities.set_index("id") if not activities.empty else pd.DataFrame()

    for _, row in top_updates.iterrows():
        activity_id = row.get("actividad_id")
        if not activity_lookup.empty and activity_id in activity_lookup.index:
            act = activity_lookup.loc[activity_id]
            code = act.get("codigo_actividad", "")
            description = act.get("descripcion", "")
        else:
            code = ""
            description = ""
        lines.append(
            f"- {code}: {row.get('avance', 0)}% – "
            f"{row.get('descripcion_avance', '') or description}"
        )

    observations = daily["observaciones"].fillna("").astype(str)
    observations = [x.strip() for x in observations if x.strip()]
    if observations:
        lines += ["", "Observaciones y restricciones reportadas:"]
        for obs in observations[:8]:
            lines.append(f"- {obs}")

    return "\n".join(lines)


with st.sidebar:
    st.markdown("## MAININ")
    st.caption("Maintenance Ingenuity")
    st.markdown("---")
    page = st.radio(
        "Menú",
        [
            "Dashboard ejecutivo",
            "Registrar avance",
            "Detalle por OT",
            "Evidencias",
            "Informe diario",
            "Administrar OTs",
            "Importar base",
            "Exportar reporte",
        ],
    )
    st.markdown("---")
    st.write(f"Usuario: **{st.session_state.get('username', 'Jose')}**")
    if st.button("Cerrar sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()


st.title("APLICATIVO DE CONTROL Y SEGUIMIENTO DE OTs")
st.caption("Cada OT puede contener varias actividades, cada una con avance independiente.")

ots, activities, progress = load_model()
activity_status = build_activity_status(activities, progress)


if page == "Registrar avance":
    if ots.empty or activities.empty:
        st.warning("Primero debe registrar o importar OTs y actividades.")
    else:
        active_ots = ots.copy()
        if "activo" in active_ots.columns:
            active_ots = active_ots[active_ots["activo"].fillna(True)]

        ot_options = active_ots["ot"].astype(str).sort_values().tolist()
        selected_ot = st.selectbox(
            "Escriba o seleccione la OT *",
            ot_options,
            index=None,
            placeholder="Buscar OT...",
        )

        if selected_ot:
            ot_info = active_ots[active_ots["ot"].astype(str) == selected_ot].iloc[0]
            ot_activities = activities[activities["ot_id"] == ot_info["id"]].copy()

            if ot_activities.empty:
                st.warning("La OT seleccionada no tiene actividades registradas.")
            else:
                st.text_input("Equipo", value=str(ot_info.get("equipo", "")), disabled=True)
                st.text_area(
                    "Descripción de la OT",
                    value=str(ot_info.get("descripcion", "")),
                    disabled=True,
                    height=80,
                )

                ot_activities["selector"] = (
                    ot_activities["codigo_actividad"].astype(str)
                    + " — "
                    + ot_activities["descripcion"].astype(str)
                )
                selected_activity_label = st.selectbox(
                    "Seleccione la actividad *",
                    ot_activities["selector"].tolist(),
                    index=None,
                    placeholder="Buscar actividad...",
                )

                if selected_activity_label:
                    activity = ot_activities[
                        ot_activities["selector"] == selected_activity_label
                    ].iloc[0]

                    c1, c2, c3 = st.columns(3)
                    c1.text_input(
                        "Código de actividad",
                        value=str(activity.get("codigo_actividad", "")),
                        disabled=True,
                    )
                    c2.text_input(
                        "Supervisor",
                        value=str(activity.get("supervisor", "")),
                        disabled=True,
                    )
                    c3.text_input(
                        "Especialidad",
                        value=str(activity.get("especialidad", "")),
                        disabled=True,
                    )

                    c1, c2, c3 = st.columns(3)
                    c1.text_input(
                        "Grupo",
                        value=str(activity.get("grupo", "")),
                        disabled=True,
                    )
                    c2.text_input(
                        "Inicio planificado",
                        value=str(activity.get("inicio_plan", "")),
                        disabled=True,
                    )
                    c3.text_input(
                        "Fin planificado",
                        value=str(activity.get("fin_plan", "")),
                        disabled=True,
                    )

                    c1, c2, c3, c4 = st.columns(4)
                    c1.text_input("Sección", value=str(activity.get("seccion", "")), disabled=True)
                    c2.text_input("Personal", value=str(activity.get("personal", "")), disabled=True)
                    c3.text_input("Duración (h)", value=str(activity.get("duracion_h", "")), disabled=True)
                    c4.text_input("HH planificadas", value=str(activity.get("hh_plan", "")), disabled=True)

                    st.text_area(
                        "Descripción de actividad",
                        value=str(activity.get("descripcion", "")),
                        disabled=True,
                        height=90,
                    )

                    current = activity_status[
                        activity_status["id"] == activity["id"]
                    ]
                    current_value = (
                        int(current.iloc[0]["avance_real"])
                        if not current.empty else 0
                    )

                    with st.form("avance_form", clear_on_submit=True):
                        avance = st.number_input(
                            "Porcentaje de avance de la actividad (%) *",
                            min_value=0,
                            max_value=100,
                            value=current_value,
                            step=5,
                        )
                        description = st.text_area(
                            "Descripción breve del avance realizado *",
                            height=110,
                        )
                        observations = st.text_area(
                            "Observaciones",
                            height=100,
                        )
                        photos = st.file_uploader(
                            "Evidencias fotográficas",
                            type=["jpg", "jpeg", "png", "webp"],
                            accept_multiple_files=True,
                        )
                        save = st.form_submit_button(
                            "Guardar avance",
                            type="primary",
                            use_container_width=True,
                        )

                    if save:
                        if not description.strip():
                            st.error("Debe ingresar una descripción del avance.")
                        elif len(photos or []) > 10:
                            st.error("Puede adjuntar como máximo 10 fotografías.")
                        else:
                            try:
                                urls = [
                                    upload_evidence(photo, selected_ot, str(activity["id"]))
                                    for photo in photos or []
                                ]
                                supabase.table("avances_actividad").insert({
                                    "actividad_id": int(activity["id"]),
                                    "avance": int(avance),
                                    "descripcion_avance": description.strip(),
                                    "observaciones": observations.strip(),
                                    "evidencias": urls,
                                    "usuario": st.session_state.get("username", "Jose"),
                                    "fecha_registro": datetime.now(timezone.utc).isoformat(),
                                }).execute()
                                invalidate()
                                st.success(
                                    f"Avance registrado: OT {selected_ot}, "
                                    f"actividad {activity['codigo_actividad']}."
                                )
                            except Exception as exc:
                                st.error(f"No fue posible guardar el avance: {exc}")


if page == "Dashboard ejecutivo":
    if ots.empty or activities.empty:
        st.info("Todavía no existen OTs y actividades registradas.")
    else:
        status = activity_status.copy()
        ot_summary = (
            status.groupby("ot_id")
            .apply(weighted_progress)
            .reset_index(name="avance_ot")
        )
        ot_summary = ot_summary.merge(
            ots[["id", "ot", "equipo", "descripcion"]],
            left_on="ot_id",
            right_on="id",
            how="left",
        )

        kpis = compute_kpis(activities, progress)
        general = kpis["avance_general"]

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("OTs", ots["id"].nunique())
        c2.metric("Actividades", kpis["actividades"])
        c3.metric("Avance general", f"{general:.1f}%")
        c4.metric("Culminadas", kpis["culminadas"])
        c5.metric("En ejecución", kpis["parciales"])
        c6.metric("No iniciadas", kpis["no_iniciadas"])

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "SPI",
            f"{kpis['spi']:.2f}",
            help="Índice de desempeño del cronograma. Valores menores a 1 indican atraso."
        )
        c2.metric("HH planificadas", f"{kpis['hh_plan']:.0f}")
        c3.metric("HH ganadas", f"{kpis['hh_ganadas']:.0f}")

        # CURVA S GENERAL
        curve = build_s_curve(activities, progress)
        fig_curve = go.Figure()
        fig_curve.add_trace(go.Scatter(
            x=curve["fecha"], y=curve["PLAN"],
            mode="lines+markers", name="PLAN"
        ))
        fig_curve.add_trace(go.Scatter(
            x=curve["fecha"], y=curve["REAL"],
            mode="lines+markers", name="REAL"
        ))
        fig_curve.update_layout(
            title="Curva S – Avance general acumulado",
            xaxis_title="Fecha",
            yaxis_title="Avance (%)",
            yaxis_range=[0, 105],
            legend_orientation="h",
            height=430,
        )
        st.plotly_chart(fig_curve, use_container_width=True)

        left, right = st.columns([1.25, 1])
        with left:
            ot_summary["ot"] = ot_summary["ot"].astype(str)
            fig = px.bar(
                ot_summary.sort_values("avance_ot"),
                x="avance_ot",
                y="ot",
                orientation="h",
                text="avance_ot",
                title="Avance ponderado por OT",
                category_orders={"ot": ot_summary.sort_values("avance_ot")["ot"].tolist()},
            )
            fig.update_traces(texttemplate="%{text:.0f}%")
            fig.update_yaxes(type="category")
            fig.update_layout(xaxis_range=[0, 105], height=max(430, 32 * len(ot_summary)))
            st.plotly_chart(fig, use_container_width=True)

        with right:
            status["estado_kpi"] = status["avance_real"].apply(
                lambda x: "CULMINADA" if x >= 100 else ("NO INICIADA" if x <= 0 else "EN EJECUCIÓN")
            )
            states = status.groupby("estado_kpi").size().reset_index(name="Actividades")
            fig2 = px.bar(
                states,
                x="estado_kpi",
                y="Actividades",
                text_auto=True,
                title="Estado de actividades",
            )
            fig2.update_layout(height=430, showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            specialty = (
                status.groupby("especialidad", as_index=False)
                .apply(lambda x: pd.Series({"avance": weighted_progress(x)}))
            )
            fig3 = px.bar(
                specialty,
                x="especialidad",
                y="avance",
                text_auto=".0f",
                title="Avance por especialidad",
            )
            fig3.update_layout(yaxis_range=[0,105], height=380)
            st.plotly_chart(fig3, use_container_width=True)

        with c2:
            supervisors = status[status["supervisor"].fillna("").str.strip() != ""]
            supervisors = (
                supervisors.groupby("supervisor", as_index=False)
                .apply(lambda x: pd.Series({"avance": weighted_progress(x)}))
                .sort_values("avance")
            )
            fig4 = px.bar(
                supervisors,
                x="avance",
                y="supervisor",
                orientation="h",
                text_auto=".0f",
                title="Avance por supervisor",
            )
            fig4.update_layout(xaxis_range=[0,105], height=380)
            st.plotly_chart(fig4, use_container_width=True)


        st.markdown("---")
        st.subheader("Detalle de actividades y avances")

        table_data = status.copy()

        if not ots.empty:
            table_data = table_data.merge(
                ots[["id", "ot", "equipo", "descripcion"]],
                left_on="ot_id",
                right_on="id",
                how="left",
                suffixes=("", "_ot"),
            )

        table_data["ot"] = table_data["ot"].astype(str)
        table_data["avance_real"] = pd.to_numeric(
            table_data["avance_real"], errors="coerce"
        ).fillna(0)

        table_data["estado"] = table_data["avance_real"].apply(
            lambda value: (
                "CULMINADO"
                if value >= 100
                else ("NO INICIADO" if value <= 0 else "EN EJECUCIÓN")
            )
        )

        available_ots = sorted(table_data["ot"].dropna().unique().tolist())
        available_groups = sorted(
            [
                value for value in table_data["grupo"].dropna().astype(str).unique().tolist()
                if value.strip()
            ]
        )
        available_supervisors = sorted(
            [
                value for value in table_data["supervisor"].dropna().astype(str).unique().tolist()
                if value.strip()
            ]
        )

        f1, f2, f3, f4 = st.columns(4)
        selected_table_ot = f1.multiselect(
            "Filtrar OT",
            available_ots,
            placeholder="Todas las OTs",
        )
        selected_table_group = f2.multiselect(
            "Filtrar grupo",
            available_groups,
            placeholder="Todos los grupos",
        )
        selected_table_supervisor = f3.multiselect(
            "Filtrar supervisor",
            available_supervisors,
            placeholder="Todos los supervisores",
        )
        selected_table_state = f4.multiselect(
            "Filtrar estado",
            ["CULMINADO", "EN EJECUCIÓN", "NO INICIADO"],
            placeholder="Todos los estados",
        )

        filtered_table = table_data.copy()
        if selected_table_ot:
            filtered_table = filtered_table[
                filtered_table["ot"].isin(selected_table_ot)
            ]
        if selected_table_group:
            filtered_table = filtered_table[
                filtered_table["grupo"].astype(str).isin(selected_table_group)
            ]
        if selected_table_supervisor:
            filtered_table = filtered_table[
                filtered_table["supervisor"].astype(str).isin(selected_table_supervisor)
            ]
        if selected_table_state:
            filtered_table = filtered_table[
                filtered_table["estado"].isin(selected_table_state)
            ]

        display_columns = [
            "ot",
            "grupo",
            "codigo_actividad",
            "descripcion",
            "supervisor",
            "inicio_plan",
            "avance_real",
            "descripcion_avance",
            "observaciones",
            "personal",
            "duracion_h",
            "hh_plan",
            "estado",
        ]
        display_columns = [
            column for column in display_columns if column in filtered_table.columns
        ]

        st.dataframe(
            filtered_table[display_columns].sort_values(
                ["ot", "codigo_actividad"]
            ),
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config={
                "ot": st.column_config.TextColumn("OT"),
                "grupo": st.column_config.TextColumn("GRUPO"),
                "codigo_actividad": st.column_config.TextColumn("ACTIVIDAD"),
                "descripcion": st.column_config.TextColumn(
                    "DESCRIPCIÓN DE ACTIVIDAD",
                    width="large",
                ),
                "supervisor": st.column_config.TextColumn("SUPERVISOR"),
                "inicio_plan": st.column_config.DateColumn(
                    "INICIO",
                    format="DD/MM/YYYY",
                ),
                "avance_real": st.column_config.ProgressColumn(
                    "AVANCE REAL",
                    min_value=0,
                    max_value=100,
                    format="%d%%",
                ),
                "descripcion_avance": st.column_config.TextColumn(
                    "DESCRIPCIÓN DEL AVANCE",
                    width="large",
                ),
                "observaciones": st.column_config.TextColumn(
                    "OBSERVACIONES",
                    width="large",
                ),
                "personal": st.column_config.NumberColumn(
                    "PERSONAL",
                    format="%.0f",
                ),
                "duracion_h": st.column_config.NumberColumn(
                    "DURACIÓN (H)",
                    format="%.1f",
                ),
                "hh_plan": st.column_config.NumberColumn(
                    "HH PLAN",
                    format="%.1f",
                ),
                "estado": st.column_config.TextColumn("ESTADO"),
            },
        )

        st.caption(
            f"Mostrando {len(filtered_table)} actividades de "
            f"{len(table_data)} registradas."
        )


if page == "Detalle por OT":
    if ots.empty:
        st.info("No existen OTs.")
    else:
        selected = st.selectbox(
            "Seleccione OT",
            ots["ot"].astype(str).sort_values().tolist(),
        )
        ot_row = ots[ots["ot"].astype(str) == selected].iloc[0]
        details = activity_status[activity_status["ot_id"] == ot_row["id"]].copy()

        st.subheader(f"OT {selected}")
        st.write(f"**Equipo:** {ot_row.get('equipo', '')}")
        st.write(f"**Descripción:** {ot_row.get('descripcion', '')}")

        if details.empty:
            st.info("La OT no tiene actividades.")
        else:
            st.metric("Avance ponderado de la OT", f"{weighted_progress(details):.0f}%")
            columns = [
                "codigo_actividad", "descripcion", "supervisor", "especialidad",
                "grupo", "seccion", "personal", "duracion_h", "hh_plan", "peso", "avance_real"
            ]
            st.dataframe(
                details[columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "avance_real": st.column_config.ProgressColumn(
                        "Avance", min_value=0, max_value=100, format="%d%%"
                    )
                },
            )

            details["codigo_actividad"] = details["codigo_actividad"].astype(str)
            fig = px.bar(
                details,
                x="codigo_actividad",
                y="avance_real",
                text_auto=".0f",
                hover_data=["descripcion"],
                title="Avance por actividad",
            )
            fig.update_layout(yaxis_range=[0,105], height=400)
            st.plotly_chart(fig, use_container_width=True)


if page == "Evidencias":
    st.subheader("Galería de evidencias por OT y actividad")

    if progress.empty or "evidencias" not in progress.columns:
        st.info("Todavía no existen evidencias fotográficas.")
    else:
        evidence_progress = progress[
            progress["evidencias"].apply(lambda x: bool(x))
        ].copy()

        if evidence_progress.empty:
            st.info("Todavía no existen evidencias fotográficas.")
        else:
            merged = evidence_progress.merge(
                activities[["id", "ot_id", "codigo_actividad", "descripcion"]],
                left_on="actividad_id",
                right_on="id",
                how="left",
                suffixes=("", "_actividad"),
            ).merge(
                ots[["id", "ot", "equipo"]],
                left_on="ot_id",
                right_on="id",
                how="left",
                suffixes=("", "_ot"),
            )

            ot_options = ["TODAS"] + sorted(merged["ot"].astype(str).unique().tolist())
            selected_ot = st.selectbox("Filtrar por OT", ot_options)
            if selected_ot != "TODAS":
                merged = merged[merged["ot"].astype(str) == selected_ot]

            for _, row in merged.sort_values("fecha_registro", ascending=False).iterrows():
                st.markdown(
                    f"### OT {row['ot']} · {row.get('codigo_actividad', '')} · "
                    f"{int(row.get('avance', 0))}%"
                )
                st.write(row.get("descripcion_actividad", row.get("descripcion", "")))
                st.caption(
                    pd.to_datetime(row["fecha_registro"]).strftime("%d/%m/%Y %H:%M")
                    if pd.notna(row.get("fecha_registro")) else ""
                )
                urls = row.get("evidencias") or []
                if isinstance(urls, str):
                    urls = [urls]
                cols = st.columns(min(3, len(urls)))
                for index, url in enumerate(urls):
                    cols[index % len(cols)].image(url, use_container_width=True)
                st.markdown("---")


if page == "Informe diario":
    st.subheader("Informe diario automático")

    summary_text = build_daily_summary(ots, activities, progress)
    edited_summary = st.text_area(
        "Resumen editable",
        value=summary_text,
        height=420,
    )

    st.download_button(
        "Descargar informe diario en TXT",
        edited_summary.encode("utf-8"),
        file_name=f"informe_diario_{datetime.now():%Y%m%d}.txt",
        mime="text/plain",
        use_container_width=True,
    )

    if not progress.empty:
        today = pd.Timestamp.now(tz="America/Lima").date()
        daily = progress[
            pd.to_datetime(progress["fecha_registro"], errors="coerce").dt.date == today
        ].copy()

        if not daily.empty:
            daily_export = daily.merge(
                activities[["id", "ot_id", "codigo_actividad", "descripcion"]],
                left_on="actividad_id",
                right_on="id",
                how="left",
                suffixes=("", "_actividad"),
            ).merge(
                ots[["id", "ot", "equipo"]],
                left_on="ot_id",
                right_on="id",
                how="left",
                suffixes=("", "_ot"),
            )

            if "fecha_registro" in daily_export.columns:
                daily_export["fecha_registro"] = pd.to_datetime(
                    daily_export["fecha_registro"], errors="coerce"
                ).dt.tz_localize(None)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                daily_export.to_excel(writer, index=False, sheet_name="Informe_Diario")

            st.download_button(
                "Descargar detalle diario en Excel",
                output.getvalue(),
                file_name=f"detalle_diario_{datetime.now():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )


if page == "Administrar OTs":
    tab1, tab2 = st.tabs(["Nueva OT", "Nueva actividad"])

    with tab1:
        with st.form("new_ot", clear_on_submit=True):
            ot_number = st.text_input("Número de OT *")
            equipment = st.text_input("Equipo")
            ot_description = st.text_area("Descripción de OT *")
            active = st.checkbox("Activa", value=True)
            create_ot = st.form_submit_button("Crear OT", type="primary")
        if create_ot:
            if not ot_number.strip() or not ot_description.strip():
                st.error("La OT y la descripción son obligatorias.")
            else:
                try:
                    supabase.table("ots").insert({
                        "ot": ot_number.strip(),
                        "equipo": equipment.strip(),
                        "descripcion": ot_description.strip(),
                        "activo": active,
                    }).execute()
                    invalidate()
                    st.success("OT creada.")
                except Exception as exc:
                    st.error(f"No fue posible crear la OT: {exc}")

    with tab2:
        if ots.empty:
            st.info("Primero cree una OT.")
        else:
            with st.form("new_activity", clear_on_submit=True):
                selected_ot_admin = st.selectbox(
                    "OT *",
                    ots["ot"].astype(str).sort_values().tolist(),
                )
                activity_code = st.text_input("Código de actividad *")
                activity_description = st.text_area("Descripción de actividad *")
                c1, c2, c3 = st.columns(3)
                supervisor = c1.text_input("Supervisor")
                specialty = c2.text_input("Especialidad")
                group = c3.text_input("Grupo")
                c1, c2, c3 = st.columns(3)
                weight = c1.number_input("Peso", min_value=0.01, value=1.0, step=0.1)
                start_plan = c2.date_input("Inicio planificado")
                finish_plan = c3.date_input("Fin planificado")
                create_activity = st.form_submit_button("Crear actividad", type="primary")

            if create_activity:
                if not activity_code.strip() or not activity_description.strip():
                    st.error("Código y descripción son obligatorios.")
                else:
                    try:
                        ot_id = int(
                            ots[ots["ot"].astype(str) == selected_ot_admin].iloc[0]["id"]
                        )
                        supabase.table("actividades").insert({
                            "ot_id": ot_id,
                            "codigo_actividad": activity_code.strip(),
                            "descripcion": activity_description.strip(),
                            "supervisor": supervisor.strip(),
                            "especialidad": specialty.strip(),
                            "grupo": group.strip(),
                            "peso": float(weight),
                            "inicio_plan": start_plan.isoformat(),
                            "fin_plan": finish_plan.isoformat(),
                        }).execute()
                        invalidate()
                        st.success("Actividad creada.")
                    except Exception as exc:
                        st.error(f"No fue posible crear la actividad: {exc}")


if page == "Importar base":
    st.subheader("Importar OTs y actividades desde Excel")
    st.write(
        "El Excel debe contener dos hojas: `OTs` y `Actividades`. "
        "Descargue la plantilla para respetar los nombres de columnas."
    )

    template = io.BytesIO()
    with pd.ExcelWriter(template, engine="openpyxl") as writer:
        pd.DataFrame(columns=["ot", "equipo", "descripcion", "activo"]).to_excel(
            writer, index=False, sheet_name="OTs"
        )
        pd.DataFrame(columns=[
            "ot", "codigo_actividad", "descripcion", "supervisor",
            "especialidad", "grupo", "peso", "inicio_plan", "fin_plan"
        ]).to_excel(writer, index=False, sheet_name="Actividades")

    st.download_button(
        "Descargar plantilla",
        template.getvalue(),
        "plantilla_ots_actividades.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    uploaded = st.file_uploader("Seleccione el Excel", type=["xlsx"])
    if uploaded and st.button("Importar información", type="primary"):
        try:
            import_ots = pd.read_excel(uploaded, sheet_name="OTs")
            import_activities = pd.read_excel(uploaded, sheet_name="Actividades")

            for _, row in import_ots.iterrows():
                existing = (
                    supabase.table("ots")
                    .select("id")
                    .eq("ot", str(row["ot"]).strip())
                    .execute()
                )
                if not existing.data:
                    supabase.table("ots").insert({
                        "ot": str(row["ot"]).strip(),
                        "equipo": str(row.get("equipo", "") or ""),
                        "descripcion": str(row.get("descripcion", "") or ""),
                        "activo": bool(row.get("activo", True)),
                    }).execute()

            refreshed_ots = pd.DataFrame(supabase.table("ots").select("*").execute().data)
            ot_map = dict(zip(refreshed_ots["ot"].astype(str), refreshed_ots["id"]))

            for _, row in import_activities.iterrows():
                ot_text = str(row["ot"]).strip()
                if ot_text not in ot_map:
                    continue
                def clean_text(value):
                    return "" if pd.isna(value) else str(value).strip()

                def clean_date(value):
                    if pd.isna(value) or value in ("", None):
                        return None
                    parsed = pd.to_datetime(value, errors="coerce")
                    if pd.isna(parsed):
                        return None
                    return parsed.date().isoformat()

                def clean_number(value, default=0):
                    if pd.isna(value) or value in ("", None):
                        return default
                    return float(value)

                activity_payload = {
                    "ot_id": int(ot_map[ot_text]),
                    "codigo_actividad": clean_text(row["codigo_actividad"]),
                    "descripcion": clean_text(row["descripcion"]),
                    "supervisor": clean_text(row.get("supervisor")),
                    "especialidad": clean_text(row.get("especialidad")),
                    "grupo": clean_text(row.get("grupo")),
                    "peso": clean_number(row.get("peso"), 1),
                    "inicio_plan": clean_date(row.get("inicio_plan")),
                    "fin_plan": clean_date(row.get("fin_plan")),
                }

                # Inserta una actividad nueva o actualiza la existente cuando
                # ya existe la combinación OT + código de actividad.
                supabase.table("actividades").upsert(
                    activity_payload,
                    on_conflict="ot_id,codigo_actividad",
                ).execute()

            invalidate()
            st.success(
                "Importación finalizada correctamente. "
                "Las OTs nuevas fueron creadas y las actividades duplicadas "
                "fueron actualizadas sin generar errores."
            )
        except Exception as exc:
            st.error(f"No fue posible importar el archivo: {exc}")


if page == "Exportar reporte":
    if progress.empty:
        st.info("No existen avances para exportar.")
    else:
        export = progress.merge(
            activities[["id", "ot_id", "codigo_actividad", "descripcion"]],
            left_on="actividad_id",
            right_on="id",
            how="left",
            suffixes=("", "_actividad"),
        )
        export = export.merge(
            ots[["id", "ot", "equipo"]],
            left_on="ot_id",
            right_on="id",
            how="left",
            suffixes=("", "_ot"),
        )
        if "fecha_registro" in export.columns:
            export["fecha_registro"] = export["fecha_registro"].dt.tz_localize(None)
        if "evidencias" in export.columns:
            export["evidencias"] = export["evidencias"].apply(
                lambda x: "\n".join(x) if isinstance(x, list) else str(x or "")
            )

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            export.to_excel(writer, index=False, sheet_name="Avances")

        st.download_button(
            "Descargar reporte Excel",
            output.getvalue(),
            "reporte_actividades_ots.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
