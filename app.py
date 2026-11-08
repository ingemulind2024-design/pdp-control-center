import io
import base64
import json
import hashlib
import secrets
import html
import hmac
import time
import uuid
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import extra_streamlit_components as stx
from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
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
    :root { --mainin-navy:#0D2F53; --mainin-blue:#166099; --mainin-ink:#16283B; --mainin-muted:#637386; --mainin-line:#E1E8EF; }
    [data-testid="stAppViewContainer"] {background:#F5F8FC;}
    [data-testid="stHeader"] {background:rgba(245,248,252,.94);}
    [data-testid="stSidebar"] {background:linear-gradient(180deg,#092746 0%,#0D345E 100%);}
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:.38rem;}
    [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,[data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,[data-testid="stSidebar"] span,
    [data-testid="stSidebar"] small {color:#F4F9FF !important;}
    [data-testid="stSidebar"] [role="radiogroup"] label {padding:5px 6px; border-radius:8px;}
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {background:rgba(255,255,255,.10);}
    [data-testid="stSidebar"] [data-testid="stButton"] button {color:#0D2F53 !important; background:#FFFFFF; border-color:#CDD8E3;}
    [data-testid="stSidebar"] hr {border-color:#385878;}
    .block-container {max-width:1750px; padding-top:1.0rem; padding-bottom:2rem;}
    h1,h2,h3 {color:#0D2F53 !important;letter-spacing:-.018em;}
    h1 {font-size:1.8rem !important;}
    h2 {font-size:1.42rem !important;}
    h3 {font-size:1.13rem !important;}
    [data-testid="stMetric"] {background:#FFFFFF; border:1px solid var(--mainin-line);padding:15px 17px;border-radius:12px;box-shadow:0 2px 8px rgba(13,47,83,.045);}
    [data-testid="stMetricLabel"] {color:#50667A !important;}
    [data-testid="stMetricValue"] {color:#0D2F53 !important;}
    .mainin-header {border:1px solid #DCE7F2;border-left:5px solid #2271AD;border-radius:14px;background:linear-gradient(110deg,#FFF,#EFF6FC);padding:20px 22px 17px;margin:4px 0 20px;box-shadow:0 5px 19px rgba(13,47,83,.045);}
    .mainin-eyebrow {font-size:.72rem;letter-spacing:.11em;font-weight:750;color:#2871AA;margin-bottom:7px;}
    .mainin-headline {font-size:clamp(1.15rem,2.25vw,1.85rem);font-weight:800;color:#0D2F53;line-height:1.25;letter-spacing:-.022em;}
    .mainin-subline {color:#61758B;font-size:.85rem;margin-top:7px;}
    .mainin-section {background:linear-gradient(90deg,#0D345E,#165D91);padding:12px 15px;border-radius:10px;margin:11px 0 17px;color:white;font-weight:700;letter-spacing:.01em;}
    .mainin-chip {display:inline-block;background:#E8F1FA;color:#155682;border-radius:999px;padding:5px 11px;font-size:.78rem;font-weight:700;margin:6px 0;}
    [data-testid="stDataFrame"] {border-radius:10px;overflow:hidden;}
    .stButton > button[kind="primary"],.stDownloadButton > button[kind="primary"] {background:#13578C !important;border-color:#13578C !important;color:white !important;}
    .stButton > button[kind="primary"]:hover,.stDownloadButton > button[kind="primary"]:hover {background:#0D365E !important;}
    [data-testid="stTextInput"] input,[data-testid="stSelectbox"] [data-baseweb="select"],
    [data-testid="stTextArea"] textarea {border-radius:8px;}
    @media(max-width:768px) {
      .mainin-header {padding:14px 12px;margin-top:0;margin-bottom:12px;}
      .mainin-subline {font-size:.76rem;}
      .block-container {padding-left:.7rem;padding-right:.7rem;}
      [data-testid="stMetric"] {padding:10px;}
      [data-testid="stMetricValue"] {font-size:1.15rem;}
    }
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


# ============================================================
# SESIÓN PERSISTENTE SEGURA - ANTAPACCAY (7 DÍAS)
# ============================================================
# Las cookies nunca almacenan usuario/contraseña en texto plano.
# Se firma un token con una clave exclusiva del servidor. Su firma
# depende también de la contraseña actual del usuario, de modo que
# cambiar esa contraseña invalida las sesiones previas.
COOKIE_SESION = "mainin_antapaccay_session_v32"
DIAS_SESION_PERSISTENTE = 7
COOKIE_MAX_AGE = DIAS_SESION_PERSISTENTE * 24 * 60 * 60

cookie_manager = stx.CookieManager(key="mainin_antapaccay_cookie_manager")


def _session_signing_key() -> bytes | None:
    """Obtiene una clave privada persistente de Streamlit Secrets.

    Prioridad: [session].signing_key. Si ya existe la Service Role Key,
    puede usarse como origen secreto para derivar una clave independiente.
    Nunca se usa la clave anon/publishable de Supabase.
    """
    raw = ""
    try:
        raw = str(st.secrets.get("session", {}).get("signing_key", "")).strip()
    except Exception:
        pass
    if not raw:
        try:
            raw = str(st.secrets.get("supabase_admin", {}).get("key", "")).strip()
        except Exception:
            pass
    if not raw:
        return None
    return hmac.new(
        raw.encode("utf-8"),
        b"MAININ/ANTAPACCAY/AUTH-COOKIE/V1",
        hashlib.sha256,
    ).digest()


def _account_signing_key(base_key: bytes, username: str, account: dict) -> bytes:
    """Vincula cada token con la credencial actual del usuario."""
    return hmac.new(
        base_key,
        ("account:" + username + "\x00" + account["password"]).encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _make_session_token(username: str, account: dict) -> str | None:
    base_key = _session_signing_key()
    if not base_key:
        return None
    now = int(time.time())
    payload = {
        "v": 1,
        "u": username,
        "iat": now,
        "exp": now + COOKIE_MAX_AGE,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signing_key = _account_signing_key(base_key, username, account)
    signature = hmac.new(signing_key, encoded.encode("ascii"), hashlib.sha256).digest()
    return encoded + "." + base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def _verify_session_token(raw_token: object, users: dict) -> tuple[str, dict] | None:
    base_key = _session_signing_key()
    if not base_key or not isinstance(raw_token, str) or len(raw_token) > 2048:
        return None
    try:
        encoded, encoded_sig = raw_token.split(".")
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
        )
        username = payload.get("u")
        account = users.get(username)
        if not account or not account.get("password"):
            return None
        now = int(time.time())
        issued = int(payload.get("iat", 0))
        expires = int(payload.get("exp", 0))
        if (payload.get("v") != 1 or issued > now + 60 or
                issued <= 0 or expires <= now or
                expires - issued > COOKIE_MAX_AGE):
            return None
        signature = base64.urlsafe_b64decode(
            encoded_sig + "=" * (-len(encoded_sig) % 4)
        )
        user_key = _account_signing_key(base_key, username, account)
        expected = hmac.new(user_key, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        return username, account
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        return None


def _set_authenticated_user(username: str, account: dict) -> None:
    st.session_state["authenticated"] = True
    st.session_state["username"] = username
    st.session_state["display_name"] = account["name"]
    st.session_state["role"] = account["role"]


def _read_session_cookie() -> str | None:
    # st.context.cookies refleja la petición inicial. La lectura por
    # CookieManager contempla navegadores que cargan la cookie después.
    try:
        cookie = cookie_manager.get(COOKIE_SESION)
        if isinstance(cookie, str) and cookie:
            return cookie
    except Exception:
        pass
    try:
        cookie = st.context.cookies.get(COOKIE_SESION)
        if isinstance(cookie, str) and cookie:
            return cookie
    except Exception:
        pass
    return None


def _handle_cookie_operations() -> None:
    """Ejecuta la orden en una pasada completa, no antes de st.rerun()."""
    token = st.session_state.pop("auth_cookie_write_pending", None)
    if token:
        try:
            cookie_manager.set(
                COOKIE_SESION,
                token,
                key="set_antapaccay_" + hashlib.sha256(token.encode()).hexdigest()[:16],
                path="/",
                expires_at=datetime.now(timezone.utc) + timedelta(days=DIAS_SESION_PERSISTENTE),
                max_age=COOKIE_MAX_AGE,
                secure=True,
                same_site="strict",
            )
        except Exception:
            st.warning("La sesión está iniciada, pero no se pudo guardar en este navegador.")

    if st.session_state.pop("auth_cookie_delete_pending", False):
        try:
            cookie_manager.delete(COOKIE_SESION, key="delete_antapaccay_cookie")
        except Exception:
            st.warning("No fue posible eliminar la cookie de este navegador.")


_handle_cookie_operations()


def authenticate() -> bool:
    if st.session_state.get("authenticated"):
        return True

    users = load_users()
    if not st.session_state.get("auth_cookie_restore_blocked", False):
        existing_token = _read_session_cookie()
        restored = _verify_session_token(existing_token, users)
        if restored:
            username, account = restored
            _set_authenticated_user(username, account)
            return True

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
            remember = st.checkbox(
                "Mantener sesión iniciada durante 7 días",
                value=True,
                disabled=(_session_signing_key() is None),
                help="Usar preferentemente en un dispositivo personal.",
            )
            submit = st.form_submit_button(
                "INGRESAR", type="primary", use_container_width=True
            )

        if _session_signing_key() is None:
            st.caption(
                "Para recordar la sesión, configure [session].signing_key "
                "en Secrets de Streamlit. El ingreso normal sigue disponible."
            )

        if submit:
            account = users.get(username)
            if account and hmac.compare_digest(password, account["password"]):
                _set_authenticated_user(username, account)
                st.session_state["auth_cookie_restore_blocked"] = False
                if remember:
                    token = _make_session_token(username, account)
                    if token:
                        st.session_state["auth_cookie_write_pending"] = token
                else:
                    st.session_state["auth_cookie_delete_pending"] = True
                # La cookie se escribe en la siguiente ejecución completa.
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
    max_side: int = 1280,
    quality: int = 78,
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


def upload_evidence(
    file,
    ot: str,
    activity_id: str,
    max_retries: int = 2,
) -> dict:
    """
    Carga robusta de evidencia.

    Prioridad:
    1. Cliente admin/service_role para evitar bloqueos RLS de Storage.
    2. Cliente normal como fallback si no existe service_role.

    Devuelve el error real si la carga falla.
    """
    original_bytes = file.getvalue()
    compressed_bytes, ext, content_type = compress_evidence_image(file)

    safe_ot = "".join(
        ch for ch in str(ot)
        if ch.isalnum() or ch in "-_"
    ) or "OT"

    filename = (
        f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_"
        f"{uuid.uuid4().hex[:12]}.{ext}"
    )

    path = f"{safe_ot}/{activity_id}/{filename}"

    # Para Storage usar service_role si está disponible.
    storage_client = (
        supabase_admin
        if supabase_admin is not None
        else supabase
    )

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            storage_client.storage.from_(BUCKET).upload(
                path=path,
                file=compressed_bytes,
                file_options={
                    "cache-control": "3600",
                    "upsert": "false",
                    "content-type": content_type,
                },
            )

            # URL pública. Si el bucket es privado, este URL no servirá
            # para visualizar; la carga sí puede haber sido exitosa.
            public_url = storage_client.storage.from_(
                BUCKET
            ).get_public_url(path)

            return {
                "url": public_url,
                "path": path,
                "original_size": len(original_bytes),
                "compressed_size": len(compressed_bytes),
                "attempts": attempt,
                "filename": getattr(file, "name", "evidencia"),
                "used_admin": supabase_admin is not None,
            }

        except Exception as exc:
            last_error = exc

            if attempt < max_retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(
        "FALLO_STORAGE | "
        f"archivo={getattr(file, 'name', 'evidencia')} | "
        f"bucket={BUCKET} | "
        f"service_role={'SI' if supabase_admin is not None else 'NO'} | "
        f"error={last_error}"
    )


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
    Lógica idéntica a Chinalco, adaptada a Antapaccay.

    - PLAN = promedio simple del avance esperado de TODAS las actividades.
    - REAL = promedio simple del último avance de TODAS las actividades.
    - Actividades sin reporte = 0%.
    - Cortes oficiales = 00:00 / 07:00 / 14:00 / 19:00.
    - Se agrega punto EN VIVO con hora actual.
    - REAL se mantiene hasta AHORA y no se proyecta al futuro.
    """
    if activities.empty:
        return pd.DataFrame(
            columns=["fecha", "PLAN", "REAL", "tipo_punto"]
        )

    acts = activities.copy()

    acts["inicio_plan"] = pd.to_datetime(
        acts["inicio_plan"],
        errors="coerce",
    )
    acts["fin_plan"] = pd.to_datetime(
        acts["fin_plan"],
        errors="coerce",
    )

    for col in ["inicio_plan", "fin_plan"]:
        if getattr(acts[col].dt, "tz", None) is not None:
            acts[col] = acts[col].dt.tz_localize(None)

    valid = acts.dropna(
        subset=[
            "id",
            "inicio_plan",
            "fin_plan",
        ]
    ).copy()

    if valid.empty:
        return pd.DataFrame(
            columns=["fecha", "PLAN", "REAL", "tipo_punto"]
        )

    invalidas = (
        valid["fin_plan"]
        <= valid["inicio_plan"]
    )

    valid.loc[
        invalidas,
        "fin_plan",
    ] = (
        valid.loc[
            invalidas,
            "inicio_plan",
        ]
        + pd.Timedelta(minutes=1)
    )

    inicio_programa = valid["inicio_plan"].min()
    fin_programa = valid["fin_plan"].max()

    # ------------------------------------------------------------
    # CORTES OFICIALES
    # ------------------------------------------------------------
    cortes = [inicio_programa]
    tipos = ["INICIO"]

    dia = inicio_programa.normalize()
    dia_final = fin_programa.normalize()

    horas_corte = [0, 7, 14, 19]

    while dia <= dia_final:
        for hora in horas_corte:
            corte = dia + pd.Timedelta(hours=hora)

            if (
                inicio_programa
                < corte
                < fin_programa
            ):
                cortes.append(corte)
                tipos.append("CORTE")

        dia += pd.Timedelta(days=1)

    cortes.append(fin_programa)
    tipos.append("FIN")

    # ------------------------------------------------------------
    # PUNTO EN VIVO
    # ------------------------------------------------------------
    ahora_lima = (
        pd.Timestamp.now(
            tz="America/Lima"
        )
        .tz_localize(None)
    )

    if (
        inicio_programa
        < ahora_lima
        < fin_programa
    ):
        cortes.append(ahora_lima)
        tipos.append("EN VIVO")

    puntos = pd.DataFrame(
        {
            "fecha": cortes,
            "tipo_punto": tipos,
        }
    )

    puntos["priority"] = puntos[
        "tipo_punto"
    ].map(
        {
            "EN VIVO": 4,
            "INICIO": 3,
            "FIN": 3,
            "CORTE": 1,
        }
    ).fillna(0)

    puntos = (
        puntos
        .sort_values(
            ["fecha", "priority"],
            ascending=[True, False],
        )
        .drop_duplicates(
            subset=["fecha"],
            keep="first",
        )
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    total_actividades = len(valid)

    # ------------------------------------------------------------
    # PLAN - PROMEDIO SIMPLE
    # ------------------------------------------------------------
    plan_values = []

    for corte in puntos["fecha"]:
        suma_plan = 0.0

        for _, actividad in valid.iterrows():
            inicio_act = actividad["inicio_plan"]
            fin_act = actividad["fin_plan"]

            if corte <= inicio_act:
                avance = 0.0

            elif corte >= fin_act:
                avance = 100.0

            else:
                duracion = (
                    fin_act - inicio_act
                ).total_seconds()

                transcurrido = (
                    corte - inicio_act
                ).total_seconds()

                avance = (
                    transcurrido
                    / duracion
                    * 100
                    if duracion > 0
                    else 100
                )

            suma_plan += max(
                0,
                min(100, avance),
            )

        plan_values.append(
            suma_plan
            / total_actividades
        )

    # ------------------------------------------------------------
    # REAL - PROMEDIO SIMPLE, IGUAL A CHINALCO
    # ------------------------------------------------------------
    prog = progress.copy()

    if not prog.empty:
        prog["fecha_registro"] = (
            pd.to_datetime(
                prog["fecha_registro"],
                errors="coerce",
                utc=True,
            )
            .dt.tz_convert("America/Lima")
            .dt.tz_localize(None)
        )

        prog["avance"] = pd.to_numeric(
            prog["avance"],
            errors="coerce",
        ).fillna(0).clip(0, 100)

        prog = prog.dropna(
            subset=[
                "actividad_id",
                "fecha_registro",
            ]
        )

    real_values = []
    ids_actividades = valid["id"].tolist()

    for corte in puntos["fecha"]:
        if prog.empty:
            real_values.append(
                0.0
                if corte <= ahora_lima
                else None
            )
            continue

        # Solo ocultar puntos realmente futuros.
        if corte > ahora_lima:
            real_values.append(None)
            continue

        disponibles = prog[
            prog["fecha_registro"] <= corte
        ]

        if disponibles.empty:
            real_values.append(0.0)
            continue

        ultimos = (
            disponibles
            .sort_values("fecha_registro")
            .groupby(
                "actividad_id",
                as_index=False,
            )
            .tail(1)
            .set_index("actividad_id")[
                "avance"
            ]
            .to_dict()
        )

        suma_real = sum(
            float(
                ultimos.get(
                    actividad_id,
                    0,
                )
            )
            for actividad_id
            in ids_actividades
        )

        real_values.append(
            suma_real
            / total_actividades
        )

    curva = pd.DataFrame(
        {
            "fecha": pd.to_datetime(
                puntos["fecha"]
            ),
            "PLAN": plan_values,
            "REAL": real_values,
            "tipo_punto": puntos[
                "tipo_punto"
            ].tolist(),
        }
    )

    curva["PLAN"] = (
        pd.to_numeric(
            curva["PLAN"],
            errors="coerce",
        )
        .fillna(0)
        .clip(0, 100)
        .cummax()
    )

    indices_real = (
        curva.index[
            curva["REAL"].notna()
        ]
        .tolist()
    )

    if indices_real:
        curva.loc[
            indices_real,
            "REAL",
        ] = (
            pd.to_numeric(
                curva.loc[
                    indices_real,
                    "REAL",
                ],
                errors="coerce",
            )
            .fillna(0)
            .clip(0, 100)
            .cummax()
        )

    curva.loc[
        curva.index[0],
        "PLAN",
    ] = 0.0

    curva.loc[
        curva.index[-1],
        "PLAN",
    ] = 100.0

    if pd.isna(
        curva.loc[
            curva.index[0],
            "REAL",
        ]
    ):
        curva.loc[
            curva.index[0],
            "REAL",
        ] = 0.0

    return curva
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
                    size=7,
                    symbol="circle",
                    line=dict(width=1),
                ),
                text=[
                    f"{live_row['PLAN']:.1f}%"
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
                        size=7,
                        symbol="circle",
                        line=dict(width=1),
                    ),
                    text=[
                        f"{live_row['REAL']:.1f}%"
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
    """
    KPI con la misma metodología de Chinalco:
    Avance general = promedio simple del último avance de
    TODAS las actividades.
    """
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

    avance_general = float(
        status["avance_real"].mean()
    ) if not status.empty else 0.0

    culminadas = int(
        (
            status["avance_real"]
            >= 100
        ).sum()
    )

    parciales = int(
        (
            (
                status["avance_real"]
                > 0
            )
            & (
                status["avance_real"]
                < 100
            )
        ).sum()
    )

    no_iniciadas = int(
        (
            status["avance_real"]
            <= 0
        ).sum()
    )

    if "hh_plan" in status.columns:
        hh_plan_series = pd.to_numeric(
            status["hh_plan"],
            errors="coerce",
        ).fillna(0)
    else:
        hh_plan_series = pd.Series(
            0.0,
            index=status.index,
        )

    hh_plan = float(
        hh_plan_series.sum()
    )

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
# INFORME PDF POR OT / ACTIVIDAD
# ============================================================
def _safe_report_text(value, default="-") -> str:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    value = str(value).strip()
    return value if value else default


def _fmt_number(value, decimals=0, default="-") -> str:
    try:
        number = float(value)
        if pd.isna(number):
            return default

        if decimals == 0:
            return f"{number:.0f}"

        return f"{number:.{decimals}f}"
    except Exception:
        return default


def _download_report_image(url: str) -> io.BytesIO | None:
    """
    Descarga una evidencia para insertarla dentro del PDF.
    Si la URL falla, el reporte continúa sin bloquearse.
    """
    if not url:
        return None

    try:
        response = requests.get(
            str(url),
            timeout=15,
        )
        response.raise_for_status()

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
            .lower()
        )

        if (
            "image" not in content_type
            and not response.content
        ):
            return None

        return io.BytesIO(
            response.content
        )

    except Exception:
        return None


def _evidence_stage_urls(
    activity_id,
    progress: pd.DataFrame,
) -> dict:
    """
    Devuelve como máximo una fotografía representativa
    por etapa: INICIO / DURANTE / FINAL.

    Prioriza el registro más reciente de cada etapa.
    """
    stages = {
        "INICIO": None,
        "DURANTE": None,
        "FINAL": None,
    }

    if progress.empty:
        return stages

    activity_progress = progress[
        progress["actividad_id"]
        == activity_id
    ].copy()

    if activity_progress.empty:
        return stages

    if "fecha_registro" in activity_progress.columns:
        activity_progress = (
            activity_progress.sort_values(
                "fecha_registro",
                ascending=False,
            )
        )

    for _, row in activity_progress.iterrows():
        stage = str(
            row.get(
                "tipo_evidencia",
                "",
            )
            or ""
        ).strip().upper()

        # Compatibilidad con registros anteriores.
        stage_map = {
            "ANTES": "INICIO",
            "INICIO": "INICIO",
            "DURANTE": "DURANTE",
            "DESPUÉS": "FINAL",
            "DESPUES": "FINAL",
            "FINAL": "FINAL",
        }

        stage = stage_map.get(
            stage,
            stage,
        )

        if stage not in stages:
            continue

        if stages[stage] is not None:
            continue

        urls = row.get(
            "evidencias",
            [],
        )

        if isinstance(urls, str):
            urls = [urls]

        urls = [
            str(url).strip()
            for url in (urls or [])
            if str(url).strip()
        ]

        if urls:
            stages[stage] = urls[0]

    return stages


def _latest_activity_report(
    activity_id,
    progress: pd.DataFrame,
) -> dict:
    if progress.empty:
        return {
            "avance": 0,
            "descripcion_avance": "",
            "observaciones": "",
            "usuario": "",
            "fecha_registro": None,
        }

    activity_progress = progress[
        progress["actividad_id"]
        == activity_id
    ].copy()

    if activity_progress.empty:
        return {
            "avance": 0,
            "descripcion_avance": "",
            "observaciones": "",
            "usuario": "",
            "fecha_registro": None,
        }

    if "fecha_registro" in activity_progress.columns:
        activity_progress = (
            activity_progress.sort_values(
                "fecha_registro"
            )
        )

    row = activity_progress.iloc[-1]

    return {
        "avance": row.get(
            "avance",
            0,
        ),
        "descripcion_avance": row.get(
            "descripcion_avance",
            "",
        ),
        "observaciones": row.get(
            "observaciones",
            "",
        ),
        "usuario": row.get(
            "usuario",
            "",
        ),
        "fecha_registro": row.get(
            "fecha_registro",
            None,
        ),
    }


def _activity_history_detail(
    activity_id,
    progress: pd.DataFrame,
) -> list[str]:
    """
    Genera el detalle secuencial de los reportes del supervisor.
    Cada registro se convierte en una línea para el informe.
    """
    if progress.empty:
        return []

    history = progress[
        progress["actividad_id"]
        == activity_id
    ].copy()

    if history.empty:
        return []

    if "fecha_registro" in history.columns:
        history = history.sort_values(
            "fecha_registro",
            ascending=True,
        )

    details = []

    for _, row in history.iterrows():
        description = _safe_report_text(
            row.get(
                "descripcion_avance",
                "",
            ),
            default="",
        )

        if description:
            advance = _fmt_number(
                row.get(
                    "avance",
                    0,
                ),
                0,
                "0",
            )

            details.append(
                f"{advance}% - {description}"
            )

    return details


def build_activity_report_pdf(
    selected_activities: pd.DataFrame,
    ots: pd.DataFrame,
    progress: pd.DataFrame,
) -> bytes:
    """
    Genera un PDF con una página por actividad.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=24,
        leftMargin=24,
        topMargin=22,
        bottomMargin=22,
    )

    styles = getSampleStyleSheet()

    styles["Normal"].fontName = "Helvetica"
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11

    title_style = styles["Heading2"]
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 11
    title_style.leading = 13
    title_style.spaceAfter = 6

    small_style = styles["Normal"]

    story = []

    navy = colors.HexColor("#244568")
    light_gray = colors.HexColor("#F4F6F8")
    border = colors.HexColor("#1D1D1D")
    yellow = colors.HexColor("#FFF200")

    for activity_number, (_, activity) in enumerate(
        selected_activities.iterrows()
    ):
        activity_id = activity.get(
            "id"
        )

        ot_id = activity.get(
            "ot_id"
        )

        ot_match = ots[
            ots["id"] == ot_id
        ]

        if ot_match.empty:
            ot_row = {}
        else:
            ot_row = ot_match.iloc[0]

        latest = _latest_activity_report(
            activity_id,
            progress,
        )

        stages = _evidence_stage_urls(
            activity_id,
            progress,
        )

        area_value = (
            activity.get(
                "seccion",
                None,
            )
            if "seccion"
            in selected_activities.columns
            else None
        )

        if not _safe_report_text(
            area_value,
            default="",
        ):
            area_value = activity.get(
                "especialidad",
                "-",
            )

        supervisor_seguridad = (
            activity.get(
                "supervisor_seguridad",
                "-",
            )
            if "supervisor_seguridad"
            in selected_activities.columns
            else "-"
        )

        supervisor_cliente = (
            activity.get(
                "supervisor_cliente",
                "-",
            )
            if "supervisor_cliente"
            in selected_activities.columns
            else "-"
        )

        senior_cliente = (
            activity.get(
                "senior_mantenimiento",
                "-",
            )
            if "senior_mantenimiento"
            in selected_activities.columns
            else "-"
        )

        header_rows = [
            [
                Paragraph(
                    "<b>AREA</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        area_value
                    ),
                    small_style,
                ),
                "",
                "",
            ],
            [
                Paragraph(
                    "<b>OT</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        ot_row.get(
                            "ot",
                            "-",
                        )
                    ),
                    small_style,
                ),
                "",
                "",
            ],
            [
                Paragraph(
                    "<b>DESCRIPCION DE ACTIVIDAD</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        activity.get(
                            "descripcion",
                            "-",
                        )
                    ),
                    small_style,
                ),
                "",
                "",
            ],
            [
                Paragraph(
                    "<b>EQUIPO</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        ot_row.get(
                            "equipo",
                            "-",
                        )
                    ),
                    small_style,
                ),
                "",
                "",
            ],
            [
                Paragraph(
                    "<b>SUPERVISOR OPERATIVO MAININ</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        activity.get(
                            "supervisor",
                            "-",
                        )
                    ),
                    small_style,
                ),
                Paragraph(
                    "<b>TURNO / GRUPO</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        activity.get(
                            "grupo",
                            "-",
                        )
                    ),
                    small_style,
                ),
            ],
            [
                Paragraph(
                    "<b>SUPERVISOR SEGURIDAD MAININ</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        supervisor_seguridad
                    ),
                    small_style,
                ),
                Paragraph(
                    "<b>PERSONAL</b>",
                    small_style,
                ),
                Paragraph(
                    _fmt_number(
                        activity.get(
                            "personal",
                            None,
                        )
                    ),
                    small_style,
                ),
            ],
            [
                Paragraph(
                    "<b>SUPERVISOR CLIENTE</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        supervisor_cliente
                    ),
                    small_style,
                ),
                Paragraph(
                    "<b>HORAS</b>",
                    small_style,
                ),
                Paragraph(
                    _fmt_number(
                        activity.get(
                            "duracion_h",
                            None,
                        ),
                        1,
                    ),
                    small_style,
                ),
            ],
            [
                Paragraph(
                    "<b>SENIOR MANTENIMIENTO CLIENTE</b>",
                    small_style,
                ),
                Paragraph(
                    _safe_report_text(
                        senior_cliente
                    ),
                    small_style,
                ),
                Paragraph(
                    "<b>HH</b>",
                    small_style,
                ),
                Paragraph(
                    _fmt_number(
                        activity.get(
                            "hh_plan",
                            None,
                        ),
                        0,
                    ),
                    small_style,
                ),
            ],
        ]

        header_table = Table(
            header_rows,
            colWidths=[
                178,
                178,
                82,
                64,
            ],
        )

        header_table.setStyle(
            TableStyle(
                [
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.55,
                        border,
                    ),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (0, -1),
                        navy,
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (0, -1),
                        colors.white,
                    ),
                    (
                        "BACKGROUND",
                        (2, 4),
                        (2, -1),
                        navy,
                    ),
                    (
                        "TEXTCOLOR",
                        (2, 4),
                        (2, -1),
                        colors.white,
                    ),
                    (
                        "SPAN",
                        (1, 0),
                        (3, 0),
                    ),
                    (
                        "SPAN",
                        (1, 1),
                        (3, 1),
                    ),
                    (
                        "SPAN",
                        (1, 2),
                        (3, 2),
                    ),
                    (
                        "SPAN",
                        (1, 3),
                        (3, 3),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        3,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        3,
                    ),
                ]
            )
        )

        # Resaltar OT y descripción.
        header_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (1, 1),
                        (3, 1),
                        yellow,
                    ),
                    (
                        "BACKGROUND",
                        (1, 2),
                        (3, 2),
                        yellow,
                    ),
                ]
            )
        )

        story.append(
            header_table
        )

        story.append(
            Spacer(
                1,
                12,
            )
        )

        story.append(
            Paragraph(
                "<b>DESCRIPCION DE LAS ACTIVIDADES</b>",
                title_style,
            )
        )

        history_detail = _activity_history_detail(
            activity_id,
            progress,
        )

        if not history_detail:
            fallback_detail = _safe_report_text(
                latest.get(
                    "descripcion_avance",
                    "",
                ),
                default="Sin detalle registrado.",
            )

            history_detail = [
                fallback_detail
            ]

        # ReportLab Paragraph no admite varios tags <bullet>
        # dentro del mismo párrafo. Usamos viñetas Unicode simples.
        detail_lines = [
            f"• {detail}"
            for detail in history_detail
        ]

        details_html = "<br/>".join(
            detail_lines
        )

        observations = _safe_report_text(
            latest.get(
                "observaciones",
                "",
            ),
            default="",
        )

        detail_html = (
            "<b>ACTIVIDAD:</b> "
            + _safe_report_text(
                activity.get(
                    "codigo_actividad",
                    "-",
                )
            )
            + "<br/><b>DETALLE:</b><br/>"
            + details_html
        )

        if observations:
            detail_html += (
                "<br/><b>OBSERVACIONES / RESTRICCIONES:</b><br/>"
                + observations
            )

        detail_table = Table(
            [
                [
                    Paragraph(
                        detail_html,
                        small_style,
                    )
                ]
            ],
            colWidths=[
                502
            ],
        )

        detail_table.setStyle(
            TableStyle(
                [
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.65,
                        border,
                    ),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.white,
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        10,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        10,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                ]
            )
        )

        story.append(
            detail_table
        )

        story.append(
            Spacer(
                1,
                12,
            )
        )

        story.append(
            Paragraph(
                "<b>EVIDENCIAS FOTOGRAFICAS</b>",
                title_style,
            )
        )

        evidence_cells = []
        evidence_labels = []

        for stage in [
            "INICIO",
            "DURANTE",
            "FINAL",
        ]:
            image_buffer = _download_report_image(
                stages.get(
                    stage
                )
            )

            if image_buffer is not None:
                try:
                    img = RLImage(
                        image_buffer,
                        width=155,
                        height=142,
                        kind="proportional",
                    )
                    evidence_cells.append(
                        img
                    )
                except Exception:
                    evidence_cells.append(
                        Paragraph(
                            "Imagen no disponible",
                            small_style,
                        )
                    )
            else:
                evidence_cells.append(
                    Paragraph(
                        "Sin evidencia",
                        small_style,
                    )
                )

            evidence_labels.append(
                Paragraph(
                    f"<b>{stage.capitalize()}</b>",
                    small_style,
                )
            )

        evidence_table = Table(
            [
                evidence_cells,
                evidence_labels,
            ],
            colWidths=[
                167,
                167,
                167,
            ],
            rowHeights=[
                150,
                20,
            ],
        )

        evidence_table.setStyle(
            TableStyle(
                [
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.55,
                        border,
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, 0),
                        "MIDDLE",
                    ),
                    (
                        "ALIGN",
                        (0, 0),
                        (-1, -1),
                        "CENTER",
                    ),
                    (
                        "BACKGROUND",
                        (0, 1),
                        (-1, 1),
                        light_gray,
                    ),
                ]
            )
        )

        story.append(
            evidence_table
        )

        story.append(
            Spacer(
                1,
                8,
            )
        )

        footer_text = (
            f"Avance actual: "
            f"{_fmt_number(latest.get('avance', 0), 0, '0')}%"
        )

        if latest.get(
            "fecha_registro"
        ) is not None:
            try:
                footer_text += (
                    " | Ultimo reporte: "
                    + pd.to_datetime(
                        latest[
                            "fecha_registro"
                        ]
                    ).strftime(
                        "%d/%m/%Y %H:%M"
                    )
                )
            except Exception:
                pass

        story.append(
            Paragraph(
                footer_text,
                small_style,
            )
        )

        if (
            activity_number
            < len(selected_activities)
            - 1
        ):
            story.append(
                PageBreak()
            )

    doc.build(
        story
    )

    return buffer.getvalue()



# ============================================================
# V35 - REPORTE OPERATIVO DE ACTIVIDADES POR SUPERVISOR
# ============================================================
def _sup_report_text(value, default="-"):
    """Normaliza campos para pantalla y PDF sin exponer etiquetas HTML."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    clean = str(value).strip()
    return clean if clean else default


def _supervisor_report_model(
    selected_activities: pd.DataFrame,
    all_ots: pd.DataFrame,
    all_progress: pd.DataFrame,
) -> pd.DataFrame:
    """Solo lectura: no recalcula ni altera lo que ya existe en Supabase."""
    result = build_activity_status(selected_activities, all_progress).copy()
    if result.empty:
        return result
    result["id"] = result["id"].astype(str)
    result["ot_id"] = result["ot_id"].astype(str)
    result["avance_real"] = pd.to_numeric(result["avance_real"], errors="coerce").fillna(0).clip(0, 100)
    result["supervisor"] = result.get("supervisor", pd.Series("", index=result.index)).fillna("SIN ASIGNAR").astype(str).str.strip().replace("", "SIN ASIGNAR")
    result["estado"] = result["avance_real"].apply(
        lambda p: "Culminada" if p >= 100 else ("En ejecución" if p > 0 else "No iniciada")
    )
    result["hh_plan_calc"] = pd.to_numeric(
        result.get("hh_plan", pd.Series(0, index=result.index)), errors="coerce"
    ).fillna(0).clip(lower=0)
    result["hh_ganadas_calc"] = (result["hh_plan_calc"] * result["avance_real"] / 100).round(2)
    result["n_reportes"] = 0
    result["ultimo_reporte"] = "Sin reporte"

    if not all_progress.empty and "actividad_id" in all_progress.columns:
        p = all_progress.copy()
        p["actividad_id"] = p["actividad_id"].astype(str)
        counts = p.groupby("actividad_id").size()
        result["n_reportes"] = result["id"].map(counts).fillna(0).astype(int)
        if "fecha_registro" in p.columns:
            p["fecha_orden"] = pd.to_datetime(p["fecha_registro"], errors="coerce", utc=True)
            latest = p.sort_values("fecha_orden", kind="stable").groupby("actividad_id", sort=False).tail(1)
            shown = latest.set_index("actividad_id")["fecha_orden"]
            dates = pd.to_datetime(result["id"].map(shown), utc=True, errors="coerce")
            result["ultimo_reporte"] = dates.dt.tz_convert(LIMA_TZ).dt.strftime("%d/%m/%Y %H:%M").fillna("Sin reporte")
    if "id" in all_ots.columns and "ot" in all_ots.columns:
        ot_catalog = all_ots[["id", "ot"]].copy()
        ot_catalog["id"] = ot_catalog["id"].astype(str)
        ot_catalog = ot_catalog.drop_duplicates("id")
        result = result.merge(ot_catalog.rename(columns={"id":"ot_id", "ot":"numero_ot"}), on="ot_id", how="left", suffixes=("", "_ot"))
    if "numero_ot" not in result.columns:
        result["numero_ot"] = "S/OT"
    result["numero_ot"] = result["numero_ot"].fillna("S/OT").astype(str)
    result["descripcion_avance"] = result.get("descripcion_avance", pd.Series("", index=result.index)).fillna("").astype(str)
    result["codigo_actividad"] = result.get("codigo_actividad", pd.Series("", index=result.index)).fillna("").astype(str)
    result["descripcion"] = result.get("descripcion", pd.Series("", index=result.index)).fillna("").astype(str)
    return result.sort_values(["supervisor", "numero_ot", "codigo_actividad"], kind="stable")


def build_supervisor_summary_pdf(report_df: pd.DataFrame, supervisor_label: str) -> bytes:
    """PDF consolidado con carátula gerencial y detalle de actividades.

    Diseño compacto A4 horizontal, sin modificar datos ni exigir dependencias extra.
    """
    buffer = io.BytesIO()
    navy = colors.HexColor("#0D345E")
    ocean = colors.HexColor("#166099")
    white = colors.white
    slate = colors.HexColor("#526579")
    faint = colors.HexColor("#EEF4F9")
    border = colors.HexColor("#D7E2EC")
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=26, bottomMargin=26)
    sheet = getSampleStyleSheet()
    tiny = ParagraphStyle("sup_tiny", parent=sheet["Normal"], fontName="Helvetica", fontSize=7.1, leading=9.3, textColor=navy)
    small = ParagraphStyle("sup_small", parent=sheet["Normal"], fontName="Helvetica", fontSize=8.2, leading=11, textColor=navy)
    heading = ParagraphStyle("sup_heading", parent=sheet["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=navy, spaceAfter=8)
    title = ParagraphStyle("sup_title", parent=sheet["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=navy, spaceAfter=10)

    def safe(value, limit=None):
        content = html.escape(_sup_report_text(value, ""), quote=False).replace("\n", "<br/>")
        if limit and len(content) > limit:
            content = content[:limit].rsplit(" ", 1)[0] + "..."
        return content or "-"

    if report_df.empty:
        raise ValueError("No hay actividades para generar el reporte.")

    n = len(report_df)
    finished = int((report_df["avance_real"] >= 100).sum())
    active = int(((report_df["avance_real"] > 0) & (report_df["avance_real"] < 100)).sum())
    pending = int((report_df["avance_real"] <= 0).sum())
    reported = int((report_df["n_reportes"] > 0).sum())
    progress_pct = float(report_df["avance_real"].mean())
    hh_plan = float(report_df["hh_plan_calc"].sum())
    hh_done = float(report_df["hh_ganadas_calc"].sum())
    story = [
        Paragraph("MAININ · UNIDAD MINERA ANTAPACCAY · MECÁNICA", small),
        Spacer(1, 9),
        Paragraph("REPORTE DE ACTIVIDADES POR SUPERVISOR", title),
        Paragraph(f"<b>Supervisor:</b> {safe(supervisor_label)} &nbsp;&nbsp;&nbsp; <b>Fecha de emisión:</b> {pd.Timestamp.now(tz=LIMA_TZ):%d/%m/%Y %H:%M}", small),
        Spacer(1, 14),
    ]
    metrics = [
        ("OTs", f'{report_df["numero_ot"].nunique()}'),
        ("Actividades", f"{n}"),
        ("Avance", f"{progress_pct:.1f}%"),
        ("Culminadas", f"{finished}"),
        ("En ejecución", f"{active}"),
        ("No iniciadas", f"{pending}"),
        ("Con reporte", f"{reported}/{n}"),
    ]
    cells = [[Paragraph(f"<b>{safe(label)}</b><br/><font size='12'>{safe(value)}</font>", small) for label, value in metrics]]
    table = Table(cells, colWidths=[112]*7)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),faint), ("BOX",(0,0),(-1,-1),.6,border),
        ("INNERGRID",(0,0),(-1,-1),.5,border),
        ("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story += [table, Spacer(1,10), Paragraph(f"<b>HH planificadas:</b> {hh_plan:,.1f} &nbsp;&nbsp; <b>HH ganadas:</b> {hh_done:,.1f} &nbsp;&nbsp; <b>Cobertura de reporte:</b> {(100*reported/n):.1f}%", small), Spacer(1,18), Paragraph("DETALLE DE ACTIVIDADES", heading)]

    headers = ["OT", "Código", "Descripción de actividad", "Grupo", "Avance", "Estado", "HH plan", "Último reporte"]
    rows = [[Paragraph(f"<b>{x}</b>", tiny) for x in headers]]
    for _, row in report_df.iterrows():
        rows.append([
            Paragraph(safe(row.get("numero_ot"),32), tiny),
            Paragraph(safe(row.get("codigo_actividad"),30), tiny),
            Paragraph(safe(row.get("descripcion"),170), tiny),
            Paragraph(safe(row.get("grupo"),37), tiny),
            Paragraph(f'{float(row.get("avance_real",0)):.1f}%', tiny),
            Paragraph(safe(row.get("estado"),26), tiny),
            Paragraph(f'{float(row.get("hh_plan_calc",0)):.1f}', tiny),
            Paragraph(safe(row.get("ultimo_reporte"),24), tiny),
        ])
    detail = Table(rows, colWidths=[74,65,250,60,54,80,55,130], repeatRows=1, hAlign="LEFT")
    detail.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),navy),
        ("TEXTCOLOR",(0,0),(-1,0),white),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,faint]),
        ("LINEBELOW",(0,0),(-1,0),.8,ocean),
        ("INNERGRID",(0,0),(-1,-1),.25,border),
        ("BOX",(0,0),(-1,-1),.5,border),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    # The header text itself is white, not only the table cell's default text.
    rows[0] = [Paragraph(f'<font color="#FFFFFF"><b>{x}</b></font>',tiny) for x in headers]
    # Update existing cell text; Table receives the same rows object.
    for i, val in enumerate(rows[0]):
        detail._cellvalues[0][i] = val
    story.append(detail)
    story.extend([Spacer(1,16), Paragraph("ÚLTIMOS AVANCES REGISTRADOS", heading)])
    last_rows = [[Paragraph('<font color="#FFFFFF"><b>OT / Actividad</b></font>',tiny), Paragraph('<font color="#FFFFFF"><b>Descripción del último avance</b></font>',tiny), Paragraph('<font color="#FFFFFF"><b>Fecha</b></font>',tiny)]]
    for _, row in report_df.iterrows():
        last_rows.append([
            Paragraph(safe(f'{row.get("numero_ot", "")} · {row.get("codigo_actividad", "")}',48),tiny),
            Paragraph(safe(row.get("descripcion_avance", ""),460), tiny),
            Paragraph(safe(row.get("ultimo_reporte"),25),tiny),
        ])
    last_table = Table(last_rows, colWidths=[155,493,120], repeatRows=1, hAlign="LEFT")
    last_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),navy),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,faint]),
        ("BOX",(0,0),(-1,-1),.5,border),
        ("INNERGRID",(0,0),(-1,-1),.25,border),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(last_table)

    def page_footer(canvas, document):
        canvas.saveState()
        width, _ = landscape(A4)
        canvas.setStrokeColor(border)
        canvas.line(28,21,width-28,21)
        canvas.setFont("Helvetica",7)
        canvas.setFillColor(slate)
        canvas.drawString(28,11,"MAININ · Antapaccay · Reporte de supervisión mecánica")
        canvas.drawRightString(width-28,11,f"Página {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
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

    st.markdown("**CONTROL CENTER · MAININ**")
    st.caption("Unidad Minera Antapaccay · Mecánica")
    st.markdown("---")

    role = st.session_state.get(
        "role",
        "reporter",
    )

    if role == "admin":
        menu_options = [
            "Dashboard ejecutivo",
            "Desempeño supervisores",
            "Reporte por supervisor",
            "Registrar avance",
            "Detalle por OT",
            "Evidencias",
            "Informe diario",
            "Reporte PDF",
            "Informe de Actividades",
            "Administrar OTs",
            "Agregar actividades Excel",
            "Exportar reporte",
        ]
    else:
        menu_options = [
            "Registrar avance"
        ]

    menu_icons = {
        "Dashboard ejecutivo": "▦", "Desempeño supervisores": "◈",
        "Reporte por supervisor": "▤", "Registrar avance": "✎",
        "Detalle por OT": "≡", "Evidencias": "▧",
        "Informe diario": "◷", "Reporte PDF": "▣",
        "Informe de Actividades": "▤", "Administrar OTs": "⚙",
        "Agregar actividades Excel": "＋", "Exportar reporte": "⇩",
    }
    page = st.radio(
        "Menú",
        menu_options,
        format_func=lambda option: f"{menu_icons.get(option, '•')}  {option}",
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
            "authenticated", "username", "display_name", "role",
            "auth_cookie_write_pending",
        ]:
            st.session_state.pop(key, None)
        st.session_state["auth_cookie_restore_blocked"] = True
        st.session_state["auth_cookie_delete_pending"] = True
        st.rerun()


st.markdown(
    """
    <div class="mainin-header">
      <div class="mainin-eyebrow">MAININ · CONTROL CENTER · ANTAPACCAY</div>
      <div class="mainin-headline">Control y seguimiento de OTs</div>
      <div class="mainin-subline">Especialidad Mecánica · Avance de actividades, evidencias, supervisores y reportabilidad</div>
    </div>
    """,
    unsafe_allow_html=True,
)

ADMIN_ONLY_PAGES = {
    "Dashboard ejecutivo",
    "Desempeño supervisores",
    "Reporte por supervisor",
    "Detalle por OT",
    "Evidencias",
    "Informe diario",
    "Reporte PDF",
    "Informe de Actividades",
    "Administrar OTs",
    "Agregar actividades Excel",
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
# DESEMPEÑO OPERATIVO V24 - ÁREA MECÁNICA
# ============================================================
if page == "Desempeño supervisores":
    st.subheader("Desempeño de supervisores | Mecánica")
    st.caption(
        "Control por supervisor y OT. Se diferencia el avance del trabajo "
        "de la disciplina de registro de los reportes."
    )

    if activity_status.empty:
        st.info("No hay actividades registradas.")
    else:
        work = activity_status.copy()
        work["id"] = work["id"].astype(str)
        work["ot_id"] = work["ot_id"].astype(str)
        work["supervisor"] = (
            work["supervisor"].fillna("").astype(str).str.strip()
            if "supervisor" in work.columns
            else pd.Series("", index=work.index)
        ).replace("", "SIN ASIGNAR")
        work["avance_real"] = pd.to_numeric(
            work["avance_real"], errors="coerce"
        ).fillna(0).clip(0, 100)

        # El estado del avance no se confunde con el estado del reporte.
        work["estado"] = work["avance_real"].map(
            lambda n: "Culminada" if n >= 100 else (
                "En ejecución" if n > 0 else "No iniciada"
            )
        )

        # Se calcula cobertura desde los registros de avances, independientemente
        # de que un avance haya sido igual a cero.
        if not progress.empty and "actividad_id" in progress.columns:
            registro = progress.copy()
            registro["actividad_id"] = registro["actividad_id"].astype(str)
            fechas = pd.to_datetime(
                registro["fecha_registro"], errors="coerce", utc=True
            ) if "fecha_registro" in registro.columns else pd.Series(
                pd.NaT, index=registro.index, dtype="datetime64[ns, UTC]"
            )
            registro["fecha_reporte"] = fechas
            registro = registro.sort_values("fecha_reporte")
            ultimos = registro.groupby("actividad_id", as_index=False).tail(1)
            ultimos = ultimos[["actividad_id", "fecha_reporte"]].copy()
            conteos = registro.groupby("actividad_id").size().rename("n_reportes")
            work = work.merge(
                ultimos, left_on="id", right_on="actividad_id", how="left"
            ).drop(columns=["actividad_id"], errors="ignore")
            work = work.merge(
                conteos, left_on="id", right_index=True, how="left"
            )
        else:
            work["fecha_reporte"] = pd.NaT
            work["n_reportes"] = 0

        work["n_reportes"] = pd.to_numeric(
            work["n_reportes"], errors="coerce"
        ).fillna(0).astype(int)
        work["con_reporte"] = work["n_reportes"] > 0

        if {"id", "ot"}.issubset(ots.columns):
            catalogo_ots = ots[["id", "ot"]].copy()
            catalogo_ots["id"] = catalogo_ots["id"].astype(str)
            catalogo_ots = catalogo_ots.drop_duplicates(subset=["id"])
            work = work.merge(
                catalogo_ots.rename(columns={"id": "ot_id", "ot": "numero_ot"}),
                on="ot_id", how="left"
            )
        else:
            work["numero_ot"] = None
        work["numero_ot"] = (
            work["numero_ot"].fillna("SIN OT").astype(str).str.strip()
            .replace("", "SIN OT")
        )

        # Se ofrece un corte temporal para identificar reportes antiguos.
        hoy_local = pd.Timestamp.now(tz=LIMA_TZ)
        work["horas_sin_actualizar"] = (
            (hoy_local - pd.to_datetime(
                work["fecha_reporte"], errors="coerce", utc=True
            ).dt.tz_convert(LIMA_TZ)).dt.total_seconds() / 3600
        ).clip(lower=0)
        work["ultimo_reporte"] = pd.to_datetime(
            work["fecha_reporte"], errors="coerce", utc=True
        ).dt.tz_convert(LIMA_TZ).dt.strftime("%d/%m/%Y %H:%M").fillna("Sin reporte")

        filtro_1, filtro_2, filtro_3, filtro_4 = st.columns(4)
        supervisor_sel = filtro_1.selectbox(
            "Supervisor",
            ["TODOS"] + sorted(work["supervisor"].unique().tolist()),
            key="v24_supervisor",
        )
        base = work if supervisor_sel == "TODOS" else work[
            work["supervisor"] == supervisor_sel
        ]
        ot_sel = filtro_2.selectbox(
            "OT",
            ["TODAS"] + sorted(base["numero_ot"].unique().tolist()),
            key="v24_ot",
        )
        estado_sel = filtro_3.selectbox(
            "Estado de avance",
            ["TODOS", "Culminada", "En ejecución", "No iniciada"],
            key="v24_estado",
        )
        reporte_sel = filtro_4.selectbox(
            "Disciplina de reporte",
            ["TODOS", "Con reporte", "Sin reporte", "Sin actualizar 24 h",
             "Sin actualizar 48 h"],
            key="v24_reportes",
        )

        base = base if ot_sel == "TODAS" else base[
            base["numero_ot"] == ot_sel
        ]
        base = base if estado_sel == "TODOS" else base[
            base["estado"] == estado_sel
        ]
        if reporte_sel == "Con reporte":
            base = base[base["con_reporte"]]
        elif reporte_sel == "Sin reporte":
            base = base[~base["con_reporte"]]
        elif reporte_sel == "Sin actualizar 24 h":
            base = base[
                (~base["con_reporte"]) | (base["horas_sin_actualizar"] >= 24)
            ]
        elif reporte_sel == "Sin actualizar 48 h":
            base = base[
                (~base["con_reporte"]) | (base["horas_sin_actualizar"] >= 48)
            ]

        if base.empty:
            st.info("No hay actividades con los filtros seleccionados.")
        else:
            total = len(base)
            terminadas = int((base["avance_real"] >= 100).sum())
            ejecutando = int(((base["avance_real"] > 0) & (base["avance_real"] < 100)).sum())
            pendientes = int((base["avance_real"] <= 0).sum())
            registradas = int(base["con_reporte"].sum())

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("OTs", base["numero_ot"].nunique())
            k2.metric("Actividades", total)
            k3.metric("Avance promedio", f"{base['avance_real'].mean():.1f}%")
            k4.metric("Con al menos un reporte", f"{registradas/total*100:.1f}%")
            k5, k6, k7, k8 = st.columns(4)
            k5.metric("Culminadas", terminadas)
            k6.metric("En ejecución", ejecutando)
            k7.metric("No iniciadas", pendientes)
            k8.metric("Sin reporte", total - registradas)

            resumen = base.groupby("supervisor", dropna=False).agg(
                OTs=("numero_ot", "nunique"),
                Actividades=("id", "count"),
                Avance=("avance_real", "mean"),
                Reportadas=("con_reporte", "sum"),
                Culminadas=("estado", lambda s: int((s == "Culminada").sum())),
                En_ejecucion=("estado", lambda s: int((s == "En ejecución").sum())),
                Sin_iniciar=("estado", lambda s: int((s == "No iniciada").sum())),
            ).reset_index().rename(columns={"supervisor": "Supervisor"})
            resumen["Cobertura (%)"] = (
                100 * resumen["Reportadas"] / resumen["Actividades"]
            ).round(1)
            resumen["Avance"] = resumen["Avance"].round(1)
            resumen = resumen.sort_values(
                ["Avance", "Actividades"], ascending=[False, False]
            )

            st.markdown("### Avance por supervisor")
            grafico = px.bar(
                resumen.sort_values("Avance"),
                x="Avance", y="Supervisor", orientation="h",
                text="Avance", color_discrete_sequence=["#174C79"],
            )
            grafico.update_traces(
                texttemplate="%{text:.1f}%", textposition="outside"
            )
            grafico.update_layout(
                xaxis_range=[0, 110], showlegend=False,
                height=max(280, 55 * len(resumen) + 85),
                xaxis_title="Avance (%)", yaxis_title=None,
            )
            st.plotly_chart(grafico, use_container_width=True)

            st.markdown("### Cumplimiento y disciplina de registro")
            st.dataframe(
                resumen.rename(columns={
                    "Avance": "Avance (%)",
                    "Reportadas": "Actividades reportadas",
                    "En_ejecucion": "En ejecución",
                    "Sin_iniciar": "No iniciadas",
                }), use_container_width=True, hide_index=True
            )

            st.markdown("### Actividades que requieren seguimiento")
            seguimiento = base[
                (base["avance_real"] < 100) | (~base["con_reporte"])
            ].copy()
            seguimiento["alerta"] = seguimiento.apply(
                lambda r: "Sin reporte" if not r["con_reporte"] else (
                    "No iniciada" if r["avance_real"] <= 0 else "En ejecución"
                ), axis=1
            )
            columnas = [
                "numero_ot", "codigo_actividad", "descripcion", "supervisor",
                "estado", "avance_real", "alerta", "ultimo_reporte",
                "inicio_plan", "fin_plan",
            ]
            columnas = [c for c in columnas if c in seguimiento.columns]
            if seguimiento.empty:
                st.success("No hay actividades pendientes de seguimiento.")
            else:
                st.dataframe(
                    seguimiento[columnas].rename(columns={
                        "numero_ot": "OT", "codigo_actividad": "Actividad",
                        "descripcion": "Descripción", "supervisor": "Supervisor",
                        "estado": "Estado", "avance_real": "Avance (%)",
                        "alerta": "Alerta", "ultimo_reporte": "Último reporte",
                        "inicio_plan": "Inicio plan", "fin_plan": "Fin plan",
                    }), use_container_width=True, hide_index=True
                )

            c_descarga_1, c_descarga_2 = st.columns(2)
            c_descarga_1.download_button(
                "📥 Descargar consolidado por supervisor (CSV)",
                data=resumen.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"desempeno_supervisores_antapaccay_{datetime.now():%Y%m%d}.csv",
                mime="text/csv", use_container_width=True,
            )
            c_descarga_2.download_button(
                "📥 Descargar detalle de actividades (CSV)",
                data=base.drop(columns=["con_reporte", "fecha_reporte", "horas_sin_actualizar"],
                               errors="ignore").to_csv(index=False).encode("utf-8-sig"),
                file_name=f"detalle_seguimiento_antapaccay_{datetime.now():%Y%m%d}.csv",
                mime="text/csv", use_container_width=True,
            )


# ============================================================
# ============================================================
# REGISTRAR AVANCE DIRECTAMENTE EN TABLA - V31 RESPONSIVA
# ============================================================
if page == "Registrar avance":
    # Limpiar el texto y liberar el uploader anterior tras un guardado exitoso.
    # En Streamlit, un file_uploader no se vacía de forma fiable quitando
    # únicamente la clave: se requiere un NUEVO key en el siguiente render.
    for _clear_id in st.session_state.pop("registro_tab_clear_ids", []):
        st.session_state.pop(f"rt_desc_{_clear_id}", None)
        _generation = int(st.session_state.get(f"rt_photo_generation_{_clear_id}", 0))
        if _generation > 0:
            st.session_state.pop(f"rt_photo_{_clear_id}_g{_generation - 1}", None)
    st.subheader("Reporte de avance")
    st.caption("Cada actividad tiene sus propios botones para cargar fotografías, guardar el avance y ver evidencias. No hay botón de guardado al final de la tabla.")
    # Mostrar confirmación antes de crear los controles de la tabla.
    _saved_activity = st.session_state.pop("registro_tab_saved", None)
    if _saved_activity:
        st.success(f"Actividad {_saved_activity} guardada correctamente. Se limpiaron su descripción y fotografías; el porcentaje se conserva.")

    if activities.empty or ots.empty:
        st.warning("Primero debe importar OTs y actividades.")
    else:
        base = activities.copy()
        base["id_key"] = base["id"].astype(str)
        base["ot_key"] = base["ot_id"].astype(str)
        base["supervisor_f"] = base.get("supervisor", pd.Series("", index=base.index)).fillna("").astype(str).str.strip()
        base["grupo_f"] = base.get("grupo", pd.Series("", index=base.index)).fillna("").astype(str).str.strip()
        ot_catalog = ots[["id", "ot"]].copy()
        if "activo" in ots.columns:
            ot_catalog = ots.loc[ots["activo"].fillna(True), ["id", "ot"]].copy()
        ot_catalog["ot_key"] = ot_catalog["id"].astype(str)
        ot_catalog = ot_catalog[["ot_key", "ot"]].drop_duplicates("ot_key")
        base = base.merge(ot_catalog, how="inner", on="ot_key", suffixes=("", "_tabla"))
        base["ot_numero"] = base["ot"].fillna("S/OT").astype(str)

        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        supervisor_sel = c1.selectbox("Supervisor", ["TODOS"] + sorted(x for x in base["supervisor_f"].unique() if x), key="registro_tab_supervisor")
        if supervisor_sel != "TODOS":
            base = base[base["supervisor_f"] == supervisor_sel]
        grupo_sel = c2.selectbox("Grupo", ["TODOS"] + sorted(x for x in base["grupo_f"].unique() if x), key="registro_tab_grupo")
        if grupo_sel != "TODOS":
            base = base[base["grupo_f"] == grupo_sel]
        ot_sel = c3.selectbox("OT", ["TODAS"] + sorted(base["ot_numero"].unique().tolist()), key="registro_tab_ot")
        if ot_sel != "TODAS":
            base = base[base["ot_numero"] == ot_sel]
        if c4.button("Limpiar filtros", use_container_width=True):
            for name in ("registro_tab_supervisor", "registro_tab_grupo", "registro_tab_ot"):
                st.session_state.pop(name, None)
            st.rerun()

        # Buscador para localizar una actividad desde el celular.
        busqueda_registro = st.text_input(
            "🔎 Buscar actividad, OT, grupo o supervisor",
            key="registro_tab_busqueda_v31",
            placeholder="Ej.: ACT-210, 11559519, molinos o RAUL NINA",
        ).strip()
        if busqueda_registro:
            columnas_busqueda = [
                "codigo_actividad", "descripcion", "ot_numero",
                "grupo_f", "supervisor_f", "equipo",
            ]
            columnas_busqueda = [c for c in columnas_busqueda if c in base.columns]
            coincidencias = pd.Series(False, index=base.index)
            for c in columnas_busqueda:
                coincidencias |= base[c].fillna("").astype(str).str.contains(
                    busqueda_registro, case=False, regex=False, na=False
                )
            base = base[coincidencias].copy()

        st.caption(
            "📱 En celular: encuentre la actividad con el buscador y "
            "deslice la tabla horizontalmente para registrar el avance."
        )

        if base.empty:
            st.info("No hay actividades para los filtros indicados.")
        else:
            # Último avance registrado: se actualiza solo al guardar; escribir
            # una observación no cambia automáticamente el porcentaje.
            ultimo = {}
            if not progress.empty and "actividad_id" in progress.columns:
                ordered = progress.sort_values("fecha_registro") if "fecha_registro" in progress.columns else progress
                for _, r in ordered.iterrows():
                    ultimo[str(r["actividad_id"])] = r

            nrows = len(base)
            st.caption(f"{nrows} actividad(es) en una sola tabla. Use los filtros para encontrar rápidamente una actividad.")
            visible = base.sort_values(["ot_numero", "codigo_actividad"], kind="stable")

            st.markdown('''<style>
            .registro-avance-header {background:#082d55;color:#fff;padding:10px 6px;border-radius:5px;font-size:12px;font-weight:700;text-align:center;}
            .registro-avance-dato {color:#111827 !important;font-size:13px;font-weight:500;line-height:1.45;overflow-wrap:anywhere;}
            .registro-avance-dato strong {color:#0a2545 !important;font-weight:750;}
            div[data-testid="stFileUploader"] small {font-size:10px;color:#111827 !important;}
            div[data-testid="stTextArea"] textarea,
            div[data-testid="stNumberInput"] input,
            div[data-testid="stSelectbox"] div[data-baseweb="select"] * {color:#111827 !important;}
            div[data-testid="stTextArea"] textarea::placeholder {color:#4b5563 !important;opacity:1;}

            /* V31: tabla horizontal en celular; no apilar las columnas. */
            @media (max-width: 800px) {
              .st-key-rt_tabla_responsiva {
                overflow-x: auto !important;
                overflow-y: visible !important;
                -webkit-overflow-scrolling: touch;
                overscroll-behavior-x: contain;
                max-width: 100% !important;
                border: 1px solid #d8e0ec;
                border-radius: 9px;
                padding: 4px 5px 10px;
              }
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] {
                display: flex !important;
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                align-items: center !important;
                gap: 7px !important;
                min-width: 1200px !important;
                width: 1200px !important;
              }
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                box-sizing: border-box !important;
                flex-grow: 0 !important;
                flex-shrink: 0 !important;
                min-width: 0 !important;
                width: 0 !important;
              }
              /* Ocultar sólo datos secundarios en celular. */
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(2),
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(4),
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(5),
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(6),
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(7) {
                display: none !important;
              }
              /* Empezar por ACTIVIDAD para encontrarla rápidamente. */
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(1)  {flex-basis: 92px !important; width: 92px !important; order: 2;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(3)  {flex-basis: 255px !important; width: 255px !important; order: 1;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(8)  {flex-basis: 73px !important; width: 73px !important; order: 3;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(9)  {flex-basis: 82px !important; width: 82px !important; order: 4;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(10) {flex-basis: 225px !important; width: 225px !important; order: 5;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(11) {flex-basis: 105px !important; width: 105px !important; order: 6;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(12) {flex-basis: 155px !important; width: 155px !important; order: 7;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(13) {flex-basis: 77px !important; width: 77px !important; order: 8;}
              .st-key-rt_tabla_responsiva div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(14) {flex-basis: 65px !important; width: 65px !important; order: 9;}
              .st-key-rt_tabla_responsiva .registro-avance-header {
                font-size: 11px; line-height: 1.2; padding: 8px 3px;
              }
              .st-key-rt_tabla_responsiva .registro-avance-dato {
                font-size: 12px; line-height: 1.4;
              }
              .st-key-rt_tabla_responsiva textarea {
                min-height: 65px !important;
                color: #111827 !important;
              }
              .st-key-rt_tabla_responsiva input {color: #111827 !important;}
              .st-key-rt_tabla_responsiva div[data-testid="stDivider"] {
                min-width: 1200px;
              }
            }
            </style>''', unsafe_allow_html=True)
            widths = [1, 1.1, 3.2, 1.4, 1.45, 1.3, 0.9, 0.9, 1.1, 3.2, 1.4, 2.2, 1.1, 0.7]
            with st.container(key="rt_tabla_responsiva"):
                headers = ["OT", "GRUPO", "ACTIVIDAD", "SUPERVISOR", "INICIO", "FIN", "DURACIÓN", "% ACTUAL", "% NUEVO", "DESCRIPCIÓN DEL AVANCE", "TIPO", "FOTO", "GUARDAR", "VER"]
                headcols = st.columns(widths, gap="small")
                for c, label in zip(headcols, headers):
                    c.markdown(f'<div class="registro-avance-header">{label}</div>', unsafe_allow_html=True)

                # Ventana para VER evidencias de una actividad sin enviarlas
                # a un bloque debajo de todas las actividades.
                @st.dialog("Evidencias registradas", width="large")
                def _ver_evidencias_actividad(actividad_id, codigo_actividad):
                    st.markdown(f"**Actividad:** {codigo_actividad}")
                    if progress.empty or "actividad_id" not in progress.columns:
                        st.info("Esta actividad todavía no tiene reportes.")
                        return
                    existing = progress[
                        progress["actividad_id"].astype(str) == str(actividad_id)
                    ]
                    if existing.empty:
                        st.info("Esta actividad todavía no tiene reportes.")
                        return
                    if "fecha_registro" in existing.columns:
                        existing = existing.sort_values("fecha_registro", ascending=False)
                    for _, report in existing.iterrows():
                        st.caption(
                            f'{report.get("tipo_evidencia", "")} · '
                            f'{report.get("descripcion_avance", "")}'
                        )
                        urls = report.get("evidencias", [])
                        if isinstance(urls, str):
                            urls = [urls]
                        if not isinstance(urls, (list, tuple)):
                            urls = []
                        for url in urls:
                            if url:
                                st.image(url, width=330)
                        st.divider()

                for _, act in visible.iterrows():
                    aid = str(act["id_key"])
                    current = ultimo.get(aid)
                    raw_current = current.get("avance", 0) if current is not None else 0
                    current_pct = int(max(0, min(100, round(float(pd.to_numeric(raw_current, errors="coerce") or 0)))))
                    cols = st.columns(widths, gap="small", vertical_alignment="center")
                    def _texto_celda(columna, valor, negrita=False):
                        contenido = html.escape(str(valor))
                        if negrita:
                            contenido = f"<strong>{contenido}</strong>"
                        columna.markdown(
                            f'<div class="registro-avance-dato">{contenido}</div>',
                            unsafe_allow_html=True,
                        )

                    _texto_celda(cols[0], act["ot_numero"])
                    _texto_celda(cols[1], act["grupo_f"])
                    _texto_celda(cols[2], f'{act.get("codigo_actividad", "")} - {act.get("descripcion", "")}', True)
                    _texto_celda(cols[3], act["supervisor_f"])
                    _texto_celda(cols[4], str(act.get("inicio_plan", ""))[:16])
                    _texto_celda(cols[5], str(act.get("fin_plan", ""))[:16])
                    _texto_celda(cols[6], act.get("duracion_h", ""))
                    cols[7].markdown(f"**{current_pct}%**")
                    pct_key = f"rt_pct_{aid}"
                    if pct_key not in st.session_state:
                        st.session_state[pct_key] = current_pct
                    new_pct = cols[8].number_input("% nuevo", 0, 100, step=1, key=pct_key, label_visibility="collapsed")
                    desc = cols[9].text_area("Descripción del avance", key=f"rt_desc_{aid}", placeholder="Describa el avance realizado...", height=72, label_visibility="collapsed")
                    # Solo se permiten nuevas evidencias DURANTE o FINAL.
                    # Los registros históricos INICIO permanecen en Supabase.
                    stage_key = f"rt_stage_{aid}"
                    if st.session_state.get(stage_key) == "INICIO":
                        st.session_state[stage_key] = "DURANTE"
                    stage = cols[10].selectbox(
                        "Etapa",
                        ["DURANTE", "FINAL"],
                        key=stage_key,
                        label_visibility="collapsed",
                    )
                    # Foto y Guardar pertenecen exclusivamente a esta fila.
                    # El selector se abre encima de la tabla, dentro de un popover.
                    with cols[11]:
                        # Cada actividad dispone de su propio selector. Al guardar,
                        # aumentamos su generación: el nuevo key crea un uploader
                        # vacío sin afectar las fotografías de otras actividades.
                        photo_generation_key = f"rt_photo_generation_{aid}"
                        photo_generation = int(st.session_state.get(photo_generation_key, 0))
                        photo_widget_key = f"rt_photo_{aid}_g{photo_generation}"
                        foto_seleccionada = st.session_state.get(photo_widget_key, []) or []
                        etiqueta_foto = (
                            f"📷 Foto ({len(foto_seleccionada)})"
                            if foto_seleccionada else "📷 Cargar foto"
                        )
                        with st.popover(etiqueta_foto, use_container_width=True):
                            st.caption(f'Evidencia de {act.get("codigo_actividad", aid)}')
                            photos = st.file_uploader(
                                "Seleccionar fotografías",
                                type=["jpg", "jpeg", "png", "webp"],
                                accept_multiple_files=True,
                                key=photo_widget_key,
                            )
                            if photos:
                                st.caption(f"{len(photos)} fotografía(s) listas para guardar")
                    with cols[12]:
                        guardar_fila = st.button(
                            "💾", key=f"rt_save_{aid}",
                            help=f'Guardar solamente {act.get("codigo_actividad", aid)}',
                            use_container_width=True,
                        )
                    with cols[13]:
                        if st.button("👁", key=f"rt_view_{aid}", help="Ver evidencias registradas"):
                            _ver_evidencias_actividad(aid, act.get("codigo_actividad", aid))

                    if guardar_fila:
                        descripcion_limpia = str(desc or "").strip()
                        if not descripcion_limpia:
                            st.warning(
                                f'Escriba la descripción de avance de '
                                f'{act.get("codigo_actividad", aid)} antes de guardar.'
                            )
                        elif len(photos or []) > 10:
                            st.error("Máximo 10 fotografías por actividad y registro.")
                        else:
                            urls = []
                            errores_fotos = []
                            with st.spinner(
                                f'Guardando {act.get("codigo_actividad", aid)}...'
                            ):
                                for photo in (photos or []):
                                    try:
                                        resultado = upload_evidence(
                                            photo,
                                            str(act["ot_numero"]),
                                            str(act["id"]),
                                            max_retries=3,
                                        )
                                        urls.append(resultado["url"])
                                    except Exception as exc:
                                        errores_fotos.append(
                                            f'{getattr(photo, "name", "Foto")}: {exc}'
                                        )
                                if errores_fotos:
                                    st.error(
                                        "No se guardó el reporte porque falló la carga "
                                        "de una o más fotografías."
                                    )
                                    for _error in errores_fotos:
                                        st.code(_error)
                                else:
                                    payload = {
                                        "actividad_id": int(act["id"]),
                                        "avance": int(new_pct),
                                        "descripcion_avance": descripcion_limpia,
                                        "observaciones": "",
                                        "evidencias": urls,
                                        "tipo_evidencia": stage,
                                        "usuario": st.session_state.get("username", ""),
                                        "fecha_registro": datetime.now(timezone.utc).isoformat(),
                                    }
                                    try:
                                        supabase.table("avances_actividad").insert(payload).execute()
                                    except Exception as exc:
                                        st.error(
                                            f'No se pudo guardar la actividad '
                                            f'{act.get("codigo_actividad", aid)}: {exc}'
                                        )
                                    else:
                                        # Cambiar el identificador del file_uploader
                                        # SOLO después de confirmar el guardado en
                                        # Supabase. Esto descarta la foto visible al
                                        # instante y evita enviarla dos veces.
                                        st.session_state[photo_generation_key] = photo_generation + 1
                                        invalidate()
                                        st.session_state.setdefault(
                                            "registro_tab_clear_ids", []
                                        ).append(aid)
                                        st.session_state["registro_tab_saved"] = (
                                            act.get("codigo_actividad", aid)
                                        )
                                        st.rerun()
                    st.divider()



# ============================================================
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
# REPORTE POR SUPERVISOR - V35 (MECÁNICA)
# ============================================================
if page == "Reporte por supervisor":
    st.subheader("Reporte de actividades por supervisor")
    st.caption("Seguimiento operativo y fotográfico de los trabajos mecánicos. Incluye todas las OTs asignadas al supervisor seleccionado.")

    if activities.empty or ots.empty:
        st.info("No hay actividades disponibles para este reporte.")
    else:
        supervisors = sorted(
            [v for v in activities.get("supervisor", pd.Series(dtype=str)).dropna().astype(str).str.strip().unique().tolist() if v]
        )
        a, b, c = st.columns([2.3, 1.7, 1.5])
        supervisor_pick = a.selectbox("Supervisor", ["TODOS"] + supervisors, key="v35_sup_supervisor")
        working = activities.copy()
        if supervisor_pick != "TODOS":
            working = working[
                working["supervisor"].fillna("").astype(str).str.strip() == supervisor_pick
            ].copy()
        otkeys = working["ot_id"].dropna().astype(str)
        otlabels = ots.copy()
        otlabels["id_text"] = otlabels["id"].astype(str)
        otchoices = sorted(otlabels.loc[otlabels["id_text"].isin(otkeys),"ot"].fillna("S/OT").astype(str).unique().tolist())
        ot_pick = b.selectbox("OT", ["TODAS"] + otchoices, key="v35_sup_ot")
        if ot_pick != "TODAS":
            allowed = set(otlabels.loc[otlabels["ot"].astype(str) == ot_pick,"id_text"])
            working = working[working["ot_id"].astype(str).isin(allowed)].copy()
        status_pick = c.selectbox("Estado", ["TODOS", "Culminada", "En ejecución", "No iniciada"], key="v35_sup_estado")
        report = _supervisor_report_model(working, ots, progress)
        if status_pick != "TODOS" and not report.empty:
            report = report[report["estado"] == status_pick].copy()

        if report.empty:
            st.info("No se encontraron actividades para los filtros seleccionados.")
        else:
            total = len(report)
            finished = int((report["avance_real"] >= 100).sum())
            active = int(((report["avance_real"] > 0) & (report["avance_real"] < 100)).sum())
            pending = int((report["avance_real"] <= 0).sum())
            with_reports = int((report["n_reportes"] > 0).sum())
            st.markdown('<div class="mainin-section">Resumen operativo por supervisor</div>', unsafe_allow_html=True)
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("OTs", report["numero_ot"].nunique())
            k2.metric("Actividades", total)
            k3.metric("Avance promedio", f'{report["avance_real"].mean():.1f}%')
            k4.metric("Cobertura de reporte", f'{100*with_reports/total:.1f}%')
            k5, k6, k7, k8 = st.columns(4)
            k5.metric("Culminadas", finished)
            k6.metric("En ejecución", active)
            k7.metric("No iniciadas", pending)
            k8.metric("HH ganadas / plan", f'{report["hh_ganadas_calc"].sum():.1f} / {report["hh_plan_calc"].sum():.1f}')
            st.markdown("### Avance por supervisor")
            by_sup = report.groupby("supervisor", dropna=False).agg(
                Actividades=("id", "size"),
                Avance=("avance_real", "mean"),
                Reportadas=("n_reportes", lambda x: int((x > 0).sum())),
            ).reset_index()
            by_sup["Cobertura (%)"] = (by_sup["Reportadas"] / by_sup["Actividades"] * 100).round(1)
            by_sup["Avance"] = by_sup["Avance"].round(1)
            if len(by_sup) > 1:
                st.dataframe(
                    by_sup.rename(columns={
                        "supervisor": "Supervisor", "Avance": "Avance (%)",
                        "Reportadas": "Actividades reportadas",
                    }), use_container_width=True, hide_index=True,
                )
                fig = px.bar(
                    by_sup.sort_values("Avance"), x="Avance", y="supervisor",
                    orientation="h", text="Avance", color_discrete_sequence=["#13578C"],
                )
                fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig.update_layout(
                    xaxis_title="Avance (%)",yaxis_title=None,
                    xaxis_range=[0, 110],showlegend=False,
                    height=max(250, 36*len(by_sup)+130),
                    margin=dict(l=20,r=18,b=22,t=15),
                )
                st.plotly_chart(fig, use_container_width=True)
            st.markdown("### Relación de actividades")
            columns = [
                "numero_ot", "codigo_actividad", "descripcion", "grupo", "supervisor",
                "avance_real", "estado", "hh_plan_calc", "hh_ganadas_calc", "n_reportes", "ultimo_reporte", "descripcion_avance",
            ]
            labels = {
                "numero_ot":"OT", "codigo_actividad":"Actividad", "descripcion":"Descripción",
                "grupo":"Grupo", "supervisor":"Supervisor", "avance_real":"Avance (%)",
                "estado":"Estado", "hh_plan_calc":"HH plan", "hh_ganadas_calc":"HH ganadas",
                "n_reportes":"N.º reportes", "ultimo_reporte":"Último reporte",
                "descripcion_avance":"Último avance registrado",
            }
            shown = report[[col for col in columns if col in report.columns]].rename(columns=labels)
            st.dataframe(shown, use_container_width=True, hide_index=True)

            st.markdown("### Actividades pendientes de seguimiento")
            open_items = report[(report["avance_real"] < 100) | (report["n_reportes"] == 0)]
            if open_items.empty:
                st.success("No hay actividades pendientes para los filtros seleccionados.")
            else:
                pending_columns = ["numero_ot","codigo_actividad","descripcion","grupo","estado","avance_real","ultimo_reporte"]
                st.dataframe(
                    open_items[pending_columns].rename(columns=labels),
                    use_container_width=True,hide_index=True,
                )

            st.markdown('<div class="mainin-section">Descargar informes</div>', unsafe_allow_html=True)
            base_name = "".join(ch for ch in supervisor_pick if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_") or "TODOS"
            st.download_button(
                "⇩ Descargar detalle en Excel (CSV)",
                data=shown.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"supervisor_{base_name}_{datetime.now():%Y%m%d}.csv",
                mime="text/csv",use_container_width=True,
            )
            option_photo = st.checkbox(
                "Incluir informe fotográfico detallado (una página por actividad)",
                value=False, key="v35_sup_photos",
                help="Descarga independiente; puede tardar más si existen numerosas fotografías.",
            )
            sig_raw = (str(sorted(report["id"].astype(str).tolist())) +
                       str(len(progress)) + supervisor_pick + ot_pick + status_pick + str(option_photo))
            sig = hashlib.sha256(sig_raw.encode("utf-8")).hexdigest()
            if st.button("Generar PDF del supervisor", type="primary", use_container_width=True, key="v35_sup_generar_pdf"):
                try:
                    with st.spinner("Preparando el informe... "):
                        if option_photo:
                            pdfbytes = build_activity_report_pdf(
                                working[working["id"].astype(str).isin(report["id"])], ots, progress
                            )
                        else:
                            pdfbytes = build_supervisor_summary_pdf(report, supervisor_pick)
                    st.session_state["v35_sup_pdf_bytes"] = pdfbytes
                    st.session_state["v35_sup_pdf_sig"] = sig
                    st.success("Informe generado. Ya puedes descargarlo.")
                except Exception as e:
                    st.error(f"No fue posible generar el PDF: {e}")
            if st.session_state.get("v35_sup_pdf_sig") == sig and st.session_state.get("v35_sup_pdf_bytes"):
                st.download_button(
                    "⇩ Descargar PDF del supervisor",
                    data=st.session_state["v35_sup_pdf_bytes"],
                    file_name=f"reporte_{base_name}_{'fotografico' if option_photo else 'operativo'}_{datetime.now():%Y%m%d}.pdf",
                    mime="application/pdf",use_container_width=True,
                )
            st.caption("Los informes consultan los registros actuales de Supabase. No modifican avances ni evidencias existentes.")


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
# INFORME DE ACTIVIDADES
# ============================================================
if page == "Informe de Actividades":
    st.subheader("Informe de Actividades")

    st.caption(
        "Genere un único PDF consolidado o un informe específico. "
        "Cada actividad se presenta en una página independiente con "
        "detalle operativo y evidencias históricas disponibles. Los nuevos reportes usan DURANTE / FINAL."
    )

    if ots.empty or activities.empty:
        st.info("No existen OTs o actividades disponibles.")

    else:
        supervisors = []

        if "supervisor" in activities.columns:
            supervisors = sorted(
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

        c1, c2, c3 = st.columns(3)

        report_supervisor = c1.selectbox(
            "Supervisor",
            ["TODOS"] + supervisors,
            key="report_activity_supervisor",
        )

        if report_supervisor == "TODOS":
            report_activities_base = activities.copy()
        else:
            report_activities_base = activities[
                activities["supervisor"]
                .fillna("")
                .astype(str)
                == report_supervisor
            ].copy()

        report_ot_ids = (
            report_activities_base["ot_id"]
            .dropna()
            .unique()
            .tolist()
        )

        report_ots = ots[
            ots["id"].isin(report_ot_ids)
        ].copy()

        ot_values = (
            report_ots["ot"]
            .astype(str)
            .sort_values()
            .tolist()
        )

        report_ot = c2.selectbox(
            "OT",
            ["TODAS"] + ot_values,
            key="report_activity_ot",
        )

        # --------------------------------------------------------
        # ACTIVIDADES SEGÚN OT
        # --------------------------------------------------------
        if report_ot == "TODAS":
            report_ot_activities = report_activities_base.copy()
            activity_options = ["TODAS"]
        else:
            report_ot_row = report_ots[
                report_ots["ot"].astype(str) == report_ot
            ].iloc[0]

            report_ot_activities = report_activities_base[
                report_activities_base["ot_id"]
                == report_ot_row["id"]
            ].copy()

            if not report_ot_activities.empty:
                report_ot_activities["report_label"] = (
                    report_ot_activities["codigo_actividad"].astype(str)
                    + " - "
                    + report_ot_activities["descripcion"].astype(str)
                )

                activity_options = (
                    ["TODAS"]
                    + report_ot_activities["report_label"].tolist()
                )
            else:
                activity_options = ["TODAS"]

        report_activity = c3.selectbox(
            "Actividad",
            activity_options,
            key="report_activity_activity",
            disabled=(report_ot == "TODAS"),
        )

        # --------------------------------------------------------
        # SELECCIÓN FINAL
        # --------------------------------------------------------
        if report_ot == "TODAS":
            selected_report_activities = report_activities_base.copy()

        elif report_activity == "TODAS":
            selected_report_activities = report_ot_activities.copy()

        else:
            selected_report_activities = report_ot_activities[
                report_ot_activities["report_label"]
                == report_activity
            ].copy()

        if selected_report_activities.empty:
            st.info("No existen actividades para los filtros seleccionados.")

        else:
            st.markdown("---")

            selected_ot_ids = (
                selected_report_activities["ot_id"]
                .dropna()
                .unique()
                .tolist()
            )

            selected_ots_count = len(selected_ot_ids)

            status_preview = build_activity_status(
                selected_report_activities,
                progress,
            )

            preview_progress = (
                float(status_preview["avance_real"].mean())
                if not status_preview.empty
                else 0.0
            )

            culminadas = (
                int((status_preview["avance_real"] >= 100).sum())
                if not status_preview.empty
                else 0
            )

            ejecucion = (
                int(
                    (
                        (status_preview["avance_real"] > 0)
                        & (status_preview["avance_real"] < 100)
                    ).sum()
                )
                if not status_preview.empty
                else 0
            )

            no_iniciadas = (
                int((status_preview["avance_real"] <= 0).sum())
                if not status_preview.empty
                else 0
            )

            k1, k2, k3, k4 = st.columns(4)

            k1.metric("OTs", selected_ots_count)
            k2.metric(
                "Actividades",
                len(selected_report_activities),
            )
            k3.metric(
                "Supervisor",
                (
                    report_supervisor
                    if report_supervisor != "TODOS"
                    else "Todos"
                ),
            )
            k4.metric(
                "Avance general",
                f"{preview_progress:.1f}%",
            )

            k5, k6, k7 = st.columns(3)
            k5.metric("Culminadas", culminadas)
            k6.metric("En ejecución", ejecucion)
            k7.metric("No iniciadas", no_iniciadas)

            preview_cols = [
                "codigo_actividad",
                "descripcion",
                "supervisor",
                "grupo",
                "inicio_plan",
                "fin_plan",
                "personal",
                "duracion_h",
                "hh_plan",
            ]

            preview_cols = [
                col
                for col in preview_cols
                if col in selected_report_activities.columns
            ]

            st.markdown("### Actividades incluidas")

            st.dataframe(
                selected_report_activities[preview_cols],
                use_container_width=True,
                hide_index=True,
            )

            # ----------------------------------------------------
            # GENERAR PDF
            # ----------------------------------------------------
            is_general = (
                report_supervisor == "TODOS"
                and report_ot == "TODAS"
            )

            if is_general:
                button_label = "📥 DESCARGAR INFORME GENERAL CONSOLIDADO"
                file_prefix = "informe_general_antapaccay"
            elif report_ot == "TODAS":
                button_label = (
                    "📥 DESCARGAR INFORME CONSOLIDADO DEL SUPERVISOR"
                )
                safe_supervisor = "".join(
                    ch
                    for ch in str(report_supervisor)
                    if ch.isalnum() or ch in "-_"
                ) or "supervisor"
                file_prefix = (
                    f"informe_supervisor_{safe_supervisor}"
                )
            else:
                button_label = "📥 DESCARGAR INFORME PDF"
                safe_ot = "".join(
                    ch
                    for ch in str(report_ot)
                    if ch.isalnum() or ch in "-_"
                ) or "OT"
                file_prefix = f"informe_actividades_{safe_ot}"

            with st.spinner("Preparando informe PDF..."):
                try:
                    activity_pdf = build_activity_report_pdf(
                        selected_report_activities,
                        ots,
                        progress,
                    )

                    file_name = (
                        f"{file_prefix}_"
                        f"{datetime.now():%Y%m%d_%H%M}.pdf"
                    )

                    st.download_button(
                        button_label,
                        data=activity_pdf,
                        file_name=file_name,
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True,
                    )

                    if is_general:
                        st.success(
                            f"Informe general listo: "
                            f"{selected_ots_count} OT(s) y "
                            f"{len(selected_report_activities)} "
                            f"actividad(es) consolidadas en un solo PDF."
                        )
                    elif report_ot == "TODAS":
                        st.caption(
                            "El PDF consolida todas las OTs y actividades "
                            "del supervisor seleccionado."
                        )
                    elif len(selected_report_activities) > 1:
                        st.caption(
                            "El PDF contiene una página independiente "
                            "por cada actividad de la OT."
                        )
                    else:
                        st.caption(
                            "El PDF contiene el informe de la actividad "
                            "seleccionada."
                        )

                except Exception as exc:
                    st.error(
                        "No fue posible generar el informe: "
                        f"{exc}"
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
# V33 - IMPORTACION INCREMENTAL SEGURA (SIN BORRAR AVANCES)
# ============================================================
def _inc_text(value):
    """Convierte valores Excel en texto sin el sufijo artificial .0."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return str(int(value))
    value = str(value).strip()
    if value.endswith(".0"):
        try:
            if float(value).is_integer():
                return str(int(float(value)))
        except (ValueError, OverflowError):
            pass
    return value


def _inc_key(value):
    """Clave de comparación, sin alterar los identificadores reales."""
    return " ".join(_inc_text(value).split()).casefold()


def _inc_decimal(value, default, column_name, row_number):
    if _inc_text(value) == "":
        return default
    try:
        number = float(value)
        if not pd.notna(number) or number < 0:
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            f"Fila {row_number}: {column_name} debe ser un número no negativo."
        )


def _inc_date(value, column_name, row_number):
    if _inc_text(value) == "":
        return None
    try:
        # Algunos Excel convierten las fechas en números seriales.
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            timestamp = pd.to_datetime(
                value, unit="D", origin="1899-12-30", errors="raise"
            )
        elif isinstance(value, str) and len(value.strip()) >= 10 and value[4:5] == "-":
            timestamp = pd.to_datetime(value, errors="raise")
        else:
            timestamp = pd.to_datetime(value, dayfirst=True, errors="raise")
        if pd.isna(timestamp):
            raise ValueError()
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp.isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Fila {row_number}: {column_name} contiene una fecha inválida.")


def _inc_fetch_all(client, table_name, columns):
    """Evita el límite por defecto de 1000 filas en Supabase."""
    rows = []
    offset = 0
    while True:
        segment = (
            client.table(table_name)
            .select(columns)
            .range(offset, offset + 999)
            .execute()
            .data or []
        )
        rows.extend(segment)
        if len(segment) < 1000:
            break
        offset += 1000
    return rows


def _inc_prepare(excel_activities, db_ots, db_activities):
    """Solo INSERT. EMERGENCIA es categoría sin OT numérica; nunca altera datos.

    Los payloads incluyen _fila_excel únicamente en memoria para permitir
    seleccionar actividades concretas. Este campo NO se envía a Supabase.
    """
    EMERGENCY_PENDING = "__PENDING_EMERGENCIA__"
    ot_map = {}
    ambiguous_ots = set()
    for record in db_ots:
        ot_key = _inc_key(record.get("ot"))
        if not ot_key:
            continue
        if ot_key in ot_map and str(ot_map[ot_key]) != str(record.get("id")):
            ambiguous_ots.add(ot_key)
        else:
            ot_map[ot_key] = record.get("id")

    existing = {
        (str(record.get("ot_id")), _inc_key(record.get("codigo_actividad")))
        for record in db_activities
    }
    seen_excel = set()
    candidates = []
    preview = []
    issues = 0
    duplicates = 0

    for row_index, (_, row) in enumerate(excel_activities.iterrows(), start=2):
        ot = _inc_text(row.get("ot"))
        code = _inc_text(row.get("codigo_actividad"))
        description = _inc_text(row.get("descripcion"))
        if not any([ot, code, description]):
            continue
        entry = {
            "Fila Excel": row_index,
            "OT": ot or "(VACÍA)",
            "Actividad": code,
            "Descripción": description,
            "Resultado": "",
            "Motivo": "",
        }
        ot_key = _inc_key(ot)
        if not ot or not code or not description:
            entry["Resultado"] = "REVISAR"
            entry["Motivo"] = "Faltan OT/categoría, código o descripción"
            issues += 1
        elif ot_key in ambiguous_ots:
            entry["Resultado"] = "REVISAR"
            entry["Motivo"] = "Hay más de una referencia con ese nombre en Supabase"
            issues += 1
        elif ot_key not in ot_map and ot_key != "emergencia":
            entry["Resultado"] = "REVISAR"
            entry["Motivo"] = "La OT no existe; créala en Administrar OTs"
            issues += 1
        else:
            # Si es EMERGENCIA y no existe en OTs, se puede crear una
            # referencia interna de agrupación justo antes de insertar.
            ot_id = ot_map.get(ot_key, EMERGENCY_PENDING)
            key = (str(ot_id), _inc_key(code))
            if key in existing:
                entry["Resultado"] = "EXISTE"
                entry["Motivo"] = "No se modificará el registro ni su historial"
                duplicates += 1
            elif key in seen_excel:
                entry["Resultado"] = "DUPLICADA EN EXCEL"
                entry["Motivo"] = "El código aparece repetido para la misma OT"
                duplicates += 1
            else:
                try:
                    payload = {
                        "ot_id": ot_id,
                        "codigo_actividad": code,
                        "descripcion": description,
                        "supervisor": _inc_text(row.get("supervisor")),
                        "especialidad": _inc_text(row.get("especialidad")) or "MECANICA",
                        "grupo": _inc_text(row.get("grupo")),
                        "peso": _inc_decimal(row.get("peso"), 1.0, "peso", row_index),
                        "inicio_plan": _inc_date(row.get("inicio_plan"), "inicio_plan", row_index),
                        "fin_plan": _inc_date(row.get("fin_plan"), "fin_plan", row_index),
                        "_fila_excel": row_index,
                    }
                    if payload["inicio_plan"] and payload["fin_plan"]:
                        if payload["fin_plan"] < payload["inicio_plan"]:
                            raise ValueError(
                                f"Fila {row_index}: el fin planificado es anterior al inicio."
                            )
                    if "seccion" in excel_activities.columns:
                        payload["seccion"] = _inc_text(row.get("seccion"))
                    for numeric in ("personal", "duracion_h", "hh_plan"):
                        if numeric in excel_activities.columns:
                            payload[numeric] = _inc_decimal(
                                row.get(numeric), 0.0, numeric, row_index
                            )
                    candidates.append(payload)
                    seen_excel.add(key)
                    entry["Resultado"] = "NUEVA"
                    if ot_id == EMERGENCY_PENDING:
                        entry["Motivo"] = (
                            "Emergencia sin OT numérica; se creará una categoría "
                            "interna EMERGENCIA al confirmar"
                        )
                    elif ot_key == "emergencia":
                        entry["Motivo"] = (
                            "Se añadirá a EMERGENCIA, sin modificar datos anteriores"
                        )
                    else:
                        entry["Motivo"] = "Solo se agregará; no se modificarán avances"
                except ValueError as error:
                    entry["Resultado"] = "REVISAR"
                    entry["Motivo"] = str(error)
                    issues += 1
        preview.append(entry)
    return candidates, pd.DataFrame(preview), issues, duplicates



def _inc_excel_backup(ot_rows, activity_rows, report_rows):
    """Respaldo de datos; las fotos siguen guardadas en Storage."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, rows in (
            ("ots", ot_rows),
            ("actividades", activity_rows),
            ("avances_actividad", report_rows),
        ):
            df = pd.DataFrame(rows)
            for col in df.columns:
                df[col] = df[col].map(
                    lambda value: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list)) else
                    (value.isoformat() if isinstance(value, (datetime, pd.Timestamp)) else value)
                )
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


if page == "Agregar actividades Excel":
    st.subheader("Agregar actividades — sin borrar nada")
    st.success(
        "Importación incremental: SOLO inserta actividades seleccionadas. "
        "Nunca elimina, reemplaza o actualiza OTs, avances ni evidencias existentes."
    )
    st.caption(
        "EMERGENCIA se acepta como categoría de actividades sin OT numérica. "
        "No representa una orden de trabajo emitida por el cliente."
    )

    if supabase_admin is None:
        st.error(
            "Falta configurar [supabase_admin] key en Secrets de Streamlit "
            "para poder agregar actividades."
        )
    else:
        st.markdown("#### 1. Respaldo de la base actual")
        st.caption(
            "Descarga primero las OTs, actividades y avances. Las referencias "
            "a fotografías estarán en el Excel, pero los archivos siguen en Storage."
        )
        if st.button("Preparar respaldo", key="inc_prepare_backup"):
            try:
                backup_ots = _inc_fetch_all(supabase_admin, "ots", "*")
                backup_activities = _inc_fetch_all(supabase_admin, "actividades", "*")
                backup_reports = _inc_fetch_all(supabase_admin, "avances_actividad", "*")
                st.session_state["inc_backup_data"] = _inc_excel_backup(
                    backup_ots, backup_activities, backup_reports
                )
                st.session_state["inc_backup_counts"] = (
                    len(backup_ots), len(backup_activities), len(backup_reports)
                )
            except Exception as exc:
                st.error(f"No se pudo preparar el respaldo: {exc}")
        if st.session_state.get("inc_backup_data"):
            b_counts = st.session_state["inc_backup_counts"]
            st.caption(
                f"Respaldo: {b_counts[0]} OTs, {b_counts[1]} actividades "
                f"y {b_counts[2]} reportes registrados."
            )
            st.download_button(
                "📥 Descargar respaldo Excel",
                data=st.session_state["inc_backup_data"],
                file_name=f"respaldo_antapaccay_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="inc_backup_download",
            )

        st.markdown("#### 2. Carga tu Excel actualizado")
        file = st.file_uploader(
            "Archivo Excel con la hoja actividades", type=["xlsx"],
            key="incremental_excel_upload_v34",
        )
        if file is not None:
            try:
                file_bytes = file.getvalue()
                file_id = hashlib.sha256(file_bytes).hexdigest()[:12]
                workbook = pd.ExcelFile(io.BytesIO(file_bytes))
                sheets = {sheet.strip().lower(): sheet for sheet in workbook.sheet_names}
                if "actividades" not in sheets:
                    raise ValueError("El Excel debe incluir una hoja llamada 'actividades'.")
                source_df = pd.read_excel(
                    workbook, sheet_name=sheets["actividades"],
                    dtype={"ot": "string", "codigo_actividad": "string"},
                )
                source_df.columns = [str(c).strip().lower() for c in source_df.columns]
                required = {"ot", "codigo_actividad", "descripcion"}
                if not required.issubset(source_df.columns):
                    raise ValueError(
                        "Faltan las columnas obligatorias: "
                        + ", ".join(sorted(required - set(source_df.columns)))
                    )

                current_ots = _inc_fetch_all(supabase_admin, "ots", "id,ot")
                current_activities = _inc_fetch_all(
                    supabase_admin, "actividades", "id,ot_id,codigo_actividad"
                )
                new_rows, review, issues, duplicates = _inc_prepare(
                    source_df, current_ots, current_activities
                )
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Filas revisadas", len(review))
                p2.metric("Nuevas disponibles", len(new_rows))
                p3.metric("Existentes / duplicadas", duplicates)
                p4.metric("Otras filas para revisar", issues)

                if not review.empty:
                    with st.expander("Ver revisión completa del Excel", expanded=bool(issues)):
                        st.dataframe(review, hide_index=True, use_container_width=True)
                if issues:
                    st.warning(
                        f"Hay {issues} fila(s) por corregir. NO se incorporarán. "
                        "Puedes seleccionar las filas válidas por separado."
                    )
                if not new_rows:
                    st.info("No se detectaron actividades nuevas para agregar.")
                else:
                    st.markdown("#### 3. Selecciona solamente las actividades que faltan")
                    st.caption(
                        "**Ninguna está seleccionada inicialmente.** Marca la casilla "
                        "Agregar únicamente en las actividades que quieres incorporar. "
                        "Las ya existentes no aparecen aquí porque se conservarán."
                    )
                    selectable = review.loc[review["Resultado"] == "NUEVA"].copy()
                    selectable.insert(0, "Agregar", False)
                    editor = st.data_editor(
                        selectable[
                            ["Agregar", "Fila Excel", "OT", "Actividad", "Descripción", "Motivo"]
                        ],
                        column_config={
                            "Agregar": st.column_config.CheckboxColumn(
                                "Agregar", help="Marca solo la actividad faltante", default=False,
                                required=True,
                            ),
                        },
                        disabled=["Fila Excel", "OT", "Actividad", "Descripción", "Motivo"],
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        key=f"inc_select_v34_{file_id}",
                    )
                    selected_row_numbers = set(
                        editor.loc[editor["Agregar"].fillna(False), "Fila Excel"].astype(int).tolist()
                    )
                    selected_payloads = [
                        p for p in new_rows if p.get("_fila_excel") in selected_row_numbers
                    ]
                    st.info(
                        f"**{len(selected_payloads)} actividad(es) seleccionada(s)** "
                        f"de {len(new_rows)} disponibles."
                    )
                    create_emergency = any(
                        p.get("ot_id") == "__PENDING_EMERGENCIA__"
                        for p in selected_payloads
                    )
                    if create_emergency:
                        st.warning(
                            "Entre las seleccionadas hay actividades EMERGENCIA. "
                            "Como no tienen OT numérica, se creará una ÚNICA referencia "
                            "interna 'EMERGENCIA' en la tabla OTs (si aún no existe). "
                            "Esto NO modifica ninguna OT previa."
                        )

                    confirm = st.checkbox(
                        "Confirmo que deseo INSERTAR solamente las filas marcadas, "
                        "manteniendo intactos los reportes, fotos y actividades existentes.",
                        key=f"inc_confirm_v34_{file_id}",
                    )
                    if st.button(
                        "✅ AGREGAR SOLO LAS ACTIVIDADES SELECCIONADAS",
                        type="primary", use_container_width=True,
                        disabled=(not confirm or not selected_payloads),
                        key="inc_import_v34",
                    ):
                        # Releer datos en el instante de guardar para evitar
                        # insert duplicados si otro usuario cargó el mismo Excel.
                        fresh_ots = _inc_fetch_all(supabase_admin, "ots", "id,ot")
                        fresh_activities = _inc_fetch_all(
                            supabase_admin, "actividades", "id,ot_id,codigo_actividad"
                        )
                        validated, _, _, _ = _inc_prepare(
                            source_df, fresh_ots, fresh_activities
                        )
                        validated = [
                            p for p in validated if p.get("_fila_excel") in selected_row_numbers
                        ]
                        already_present = len(selected_payloads) - len(validated)

                        if not validated:
                            st.info(
                                "Las actividades seleccionadas ya existen o ahora requieren revisión; "
                                "no se insertó ninguna."
                            )
                        else:
                            # Solo la categoría EMERGENCIA puede requerir alta.
                            if any(p["ot_id"] == "__PENDING_EMERGENCIA__" for p in validated):
                                existing_emergencies = [
                                    r for r in fresh_ots
                                    if _inc_key(r.get("ot")) == "emergencia"
                                ]
                                if len(existing_emergencies) > 1:
                                    st.error(
                                        "Existen referencias EMERGENCIA duplicadas. "
                                        "No se agregó nada: revise esas OTs primero."
                                    )
                                    st.stop()
                                if not existing_emergencies:
                                    try:
                                        supabase_admin.table("ots").insert({
                                            "ot": "EMERGENCIA",
                                            "equipo": "TRABAJOS DE EMERGENCIA",
                                            "descripcion": "Agrupación interna: actividades sin OT numérica",
                                            "activo": True,
                                        }).execute()
                                    except Exception as error:
                                        st.error(
                                            "No se pudo crear la agrupación EMERGENCIA: "
                                            f"{error}. No se importaron esas actividades."
                                        )
                                        st.stop()

                                # Verificación nueva con el id real, antes de insertar.
                                fresh_ots = _inc_fetch_all(supabase_admin, "ots", "id,ot")
                                refreshed, _, _, _ = _inc_prepare(
                                    source_df, fresh_ots, fresh_activities
                                )
                                validated = [
                                    p for p in refreshed
                                    if p.get("_fila_excel") in selected_row_numbers
                                ]
                                if any(p["ot_id"] == "__PENDING_EMERGENCIA__" for p in validated):
                                    st.error(
                                        "No se pudo confirmar la referencia EMERGENCIA; "
                                        "la importación se detuvo."
                                    )
                                    st.stop()

                            successes = 0
                            failures = []
                            progress_widget = st.progress(0, text="Agregando solo seleccionadas...")
                            for index, raw_payload in enumerate(validated, start=1):
                                payload = {
                                    k: v for k, v in raw_payload.items()
                                    if k != "_fila_excel"
                                }
                                try:
                                    supabase_admin.table("actividades").insert(payload).execute()
                                    successes += 1
                                except Exception as exc:
                                    failures.append(
                                        f"Fila {raw_payload.get('_fila_excel')} · "
                                        f"{payload.get('codigo_actividad')} · {exc}"
                                    )
                                progress_widget.progress(
                                    index / len(validated),
                                    text=f"Procesadas {index} de {len(validated)}",
                                )
                            invalidate()
                            st.cache_data.clear()
                            if successes:
                                st.success(
                                    f"✅ Se agregaron {successes} actividad(es). "
                                    "Las actividades anteriores, avances y fotos no se modificaron."
                                )
                            if already_present:
                                st.info(
                                    f"{already_present} actividad(es) seleccionada(s) "
                                    "no se importaron porque ya existen o requieren revisión."
                                )
                            if failures:
                                st.error(
                                    f"Hubo {len(failures)} error(es). Ningún registro "
                                    "existente fue borrado ni actualizado."
                                )
                                with st.expander("Ver errores de importación"):
                                    for item in failures:
                                        st.write(item)
            except Exception as exc:
                st.error(f"No fue posible revisar o importar el Excel: {exc}")


# ============================================================
# IMPORTAR BASE
# ============================================================
if page == "Importar base":
    st.subheader(
        "REINICIO COMPLETO DE BASE (OPERACIÓN DESTRUCTIVA)"
    )

    st.warning(
        "PELIGRO: esta función ELIMINA las OTs existentes y puede borrar "
        "actividades, avances y sus relaciones. NO la utilice para agregar "
        "actividades faltantes. Vaya a 'Agregar actividades Excel'."
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
