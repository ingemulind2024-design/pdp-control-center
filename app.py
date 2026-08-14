import io
import hmac
import uuid
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from supabase import Client, create_client


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
st.set_page_config(
    page_title="PDP Control Center - Antapaccay",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BUCKET = "evidencias-ots"
LIMA_TZ = "America/Lima"
CUT_HOURS = (0, 7, 14, 19)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {background:#082d55;}
    [data-testid="stSidebar"] * {color:white;}
    [data-testid="stMetric"] {
        background:#fff;
        border:1px solid #e5e7eb;
        padding:14px;
        border-radius:12px;
        box-shadow:0 2px 10px rgba(0,0,0,.05);
    }
    .block-container {padding-top:1.15rem;}
    h1,h2,h3 {color:#082d55;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# AUTENTICACIÓN
# ============================================================
def load_users() -> dict:
    """Carga usuarios y roles desde Streamlit Secrets."""
    users = {}

    try:
        users_section = st.secrets.get("users", {})
        for username in users_section:
            record = users_section[username]
            users[str(username)] = {
                "password": str(record.get("password", "")),
                "role": str(record.get("role", "reporter")).lower(),
                "name": str(record.get("name", username)),
            }
    except Exception:
        users = {}

    # Compatibilidad con configuración anterior.
    if not users:
        legacy_username = st.secrets.get("auth", {}).get("username", "Jose")
        legacy_password = st.secrets.get("auth", {}).get("password", "Mainin2026")
        users[str(legacy_username)] = {
            "password": str(legacy_password),
            "role": "admin",
            "name": str(legacy_username),
        }

    return users


def authenticate() -> bool:
    if st.session_state.get("authenticated"):
        return True

    users = load_users()

    st.markdown(
        """
        <div style="
            max-width:540px;
            margin:70px auto 12px auto;
            padding:42px 35px;
            background:#fff;
            border-radius:18px;
            border-top:8px solid #f5b700;
            box-shadow:0 10px 35px rgba(0,0,0,.10);
            text-align:center;
        ">
          <div style="font-size:34px;font-weight:800;color:#082d55;">
            PDP CONTROL CENTER
          </div>
          <div style="font-size:18px;color:#667085;margin-top:8px;">
            Control y seguimiento de órdenes de trabajo
          </div>
          <div style="font-size:14px;color:#98a2b3;margin-top:5px;">
            Unidad Minera Antapaccay
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 1.1, 1])

    with center:
        with st.form("login"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button(
                "INGRESAR",
                type="primary",
                use_container_width=True,
            )

        if submit:
            account = users.get(username)
            if account and hmac.compare_digest(password, account["password"]):
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.display_name = account["name"]
                st.session_state.role = account["role"]
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")

    return False


if not authenticate():
    st.stop()


# ============================================================
# SUPABASE
# ============================================================
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


@st.cache_resource
def get_supabase_admin() -> Client | None:
    """
    Cliente administrativo para reinicio/importación.
    La Service Role Key debe permanecer únicamente en Streamlit Secrets.
    """
    try:
        admin_url = st.secrets["supabase"]["url"]
        admin_key = st.secrets["supabase_admin"]["key"]
        return create_client(admin_url, admin_key)
    except Exception:
        return None


supabase = get_supabase()
supabase_admin = get_supabase_admin()


@st.cache_data(ttl=20)
def read_table(name: str) -> pd.DataFrame:
    result = supabase.table(name).select("*").execute()
    return pd.DataFrame(result.data or [])


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
            progress["fecha_registro"],
            errors="coerce",
            utc=True,
        ).dt.tz_convert(LIMA_TZ)

    return ots, activities, progress


# ============================================================
# EVIDENCIAS - COMPRESIÓN AUTOMÁTICA
# ============================================================
def compress_evidence_image(
    uploaded_file,
    max_side: int = 1600,
    quality: int = 82,
) -> tuple[bytes, str, str]:
    """
    Comprime la evidencia antes de almacenarla.

    - corrige orientación EXIF;
    - limita el lado mayor a 1600 px;
    - convierte a JPEG optimizado;
    - reduce el consumo de Storage y datos móviles.
    """
    raw = uploaded_file.getvalue()

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)

            if image.mode != "RGB":
                image = image.convert("RGB")

            width, height = image.size
            longest = max(width, height)

            if longest > max_side:
                ratio = max_side / float(longest)
                new_size = (
                    max(1, int(width * ratio)),
                    max(1, int(height * ratio)),
                )
                image = image.resize(
                    new_size,
                    Image.Resampling.LANCZOS,
                )

            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )

            return output.getvalue(), "jpg", "image/jpeg"

    except Exception as exc:
        raise ValueError(
            f"No se pudo procesar '{getattr(uploaded_file, 'name', 'evidencia')}'. "
            "Use una fotografía JPG, JPEG, PNG o WEBP válida."
        ) from exc


def upload_evidence(file, ot: str, activity_id: str) -> dict:
    original_bytes = file.getvalue()
    compressed_bytes, ext, content_type = compress_evidence_image(file)

    safe_ot = "".join(
        ch for ch in str(ot)
        if ch.isalnum() or ch in "-_"
    ) or "OT"

    filename = (
        f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_"
        f"{uuid.uuid4().hex[:10]}.{ext}"
    )

    path = f"{safe_ot}/{activity_id}/{filename}"

    supabase.storage.from_(BUCKET).upload(
        path=path,
        file=compressed_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "false",
            "cache-control": "3600",
        },
    )

    return {
        "url": supabase.storage.from_(BUCKET).get_public_url(path),
        "original_size": len(original_bytes),
        "compressed_size": len(compressed_bytes),
    }


# ============================================================
# UTILIDADES DE AVANCE
# ============================================================
def latest_progress(progress: pd.DataFrame) -> pd.DataFrame:
    if progress.empty:
        return pd.DataFrame(columns=["actividad_id", "avance"])

    work = progress.copy()

    if "fecha_registro" not in work.columns:
        return pd.DataFrame(columns=["actividad_id", "avance"])

    return (
        work.sort_values("fecha_registro")
        .groupby("actividad_id", as_index=False)
        .tail(1)
    )


def build_activity_status(
    activities: pd.DataFrame,
    progress: pd.DataFrame,
) -> pd.DataFrame:
    if activities.empty:
        return activities.copy()

    latest = latest_progress(progress)

    if latest.empty:
        result = activities.copy()
        result["avance_real"] = 0.0
        result["descripcion_avance"] = ""
        result["observaciones"] = ""
        result["fecha_registro"] = pd.NaT
    else:
        wanted = [
            "actividad_id",
            "avance",
            "descripcion_avance",
            "observaciones",
            "fecha_registro",
        ]
        wanted = [col for col in wanted if col in latest.columns]

        result = activities.merge(
            latest[wanted],
            left_on="id",
            right_on="actividad_id",
            how="left",
        )

        result["avance_real"] = pd.to_numeric(
            result.get("avance", 0),
            errors="coerce",
        ).fillna(0)

    if "peso" not in result.columns:
        result["peso"] = 1.0

    result["peso"] = pd.to_numeric(
        result["peso"],
        errors="coerce",
    ).fillna(1)

    return result


def weighted_progress(activity_status: pd.DataFrame) -> float:
    if activity_status.empty:
        return 0.0

    work = activity_status.copy()
    work["avance_real"] = pd.to_numeric(
        work.get("avance_real", 0),
        errors="coerce",
    ).fillna(0)

    if "peso" not in work.columns:
        return float(work["avance_real"].mean())

    work["peso"] = pd.to_numeric(
        work["peso"],
        errors="coerce",
    ).fillna(1)

    denominator = work["peso"].sum()

    if denominator <= 0:
        return float(work["avance_real"].mean())

    return float(
        (work["avance_real"] * work["peso"]).sum()
        / denominator
    )


# ============================================================
# CURVA S
# ============================================================
def build_s_curve(
    activities: pd.DataFrame,
    progress: pd.DataFrame,
) -> pd.DataFrame:
    """
    Curva S Antapaccay con configuración tipo Chinalco:
    - cortes oficiales 00:00 / 07:00 / 14:00 / 19:00
    - punto EN VIVO para PLAN y REAL
    - inicio y fin exactos
    """
    empty_curve = pd.DataFrame(
        columns=["fecha", "PLAN", "REAL", "tipo_punto"]
    )

    if activities.empty:
        return empty_curve

    acts = activities.copy()

    if "inicio_plan" not in acts.columns or "fin_plan" not in acts.columns:
        return empty_curve

    acts["inicio_plan"] = pd.to_datetime(
        acts["inicio_plan"], errors="coerce"
    )
    acts["fin_plan"] = pd.to_datetime(
        acts["fin_plan"], errors="coerce"
    )

    for column in ["inicio_plan", "fin_plan"]:
        if getattr(acts[column].dt, "tz", None) is not None:
            acts[column] = acts[column].dt.tz_localize(None)

    valid = acts.dropna(
        subset=["id", "inicio_plan", "fin_plan"]
    ).copy()

    if valid.empty:
        return empty_curve

    invalid = valid["fin_plan"] <= valid["inicio_plan"]
    valid.loc[invalid, "fin_plan"] = (
        valid.loc[invalid, "inicio_plan"]
        + pd.Timedelta(minutes=1)
    )

    schedule_start = valid["inicio_plan"].min()
    schedule_finish = valid["fin_plan"].max()
    total_activities = len(valid)

    now_live = pd.Timestamp.now(
        tz=LIMA_TZ
    ).tz_localize(None)

    points = [
        {"fecha": schedule_start, "tipo_punto": "INICIO"}
    ]

    day = schedule_start.normalize()
    last_day = schedule_finish.normalize()

    while day <= last_day:
        for hour in CUT_HOURS:
            cutoff = day + pd.Timedelta(hours=hour)
            if schedule_start < cutoff < schedule_finish:
                points.append(
                    {"fecha": cutoff, "tipo_punto": "CORTE"}
                )
        day += pd.Timedelta(days=1)

    if schedule_start < now_live < schedule_finish:
        points.append(
            {"fecha": now_live, "tipo_punto": "EN VIVO"}
        )

    points.append(
        {"fecha": schedule_finish, "tipo_punto": "FIN"}
    )

    points_df = pd.DataFrame(points)
    points_df["fecha"] = pd.to_datetime(points_df["fecha"])
    points_df["priority"] = points_df["tipo_punto"].map(
        {"EN VIVO": 4, "INICIO": 3, "FIN": 3, "CORTE": 1}
    ).fillna(0)

    points_df = (
        points_df.sort_values(
            ["fecha", "priority"],
            ascending=[True, False],
        )
        .drop_duplicates(subset=["fecha"], keep="first")
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    # PLAN
    plan_values = []

    for cutoff in points_df["fecha"]:
        total_plan = 0.0

        for _, activity in valid.iterrows():
            start_plan = activity["inicio_plan"]
            finish_plan = activity["fin_plan"]

            if cutoff <= start_plan:
                value = 0.0
            elif cutoff >= finish_plan:
                value = 100.0
            else:
                duration = (
                    finish_plan - start_plan
                ).total_seconds()
                elapsed = (
                    cutoff - start_plan
                ).total_seconds()

                value = (
                    elapsed / duration * 100.0
                    if duration > 0
                    else 100.0
                )

            total_plan += max(0.0, min(100.0, value))

        plan_values.append(
            total_plan / total_activities
        )

    # REAL
    prog = progress.copy() if not progress.empty else pd.DataFrame()

    required = {"actividad_id", "avance", "fecha_registro"}

    if not prog.empty and not required.issubset(prog.columns):
        prog = pd.DataFrame()

    if not prog.empty:
        prog["fecha_registro"] = pd.to_datetime(
            prog["fecha_registro"],
            errors="coerce",
        )

        if getattr(prog["fecha_registro"].dt, "tz", None) is not None:
            try:
                prog["fecha_registro"] = (
                    prog["fecha_registro"]
                    .dt.tz_convert(LIMA_TZ)
                    .dt.tz_localize(None)
                )
            except Exception:
                prog["fecha_registro"] = (
                    prog["fecha_registro"]
                    .dt.tz_localize(None)
                )

        prog["avance"] = pd.to_numeric(
            prog["avance"],
            errors="coerce",
        ).fillna(0).clip(0, 100)

        prog = prog.dropna(
            subset=["actividad_id", "fecha_registro"]
        )

    activity_ids = valid["id"].tolist()
    real_values = []

    for _, point in points_df.iterrows():
        cutoff = point["fecha"]
        point_type = point["tipo_punto"]

        if cutoff > now_live and point_type != "EN VIVO":
            real_values.append(None)
            continue

        if prog.empty:
            real_values.append(0.0)
            continue

        available = prog[
            prog["fecha_registro"] <= cutoff
        ]

        if available.empty:
            real_values.append(0.0)
            continue

        latest = (
            available
            .sort_values("fecha_registro")
            .groupby("actividad_id", as_index=False)
            .tail(1)
            .set_index("actividad_id")["avance"]
            .to_dict()
        )

        real_total = sum(
            float(latest.get(activity_id, 0.0))
            for activity_id in activity_ids
        )

        real_values.append(
            real_total / total_activities
        )

    curve = points_df[["fecha", "tipo_punto"]].copy()
    curve["PLAN"] = (
        pd.Series(plan_values)
        .clip(0, 100)
        .cummax()
    )
    curve["REAL"] = real_values

    real_mask = curve["REAL"].notna()
    if real_mask.any():
        curve.loc[real_mask, "REAL"] = (
            pd.to_numeric(
                curve.loc[real_mask, "REAL"],
                errors="coerce",
            )
            .fillna(0)
            .clip(0, 100)
            .cummax()
        )

    curve.loc[curve.index[0], "PLAN"] = 0.0
    curve.loc[curve.index[-1], "PLAN"] = 100.0

    return curve
def render_s_curve(curve: pd.DataFrame):
    if curve.empty:
        st.info(
            "No hay información suficiente para generar la Curva S."
        )
        return

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=curve["fecha"],
            y=curve["PLAN"],
            mode="lines+markers+text",
            name="PLAN",
            line=dict(
                width=4,
                shape="spline",
                smoothing=0.8,
            ),
            marker=dict(size=7),
            text=[
                f"{value:.1f}%"
                for value in curve["PLAN"]
            ],
            textposition="top center",
            customdata=curve["tipo_punto"],
            hovertemplate=(
                "%{x|%d/%m/%Y %H:%M}<br>"
                "PLAN: %{y:.1f}%<br>"
                "Punto: %{customdata}"
                "<extra></extra>"
            ),
        )
    )

    real_curve = curve[
        curve["REAL"].notna()
    ].copy()

    if not real_curve.empty:
        fig.add_trace(
            go.Scatter(
                x=real_curve["fecha"],
                y=real_curve["REAL"],
                mode="lines+markers+text",
                name="REAL",
                line=dict(
                    width=4,
                    shape="spline",
                    smoothing=0.8,
                ),
                marker=dict(size=8),
                text=[
                    f"{value:.1f}%"
                    for value in real_curve["REAL"]
                ],
                textposition="bottom center",
                customdata=real_curve["tipo_punto"],
                hovertemplate=(
                    "%{x|%d/%m/%Y %H:%M}<br>"
                    "REAL: %{y:.1f}%<br>"
                    "Punto: %{customdata}"
                    "<extra></extra>"
                ),
            )
        )

    live = curve[
        curve["tipo_punto"] == "EN VIVO"
    ]

    if not live.empty:
        live_row = live.iloc[0]

        fig.add_trace(
            go.Scatter(
                x=[live_row["fecha"]],
                y=[live_row["PLAN"]],
                mode="markers+text",
                marker=dict(
                    size=15,
                    symbol="circle",
                    line=dict(width=2),
                ),
                text=[
                    f"EN VIVO<br>{live_row['PLAN']:.1f}%"
                ],
                textposition="top center",
                showlegend=False,
                hovertemplate=(
                    "%{x|%d/%m/%Y %H:%M}<br>"
                    "PLAN EN VIVO: %{y:.1f}%"
                    "<extra></extra>"
                ),
            )
        )

        if pd.notna(live_row["REAL"]):
            fig.add_trace(
                go.Scatter(
                    x=[live_row["fecha"]],
                    y=[live_row["REAL"]],
                    mode="markers+text",
                    marker=dict(
                        size=15,
                        symbol="circle",
                        line=dict(width=2),
                    ),
                    text=[
                        f"EN VIVO<br>{live_row['REAL']:.1f}%"
                    ],
                    textposition="bottom center",
                    showlegend=False,
                    hovertemplate=(
                        "%{x|%d/%m/%Y %H:%M}<br>"
                        "REAL EN VIVO: %{y:.1f}%"
                        "<extra></extra>"
                    ),
                )
            )

        fig.add_vline(
            x=live_row["fecha"],
            line_width=1,
            line_dash="dot",
            annotation_text="AHORA",
            annotation_position="top",
        )

    tick_points = curve[
        curve["tipo_punto"].isin(
            ["INICIO", "CORTE", "EN VIVO", "FIN"]
        )
    ]

    tick_values = tick_points["fecha"].tolist()
    tick_text = []

    for _, row in tick_points.iterrows():
        label = pd.to_datetime(
            row["fecha"]
        ).strftime("%d/%m<br>%H:%M")

        if row["tipo_punto"] == "EN VIVO":
            label += "<br><b>EN VIVO</b>"

        tick_text.append(label)

    fig.update_layout(
        title="Curva S consolidada - Plan vs Real",
        xaxis_title="Fecha / hora",
        yaxis_title="Acumulado (%)",
        yaxis=dict(
            range=[0, 108],
            ticksuffix="%",
        ),
        xaxis=dict(
            tickmode="array",
            tickvals=tick_values,
            ticktext=tick_text,
        ),
        hovermode="x unified",
        height=540,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
        ),
        margin=dict(
            l=20,
            r=20,
            t=80,
            b=90,
        ),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )



# ============================================================
# KPIs / INFORMES
# ============================================================
def compute_kpis(
    activities: pd.DataFrame,
    progress: pd.DataFrame,
) -> dict:
    status = build_activity_status(
        activities,
        progress,
    )

    if status.empty:
        return {
            "avance_general": 0.0,
            "actividades": 0,
            "culminadas": 0,
            "parciales": 0,
            "no_iniciadas": 0,
            "hh_plan": 0.0,
            "hh_ganadas": 0.0,
        }

    avance_general = weighted_progress(status)

    culminadas = int(
        (status["avance_real"] >= 100).sum()
    )

    parciales = int(
        (
            (status["avance_real"] > 0)
            & (status["avance_real"] < 100)
        ).sum()
    )

    no_iniciadas = int(
        (status["avance_real"] <= 0).sum()
    )

    if "hh_plan" in status.columns:
        hh_plan_series = pd.to_numeric(
            status["hh_plan"],
            errors="coerce",
        ).fillna(0)
    else:
        hh_plan_series = pd.Series(
            0,
            index=status.index,
            dtype=float,
        )

    hh_plan = float(hh_plan_series.sum())

    hh_ganadas = float(
        (
            hh_plan_series
            * status["avance_real"]
            / 100
        ).sum()
    )

    return {
        "avance_general": avance_general,
        "actividades": len(status),
        "culminadas": culminadas,
        "parciales": parciales,
        "no_iniciadas": no_iniciadas,
        "hh_plan": hh_plan,
        "hh_ganadas": hh_ganadas,
    }


def get_current_plan(curve: pd.DataFrame) -> float:
    if curve.empty:
        return 0.0

    now = pd.Timestamp.now(
        tz=LIMA_TZ
    ).tz_localize(None)

    work = curve.copy()

    previous = work[
        work["fecha"] <= now
    ]

    if previous.empty:
        return 0.0

    return float(
        previous.iloc[-1]["PLAN"]
    )


def build_daily_summary(
    ots: pd.DataFrame,
    activities: pd.DataFrame,
    progress: pd.DataFrame,
) -> str:
    if progress.empty:
        return "No existen avances registrados."

    today = pd.Timestamp.now(
        tz=LIMA_TZ
    ).date()

    daily = progress[
        pd.to_datetime(
            progress["fecha_registro"],
            errors="coerce",
        ).dt.date == today
    ].copy()

    if daily.empty:
        return "No se registraron avances durante el día."

    kpis = compute_kpis(
        activities,
        progress,
    )

    top_updates = daily.sort_values(
        "fecha_registro",
        ascending=False,
    ).head(8)

    lines = [
        f"Resumen diario de control de OTs – {today.strftime('%d/%m/%Y')}",
        f"Avance general acumulado: {kpis['avance_general']:.1f}%.",
        f"Registros realizados hoy: {len(daily)}.",
        f"Actividades culminadas: {kpis['culminadas']}.",
        f"Actividades en ejecución: {kpis['parciales']}.",
        f"Actividades no iniciadas: {kpis['no_iniciadas']}.",
        "",
        "Principales actualizaciones:",
    ]

    activity_lookup = (
        activities.set_index("id")
        if not activities.empty
        else pd.DataFrame()
    )

    for _, row in top_updates.iterrows():
        activity_id = row.get(
            "actividad_id"
        )

        if (
            not activity_lookup.empty
            and activity_id
            in activity_lookup.index
        ):
            act = activity_lookup.loc[
                activity_id
            ]
            code = act.get(
                "codigo_actividad",
                "",
            )
            description = act.get(
                "descripcion",
                "",
            )
        else:
            code = ""
            description = ""

        lines.append(
            f"- {code}: "
            f"{row.get('avance', 0)}% – "
            f"{row.get('descripcion_avance', '') or description}"
        )

    if "observaciones" in daily.columns:
        observations = (
            daily["observaciones"]
            .fillna("")
            .astype(str)
        )

        observations = [
            value.strip()
            for value in observations
            if value.strip()
        ]

        if observations:
            lines += [
                "",
                "Observaciones y restricciones reportadas:",
            ]

            for observation in observations[:8]:
                lines.append(
                    f"- {observation}"
                )

    return "\n".join(lines)


def build_pdf_report(
    ots: pd.DataFrame,
    activities: pd.DataFrame,
    progress: pd.DataFrame,
) -> bytes:
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=28,
        leftMargin=28,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(
        Paragraph(
            "PDP CONTROL CENTER – ANTAPACCAY",
            styles["Title"],
        )
    )

    story.append(
        Spacer(1, 8)
    )

    story.append(
        Paragraph(
            "Informe Ejecutivo",
            styles["Heading2"],
        )
    )

    story.append(
        Paragraph(
            f"Fecha de emisión: "
            f"{datetime.now():%d/%m/%Y %H:%M}",
            styles["Normal"],
        )
    )

    story.append(
        Spacer(1, 12)
    )

    kpis = compute_kpis(
        activities,
        progress,
    )

    curve = build_s_curve(
        activities,
        progress,
    )

    plan_now = get_current_plan(curve)
    deviation = (
        kpis["avance_general"]
        - plan_now
    )

    summary_data = [
        ["Indicador", "Valor"],
        [
            "OTs",
            str(
                ots["id"].nunique()
                if not ots.empty
                and "id" in ots.columns
                else 0
            ),
        ],
        [
            "Actividades",
            str(kpis["actividades"]),
        ],
        [
            "Avance Plan",
            f"{plan_now:.1f}%",
        ],
        [
            "Avance Real",
            f"{kpis['avance_general']:.1f}%",
        ],
        [
            "Desviación",
            f"{deviation:+.1f} pp",
        ],
        [
            "HH planificadas",
            f"{kpis['hh_plan']:.0f}",
        ],
        [
            "HH ganadas",
            f"{kpis['hh_ganadas']:.0f}",
        ],
        [
            "Culminadas",
            str(kpis["culminadas"]),
        ],
        [
            "En ejecución",
            str(kpis["parciales"]),
        ],
        [
            "No iniciadas",
            str(kpis["no_iniciadas"]),
        ],
    ]

    table = Table(
        summary_data,
        colWidths=[220, 180],
    )

    table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#0B5A9C"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold",
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "ALIGN",
                    (1, 1),
                    (1, -1),
                    "CENTER",
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#F3F6F9"),
                    ],
                ),
            ]
        )
    )

    story.append(table)

    story.append(
        Spacer(1, 18)
    )

    if not progress.empty:
        story.append(
            Paragraph(
                "Resumen de avances",
                styles["Heading2"],
            )
        )

        daily_summary = build_daily_summary(
            ots,
            activities,
            progress,
        )

        for line in daily_summary.split("\n"):
            if line.strip():
                story.append(
                    Paragraph(
                        line,
                        styles["BodyText"],
                    )
                )
            else:
                story.append(
                    Spacer(1, 6)
                )

    story.append(
        Spacer(1, 16)
    )

    story.append(
        Paragraph(
            "Detalle por OT",
            styles["Heading2"],
        )
    )

    status = build_activity_status(
        activities,
        progress,
    )

    if (
        not status.empty
        and not ots.empty
        and "ot_id" in status.columns
    ):
        rows = []

        for ot_id, group in status.groupby(
            "ot_id"
        ):
            rows.append(
                {
                    "ot_id": ot_id,
                    "avance_ot": weighted_progress(
                        group
                    ),
                }
            )

        ot_summary = pd.DataFrame(rows)

        merge_cols = [
            col
            for col in [
                "id",
                "ot",
                "equipo",
            ]
            if col in ots.columns
        ]

        ot_summary = ot_summary.merge(
            ots[merge_cols],
            left_on="ot_id",
            right_on="id",
            how="left",
        )

        ot_table = [
            ["OT", "Equipo", "Avance"]
        ]

        for _, row in ot_summary.sort_values(
            "ot"
        ).iterrows():
            ot_table.append(
                [
                    str(row.get("ot", "")),
                    str(row.get("equipo", "")),
                    f"{row.get('avance_ot', 0):.1f}%",
                ]
            )

        table2 = Table(
            ot_table,
            colWidths=[95, 255, 70],
        )

        table2.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor(
                            "#0B5A9C"
                        ),
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold",
                    ),
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.5,
                        colors.grey,
                    ),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [
                            colors.white,
                            colors.HexColor(
                                "#F3F6F9"
                            ),
                        ],
                    ),
                ]
            )
        )

        story.append(table2)

    doc.build(story)

    return buffer.getvalue()


# ============================================================
# SIDEBAR / MENÚ
# ============================================================
with st.sidebar:
    try:
        st.image(
            "logo_mainin.png",
            width=220,
        )
    except Exception:
        pass

    st.caption(
        "Unidad Minera Antapaccay"
    )
    st.markdown("---")

    role = st.session_state.get(
        "role",
        "reporter",
    )

    if role == "admin":
        menu_options = [
            "Dashboard ejecutivo",
            "Registrar avance",
            "Detalle por OT",
            "Evidencias",
            "Informe diario",
            "Reporte PDF",
            "Administrar OTs",
            "Importar base",
            "Exportar reporte",
        ]
    else:
        menu_options = [
            "Registrar avance"
        ]

    page = st.radio(
        "Menú",
        menu_options,
    )

    st.markdown("---")

    st.write(
        "Usuario: "
        f"**{st.session_state.get('display_name', st.session_state.get('username', ''))}**"
    )

    st.caption(
        "Rol: Administrador"
        if role == "admin"
        else "Rol: Reportador de avances"
    )

    if st.button(
        "Cerrar sesión",
        use_container_width=True,
    ):
        for key in [
            "authenticated",
            "username",
            "display_name",
            "role",
        ]:
            st.session_state.pop(
                key,
                None,
            )

        st.rerun()


st.title(
    "APLICATIVO DE CONTROL Y SEGUIMIENTO DE OTs"
)
st.caption(
    "Unidad Minera Antapaccay · "
    "Cada OT puede contener varias actividades con avance independiente."
)

ADMIN_ONLY_PAGES = {
    "Dashboard ejecutivo",
    "Detalle por OT",
    "Evidencias",
    "Informe diario",
    "Reporte PDF",
    "Administrar OTs",
    "Importar base",
    "Exportar reporte",
}

if (
    st.session_state.get(
        "role",
        "reporter",
    ) != "admin"
    and page in ADMIN_ONLY_PAGES
):
    st.error(
        "No tiene autorización para acceder a este módulo."
    )
    st.stop()


ots, activities, progress = load_model()
activity_status = build_activity_status(
    activities,
    progress,
)


# ============================================================
# REGISTRAR AVANCE
# ============================================================
if page == "Registrar avance":
    st.subheader(
        "Registrar avance"
    )

    if ots.empty or activities.empty:
        st.warning(
            "Primero debe registrar o importar OTs y actividades."
        )

    else:
        # --------------------------------------------------------
        # FILTRO 1: SUPERVISOR
        # --------------------------------------------------------
        supervisor_values = []

        if "supervisor" in activities.columns:
            supervisor_values = sorted(
                [
                    value
                    for value in activities["supervisor"]
                    .fillna("")
                    .astype(str)
                    .unique()
                    .tolist()
                    if value.strip()
                ]
            )

        supervisor_options = ["TODOS"] + supervisor_values

        filter_supervisor_col, filter_ot_col = st.columns(2)

        selected_register_supervisor = (
            filter_supervisor_col.selectbox(
                "Seleccione supervisor",
                supervisor_options,
                index=0,
                key="register_supervisor_filter",
            )
        )

        # --------------------------------------------------------
        # FILTRO 2: OTs SEGÚN SUPERVISOR
        # --------------------------------------------------------
        active_ots = ots.copy()

        if "activo" in active_ots.columns:
            active_ots = active_ots[
                active_ots["activo"].fillna(True)
            ]

        if selected_register_supervisor == "TODOS":
            available_ots = active_ots.copy()

        else:
            supervisor_activities = activities[
                activities["supervisor"]
                .fillna("")
                .astype(str)
                == selected_register_supervisor
            ].copy()

            supervisor_ot_ids = (
                supervisor_activities["ot_id"]
                .dropna()
                .unique()
                .tolist()
            )

            available_ots = active_ots[
                active_ots["id"].isin(supervisor_ot_ids)
            ].copy()

        ot_options = (
            available_ots["ot"]
            .astype(str)
            .sort_values()
            .tolist()
        )

        selected_ot = filter_ot_col.selectbox(
            "Escriba o seleccione la OT *",
            ot_options,
            index=None,
            placeholder="Buscar OT...",
            key="register_ot_filter",
        )

        if selected_register_supervisor == "TODOS":
            st.caption(
                f"Mostrando todas las OTs disponibles: "
                f"{len(ot_options)} OT(s)."
            )
        else:
            st.caption(
                f"{len(ot_options)} OT(s) asignada(s) a "
                f"{selected_register_supervisor}."
            )

        if selected_ot:
            ot_info = available_ots[
                available_ots["ot"].astype(str)
                == selected_ot
            ].iloc[0]

            ot_activities = activities[
                activities["ot_id"]
                == ot_info["id"]
            ].copy()

            # Si hay supervisor específico, filtrar también actividades.
            if (
                selected_register_supervisor != "TODOS"
                and "supervisor" in ot_activities.columns
            ):
                ot_activities = ot_activities[
                    ot_activities["supervisor"]
                    .fillna("")
                    .astype(str)
                    == selected_register_supervisor
                ]

            if ot_activities.empty:
                st.warning(
                    "La OT seleccionada no tiene actividades para el filtro actual."
                )

            else:
                c1, c2 = st.columns(
                    [1, 2]
                )

                c1.text_input(
                    "Equipo",
                    value=str(
                        ot_info.get(
                            "equipo",
                            "",
                        )
                    ),
                    disabled=True,
                )

                c2.text_input(
                    "Descripción de la OT",
                    value=str(
                        ot_info.get(
                            "descripcion",
                            "",
                        )
                    ),
                    disabled=True,
                )

                ot_activities[
                    "selector"
                ] = (
                    ot_activities[
                        "codigo_actividad"
                    ].astype(str)
                    + " — "
                    + ot_activities[
                        "descripcion"
                    ].astype(str)
                )

                selected_activity_label = (
                    st.selectbox(
                        "Seleccione la actividad *",
                        ot_activities[
                            "selector"
                        ].tolist(),
                        index=None,
                        placeholder=(
                            "Buscar actividad..."
                        ),
                        key="register_activity_filter",
                    )
                )

                if selected_activity_label:
                    activity = (
                        ot_activities[
                            ot_activities[
                                "selector"
                            ]
                            == selected_activity_label
                        ]
                        .iloc[0]
                    )

                    activity_id = activity[
                        "id"
                    ]

                    latest_for_activity = (
                        progress[
                            progress[
                                "actividad_id"
                            ]
                            == activity_id
                        ]
                        .sort_values(
                            "fecha_registro"
                        )
                        if not progress.empty
                        and "actividad_id"
                        in progress.columns
                        else pd.DataFrame()
                    )

                    current_progress = 0

                    if not latest_for_activity.empty:
                        current_progress = int(
                            round(
                                float(
                                    pd.to_numeric(
                                        latest_for_activity
                                        .iloc[-1]
                                        .get(
                                            "avance",
                                            0,
                                        ),
                                        errors="coerce",
                                    )
                                    or 0
                                )
                            )
                        )

                    c1, c2, c3 = st.columns(
                        3
                    )

                    c1.text_input(
                        "Código de actividad",
                        value=str(
                            activity.get(
                                "codigo_actividad",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    c2.text_input(
                        "Supervisor",
                        value=str(
                            activity.get(
                                "supervisor",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    c3.text_input(
                        "Especialidad",
                        value=str(
                            activity.get(
                                "especialidad",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    c1, c2, c3 = st.columns(
                        3
                    )

                    c1.text_input(
                        "Grupo",
                        value=str(
                            activity.get(
                                "grupo",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    c2.text_input(
                        "Inicio planificado",
                        value=str(
                            activity.get(
                                "inicio_plan",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    c3.text_input(
                        "Fin planificado",
                        value=str(
                            activity.get(
                                "fin_plan",
                                "",
                            )
                        ),
                        disabled=True,
                    )

                    st.info(
                        f"Avance actual de esta actividad: "
                        f"**{current_progress}%**"
                    )

                    form_key = (
                        f"advance_form_"
                        f"{activity_id}"
                    )

                    with st.form(
                        form_key,
                        clear_on_submit=False,
                    ):
                        c1, c2 = st.columns(
                            [1, 2]
                        )

                        advance = c1.number_input(
                            "Nuevo avance (%) *",
                            min_value=0,
                            max_value=100,
                            value=current_progress,
                            step=1,
                            key=(
                                f"avance_"
                                f"{activity_id}"
                            ),
                        )

                        evidence_type = (
                            c2.selectbox(
                                "Etapa de evidencia",
                                [
                                    "INICIO",
                                    "DURANTE",
                                    "FINAL",
                                ],
                            )
                        )

                        advance_description = (
                            st.text_area(
                                "Descripción breve del avance *",
                                placeholder=(
                                    "Indique el trabajo "
                                    "ejecutado..."
                                ),
                                height=100,
                            )
                        )

                        observations = (
                            st.text_area(
                                "Observaciones / Restricciones",
                                placeholder=(
                                    "Indique restricciones, "
                                    "riesgos, pendientes o "
                                    "comentarios relevantes..."
                                ),
                                height=110,
                            )
                        )

                        photos = st.file_uploader(
                            "Evidencias fotográficas",
                            type=[
                                "jpg",
                                "jpeg",
                                "png",
                                "webp",
                            ],
                            accept_multiple_files=True,
                            help=(
                                "Puede cargar hasta 10 "
                                "fotografías. Las imágenes "
                                "se comprimen automáticamente "
                                "antes de almacenarse."
                            ),
                        )

                        submit_advance = (
                            st.form_submit_button(
                                "GUARDAR AVANCE",
                                type="primary",
                                use_container_width=True,
                            )
                        )

                    if submit_advance:
                        if not str(
                            advance_description
                        ).strip():
                            st.error(
                                "La descripción del avance es obligatoria."
                            )

                        elif photos and len(
                            photos
                        ) > 10:
                            st.error(
                                "Puede cargar como máximo 10 fotografías por registro."
                            )

                        else:
                            try:
                                evidence_urls = []
                                total_original_bytes = 0
                                total_compressed_bytes = 0

                                for photo in (
                                    photos or []
                                ):
                                    upload_result = upload_evidence(
                                        photo,
                                        str(
                                            selected_ot
                                        ),
                                        str(
                                            activity_id
                                        ),
                                    )

                                    evidence_urls.append(
                                        upload_result["url"]
                                    )

                                    total_original_bytes += int(
                                        upload_result["original_size"]
                                    )

                                    total_compressed_bytes += int(
                                        upload_result["compressed_size"]
                                    )

                                payload = {
                                    "actividad_id": (
                                        int(
                                            activity_id
                                        )
                                    ),
                                    "avance": int(
                                        round(
                                            float(advance)
                                        )
                                    ),
                                    "descripcion_avance": (
                                        str(
                                            advance_description
                                        ).strip()
                                    ),
                                    "observaciones": (
                                        str(
                                            observations
                                        ).strip()
                                    ),
                                    "evidencias": (
                                        evidence_urls
                                    ),
                                    "tipo_evidencia": (
                                        evidence_type
                                    ),
                                    "usuario": (
                                        st.session_state.get(
                                            "username",
                                            "",
                                        )
                                    ),
                                    "fecha_registro": (
                                        datetime.now(
                                            timezone.utc
                                        ).isoformat()
                                    ),
                                }

                                supabase.table(
                                    "avances_actividad"
                                ).insert(
                                    payload
                                ).execute()

                                invalidate()

                                photo_count = len(
                                    photos or []
                                )

                                if photo_count > 0:
                                    original_mb = (
                                        total_original_bytes
                                        / 1024
                                        / 1024
                                    )
                                    compressed_mb = (
                                        total_compressed_bytes
                                        / 1024
                                        / 1024
                                    )

                                    if total_original_bytes > 0:
                                        reduction_pct = max(
                                            0.0,
                                            (
                                                1
                                                - (
                                                    total_compressed_bytes
                                                    / total_original_bytes
                                                )
                                            )
                                            * 100,
                                        )
                                    else:
                                        reduction_pct = 0.0

                                    success_message = (
                                        f"✅ Avance guardado correctamente. "
                                        f"📷 {photo_count} evidencia(s) cargada(s) y comprimida(s). "
                                        f"Tamaño: {original_mb:.2f} MB → "
                                        f"{compressed_mb:.2f} MB "
                                        f"({reduction_pct:.0f}% de reducción)."
                                    )
                                else:
                                    success_message = (
                                        "✅ Avance guardado correctamente. "
                                        "No se adjuntaron evidencias fotográficas."
                                    )

                                st.session_state[
                                    "advance_saved_message"
                                ] = success_message

                                st.rerun()

                            except Exception as exc:
                                st.error(
                                    "No fue posible registrar el avance: "
                                    f"{exc}"
                                )

                    # Confirmación debajo del botón GUARDAR AVANCE.
                    if st.session_state.get("advance_saved_message"):
                        st.success(
                            st.session_state.pop("advance_saved_message")
                        )


# ============================================================
# DASHBOARD
# ============================================================
if page == "Dashboard ejecutivo":
    st.subheader("Dashboard - Antapaccay")

    if activities.empty:
        st.info("No existen actividades cargadas.")

    else:
        # ========================================================
        # BASE DE CÁLCULO
        # ========================================================
        status = build_activity_status(
            activities,
            progress,
        )

        kpis = compute_kpis(
            activities,
            progress,
        )

        curve = build_s_curve(
            activities,
            progress,
        )

        total_ots = (
            int(ots["id"].nunique())
            if not ots.empty and "id" in ots.columns
            else 0
        )

        total_activities = int(
            kpis.get("actividades", 0)
        )

        real_now = float(
            kpis.get("avance_general", 0.0)
        )

        plan_now = float(
            get_current_plan(curve)
        )

        deviation = (
            real_now - plan_now
        )

        spi = (
            real_now / plan_now
            if plan_now > 0
            else 0.0
        )

        hh_plan = float(
            kpis.get("hh_plan", 0.0)
        )

        hh_earned = float(
            kpis.get("hh_ganadas", 0.0)
        )

        # ========================================================
        # ENCABEZADO OPERATIVO
        # ========================================================
        st.caption(
            f"Control operativo exclusivo de Antapaccay · "
            f"{total_ots} OTs · "
            f"{total_activities} actividades"
        )

        # ========================================================
        # KPIs PRINCIPALES - MISMO ESQUEMA DEL PDF CHINALCO
        # ========================================================
        k1, k2, k3, k4, k5, k6 = st.columns(6)

        k1.metric(
            "OTs",
            f"{total_ots}",
        )

        k2.metric(
            "Actividades",
            f"{total_activities}",
        )

        k3.metric(
            "Avance general",
            f"{real_now:.1f}%",
        )

        k4.metric(
            "Culminadas",
            f"{int(kpis.get('culminadas', 0))}",
        )

        k5.metric(
            "En ejecución",
            f"{int(kpis.get('parciales', 0))}",
        )

        k6.metric(
            "No iniciadas",
            f"{int(kpis.get('no_iniciadas', 0))}",
        )

        st.write("")

        k7, k8, k9 = st.columns(3)

        k7.metric(
            "SPI",
            f"{spi:.2f}",
            help=(
                "SPI = Avance Real / Avance Plan al corte actual. "
                "SPI < 1.00 indica atraso; SPI = 1.00 indica cumplimiento."
            ),
        )

        k8.metric(
            "HH planificadas",
            f"{hh_plan:.0f}",
        )

        k9.metric(
            "HH ganadas",
            f"{hh_earned:.0f}",
        )

        # ========================================================
        # SEMÁFORO DE DESVIACIÓN
        # ========================================================
        st.markdown("---")

        if plan_now <= 0:
            st.info(
                "⚪ PLAN AÚN NO INICIADO · "
                "El SPI se habilitará cuando exista avance planificado."
            )

        elif spi < 0.85:
            st.error(
                f"🔴 DESVIACIÓN CRÍTICA · SPI {spi:.2f} · "
                f"Plan {plan_now:.1f}% · Real {real_now:.1f}% · "
                f"Brecha {deviation:+.1f} pp"
            )

        elif spi < 0.95:
            st.warning(
                f"🟠 DESVIACIÓN EN ALERTA · SPI {spi:.2f} · "
                f"Plan {plan_now:.1f}% · Real {real_now:.1f}% · "
                f"Brecha {deviation:+.1f} pp"
            )

        else:
            st.success(
                f"🟢 DESEMPEÑO CONTROLADO · SPI {spi:.2f} · "
                f"Plan {plan_now:.1f}% · Real {real_now:.1f}% · "
                f"Brecha {deviation:+.1f} pp"
            )

        # ========================================================
        # CURVA S - INMEDIATAMENTE DESPUÉS DE LOS KPIs
        # ========================================================
        st.markdown("---")
        st.subheader("Curva S - Plan vs Real")
        render_s_curve(curve)

        # ========================================================
        # PREPARACIÓN DEL DATASET CONSOLIDADO
        # ========================================================
        dashboard_data = status.copy()

        if (
            not ots.empty
            and "ot_id" in dashboard_data.columns
        ):
            merge_cols = [
                col
                for col in [
                    "id",
                    "ot",
                    "equipo",
                ]
                if col in ots.columns
            ]

            dashboard_data = dashboard_data.merge(
                ots[merge_cols],
                left_on="ot_id",
                right_on="id",
                how="left",
                suffixes=("", "_ot"),
            )

        if "ot" not in dashboard_data.columns:
            dashboard_data["ot"] = ""

        if "equipo" not in dashboard_data.columns:
            dashboard_data["equipo"] = ""

        dashboard_data["ot"] = (
            dashboard_data["ot"]
            .fillna("")
            .astype(str)
        )

        dashboard_data["equipo"] = (
            dashboard_data["equipo"]
            .fillna("")
            .astype(str)
        )

        dashboard_data["avance_real"] = pd.to_numeric(
            dashboard_data.get("avance_real", 0),
            errors="coerce",
        ).fillna(0).clip(0, 100)

        dashboard_data["estado"] = (
            dashboard_data["avance_real"].apply(
                lambda value: (
                    "Culminadas"
                    if value >= 100
                    else (
                        "No iniciadas"
                        if value <= 0
                        else "En ejecución"
                    )
                )
            )
        )

        # ========================================================
        # AVANCE POR OT
        # ========================================================
        st.markdown("---")
        st.subheader("Avance por OT")

        if (
            not dashboard_data.empty
            and "ot_id" in dashboard_data.columns
        ):
            ot_rows = []

            for ot_id, group in dashboard_data.groupby(
                "ot_id",
                dropna=False,
            ):
                ot_name = str(
                    group["ot"].iloc[0]
                ).strip()

                # Mostrar únicamente la OT en el eje vertical.
                # También limpia valores tipo "1175904.0" si vienen desde Excel.
                if ot_name.endswith(".0"):
                    try:
                        ot_name = str(int(float(ot_name)))
                    except Exception:
                        pass

                ot_rows.append(
                    {
                        "OT": ot_name,
                        "Avance": weighted_progress(group),
                    }
                )

            ot_summary = pd.DataFrame(
                ot_rows
            )

            if not ot_summary.empty:
                ot_summary = (
                    ot_summary.sort_values(
                        "Avance",
                        ascending=True,
                    )
                )

                fig_ot = px.bar(
                    ot_summary,
                    x="Avance",
                    y="OT",
                    orientation="h",
                    text="Avance",
                )

                # Mostrar únicamente el porcentaje al final de cada barra.
                fig_ot.update_traces(
                    texttemplate="%{text:.1f}%",
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate=(
                        "OT: %{y}<br>"
                        "Avance: %{x:.1f}%"
                        "<extra></extra>"
                    ),
                )

                # Eje vertical = SOLO OT.
                # Eje horizontal = porcentaje de avance.
                fig_ot.update_layout(
                    xaxis_title="Avance (%)",
                    yaxis_title="",
                    xaxis=dict(
                        range=[0, 105],
                        tickmode="array",
                        tickvals=[0, 20, 40, 60, 80, 100],
                        ticktext=["0", "20", "40", "60", "80", "100"],
                    ),
                    yaxis=dict(
                        type="category",
                        automargin=True,
                    ),
                    height=max(
                        430,
                        31 * len(ot_summary) + 120,
                    ),
                    showlegend=False,
                    margin=dict(
                        l=20,
                        r=95,
                        t=15,
                        b=55,
                    ),
                )

                st.plotly_chart(
                    fig_ot,
                    use_container_width=True,
                    config={
                        "displayModeBar": False,
                        "responsive": True,
                    },
                )

        # ========================================================
        # ESTADO DE ACTIVIDADES
        # ========================================================
        st.markdown("---")
        st.subheader("Estado de actividades")

        state_order = [
            "Culminadas",
            "En ejecución",
            "No iniciadas",
        ]

        state_counts = (
            dashboard_data["estado"]
            .value_counts()
            .reindex(
                state_order,
                fill_value=0,
            )
            .rename_axis("Estado")
            .reset_index(name="Actividades")
        )

        fig_state = px.bar(
            state_counts,
            x="Estado",
            y="Actividades",
            text="Actividades",
        )

        fig_state.update_traces(
            textposition="outside",
        )

        ymax = max(
            1,
            int(state_counts["Actividades"].max()),
        )

        fig_state.update_layout(
            xaxis_title="",
            yaxis_title="N.º de actividades",
            yaxis=dict(
                range=[0, ymax * 1.25],
                dtick=1 if ymax <= 12 else None,
            ),
            height=400,
            showlegend=False,
            margin=dict(
                l=40,
                r=20,
                t=15,
                b=40,
            ),
        )

        st.plotly_chart(
            fig_state,
            use_container_width=True,
        )

        # ========================================================
        # AVANCE POR ESPECIALIDAD / SUPERVISOR
        # ========================================================
        st.markdown("---")

        col_specialty, col_supervisor = st.columns(2)

        with col_specialty:
            st.subheader(
                "Avance por especialidad"
            )

            specialty_source = dashboard_data.copy()

            if "especialidad" in specialty_source.columns:
                specialty_source = specialty_source[
                    specialty_source["especialidad"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    != ""
                ]

                specialty_rows = []

                for specialty_name, group in (
                    specialty_source.groupby(
                        "especialidad"
                    )
                ):
                    specialty_rows.append(
                        {
                            "Especialidad": str(
                                specialty_name
                            ),
                            "Avance": weighted_progress(group),
                        }
                    )

                specialty_df = pd.DataFrame(
                    specialty_rows
                )

                if not specialty_df.empty:
                    specialty_df = (
                        specialty_df.sort_values(
                            "Avance",
                            ascending=True,
                        )
                    )

                    fig_specialty = px.bar(
                        specialty_df,
                        x="Avance",
                        y="Especialidad",
                        orientation="h",
                        text="Avance",
                    )

                    fig_specialty.update_traces(
                        texttemplate="%{text:.1f}%",
                        textposition="outside",
                        cliponaxis=False,
                    )

                    fig_specialty.update_layout(
                        xaxis_title="Avance (%)",
                        yaxis_title="",
                        xaxis=dict(
                            range=[0, 105],
                            ticksuffix="%",
                        ),
                        height=max(
                            360,
                            44 * len(specialty_df) + 110,
                        ),
                        showlegend=False,
                        margin=dict(
                            l=20,
                            r=75,
                            t=15,
                            b=55,
                        ),
                    )

                    st.plotly_chart(
                        fig_specialty,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "No hay especialidades registradas."
                    )

        with col_supervisor:
            st.subheader(
                "Avance por supervisor"
            )

            supervisor_source = dashboard_data.copy()

            if "supervisor" in supervisor_source.columns:
                supervisor_source = supervisor_source[
                    supervisor_source["supervisor"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    != ""
                ]

                supervisor_rows = []

                for supervisor_name, group in (
                    supervisor_source.groupby(
                        "supervisor"
                    )
                ):
                    supervisor_rows.append(
                        {
                            "Supervisor": str(
                                supervisor_name
                            ),
                            "Avance": weighted_progress(group),
                        }
                    )

                supervisor_df = pd.DataFrame(
                    supervisor_rows
                )

                if not supervisor_df.empty:
                    supervisor_df = (
                        supervisor_df.sort_values(
                            "Avance",
                            ascending=True,
                        )
                    )

                    fig_supervisor = px.bar(
                        supervisor_df,
                        x="Avance",
                        y="Supervisor",
                        orientation="h",
                        text="Avance",
                    )

                    fig_supervisor.update_traces(
                        texttemplate="%{text:.1f}%",
                        textposition="outside",
                        cliponaxis=False,
                    )

                    fig_supervisor.update_layout(
                        xaxis_title="Avance (%)",
                        yaxis_title="",
                        xaxis=dict(
                            range=[0, 105],
                            ticksuffix="%",
                        ),
                        height=max(
                            360,
                            44 * len(supervisor_df) + 110,
                        ),
                        showlegend=False,
                        margin=dict(
                            l=20,
                            r=75,
                            t=15,
                            b=55,
                        ),
                    )

                    st.plotly_chart(
                        fig_supervisor,
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "No hay supervisores registrados."
                    )

        # ========================================================
        # DETALLE DE PLANIFICACIÓN Y AVANCE
        # ========================================================
        st.markdown("---")
        st.subheader(
            "Detalle de planificación y avance"
        )

        f1, f2, f3 = st.columns(3)

        ot_filter_options = ["TODAS"] + sorted(
            [
                value
                for value in dashboard_data["ot"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
                if value.strip()
            ]
        )

        specialty_filter_options = ["TODAS"]

        if "especialidad" in dashboard_data.columns:
            specialty_filter_options += sorted(
                [
                    value
                    for value in dashboard_data[
                        "especialidad"
                    ]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                    if value.strip()
                ]
            )

        selected_ot_filter = f1.selectbox(
            "Filtrar por OT",
            ot_filter_options,
        )

        selected_specialty_filter = f2.selectbox(
            "Filtrar por especialidad",
            specialty_filter_options,
        )

        selected_state_filter = f3.selectbox(
            "Estado",
            [
                "TODOS",
                "Culminadas",
                "En ejecución",
                "No iniciadas",
            ],
        )

        detail_filtered = dashboard_data.copy()

        if selected_ot_filter != "TODAS":
            detail_filtered = detail_filtered[
                detail_filtered["ot"]
                == selected_ot_filter
            ]

        if (
            selected_specialty_filter != "TODAS"
            and "especialidad"
            in detail_filtered.columns
        ):
            detail_filtered = detail_filtered[
                detail_filtered["especialidad"]
                .astype(str)
                == selected_specialty_filter
            ]

        if selected_state_filter != "TODOS":
            detail_filtered = detail_filtered[
                detail_filtered["estado"]
                == selected_state_filter
            ]

        detail_columns = [
            "ot",
            "equipo",
            "codigo_actividad",
            "descripcion",
            "especialidad",
            "supervisor",
            "grupo",
            "inicio_plan",
            "fin_plan",
            "hh_plan",
            "avance_real",
        ]

        detail_columns = [
            col
            for col in detail_columns
            if col in detail_filtered.columns
        ]

        detail_display = detail_filtered[
            detail_columns
        ].copy()

        rename_map = {
            "ot": "OT",
            "equipo": "EQUIPO",
            "codigo_actividad": "ACTIVIDAD",
            "descripcion": "DESCRIPCIÓN",
            "especialidad": "ESPECIALIDAD",
            "supervisor": "SUPERVISOR",
            "grupo": "GRUPO",
            "inicio_plan": "INICIO PLAN",
            "fin_plan": "FIN PLAN",
            "hh_plan": "HH PLAN",
            "avance_real": "AVANCE REAL (%)",
        }

        detail_display = detail_display.rename(
            columns=rename_map
        )

        st.dataframe(
            detail_display,
            use_container_width=True,
            hide_index=True,
            height=min(
                650,
                max(
                    250,
                    36 * len(detail_display) + 70,
                ),
            ),
            column_config={
                "AVANCE REAL (%)": st.column_config.NumberColumn(
                    "AVANCE REAL (%)",
                    format="%.1f",
                ),
                "HH PLAN": st.column_config.NumberColumn(
                    "HH PLAN",
                    format="%.0f",
                ),
            },
        )

        filtered_completed = int(
            (
                detail_filtered["avance_real"]
                >= 100
            ).sum()
        )

        filtered_in_progress = int(
            (
                (
                    detail_filtered["avance_real"]
                    > 0
                )
                & (
                    detail_filtered["avance_real"]
                    < 100
                )
            ).sum()
        )

        filtered_not_started = int(
            (
                detail_filtered["avance_real"]
                <= 0
            ).sum()
        )

        st.caption(
            f"Mostrando {len(detail_filtered)} actividades · "
            f"{filtered_completed} culminadas · "
            f"{filtered_in_progress} en ejecución · "
            f"{filtered_not_started} no iniciadas."
        )


# ============================================================
# DETALLE POR OT
# ============================================================
if page == "Detalle por OT":
    st.subheader("Detalle por OT")

    if ots.empty or activities.empty:
        st.info("No existen OTs o actividades registradas.")

    else:
        # --------------------------------------------------------
        # FILTROS: SUPERVISOR + OT
        # --------------------------------------------------------
        supervisor_values = []

        if "supervisor" in activities.columns:
            supervisor_values = sorted(
                [
                    value
                    for value in activities["supervisor"]
                    .fillna("")
                    .astype(str)
                    .unique()
                    .tolist()
                    if value.strip()
                ]
            )

        supervisor_options = ["TODOS"] + supervisor_values

        filter_supervisor_col, filter_ot_col = st.columns(2)

        selected_detail_supervisor = (
            filter_supervisor_col.selectbox(
                "Seleccione supervisor",
                supervisor_options,
                index=0,
                key="detail_supervisor_filter_final",
            )
        )

        # --------------------------------------------------------
        # OTs DISPONIBLES SEGÚN SUPERVISOR
        # --------------------------------------------------------
        if selected_detail_supervisor == "TODOS":
            available_ots = ots.copy()

        else:
            supervisor_activities = activities[
                activities["supervisor"]
                .fillna("")
                .astype(str)
                == selected_detail_supervisor
            ].copy()

            supervisor_ot_ids = (
                supervisor_activities["ot_id"]
                .dropna()
                .unique()
                .tolist()
            )

            available_ots = ots[
                ots["id"].isin(supervisor_ot_ids)
            ].copy()

        ot_options = (
            available_ots["ot"]
            .astype(str)
            .sort_values()
            .tolist()
        )

        selected_detail_ot = (
            filter_ot_col.selectbox(
                "Seleccione OT",
                ot_options,
                index=None,
                placeholder="Buscar OT...",
                key="detail_ot_filter_final",
            )
        )

        if selected_detail_supervisor == "TODOS":
            st.caption(
                f"Mostrando todas las OTs disponibles: "
                f"{len(ot_options)} OT(s)."
            )
        else:
            st.caption(
                f"{len(ot_options)} OT(s) asignada(s) a "
                f"{selected_detail_supervisor}."
            )

        # --------------------------------------------------------
        # DETALLE SOLO CUANDO SELECCIONA OT
        # --------------------------------------------------------
        if selected_detail_ot:
            ot_row = available_ots[
                available_ots["ot"].astype(str)
                == selected_detail_ot
            ].iloc[0]

            if selected_detail_supervisor != "TODOS":
                st.write(
                    f"**Supervisor:** {selected_detail_supervisor}"
                )

            st.write(
                f"**Equipo:** {ot_row.get('equipo', '')}"
            )

            st.write(
                f"**Descripción:** {ot_row.get('descripcion', '')}"
            )

            detail_activities = activity_status[
                activity_status["ot_id"]
                == ot_row["id"]
            ].copy()

            # Si se selecciona supervisor específico, filtrar actividades.
            if (
                selected_detail_supervisor != "TODOS"
                and "supervisor" in detail_activities.columns
            ):
                detail_activities = detail_activities[
                    detail_activities["supervisor"]
                    .fillna("")
                    .astype(str)
                    == selected_detail_supervisor
                ]

            if detail_activities.empty:
                st.info(
                    "No existen actividades para los filtros seleccionados."
                )

            else:
                detail_activities["avance_real"] = pd.to_numeric(
                    detail_activities["avance_real"],
                    errors="coerce",
                ).fillna(0)

                st.metric(
                    "Avance de la OT",
                    f"{weighted_progress(detail_activities):.1f}%",
                )

                detail_cols = [
                    "codigo_actividad",
                    "descripcion",
                    "supervisor",
                    "especialidad",
                    "grupo",
                    "inicio_plan",
                    "fin_plan",
                    "avance_real",
                    "descripcion_avance",
                    "observaciones",
                ]

                detail_cols = [
                    col
                    for col in detail_cols
                    if col in detail_activities.columns
                ]

                st.dataframe(
                    detail_activities[detail_cols],
                    use_container_width=True,
                    hide_index=True,
                )

                # ------------------------------------------------
                # HISTORIAL COHERENTE CON EL FILTRO ACTUAL
                # ------------------------------------------------
                activity_ids = detail_activities["id"].tolist()

                if (
                    not progress.empty
                    and "actividad_id" in progress.columns
                ):
                    history = progress[
                        progress["actividad_id"].isin(activity_ids)
                    ].copy()

                    if not history.empty:
                        activity_info_cols = [
                            "id",
                            "codigo_actividad",
                            "descripcion",
                        ]

                        if "supervisor" in activities.columns:
                            activity_info_cols.append("supervisor")

                        activity_info = activities[
                            activity_info_cols
                        ].copy()

                        history = history.merge(
                            activity_info,
                            left_on="actividad_id",
                            right_on="id",
                            how="left",
                            suffixes=("", "_actividad"),
                        )

                        st.markdown("### Historial de reportes")

                        history_cols = [
                            "fecha_registro",
                            "codigo_actividad",
                            "supervisor",
                            "avance",
                            "descripcion_avance",
                            "observaciones",
                            "tipo_evidencia",
                            "usuario",
                        ]

                        history_cols = [
                            col
                            for col in history_cols
                            if col in history.columns
                        ]

                        st.dataframe(
                            history.sort_values(
                                "fecha_registro",
                                ascending=False,
                            )[history_cols],
                            use_container_width=True,
                            hide_index=True,
                        )


# ============================================================
# EVIDENCIAS
# ============================================================
if page == "Evidencias":
    st.subheader("Evidencias - Antapaccay")

    if (
        progress.empty
        or "evidencias" not in progress.columns
    ):
        st.info("No existen evidencias registradas.")

    else:
        evidence_progress = progress.copy()

        def has_evidence(value):
            if isinstance(value, list):
                return len(value) > 0

            if isinstance(value, str):
                return bool(value.strip())

            return False

        evidence_progress = evidence_progress[
            evidence_progress["evidencias"].apply(has_evidence)
        ].copy()

        if evidence_progress.empty:
            st.info("No existen evidencias registradas.")

        else:
            # ----------------------------------------------------
            # ENRIQUECER CON DATOS DE ACTIVIDAD Y OT
            # ----------------------------------------------------
            activity_cols = [
                col
                for col in [
                    "id",
                    "ot_id",
                    "codigo_actividad",
                    "descripcion",
                    "supervisor",
                    "especialidad",
                    "grupo",
                ]
                if col in activities.columns
            ]

            merged = evidence_progress.merge(
                activities[activity_cols],
                left_on="actividad_id",
                right_on="id",
                how="left",
                suffixes=("", "_actividad"),
            )

            ot_cols = [
                col
                for col in [
                    "id",
                    "ot",
                    "equipo",
                ]
                if col in ots.columns
            ]

            merged = merged.merge(
                ots[ot_cols],
                left_on="ot_id",
                right_on="id",
                how="left",
                suffixes=("", "_ot"),
            )

            if "ot" not in merged.columns:
                merged["ot"] = ""

            if "codigo_actividad" not in merged.columns:
                merged["codigo_actividad"] = ""

            if "tipo_evidencia" not in merged.columns:
                merged["tipo_evidencia"] = ""

            merged["ot"] = (
                merged["ot"]
                .fillna("")
                .astype(str)
            )

            merged["codigo_actividad"] = (
                merged["codigo_actividad"]
                .fillna("")
                .astype(str)
            )

            merged["tipo_evidencia"] = (
                merged["tipo_evidencia"]
                .fillna("")
                .astype(str)
                .str.upper()
            )

            # Limpiar OTs que puedan venir como 123456.0
            def clean_ot_label(value):
                value = str(value).strip()

                if value.endswith(".0"):
                    try:
                        return str(int(float(value)))
                    except Exception:
                        pass

                return value

            merged["ot"] = merged["ot"].apply(clean_ot_label)

            # ----------------------------------------------------
            # FILTROS SUPERIORES
            # ----------------------------------------------------
            filter_ot_col, filter_type_col = st.columns(2)

            ot_options = (
                ["TODAS"]
                + sorted(
                    [
                        value
                        for value in merged["ot"]
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()
                        if value.strip()
                    ]
                )
            )

            evidence_types = sorted(
                [
                    value
                    for value in merged["tipo_evidencia"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                    if value.strip()
                ]
            )

            type_options = ["TODAS"] + evidence_types

            selected_ot = filter_ot_col.selectbox(
                "Filtrar por OT",
                ot_options,
                key="evidence_filter_ot",
            )

            selected_type = filter_type_col.selectbox(
                "Tipo de evidencia",
                type_options,
                key="evidence_filter_type",
            )

            filtered_evidence = merged.copy()

            if selected_ot != "TODAS":
                filtered_evidence = filtered_evidence[
                    filtered_evidence["ot"] == selected_ot
                ]

            if selected_type != "TODAS":
                filtered_evidence = filtered_evidence[
                    filtered_evidence["tipo_evidencia"] == selected_type
                ]

            # Orden más reciente primero
            if "fecha_registro" in filtered_evidence.columns:
                filtered_evidence = filtered_evidence.sort_values(
                    "fecha_registro",
                    ascending=False,
                )

            st.caption(
                f"{len(filtered_evidence)} registro(s) con evidencia."
            )

            st.write("")

            # ----------------------------------------------------
            # REGISTROS DESPLEGABLES
            # ----------------------------------------------------
            for row_index, (_, row) in enumerate(
                filtered_evidence.iterrows()
            ):
                ot_label = clean_ot_label(
                    row.get("ot", "")
                )

                activity_label = str(
                    row.get(
                        "codigo_actividad",
                        "",
                    )
                    or ""
                ).strip()

                try:
                    progress_value = float(
                        row.get("avance", 0)
                        or 0
                    )
                except Exception:
                    progress_value = 0.0

                if abs(progress_value - round(progress_value)) < 0.0001:
                    progress_text = f"{int(round(progress_value))}%"
                else:
                    progress_text = f"{progress_value:.1f}%"

                expander_title = (
                    f"OT {ot_label} · "
                    f"{activity_label} · "
                    f"{progress_text}"
                )

                with st.expander(
                    expander_title,
                    expanded=False,
                ):
                    # --------------------------------------------
                    # INFORMACIÓN PRINCIPAL
                    # --------------------------------------------
                    c1, c2, c3, c4 = st.columns(4)

                    c1.write(
                        "**OT**  \n"
                        f"{ot_label}"
                    )

                    c2.write(
                        "**Actividad**  \n"
                        f"{activity_label}"
                    )

                    c3.write(
                        "**Avance**  \n"
                        f"{progress_text}"
                    )

                    c4.write(
                        "**Tipo de evidencia**  \n"
                        f"{row.get('tipo_evidencia', '') or '-'}"
                    )

                    description_text = str(
                        row.get(
                            "descripcion_actividad",
                            row.get(
                                "descripcion",
                                "",
                            ),
                        )
                        or ""
                    ).strip()

                    if description_text:
                        st.write(
                            f"**Descripción de actividad:** "
                            f"{description_text}"
                        )

                    # --------------------------------------------
                    # DETALLE DEL REPORTE
                    # --------------------------------------------
                    detail_col1, detail_col2, detail_col3 = st.columns(3)

                    supervisor_text = str(
                        row.get(
                            "supervisor",
                            "",
                        )
                        or ""
                    ).strip()

                    user_text = str(
                        row.get(
                            "usuario",
                            "",
                        )
                        or ""
                    ).strip()

                    date_text = ""

                    if pd.notna(
                        row.get("fecha_registro")
                    ):
                        try:
                            date_text = pd.to_datetime(
                                row["fecha_registro"]
                            ).strftime(
                                "%d/%m/%Y %H:%M"
                            )
                        except Exception:
                            date_text = str(
                                row.get(
                                    "fecha_registro",
                                    "",
                                )
                            )

                    detail_col1.write(
                        "**Supervisor**  \n"
                        f"{supervisor_text or '-'}"
                    )

                    detail_col2.write(
                        "**Usuario que registró**  \n"
                        f"{user_text or '-'}"
                    )

                    detail_col3.write(
                        "**Fecha / hora**  \n"
                        f"{date_text or '-'}"
                    )

                    advance_description = str(
                        row.get(
                            "descripcion_avance",
                            "",
                        )
                        or ""
                    ).strip()

                    if advance_description:
                        st.write(
                            "**Descripción del avance:**"
                        )
                        st.write(
                            advance_description
                        )

                    observations_text = str(
                        row.get(
                            "observaciones",
                            "",
                        )
                        or ""
                    ).strip()

                    if observations_text:
                        st.info(
                            "Observaciones / Restricciones: "
                            + observations_text
                        )

                    # --------------------------------------------
                    # GALERÍA DE FOTOS
                    # --------------------------------------------
                    urls = (
                        row.get("evidencias")
                        or []
                    )

                    if isinstance(urls, str):
                        urls = [urls]

                    urls = [
                        url
                        for url in urls
                        if str(url).strip()
                    ]

                    if urls:
                        st.markdown(
                            "**Evidencias fotográficas**"
                        )

                        image_columns = st.columns(
                            min(3, len(urls))
                        )

                        for image_index, url in enumerate(
                            urls
                        ):
                            image_columns[
                                image_index
                                % len(image_columns)
                            ].image(
                                url,
                                use_container_width=True,
                            )
                    else:
                        st.caption(
                            "Este registro no contiene fotografías disponibles."
                        )


# ============================================================
# INFORME DIARIO
# ============================================================
if page == "Informe diario":
    st.subheader(
        "Informe diario automático"
    )

    summary_text = (
        build_daily_summary(
            ots,
            activities,
            progress,
        )
    )

    edited_summary = (
        st.text_area(
            "Resumen editable",
            value=summary_text,
            height=420,
        )
    )

    st.download_button(
        "Descargar informe diario en TXT",
        edited_summary.encode(
            "utf-8"
        ),
        file_name=(
            f"informe_diario_"
            f"{datetime.now():%Y%m%d}.txt"
        ),
        mime="text/plain",
        use_container_width=True,
    )

    if not progress.empty:
        today = pd.Timestamp.now(
            tz=LIMA_TZ
        ).date()

        daily = progress[
            pd.to_datetime(
                progress[
                    "fecha_registro"
                ],
                errors="coerce",
            ).dt.date
            == today
        ].copy()

        if not daily.empty:
            activity_cols = [
                col
                for col in [
                    "id",
                    "ot_id",
                    "codigo_actividad",
                    "descripcion",
                ]
                if col
                in activities.columns
            ]

            daily_export = daily.merge(
                activities[
                    activity_cols
                ],
                left_on=(
                    "actividad_id"
                ),
                right_on="id",
                how="left",
                suffixes=(
                    "",
                    "_actividad",
                ),
            )

            ot_cols = [
                col
                for col in [
                    "id",
                    "ot",
                    "equipo",
                ]
                if col in ots.columns
            ]

            daily_export = (
                daily_export.merge(
                    ots[ot_cols],
                    left_on="ot_id",
                    right_on="id",
                    how="left",
                    suffixes=(
                        "",
                        "_ot",
                    ),
                )
            )

            if (
                "fecha_registro"
                in daily_export.columns
            ):
                daily_export[
                    "fecha_registro"
                ] = pd.to_datetime(
                    daily_export[
                        "fecha_registro"
                    ],
                    errors="coerce",
                ).dt.tz_localize(
                    None
                )

            output = io.BytesIO()

            with pd.ExcelWriter(
                output,
                engine="openpyxl",
            ) as writer:
                daily_export.to_excel(
                    writer,
                    index=False,
                    sheet_name=(
                        "Informe_Diario"
                    ),
                )

            st.download_button(
                "Descargar detalle diario en Excel",
                output.getvalue(),
                file_name=(
                    f"detalle_diario_"
                    f"{datetime.now():%Y%m%d}.xlsx"
                ),
                mime=(
                    "application/vnd."
                    "openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                use_container_width=True,
            )


# ============================================================
# REPORTE PDF
# ============================================================
if page == "Reporte PDF":
    st.subheader(
        "Generar informe ejecutivo en PDF"
    )

    st.write(
        "El informe incluye KPIs, "
        "Plan vs Real y resumen por OT."
    )

    try:
        pdf_bytes = (
            build_pdf_report(
                ots,
                activities,
                progress,
            )
        )

        st.download_button(
            "Descargar informe ejecutivo PDF",
            data=pdf_bytes,
            file_name=(
                f"informe_ejecutivo_"
                f"antapaccay_"
                f"{datetime.now():%Y%m%d_%H%M}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )

    except Exception as exc:
        st.error(
            f"No fue posible generar el PDF: {exc}"
        )


# ============================================================
# ADMINISTRAR OTs
# ============================================================
if page == "Administrar OTs":
    st.subheader(
        "Administrar OTs"
    )

    tab1, tab2 = st.tabs(
        [
            "Nueva OT",
            "Nueva actividad",
        ]
    )

    with tab1:
        with st.form(
            "new_ot",
            clear_on_submit=True,
        ):
            ot_number = st.text_input(
                "Número de OT *"
            )

            equipment = st.text_input(
                "Equipo"
            )

            ot_description = (
                st.text_area(
                    "Descripción de OT *"
                )
            )

            active = st.checkbox(
                "Activa",
                value=True,
            )

            create_ot = (
                st.form_submit_button(
                    "Crear OT",
                    type="primary",
                )
            )

        if create_ot:
            if (
                not ot_number.strip()
                or not ot_description.strip()
            ):
                st.error(
                    "La OT y la descripción son obligatorias."
                )

            else:
                try:
                    supabase.table(
                        "ots"
                    ).insert(
                        {
                            "ot": (
                                ot_number.strip()
                            ),
                            "equipo": (
                                equipment.strip()
                            ),
                            "descripcion": (
                                ot_description.strip()
                            ),
                            "activo": active,
                        }
                    ).execute()

                    invalidate()

                    st.success(
                        "OT creada."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        "No fue posible crear la OT: "
                        f"{exc}"
                    )

    with tab2:
        if ots.empty:
            st.info(
                "Primero cree una OT."
            )

        else:
            with st.form(
                "new_activity",
                clear_on_submit=True,
            ):
                selected_ot_admin = (
                    st.selectbox(
                        "OT *",
                        ots["ot"]
                        .astype(str)
                        .sort_values()
                        .tolist(),
                    )
                )

                activity_code = (
                    st.text_input(
                        "Código de actividad *"
                    )
                )

                activity_description = (
                    st.text_area(
                        "Descripción de actividad *"
                    )
                )

                c1, c2, c3 = (
                    st.columns(3)
                )

                supervisor = c1.text_input(
                    "Supervisor"
                )

                specialty = c2.text_input(
                    "Especialidad"
                )

                group = c3.text_input(
                    "Grupo"
                )

                c1, c2, c3 = (
                    st.columns(3)
                )

                weight = c1.number_input(
                    "Peso",
                    min_value=0.01,
                    value=1.0,
                    step=0.1,
                )

                start_plan = (
                    c2.date_input(
                        "Inicio planificado"
                    )
                )

                finish_plan = (
                    c3.date_input(
                        "Fin planificado"
                    )
                )

                create_activity = (
                    st.form_submit_button(
                        "Crear actividad",
                        type="primary",
                    )
                )

            if create_activity:
                if (
                    not activity_code.strip()
                    or not activity_description.strip()
                ):
                    st.error(
                        "Código y descripción son obligatorios."
                    )

                else:
                    try:
                        ot_id = int(
                            ots[
                                ots["ot"]
                                .astype(str)
                                == selected_ot_admin
                            ]
                            .iloc[0]["id"]
                        )

                        payload = {
                            "ot_id": ot_id,
                            "codigo_actividad": (
                                activity_code.strip()
                            ),
                            "descripcion": (
                                activity_description.strip()
                            ),
                            "supervisor": (
                                supervisor.strip()
                            ),
                            "especialidad": (
                                specialty.strip()
                            ),
                            "grupo": (
                                group.strip()
                            ),
                            "peso": float(
                                weight
                            ),
                            "inicio_plan": (
                                start_plan.isoformat()
                            ),
                            "fin_plan": (
                                finish_plan.isoformat()
                            ),
                        }

                        supabase.table(
                            "actividades"
                        ).insert(
                            payload
                        ).execute()

                        invalidate()

                        st.success(
                            "Actividad creada."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            "No fue posible crear la actividad: "
                            f"{exc}"
                        )


# ============================================================
# IMPORTAR BASE
# ============================================================
if page == "Importar base":
    st.subheader(
        "Importar / Reiniciar base PDP"
    )

    st.warning(
        "Esta opción reemplaza OTs, actividades y avances asociados. "
        "Úsela únicamente para cargar una nueva PDP completa."
    )

    if supabase_admin is None:
        st.error(
            "No está configurada la Service Role Key "
            "en [supabase_admin] de Streamlit Secrets."
        )

    else:
        uploaded_excel = (
            st.file_uploader(
                "Cargar archivo Excel",
                type=["xlsx"],
                key="base_import",
            )
        )

        st.caption(
            "El Excel debe incluir dos hojas: "
            "`ots` y `actividades`."
        )

        if uploaded_excel:
            try:
                xls = pd.ExcelFile(
                    uploaded_excel
                )

                sheet_lookup = {
                    name.lower().strip(): name
                    for name in xls.sheet_names
                }

                if (
                    "ots"
                    not in sheet_lookup
                    or "actividades"
                    not in sheet_lookup
                ):
                    raise ValueError(
                        "El Excel debe contener las hojas "
                        "'ots' y 'actividades'."
                    )

                import_ots = pd.read_excel(
                    uploaded_excel,
                    sheet_name=(
                        sheet_lookup["ots"]
                    ),
                )

                uploaded_excel.seek(0)

                import_activities = (
                    pd.read_excel(
                        uploaded_excel,
                        sheet_name=(
                            sheet_lookup[
                                "actividades"
                            ]
                        ),
                    )
                )

                st.success(
                    "Archivo leído correctamente."
                )

                c1, c2 = st.columns(2)

                c1.metric(
                    "OTs detectadas",
                    len(import_ots),
                )

                c2.metric(
                    "Actividades detectadas",
                    len(import_activities),
                )

                confirm_reset = (
                    st.checkbox(
                        "Confirmo que deseo reemplazar "
                        "la base actual."
                    )
                )

                run_import = st.button(
                    "REINICIAR E IMPORTAR",
                    type="primary",
                    disabled=(
                        not confirm_reset
                    ),
                    use_container_width=True,
                )

                if run_import:
                    def clean_text(
                        value,
                    ):
                        if (
                            pd.isna(value)
                            or value is None
                        ):
                            return ""

                        text = str(
                            value
                        ).strip()

                        if text.endswith(
                            ".0"
                        ):
                            try:
                                numeric = float(
                                    text
                                )

                                if numeric.is_integer():
                                    return str(
                                        int(
                                            numeric
                                        )
                                    )

                            except Exception:
                                pass

                        return text

                    def clean_datetime(
                        value,
                    ):
                        if (
                            pd.isna(value)
                            or value
                            in ("", None)
                        ):
                            return None

                        parsed = pd.to_datetime(
                            value,
                            errors="coerce",
                            dayfirst=True,
                        )

                        if pd.isna(
                            parsed
                        ):
                            return None

                        if getattr(
                            parsed,
                            "tzinfo",
                            None,
                        ) is not None:
                            parsed = (
                                parsed.tz_localize(
                                    None
                                )
                            )

                        return (
                            parsed.isoformat(
                                timespec="seconds"
                            )
                        )

                    def clean_number(
                        value,
                        default=0,
                    ):
                        if (
                            pd.isna(value)
                            or value
                            in ("", None)
                        ):
                            return default

                        return float(value)

                    def clean_boolean(
                        value,
                        default=True,
                    ):
                        if (
                            pd.isna(value)
                            or value
                            in ("", None)
                        ):
                            return default

                        if isinstance(
                            value,
                            bool,
                        ):
                            return value

                        return (
                            str(value)
                            .strip()
                            .lower()
                            not in {
                                "false",
                                "falso",
                                "0",
                                "no",
                            }
                        )

                    clean_ots = []

                    for _, row in (
                        import_ots.iterrows()
                    ):
                        ot_text = clean_text(
                            row.get("ot")
                        )

                        description = (
                            clean_text(
                                row.get(
                                    "descripcion"
                                )
                            )
                        )

                        if (
                            not ot_text
                            or not description
                        ):
                            continue

                        clean_ots.append(
                            {
                                "ot": ot_text,
                                "equipo": (
                                    clean_text(
                                        row.get(
                                            "equipo"
                                        )
                                    )
                                ),
                                "descripcion": (
                                    description
                                ),
                                "activo": (
                                    clean_boolean(
                                        row.get(
                                            "activo"
                                        ),
                                        True,
                                    )
                                ),
                            }
                        )

                    valid_ot_numbers = {
                        row["ot"]
                        for row in clean_ots
                    }

                    clean_activities = []

                    for _, row in (
                        import_activities
                        .iterrows()
                    ):
                        ot_text = clean_text(
                            row.get("ot")
                        )

                        activity_code = (
                            clean_text(
                                row.get(
                                    "codigo_actividad"
                                )
                            )
                        )

                        activity_description = (
                            clean_text(
                                row.get(
                                    "descripcion"
                                )
                            )
                        )

                        if (
                            not ot_text
                            or ot_text
                            not in valid_ot_numbers
                            or not activity_code
                            or not activity_description
                        ):
                            continue

                        payload = {
                            "ot": ot_text,
                            "codigo_actividad": (
                                activity_code
                            ),
                            "descripcion": (
                                activity_description
                            ),
                            "supervisor": (
                                clean_text(
                                    row.get(
                                        "supervisor"
                                    )
                                )
                            ),
                            "especialidad": (
                                clean_text(
                                    row.get(
                                        "especialidad"
                                    )
                                )
                            ),
                            "grupo": (
                                clean_text(
                                    row.get(
                                        "grupo"
                                    )
                                )
                            ),
                            "peso": (
                                clean_number(
                                    row.get(
                                        "peso"
                                    ),
                                    1,
                                )
                            ),
                            "inicio_plan": (
                                clean_datetime(
                                    row.get(
                                        "inicio_plan"
                                    )
                                )
                            ),
                            "fin_plan": (
                                clean_datetime(
                                    row.get(
                                        "fin_plan"
                                    )
                                )
                            ),
                        }

                        # Columnas opcionales compatibles con
                        # la versión operativa actual.
                        optional_text_cols = [
                            "seccion",
                            "personal",
                            "duracion_h",
                            "hh_plan",
                        ]

                        for col in optional_text_cols:
                            if (
                                col
                                in import_activities.columns
                            ):
                                value = row.get(
                                    col
                                )

                                if col in {
                                    "personal",
                                    "duracion_h",
                                    "hh_plan",
                                }:
                                    payload[col] = (
                                        clean_number(
                                            value,
                                            0,
                                        )
                                    )
                                else:
                                    payload[col] = (
                                        clean_text(
                                            value
                                        )
                                    )

                        clean_activities.append(
                            payload
                        )

                    if not clean_ots:
                        raise ValueError(
                            "El Excel no contiene OTs válidas."
                        )

                    if not clean_activities:
                        raise ValueError(
                            "El Excel no contiene actividades válidas."
                        )

                    progress_bar = (
                        st.progress(
                            0,
                            text=(
                                "Validación completada."
                            ),
                        )
                    )

                    progress_bar.progress(
                        15,
                        text=(
                            "Eliminando la base anterior..."
                        ),
                    )

                    supabase_admin.table(
                        "ots"
                    ).delete().neq(
                        "id",
                        0,
                    ).execute()

                    progress_bar.progress(
                        35,
                        text=(
                            "Cargando nuevas OTs..."
                        ),
                    )

                    batch_size = 200

                    for start_index in range(
                        0,
                        len(clean_ots),
                        batch_size,
                    ):
                        supabase_admin.table(
                            "ots"
                        ).insert(
                            clean_ots[
                                start_index:
                                start_index
                                + batch_size
                            ]
                        ).execute()

                    refreshed_ots = (
                        pd.DataFrame(
                            supabase_admin.table(
                                "ots"
                            )
                            .select(
                                "id,ot"
                            )
                            .execute()
                            .data
                        )
                    )

                    ot_map = dict(
                        zip(
                            refreshed_ots[
                                "ot"
                            ].astype(str),
                            refreshed_ots[
                                "id"
                            ],
                        )
                    )

                    activity_payloads = []

                    for row in clean_activities:
                        activity_payload = {
                            key: value
                            for key, value
                            in row.items()
                            if key != "ot"
                        }

                        activity_payload[
                            "ot_id"
                        ] = int(
                            ot_map[
                                row["ot"]
                            ]
                        )

                        activity_payloads.append(
                            activity_payload
                        )

                    progress_bar.progress(
                        60,
                        text=(
                            "Cargando nuevas actividades..."
                        ),
                    )

                    for start_index in range(
                        0,
                        len(activity_payloads),
                        batch_size,
                    ):
                        supabase_admin.table(
                            "actividades"
                        ).insert(
                            activity_payloads[
                                start_index:
                                start_index
                                + batch_size
                            ]
                        ).execute()

                    progress_bar.progress(
                        90,
                        text=(
                            "Actualizando el dashboard..."
                        ),
                    )

                    invalidate()
                    st.cache_data.clear()

                    progress_bar.progress(
                        100,
                        text=(
                            "Nueva base cargada correctamente."
                        ),
                    )

                    st.success(
                        f"Reinicio completado. "
                        f"{len(clean_ots)} OTs y "
                        f"{len(activity_payloads)} actividades cargadas."
                    )

                    st.balloons()

            except Exception as exc:
                st.error(
                    "No fue posible leer o importar la base: "
                    f"{exc}"
                )


# ============================================================
# EXPORTAR REPORTE
# ============================================================
if page == "Exportar reporte":
    st.subheader(
        "Exportar reporte consolidado"
    )

    if progress.empty:
        st.info(
            "No existen avances para exportar."
        )

    else:
        activity_cols = [
            col
            for col in [
                "id",
                "ot_id",
                "codigo_actividad",
                "descripcion",
                "supervisor",
                "especialidad",
                "grupo",
                "inicio_plan",
                "fin_plan",
            ]
            if col
            in activities.columns
        ]

        export = progress.merge(
            activities[
                activity_cols
            ],
            left_on="actividad_id",
            right_on="id",
            how="left",
            suffixes=(
                "",
                "_actividad",
            ),
        )

        ot_cols = [
            col
            for col in [
                "id",
                "ot",
                "equipo",
            ]
            if col
            in ots.columns
        ]

        export = export.merge(
            ots[ot_cols],
            left_on="ot_id",
            right_on="id",
            how="left",
            suffixes=(
                "",
                "_ot",
            ),
        )

        if (
            "fecha_registro"
            in export.columns
        ):
            export[
                "fecha_registro"
            ] = pd.to_datetime(
                export[
                    "fecha_registro"
                ],
                errors="coerce",
            )

            if getattr(
                export[
                    "fecha_registro"
                ].dt,
                "tz",
                None,
            ) is not None:
                export[
                    "fecha_registro"
                ] = export[
                    "fecha_registro"
                ].dt.tz_localize(
                    None
                )

        if (
            "evidencias"
            in export.columns
        ):
            export[
                "evidencias"
            ] = export[
                "evidencias"
            ].apply(
                lambda value: (
                    "\n".join(value)
                    if isinstance(
                        value,
                        list,
                    )
                    else str(
                        value or ""
                    )
                )
            )

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl",
        ) as writer:
            export.to_excel(
                writer,
                index=False,
                sheet_name=(
                    "Avances"
                ),
            )

        st.download_button(
            "Descargar reporte consolidado",
            output.getvalue(),
            file_name=(
                f"reporte_antapaccay_"
                f"{datetime.now():%Y%m%d_%H%M}.xlsx"
            ),
            mime=(
                "application/vnd."
                "openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )
