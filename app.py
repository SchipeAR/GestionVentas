import streamlit as st

# ---------- URL/State helpers para selid (anti-loop) ----------
QP_DISABLED = any(k.startswith("_x_tr") for k in st.query_params.keys()) or (st.query_params.get("noqp") == "1")

def qp_get(key, default=None):
    val = st.query_params.get(key, default)
    if isinstance(val, list):
        return val[0] if val else default
    return val

def qp_set(**kwargs):
    if QP_DISABLED:
        for k, v in kwargs.items():
            st.session_state[k] = v
        return
    curr = dict(st.query_params)
    wanted = {k: ("" if v is None else str(v)) for k, v in kwargs.items()}
    if any(curr.get(k) != wanted[k] for k in wanted.keys()):
        newqp = {**curr, **wanted}
        st.query_params.update(newqp)

def get_current_selid():
    if not QP_DISABLED:
        raw = st.query_params.get("selid")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        try:
            return int(raw) if raw is not None else None
        except Exception:
            return None
    try:
        return int(st.session_state.get("selid")) if st.session_state.get("selid") is not None else None
    except Exception:
        return None

def _set_selid(new_selid: int):
    if not QP_DISABLED:
        if st.query_params.get("selid") != str(new_selid):
            _set_selid(int(new_selid))
            st.rerun()
    else:
        if st.session_state.get("selid") != int(new_selid):
            st.session_state["selid"] = int(new_selid)
            st.rerun()

def _clear_selid():
    if not QP_DISABLED:
        qp = dict(st.query_params)
        if "selid" in qp:
            qp.pop("selid", None)
            st.query_params.update(qp)
            st.rerun()
    else:
        if "selid" in st.session_state:
            st.session_state.pop("selid")
            st.rerun()
# ---------------------------------------------------------------

import sqlite3
from datetime import datetime, date
import pandas as pd
from calendar import monthrange
import os
from streamlit.components.v1 import html as st_html
import base64, json, requests, os
from passlib.hash import bcrypt as bcrypt_hash
import os, sqlite3, streamlit as st
import tempfile
import hashlib
import json
import urllib.parse
import time
import unicodedata
import re
import io
import streamlit.components.v1 as components
from urllib.parse import urlparse
from contextlib import contextmanager
import sqlite3
import gspread
from google.oauth2 import service_account
from gspread_formatting import (
    set_frozen,
    format_cell_range,
    set_column_widths,
    CellFormat, TextFormat, NumberFormat, Color
)
from contextlib import closing

def _sheets_client():
    creds_info = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def formatear_hoja_backup(worksheet_title: str):
    url   = st.secrets.get("GS_WEBAPP_URL", "")
    token = st.secrets.get("GS_WEBAPP_TOKEN", "")
    if not url or not token:
        st.info("Faltan GS_WEBAPP_URL / GS_WEBAPP_TOKEN en Secrets.")
        return

    try:
        payload = {
            "token": token,
            "action": "format_sheet",
            "worksheet": worksheet_title,
        }
        r = requests.post(url, json=payload, timeout=30)
        st.write("Respuesta WebApp:", r.status_code, r.text)  # <-- DEBUG visible
        if r.ok:
            st.success("Pedido de formateo enviado ✅")
        else:
            st.error("La WebApp no aceptó el pedido de formateo.")
    except Exception as e:
        st.error(f"No se pudo contactar a la WebApp: {e}")
@contextmanager
def safe_tab(nombre: str):
    """Muestra cualquier excepción de la sección en pantalla en vez de 'pantalla vacía'."""
    try:
        yield
    except Exception as e:
        st.error(f"❌ Error en la sección: {nombre}")
        st.exception(e)

def _safe_list_operations(filters=None):
    try:
        return list_operations(filters or {})
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            st.error("⚠️ La base de datos está ocupada/bloqueada. Probá recargar en 10–20s.")
            st.stop()
        raise

QP_DISABLED = any(k.startswith("_x_tr") for k in st.query_params.keys()) or (st.query_params.get("noqp") == "1")

GH_REPO        = st.secrets["GH_REPO"]                         # ej: "tuusuario/tu-repo"
GH_BRANCH      = st.secrets.get("GH_BRANCH", "main")
GH_PUBLIC_PATH = st.secrets.get("GH_PUBLIC_PATH", "public/latest_stock.csv")
GH_TOKEN       = st.secrets["GH_TOKEN"]

st.set_page_config(layout="wide")

try:
    import datetime as _dt
    st.caption(f"↻ {_dt.datetime.now():%Y-%m-%d %H:%M:%S} · QP_DISABLED={QP_DISABLED}")
except Exception:
    pass

group_esim_sim = st.session_state.get("group_esim_sim", True)
show_full      = st.session_state.get("show_full", False)
margin_usd     = st.session_state.get("margin_usd", 30.0)
TOTO_VENDOR_NAME = "Toto Donofrio"
TOTO_INV_NAME    = "TOBIAS (YO)"   # <-- si en tu DB el inversor se llama distinto, cambialo acá
TOTO_INV_PCT     = 0.18

def qp_get(key, default=None):
    """Lee ?key=... desde st.query_params y devuelve str (o default)."""
    val = st.query_params.get(key, default)
    # según versión puede venir list o str; normalizamos a str
    if isinstance(val, list):
        return val[0] if val else default
    return val


def qp_set(**kwargs):
    """Setea varios query params de una."""
    # convertimos todo a str por prolijidad
    st.query_params.update({k: "" if v is None else str(v) for k, v in kwargs.items()})

def qp_clear():
    """Borra todos los query params."""
    st.query_params.clear()

def get_current_selid() -> int | None:
    """Lee el ID seleccionado desde la URL o session_state (modo seguro)."""
    if not QP_DISABLED:
        raw = st.query_params.get("selid")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        try:
            return int(raw) if raw is not None else None
        except Exception:
            return None
    # modo seguro: session_state
    try:
        return int(st.session_state.get("selid")) if st.session_state.get("selid") is not None else None
    except Exception:
        return None

def _set_selid(new_selid: int):
    """Setea el ID a gestionar sin navegar a otra página."""
    if not QP_DISABLED:
        _set_selid(int(new_selid))
        st.rerun()
    else:
        st.session_state["selid"] = int(new_selid)
        st.rerun()

def _clear_selid():
    """Limpia la selección actual."""
    if not QP_DISABLED:
        qp = st.query_params
        if "selid" in qp:
            del qp["selid"]
            st.query_params.update(qp)
            st.rerun()
    else:
        st.session_state.pop("selid", None)
        st.rerun()

def _pub_cfg():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PUBLIC_PATH}"
    return url

def _pub_headers():
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def _pub_get_sha():
    url = _pub_cfg()
    r = requests.get(url, headers=_pub_headers(), params={"ref": GH_BRANCH}, timeout=30)
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    raise RuntimeError(f"GitHub GET falló: {r.status_code} {r.text[:200]}")

def publish_public_view(show_df: pd.DataFrame):
    # Solo columnas públicas
    df_public = show_df[["Modelo", "Valor Venta (USD)"]].copy()
    csv_bytes = df_public.to_csv(index=False).encode("utf-8")

    url = _pub_cfg()
    sha = _pub_get_sha()
    payload = {
        "message": f"publish latest_stock {time.strftime('%Y-%m-%d %H:%M')}",
        "content": base64.b64encode(csv_bytes).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_pub_headers(), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub PUT falló: {r.status_code} {r.text[:200]}")

import requests, json, textwrap, streamlit as st

def call_webapp(action: str, data: dict):
    url = st.secrets["GS_WEBAPP_URL"]
    tok = st.secrets.get("GS_WEBAPP_TOKEN", "")
    payload = {"action": action, "token": tok, **(data or {})}
    r = requests.post(url, json=payload, timeout=40)
    # Muestra respuesta para debug inmediato
    st.write("STATUS:", r.status_code)
    st.code(textwrap.shorten(r.text, width=800, placeholder=" … "), language="json")
    return r


# === VISTA PÚBLICA =====================================================
public = qp_get("public", "0")
if str(public) == "1":
    st.title("🟢 Stock iPhone — Vista pública")

    # Descargar el CSV público desde el repo (vía GitHub API Contents)
    url = _pub_cfg()
    r = requests.get(url, headers=_pub_headers(), params={"ref": GH_BRANCH}, timeout=30)
    if r.status_code == 404:
        st.warning("Aún no hay stock publicado. Procesá en la vista de admin para publicarlo.")
        st.stop()
    r.raise_for_status()
    content_b64 = r.json().get("content", "")
    csv_bytes = base64.b64decode(content_b64)
    dfpub = pd.read_csv(io.BytesIO(csv_bytes))

    # Mostrar tabla (solo 2 columnas)
    st.dataframe(dfpub, use_container_width=True)

    # Generar texto WhatsApp
    lines = [f"▪️{r['Modelo']} - $ {int(round(float(r['Valor Venta (USD)'])))}"
             for _, r in dfpub.iterrows()]
    msg = "\n".join(lines)

    import streamlit.components.v1 as components
    components.html(f"""
<div style='display:flex;gap:8px;align-items:center;margin:10px 0 8px;'>
  <button id='copyBtn'>Copiar Lista Whatsapp</button>
</div>
<textarea id='wa' rows='12' style='width:100%;'>{msg}</textarea>
<script>
const btn = document.getElementById('copyBtn');
btn.addEventListener('click', async () => {{
  const ta = document.getElementById('wa');
  ta.select();
  try {{ await navigator.clipboard.writeText(ta.value); }} catch(e) {{ document.execCommand('copy'); }}
}});
</script>
    """, height=260)

    # Descargar Excel (opcional; sigue siendo solo 2 columnas)
    from io import BytesIO
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        dfpub.to_excel(writer, index=False, sheet_name="Lista")
    buf.seek(0)
    st.download_button(
        "⬇️ Descargar Excel (Vista pública)",
        data=buf.getvalue(),
        file_name="lista_whatsapp_publica.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.stop()
# =======================================================================

# =======================================================================


st.markdown("""
<style>
/* Ancho total y menos padding lateral */
.block-container {
  max-width: 100% !important;
  padding-left: 0.8rem !important;
  padding-right: 0.8rem !important;
}
</style>
""", unsafe_allow_html=True)
# Porcentaje por defecto de cada inversor (fallback)
INV_PCT_DEFAULTS = {
    "GONZA": 0.18,
    "MARTIN": 0.18,
    "TOBIAS (YO)": 0.18,
}
SHOW_INV_MONTHLY_TABLE = False

def load_css():
    st.markdown("""
    <style>
      /* ===== Variables en grises ===== */
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      :root{
        --bg:#0e0e10;           /* fondo principal */
        --panel:#141416;        /* tarjetas/paneles */
        --panel-2:#17181a;      /* leve contraste */
        --border:#232327;       /* líneas/bordes */
        --muted:#9aa0a6;        /* texto secundario */
        --text:#e7e7e7;         /* texto principal */
        --primary:#22c55e;      /* acciones */
        --primary-2:#16a34a;
        --danger:#ef4444;
        --radius:16px;
      }

      /* ===== Fondo general, 100% gris (sin azules) ===== */
      .stApp{
        background:
          radial-gradient(900px 500px at 10% -10%, #17181a 0, transparent 55%),
          radial-gradient(900px 500px at 110% 10%, #1a1b1e 0, transparent 55%),
          linear-gradient(180deg, #0e0e10 0%, #0b0b0c 100%);
        font-family:'Inter', system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial, sans-serif;
        color: var(--text);
      }
      .block-container{max-width:1200px; padding-top:1.1rem;}

      /* ===== Títulos ===== */
      h1{font-size:2rem; line-height:1.15; margin:.2rem 0 1rem}
      h2,h3{letter-spacing:.2px}
      .accent{
        background: linear-gradient(90deg, var(--text), #cfcfcf);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      }

      /* ===== Tarjetas ===== */
      .card{
        background: linear-gradient(180deg, var(--panel), var(--panel-2));
        border:1px solid var(--border);
        border-radius:var(--radius);
        padding:18px; margin:12px 0;
        box-shadow: 0 18px 45px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.02);
      }
      .card h3{margin:0 0 .8rem 0; font-weight:600}

      /* ===== Tabs redondeadas ===== */
      div[role="tablist"]{gap:.45rem; margin-bottom:.65rem}
      button[role="tab"]{
        border-radius:999px !important; padding:.52rem 1rem !important;
        background:#121214 !important; color:#c9c9c9 !important; border:1px solid var(--border) !important;
      }
      button[role="tab"][aria-selected="true"]{
        background: linear-gradient(180deg, #1a1b1d, #121213) !important;
        color:#fff !important; border-color: var(--primary) !important;
        box-shadow: 0 0 0 2px rgba(34,197,94,.14);
      }

      /* ===== Inputs/Selects en gris ===== */
      .stTextInput input, .stNumberInput input, .stDateInput input,
      .stSelectbox [role="combobox"], .stTextArea textarea{
        background:#0f1011; color:var(--text);
        border:1px solid var(--border); border-radius:12px;
      }
      .stTextInput input:focus, .stNumberInput input:focus,
      .stDateInput input:focus, .stSelectbox [role="combobox"]:focus,
      .stTextArea textarea:focus{
        border-color:#2c2d31; box-shadow: 0 0 0 3px rgba(120,120,120,.15);
      }

      /* ===== Botones ===== */
      div.stButton>button{
        border-radius:12px; padding:.62rem 1rem; border:1px solid var(--border);
        background: linear-gradient(180deg,#1a1b1d,#121213); color:#e7e7e7;
        transition: transform .05s ease, box-shadow .2s ease, border-color .2s ease, filter .2s;
      }
      div.stButton>button:hover{transform:translateY(-1px); border-color:#2f3136; box-shadow:0 10px 28px rgba(0,0,0,.28)}
      div.stButton>button:active{transform:translateY(0)}
      /* primario (verde) */
      div.stButton>button[kind="primary"]{
        background: linear-gradient(180deg, var(--primary), var(--primary-2)) !important;
        border-color: var(--primary-2) !important; color:#08150d !important; font-weight:600;
        text-shadow: 0 1px 0 rgba(255,255,255,.28);
      }
      /* peligro (rojo) */
      .btn-danger{background:linear-gradient(180deg,#ef4444,#dc2626)!important;color:#fff!important;border-color:#b91c1c!important}

      /* ===== Expanders/Tablas ===== */
      details[data-testid="stExpander"]{
        border:1px solid var(--border); border-radius:var(--radius); background:var(--panel);
      }
      details[data-testid="stExpander"] > summary{color:var(--text); font-weight:600}
      .stDataFrame thead tr th{background:#161719; color:#d2d2d2}
      .stDataFrame tbody tr:hover{background:#111112cc}

      /* ===== Badges ===== */
      .badge{
        display:inline-flex; align-items:center; gap:.35rem; padding:.22rem .6rem;
        background:#151617; border:1px solid var(--border); color:#b7b7b7; border-radius:999px; font-size:.78rem;
      }
      .badge--danger{background:#201314; border-color:#3a1b1d; color:#ffb3b7}

      /* ===== Hero header en gris ===== */
      .hero{
        display:flex; align-items:center; justify-content:space-between;
        gap:16px; padding:16px 18px; margin: 4px 0 12px;
        background:linear-gradient(180deg,#18191b,#111113); border:1px solid var(--border); border-radius:var(--radius);
      }
      .hero .title{font-size:1.4rem; font-weight:700}
      .hero .subtitle{color:#b3b3b3; font-size:.95rem}
    </style>
    """, unsafe_allow_html=True)


# ¡Llamalo!
load_css()

st.markdown("""
<style>
.pill, .bar-wrap { display: none !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.cal .chips, .cal .chip { display: none !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.pill { background: rgba(255,255,255,.06) !important; border-color: rgba(255,255,255,.12) !important; }
.bar-wrap { background: rgba(255,255,255,.10) !important; }
</style>
""", unsafe_allow_html=True)


# ⇩⇩ Pegar debajo de load_css() ⇩⇩
st.markdown("""
<style>
  .hero{ padding:22px 24px; }
  /* Título grande y responsivo */
  .hero .title{
    font-size: clamp(1.9rem, 2.6vw + 0.6rem, 2.6rem);
    line-height: 1.12;
    letter-spacing: .2px;
  }
  /* Subtítulo un poco más legible */
  .hero .subtitle{ font-size: 1rem; opacity: .9; }
</style>
""", unsafe_allow_html=True)


from contextlib import contextmanager

st.markdown(
    """
    <div class="hero">
      <div>
        <div class="title"><span class="accent">Gestión Ventas</span></div>
      </div>
      <div class="badge">UI mejorada</div>
    </div>
    """,
    unsafe_allow_html=True
)

@contextmanager
def card(title:str="", icon:str=""):
    st.markdown(f"<div class='card'>", unsafe_allow_html=True)
    if title:
        st.markdown(f"<h3>{icon} {title}</h3>", unsafe_allow_html=True)
    yield
    st.markdown("</div>", unsafe_allow_html=True)

DB_PATH = "ventas.db"
DELETE_SALES_PASSWORD = "totoborrar"   # contraseña para borrar ventas

def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

def _sqlite_consistent_bytes(db_path: str) -> bytes:
    """
    Devuelve el contenido de la DB en bytes, consistente,
    independientemente de que esté en WAL o no.
    """
    # archivo temporal donde volcamos un backup "limpio"
    fd, tmp_path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    try:
        # Abrimos la DB real y volcamos WAL -> archivo principal
        with sqlite3.connect(db_path, timeout=30) as src:
            # IMPORTANTE: si no está en WAL, no pasa nada; si está, mergea
            src.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            # backup nativo y atómico a tmp
            with sqlite3.connect(tmp_path) as dst:
                src.backup(dst)

        # Leemos bytes del backup consistente
        with open(tmp_path, "rb") as f:
            data = f.read()
        return data
    finally:
        try: os.remove(tmp_path)
        except: pass
    
def _db_is_empty(path: str) -> bool:
    # No existe, muy chica o sin tablas => la consideramos "vacía"
    if (not os.path.exists(path)) or (os.path.getsize(path) < 2048):
        return True
    try:
        with sqlite3.connect(path) as con:
            cnt = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        return (cnt or 0) == 0
    except Exception:
        return True

def restore_on_boot_once():
    """
    Se ejecuta una sola vez por sesión.
    Si la DB está vacía, intenta restaurar desde GitHub y hace rerun.
    Requiere que ya exista restore_from_github_snapshot().
    """
    if st.session_state.get("_did_boot_restore"):
        return
    st.session_state["_did_boot_restore"] = True

    if _db_is_empty(DB_PATH):
        try:
            restore_from_github_snapshot()   # <- usa tu función de restore a GH
            st.toast("Base restaurada desde GitHub ✅")
            st.rerun()  # recarga la UI ya con datos
        except Exception as e:
            st.warning(f"No se pudo restaurar el backup (seguís con base vacía): {e}")

# === Backup/Restore a GitHub (snapshot de SQLite) ===

def _gh_cfg():
    repo   = st.secrets["GH_REPO"]
    branch = st.secrets.get("GH_BRANCH", "main")
    path   = st.secrets.get("GH_PATH", "ventas.db")
    url    = f"https://api.github.com/repos/{repo}/contents/{path}"
    return url, branch

def _gh_headers():
    return {
        "Authorization": f"token {st.secrets['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def _gh_get_current_sha():
    url, branch = _gh_cfg()
    r = requests.get(url, headers=_gh_headers(), params={"ref": branch}, timeout=30)
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    raise RuntimeError(f"GitHub GET falló: {r.status_code} — {r.text[:200]}")

def _gh_get_current_bytes_or_none():
    """Trae bytes del archivo actual en GitHub para comparar (si es pequeño)."""
    url, branch = _gh_cfg()
    r = requests.get(url, headers=_gh_headers(), params={"ref": branch}, timeout=30)
    if r.status_code == 200:
        j = r.json()
        b64 = j.get("content")
        if b64 and j.get("encoding") == "base64":
            return base64.b64decode(b64)
        return None
    if r.status_code == 404:
        return None
    raise RuntimeError(f"GitHub GET falló: {r.status_code} — {r.text[:200]}")

def backup_snapshot_to_github():
    if not os.path.exists(DB_PATH):
        raise RuntimeError("No existe la base local para respaldar.")

    data = _sqlite_consistent_bytes(DB_PATH)

    current = _gh_get_current_bytes_or_none()
    if current is not None and _sha256_bytes(current) == _sha256_bytes(data):
        return "Sin cambios: el backup es idéntico al último en GitHub."

    url, branch = _gh_cfg()
    payload = {
        "message": f"Backup ventas.db {datetime.now():%Y-%m-%d %H:%M:%S}",
        "content": base64.b64encode(data).decode("ascii"),
        "branch": branch
    }
    sha = _gh_get_current_sha()
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_gh_headers(), json=payload, timeout=60)
    if r.status_code in (200, 201):
        j = r.json()
        return j.get("content", {}).get("html_url") or j.get("commit", {}).get("html_url")
    raise RuntimeError(f"GitHub PUT falló: {r.status_code} — {r.text[:200]}")

def restore_from_github_snapshot():
    """Baja GH_PATH y pisa ventas.db local."""
    url, branch = _gh_cfg()
    r = requests.get(url, headers=_gh_headers(), params={"ref": branch}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError("No hay backup en GitHub o no se puede acceder.")

    j = r.json()
    content_b64 = j.get("content")
    if not content_b64:
        raise RuntimeError("Contenido vacío del backup.")
    raw = base64.b64decode(content_b64)

    with open(DB_PATH, "wb") as f:
        f.write(raw)

    # Validación mínima
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1;").fetchone()
    except Exception as e:
        raise RuntimeError(f"Backup descargado inválido: {e}")

    return True

# ====== LOG PERSISTENTE EN SESSION_STATE ======
if "export_logs" not in st.session_state:
    st.session_state.export_logs = []

def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    st.session_state.export_logs.append(f"[{ts}] {msg}")
    st.write(msg)

def _ping_webapp():
    url   = st.secrets.get("GS_WEBAPP_URL", "")
    token = st.secrets.get("GS_WEBAPP_TOKEN", "")
    if not url:
        st.error("Falta GS_WEBAPP_URL en Secrets.")
        return False
    if "script.google.com/macros/s/" not in url or not url.endswith("/exec"):
        st.error("GS_WEBAPP_URL no es una Web App válida (debe terminar en /exec).")
        st.write("Valor actual:", url)
        return False
    try:
        r = requests.get(url, params={"token": token}, timeout=20, allow_redirects=True)
        st.info(f"Ping {urllib.parse.urlparse(r.url).netloc} → {r.status_code}: {r.text[:80]}")
        return r.status_code == 200
    except Exception as e:
        st.error(f"No se pudo contactar la Web App: {e}")
        return False
    
def exportar_a_sheets_webapp_desde_sqlite(db_path: str):
    url   = st.secrets.get("GS_WEBAPP_URL", "")
    token = st.secrets.get("GS_WEBAPP_TOKEN", "")
    with st.status("Exportando a Google Sheets…", expanded=True) as status:
        try:
            # 0) Validaciones básicas
            if not url or not token:
                _log("❌ Falta GS_WEBAPP_URL o GS_WEBAPP_TOKEN en Secrets.")
                status.update(label="Fallo: faltan secrets", state="error"); return
            _log("✅ Secrets presentes.")

            # 1) DB: existencia y tamaño
            if not os.path.exists(db_path):
                _log(f"❌ No existe la base: {db_path}")
                status.update(label="Fallo: no existe ventas.db", state="error"); return
            _log(f"📦 ventas.db encontrada ({os.path.getsize(db_path)} bytes).")

            # 2) Leer tablas
            with sqlite3.connect(db_path) as con:
                cur = con.cursor()
                tablas = [r[0] for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                _log(f"📚 Tablas encontradas: {', '.join(tablas) if tablas else '(ninguna)'}")
                if not tablas:
                    _log("❌ La base no tiene tablas (o está vacía).")
                    status.update(label="Fallo: base vacía", state="error"); return

                sheets = []
                total_filas = 0
                for t in tablas:
                    df = pd.read_sql_query(f"SELECT * FROM {t}", con)
                    values = [df.columns.tolist()] + df.astype(str).fillna("").values.tolist()
                    sheets.append({"name": t, "values": values})
                    total_filas += len(df)
                _log(f"🧮 Filas totales a exportar: {total_filas}")

            # 3) Probar Web App rápida (opcional pero útil)
            try:
                rp = requests.get(url, params={"token": token}, timeout=15, allow_redirects=True)
                _log(f"Ping final {urlparse(rp.url).netloc} → {rp.status_code}: {rp.text[:60]}")
                if rp.status_code != 200:
                    _log("⚠️ Web App no respondió 200 en ping; intento igual el POST…")
            except Exception as e:
                _log(f"⚠️ Ping falló ({e}); intento igual el POST…")

            # 4) Enviar POST con reintentos suaves
            payload = {"token": token, "action": "write_tables", "sheets": sheets}
            for attempt in range(3):
                _log(f"⬆️ POST intento {attempt+1}…")
                try:
                    r = requests.post(url, json=payload, timeout=60, allow_redirects=True)
                    _log(f"↩️ Respuesta {r.status_code}: {r.text[:120]}")
                    if r.status_code == 200 and "ok" in r.text.lower():
                        status.update(label="Exportación completada", state="complete")
                        st.toast("Google Sheets actualizado ✅")
                        return
                    if r.status_code == 429:
                        time.sleep(2 * (attempt + 1))
                        continue
                    status.update(label=f"Fallo HTTP {r.status_code}", state="error")
                    return
                except Exception as e:
                    _log(f"❌ Error de red: {e}")
                    status.update(label="Fallo de red", state="error")
                    return

            status.update(label="Fallo: 429 persistente", state="error")
        except Exception as e:
            _log(f"💥 Excepción no controlada: {e}")
            status.update(label="Fallo inesperado", state="error")

# =========================
# DB Helpers & Migrations
# =========================
def publish_public_view_sqlite(show_df: pd.DataFrame):
    # Guarda solo las 2 columnas visibles públicamente
    df_public = show_df[["Modelo", "Valor Venta (USD)"]].copy()
    with sqlite3.connect(DB_PATH) as con:
        df_public.to_sql("latest_stock", con, if_exists="replace", index=False)

def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

# ==== Helpers robustos para detectar ventas con 0 cuotas ====
def _table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    ).fetchone() is not None

def _cols(con, table: str):
    return {row[1].lower() for row in con.execute(f"PRAGMA table_info({table})")}

def _pick(cols: set, candidates: list[str]) -> str | None:
    for c in candidates:
        if c and c.lower() in cols:
            return c
    return None

def _pick_installments_table_and_fk(con):
    """Elige la tabla de cuotas y su columna FK hacia operations.id."""
    for tbl in ["installments_venta", "installments", "cuotas"]:
        if _table_exists(con, tbl):
            icols = _cols(con, tbl)
            fk = _pick(icols, ["op_id", "operation_id", "venta_id", "id_venta", "op"])
            if fk:
                return tbl, fk
    return None, None

def get_ops_zero_cuotas():
    """
    Devuelve ventas que no tienen NINGUNA cuota (por eso no aparecen en listados).
    Se adapta al esquema real de la base.
    """
    with get_conn() as con:
        if not _table_exists(con, "operations"):
            return []

        ocols = _cols(con, "operations")

        # Columnas opcionales (solo se usan si existen)
        desc_col  = _pick(ocols, ["descripcion", "desc", "detalle", "concepto"])
        vend_col  = _pick(ocols, ["zona", "vendedor", "seller"])
        fecha_col = _pick(ocols, ["fecha", "date", "created_at"])
        cuotas_col = _pick(ocols, ["cuotas", "cuotas_totales"])

        # SELECT adaptable (si no existe, mandamos string vacío)
        sel_desc  = f", o.{desc_col} AS descripcion" if desc_col  else ", '' AS descripcion"
        sel_vend  = f", o.{vend_col} AS vendedor"    if vend_col  else ", '' AS vendedor"
        sel_fecha = f", o.{fecha_col} AS fecha"      if fecha_col else ", '' AS fecha"

        inst_tbl, inst_fk = _pick_installments_table_and_fk(con)

        try:
            if inst_tbl and inst_fk:
                q = f"""
                    SELECT o.id {sel_desc} {sel_vend} {sel_fecha}
                    FROM operations o
                    LEFT JOIN {inst_tbl} iv ON iv.{inst_fk} = o.id
                    GROUP BY o.id
                    HAVING COALESCE(COUNT(iv.{inst_fk}), 0) = 0
                    ORDER BY o.id DESC
                """
            elif cuotas_col:
                q = f"""
                    SELECT o.id {sel_desc} {sel_vend} {sel_fecha}
                    FROM operations o
                    WHERE COALESCE(o.{cuotas_col}, 0) = 0
                    ORDER BY o.id DESC
                """
            else:
                # No hay forma clara de saber cuotas → devolvemos vacío
                return []

            rows = con.execute(q).fetchall()
        except Exception:
            # Fallback ultra simple por si igual falla: NO referenciar columnas opcionales
            rows = []
            try:
                if inst_tbl and inst_fk:
                    q2 = f"""
                        SELECT o.id FROM operations o
                        LEFT JOIN {inst_tbl} iv ON iv.{inst_fk} = o.id
                        GROUP BY o.id
                        HAVING COALESCE(COUNT(iv.{inst_fk}), 0) = 0
                        ORDER BY o.id DESC
                    """
                    rows = [(r[0], "", "", "") for r in con.execute(q2).fetchall()]
                elif cuotas_col:
                    q2 = f"SELECT id FROM operations WHERE COALESCE({cuotas_col},0)=0 ORDER BY id DESC"
                    rows = [(r[0], "", "", "") for r in con.execute(q2).fetchall()]
            except Exception:
                rows = []

        # Normalizamos a dicts
        out = []
        for r in rows:
            # r puede venir con sólo id; completamos strings vacíos
            rid   = r[0]
            desc  = r[1] if len(r) > 1 else ""
            vend  = r[2] if len(r) > 2 else ""
            fecha = r[3] if len(r) > 3 else ""
            out.append({"id": rid, "descripcion": str(desc or ""), "vendedor": str(vend or ""), "fecha": str(fecha or "")})
        return out
# === Notas por cuota (persistentes en la DB) ===
def ensure_notes_table():
    with get_conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS installment_notes(
            iid INTEGER PRIMARY KEY,
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        )""")
        con.commit()

def compra_cuotas_count(n_cuotas_venta: int) -> int:
    """# cuotas al inversor: 6 por defecto, 1 si la venta es de un pago."""
    return 1 if int(n_cuotas_venta or 0) == 1 else 6

def fmt_dmy_from_iso(iso_val) -> str:
    if not iso_val:
        return ""
    s = str(iso_val)
    # probamos varias formas: datetime ISO, date ISO, con "T", con espacio, solo fecha
    candidates = [s, s.split("T")[0], s.split(" ")[0]]
    for p in candidates:
        try:
            # primero intentamos datetime completo
            dt = datetime.fromisoformat(p)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            try:
                d = date.fromisoformat(p)
                return d.strftime("%d/%m/%Y")
            except Exception:
                pass
    return s  # fallback sin romper si viene en otro formato

def get_installment_note(iid: int) -> str:
    ensure_notes_table()
    with get_conn() as con:
        row = con.execute("SELECT note FROM installment_notes WHERE iid = ?", (iid,)).fetchone()
        return row[0] if row else ""

def set_installment_note(iid: int, note: str, updated_at_iso: str | None = None):
    ensure_notes_table()
    with get_conn() as con:
        con.execute("""
        INSERT INTO installment_notes (iid, note, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(iid) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at
        """, (iid, note, updated_at_iso or to_iso(date.today())))
        con.commit()
def ensure_ops_cols_weekly_ars():
    """Garantiza que operations tenga currency y freq. Es idempotente."""
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("PRAGMA table_info('operations')")
        cols = {row[1] for row in cur.fetchall()}  # set de nombres

        if "currency" not in cols:
            try:
                cur.execute("ALTER TABLE operations ADD COLUMN currency TEXT DEFAULT 'USD'")
            except Exception:
                pass  # por si ya existe

        if "freq" not in cols:
            try:
                cur.execute("ALTER TABLE operations ADD COLUMN freq TEXT DEFAULT 'MENSUAL'")
            except Exception:
                pass  # por si ya existe

        con.commit()
# ------------------- Utilidades de normalización -------------------
def normalize_text(t: str) -> str:
    t = unicodedata.normalize('NFKD', t)
    # bullets, dashes, asterisks, rare unicode
    t = t.replace('▪️',' ').replace('•',' ').replace('—','-')
    # normalize spaces and uppercase
    t = t.upper()
    t = re.sub(r'[ \t]+', ' ', t)
    return t

# ------------------- Parser principal -------------------
def parse_lines(vendor: str, text: str) -> pd.DataFrame:
    text = normalize_text(text)
    rows = []
    for raw in text.splitlines():
        line = raw.strip(' -*\u2022')
        if not line:
            continue

        # precio (USD o $)
        m_price = re.search(r'(?:USD|\$)\s*([0-9]+(?:[.,][0-9]+)?)', line)
        if not m_price:
            continue
        price = float(m_price.group(1).replace(',', '.'))

        # sacar colores/observaciones entre ( )
        core = re.sub(r'\([^)]*\)', '', line)

        # SIM/eSIM
        sim = 'ESIM' if 'ESIM' in core else ('SIM' if ' SIM ' in core or core.endswith(' SIM') else None)

        # storage
        storage_label = None
        storage_gb = None
        m_tb = re.search(r'\b(\d+)\s*TB\b', core)
        m_gb = re.search(r'\b(\d+)\s*GB\b', core)
        if m_tb:
            storage_label = f"{m_tb.group(1)} TB"; storage_gb = int(m_tb.group(1)) * 1000
        elif m_gb:
            storage_label = f"{m_gb.group(1)} GB"; storage_gb = int(m_gb.group(1))
        else:
            # formato tipo "* 16 128 USD 740"
            m_marco = re.search(r'(^|\s)(\d{2}[A-Z]?)\s+(\d{2,4})\s+USD', core)
            if m_marco:
                storage_gb = int(m_marco.group(3)); storage_label = f"{storage_gb} GB"

        # generación (13/14/15/16/16E)
        core2 = core.replace('IPHONE ', '')
        m_gen = re.search(r'\b(16E|13|14|15|16)\b', core2)
        gen = m_gen.group(1) if m_gen else None

        # variante
        variant = ''
        if re.search(r'PRO\s+MAX', core2):
            variant = 'PRO MAX'
        elif re.search(r'\bPRO\b', core2):
            variant = 'PRO'
        elif re.search(r'\bPLUS\b', core2):
            variant = 'PLUS'

        # intentos extra
        if not gen or not storage_label:
            m_gen2 = re.search(r'^\*?\s*(\d{2}[A-Z]?)\b', core2)
            if not gen and m_gen2:
                gen = m_gen2.group(1)
        if not gen or not storage_label:
            # no tengo datos suficientes
            continue

        # claves
        key = f"IPHONE {gen} {variant}".strip()
        key_full = f"{key} {storage_label}"

        rows.append({
            "vendor": vendor,
            "line": line,
            "gen": gen,
            "variant": variant,
            "storage_gb": storage_gb,
            "storage": storage_label,
            "sim": sim,
            "price_usd": price,
            "key": key_full,
            "key_with_sim": f"{key_full} {sim or ''}".strip()
        })
    return pd.DataFrame(rows)

def init_db():
    with get_conn() as con:
        cur = con.cursor()

        # =========================
        # Tablas base
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            descripcion TEXT,
            cliente TEXT,
            zona TEXT,
            nombre TEXT,
            proveedor TEXT,
            L REAL,
            N REAL,
            O INTEGER,
            estado TEXT,
            y_pagado REAL DEFAULT 0,
            comision REAL,
            sale_date TEXT,
            purchase_price REAL,
            created_at TEXT DEFAULT (date('now'))
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS installments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            amount REAL NOT NULL,
            paid INTEGER NOT NULL DEFAULT 0,
            paid_at TEXT,
            is_purchase INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
        );
        """)

        # =========================
        # MIGRACIONES DEFENSIVAS
        # =========================
        cur.execute("PRAGMA table_info(operations);")
        op_cols = [r[1] for r in cur.fetchall()]
        if "comision" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN comision REAL;")
        if "sale_date" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN sale_date TEXT;")
        if "purchase_price" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN purchase_price REAL;")
        if "cliente" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN cliente TEXT;")
        if "proveedor" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN proveedor TEXT;")
        if "created_at" not in op_cols:
            cur.execute("ALTER TABLE operations ADD COLUMN created_at TEXT DEFAULT (date('now'));")

        # =========================
        # USERS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        """)
        cur.execute("PRAGMA table_info(users);")
        user_cols = [r[1] for r in cur.fetchall()]
        if "role" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin';")
        if "vendedor" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN vendedor TEXT;")

        # Seed de usuarios por defecto
        cur.execute("SELECT COUNT(*) FROM users;")
        if (cur.fetchone() or [0])[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                ("admin", bcrypt_hash.hash("admin"), "admin", None)
            )
            cur.execute(
                "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                ("vendedor", bcrypt_hash.hash("vendedor"), "seller", "Vendedor 1")
            )

        # =========================
        # VENDORS
        # =========================
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        );
        """)

        # =========================
        # ÍNDICES
        # =========================
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inst_op_purchase_paid ON installments(operation_id, is_purchase, paid);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_nombre ON operations(nombre);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_zona ON operations(zona);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_cliente ON operations(cliente);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_proveedor ON operations(proveedor);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_estado ON operations(estado);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ops_sale_date ON operations(sale_date);")
# --- migración simple: agrega columna 'revendedor' si no existe
import sqlite3

def ensure_column_revendedor():
    try:
        with get_conn() as con:
            con.execute("ALTER TABLE operations ADD COLUMN revendedor TEXT")
    except Exception:
        # ya existe o la tabla es distinta; ignorar
        pass

ensure_column_revendedor()


# =========================
# CRUD básicos
# =========================
def upsert_operation(op):
    with get_conn() as con:
        cur = con.cursor()
        if op.get("id"):
            q = """
                UPDATE operations
                SET tipo=?, descripcion=?, cliente=?, zona=?, nombre=?, proveedor=?, revendedor=?,
                    L=?, N=?, O=?, estado=?, y_pagado=?, comision=?, sale_date=?, purchase_price=?,
                    currency=?, freq=?
                WHERE id=?
            """
            cur.execute(q, (
                op["tipo"], op.get("descripcion"), op.get("cliente"), op.get("zona"), op["nombre"],
                op.get("proveedor"), op.get("revendedor"),
                op.get("L"), op.get("N"), op.get("O"), op.get("estado"),
                op.get("y_pagado"), op.get("comision"), op.get("sale_date"),
                op.get("purchase_price"),
                op.get("currency"), op.get("freq"),              # ← agregado
                op["id"]
            ))
            return op["id"]
        else:
            q = """
                INSERT INTO operations (
                    tipo, descripcion, cliente, zona, nombre, proveedor, revendedor,
                    L, N, O, estado, y_pagado, comision, sale_date, purchase_price,
                    currency, freq
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """
            cur.execute(q, (
                op["tipo"], op.get("descripcion"), op.get("cliente"), op.get("zona"), op["nombre"],
                op.get("proveedor"), op.get("revendedor"),
                op.get("L"), op.get("N"), op.get("O"), op.get("estado"),
                op.get("y_pagado"), op.get("comision"), op.get("sale_date"),
                op.get("purchase_price"),
                op.get("currency"), op.get("freq")               # ← agregado
            ))
            return cur.lastrowid

def delete_operation(operation_id: int):
    with get_conn() as con:
        con.execute("DELETE FROM operations WHERE id=?", (operation_id,))

def list_operations(filters=None):
    filters = filters or {}
    where = []
    params = []
    if "estado" in filters and filters["estado"]:
        where.append("estado=?"); params.append(filters["estado"])
    if "inversor" in filters and filters["inversor"]:
        where.append("UPPER(nombre)=UPPER(?)"); params.append(filters["inversor"])
    if "vendedor" in filters and filters["vendedor"]:
        where.append("UPPER(zona)=UPPER(?)"); params.append(filters["vendedor"])
    if "cliente" in filters and filters["cliente"]:
        where.append("UPPER(cliente)=UPPER(?)"); params.append(filters["cliente"])
    if "proveedor" in filters and filters["proveedor"]:
        where.append("UPPER(proveedor)=UPPER(?)"); params.append(filters["proveedor"])
    if "inversor_like" in filters and filters["inversor_like"]:
        where.append("UPPER(nombre) LIKE UPPER(?)"); params.append(f"%{filters['inversor_like']}%")
    if "vendedor_like" in filters and filters["vendedor_like"]:
        where.append("UPPER(zona) LIKE UPPER(?)"); params.append(f"%{filters['vendedor_like']}%")
    if "cliente_like" in filters and filters["cliente_like"]:
        where.append("UPPER(cliente) LIKE UPPER(?)"); params.append(f"%{filters['cliente_like']}%")
    if "proveedor_like" in filters and filters["proveedor_like"]:
        where.append("UPPER(proveedor) LIKE UPPER(?)"); params.append(f"%{filters['proveedor_like']}%")
    q = "SELECT * FROM operations"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC"
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(q, params)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in rows]

def get_operation(operation_id):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM operations WHERE id=?", (operation_id,))
        row = cur.fetchone()
        if not row: return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))

def delete_installments(operation_id, is_purchase=None):
    with get_conn() as con:
        if is_purchase is None:
            con.execute("DELETE FROM installments WHERE operation_id=?", (operation_id,))
        else:
            con.execute("DELETE FROM installments WHERE operation_id=? AND is_purchase=?", (operation_id, 1 if is_purchase else 0))

def create_installments(operation_id, amounts, is_purchase=False):
    with get_conn() as con:
        for i, amt in enumerate(amounts, start=1):
            con.execute(
                "INSERT INTO installments (operation_id, idx, amount, paid, is_purchase) VALUES (?, ?, ?, 0, ?)",
                (operation_id, i, float(amt), 1 if is_purchase else 0)
            )

def list_installments(operation_id, is_purchase=None):
    with get_conn() as con:
        cur = con.cursor()
        if is_purchase is None:
            cur.execute("SELECT * FROM installments WHERE operation_id=? ORDER BY idx ASC", (operation_id,))
        else:
            cur.execute("SELECT * FROM installments WHERE operation_id=? AND is_purchase=? ORDER BY idx ASC",
                        (operation_id, 1 if is_purchase else 0))
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in rows]

def set_installment_paid(installment_id, paid=True, paid_at_iso=None):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("UPDATE installments SET paid=?, paid_at=? WHERE id=?", 
                    (1 if paid else 0, paid_at_iso, installment_id))

def sum_paid(operation_id, is_purchase=False):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) FROM installments WHERE operation_id=? AND paid=1 AND is_purchase=?",
            (operation_id, 1 if is_purchase else 0)
        )
        return float(cur.fetchone()[0])

def count_paid_installments(operation_id, is_purchase=False):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM installments WHERE operation_id=? AND paid=1 AND is_purchase=?",
                    (operation_id, 1 if is_purchase else 0))
        return int(cur.fetchone()[0])

def recalc_status_for_operation(op_id):
    op = get_operation(op_id)
    if not op: return
    y_venta = sum_paid(op_id, is_purchase=False)
    venta_total = op.get("N") or 0.0
    estado_venta = "CANCELADO" if abs(y_venta - venta_total) < 0.01 else "VIGENTE"
    with get_conn() as con:
        con.execute("UPDATE operations SET estado=?, y_pagado=? WHERE id=?", (estado_venta, y_venta, op_id))

# =========================
# Lógica de negocio
# =========================
INVERSORES = ["GONZA", "MARTIN", "TOBIAS (YO)"]

def calcular_precio_compra(costo_neto: float, inversor: str, inv_pct: float | None = None) -> float:
    """
    costo_neto: costo sin % inversor
    inversor:   nombre del inversor (para el default)
    inv_pct:    porcentaje en 1.0 = 100% (ej. 0.18 = 18%).
                Si es None, usa INV_PCT_DEFAULTS por nombre de inversor.
    """
    c = float(costo_neto or 0.0)
    p = (float(inv_pct) if inv_pct is not None else INV_PCT_DEFAULTS.get(str(inversor), 0.18))
    return round(c * (1.0 + max(0.0, p)), 2)

# Comisión = 40% de (Venta - (Costo_neto * 1.25))
COMISION_PCT = 0.40

def calc_comision_auto(
    venta: float,
    costo_neto: float | None = None,
    purchase_price: float | None = None,
) -> float:
    """
    Comisión = COMISION_PCT * max(venta - base, 0)
    base = (purchase_price * 1.25) si está disponible; si no, (costo_neto * 1.25).
    Así la comisión siempre incluye el 18% del inversor.
    """
    base_cost = purchase_price if purchase_price is not None else costo_neto
    base = float(base_cost or 0.0) * 1.25
    margen = float(venta or 0.0) - base
    if margen <= 0:
        return 0.0
    return COMISION_PCT * margen


def distribuir(importe, cuotas):
    from decimal import Decimal, ROUND_HALF_UP, getcontext
    getcontext().prec = 28
    if not cuotas or cuotas <= 0 or importe is None:
        return []
    total = Decimal(str(importe))
    n = int(cuotas)
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    partes = [base for _ in range(n)]
    delta = total - sum(partes)
    if delta != 0:
        partes[-1] = (partes[-1] + delta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return [float(p) for p in partes]

def to_iso(d: date):
    return date(d.year, d.month, d.day).isoformat()

def parse_iso_or_today(s: str):
    if not s:
        return date.today()
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            return date.today()

def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))

# ===== Formateo de números y fechas (mostrar sin decimales, redondeo hacia arriba) =====
import math

def ceil_int(x):
    try:
        return int(math.ceil(float(x or 0)))
    except Exception:
        return 0

def fmt_money_up(x):
    return f"${ceil_int(x):,}".replace(",", ".")

def fmt_int(x):
    return f"{ceil_int(x)}"

def fmt_date_dmy(d):
    # siempre dd/mm/yyyy
    if not d: 
        return ""
    if isinstance(d, str):
        d = parse_iso_or_today(d)
    return d.strftime("%d/%m/%Y")


# ========= Helpers analíticos =========
def build_ops_df(ops):
    rows = []
    for op in ops:
        venta = float(op.get("N") or 0.0)
        costo_neto = float(op.get("L") or 0.0)
        price = float(op.get("purchase_price") or 0.0)
        comision = float(op.get("comision") or 0.0)
        cuotas = int(op.get("O") or 0)
        ganancia = venta - price - comision
        rows.append({
            "id": op["id"],
            "descripcion": op.get("descripcion"),
            "cliente": op.get("cliente"),
            "proveedor": op.get("proveedor"),
            "vendedor": op.get("zona"),
            "Revendedor": op.get("revendedor") or "",
            "inversor": op.get("nombre"),
            "venta_total": venta,
            "costo_neto": costo_neto,
            "precio_compra": price,
            "comision": comision,
            "cuotas": cuotas,
            "estado": op.get("estado"),
            "sale_date": parse_iso_or_today(op.get("sale_date") or op.get("created_at")),
            "ganancia": ganancia
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "id","descripcion","cliente","proveedor","vendedor","Revendedor","inversor","venta_total","costo_neto",
        "precio_compra","comision","cuotas","sale_date","ganancia","estado"
    ])

def build_installments_df(ops):
    rows = []
    for op in ops:
        base = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
        op_id = op["id"]
        cliente = op.get("cliente")
        vendedor = op.get("zona")
        inversor = op.get("nombre")
        for c in list_installments(op_id, is_purchase=False):
            due = add_months(base, int(c["idx"]) - 1)
            rows.append({
                "operation_id": op_id, "tipo": "VENTA", "idx": int(c["idx"]),
                "amount": float(c["amount"]), "paid": bool(c["paid"]),
                "paid_at": None if not c["paid_at"] else parse_iso_or_today(c["paid_at"]),
                "due_date": due, "cliente": cliente, "vendedor": vendedor, "inversor": inversor
            })
        for c in list_installments(op_id, is_purchase=True):
            due = add_months(base, int(c["idx"]) - 1)
            rows.append({
                "operation_id": op_id, "tipo": "COMPRA", "idx": int(c["idx"]),
                "amount": float(c["amount"]), "paid": bool(c["paid"]),
                "paid_at": None if not c["paid_at"] else parse_iso_or_today(c["paid_at"]),
                "due_date": due, "cliente": cliente, "vendedor": vendedor, "inversor": inversor
            })
    cols = ["operation_id","tipo","idx","amount","paid","paid_at","due_date","cliente","vendedor","inversor"]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

# ========= Autenticación y roles =========
def auth_get_user(username: str):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT id, username, password_hash, role, vendedor FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row: return None
        return {"id": row[0], "username": row[1], "password_hash": row[2], "role": row[3], "vendedor": row[4]}

def require_login():
    if st.session_state.get("auth_ok") and st.session_state.get("user"):
        return
    st.title("🔒 Iniciar sesión")
    username = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        user = auth_get_user(username.strip())
        if user and bcrypt_hash.verify(password, user["password_hash"]):
            st.session_state.auth_ok = True
            st.session_state.user = {"username": user["username"], "role": user["role"], "vendedor": user["vendedor"]}
            st.rerun()
        else:
            st.error("Usuario o contraseña inválidos")
            st.stop()
    st.stop()

def user_scope_filters(base_filters=None):
    base_filters = base_filters or {}
    user = st.session_state.get("user") or {}
    if user.get("role") == "seller":
        if user.get("vendedor"):
            base_filters = dict(base_filters)
            base_filters["vendedor"] = user["vendedor"]
    return base_filters

def is_admin():
    return (st.session_state.get("user") or {}).get("role") == "admin"

# ===== Helpers VENDORS =====
def list_vendors(active_only=True):
    with get_conn() as con:
        cur = con.cursor()
        if active_only:
            cur.execute("SELECT id, nombre FROM vendors WHERE activo=1 ORDER BY nombre;")
            rows = cur.fetchall()
            return [{"id": r[0], "nombre": r[1]} for r in rows]
        else:
            cur.execute("SELECT id, nombre, activo FROM vendors ORDER BY nombre;")
            rows = cur.fetchall()
            return [{"id": r[0], "nombre": r[1], "activo": r[2]} for r in rows]

def add_vendor(nombre: str):
    if not nombre or not nombre.strip():
        return False, "Nombre vacío"
    try:
        with get_conn() as con:
            con.execute("INSERT INTO vendors (nombre, activo) VALUES (?,1);", (nombre.strip(),))
        return True, "Vendedor creado"
    except sqlite3.IntegrityError:
        return False, "Ese vendedor ya existe"

def deactivate_vendor(vendor_id: int):
    with get_conn() as con:
        con.execute("UPDATE vendors SET activo=0 WHERE id=?", (vendor_id,))

def count_ops_for_vendor_name(nombre: str) -> int:
    """Cuenta cuántas ventas referencian a este vendedor por nombre (columna zona)."""
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM operations WHERE UPPER(zona)=UPPER(?)", (nombre.strip(),))
        return int(cur.fetchone()[0] or 0)

def delete_vendor(vendor_id: int):
    """Borra el vendedor del maestro (no toca ventas existentes)."""
    with get_conn() as con:
        con.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))


# ===== Helpers USERS (admin) =====
def create_user(username: str, password: str, role: str, vendedor_nombre: str | None):
    if not username or not password:
        return False, "Usuario/contraseña vacíos"
    if role not in ("admin", "seller"):
        return False, "Rol inválido"
    try:
        pwd_hash = bcrypt_hash.hash(password)
        with get_conn() as con:
            con.execute(
                "INSERT INTO users (username, password_hash, role, vendedor) VALUES (?,?,?,?)",
                (username.strip(), pwd_hash, role, vendedor_nombre if role=="seller" else None)
            )
        return True, "Usuario creado"
    except sqlite3.IntegrityError:
        return False, "Ya existe un usuario con ese nombre"

def delete_user(username: str):
    with get_conn() as con:
        con.execute("DELETE FROM users WHERE username=?", (username,))

# ===== Cambios de credenciales ADMIN =====
def set_admin_password(current_username: str, current_password: str, new_password: str):
    """Cambia la contraseña del admin actual verificando la contraseña actual."""
    user = auth_get_user(current_username.strip())
    if not user or user["role"] != "admin":
        return False, "Usuario admin no encontrado."
    if not bcrypt_hash.verify(current_password, user["password_hash"]):
        return False, "Contraseña actual incorrecta."
    if not new_password:
        return False, "La nueva contraseña no puede estar vacía."
    pwd_hash = bcrypt_hash.hash(new_password)
    with get_conn() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (pwd_hash, user["id"]))
    return True, "Contraseña actualizada."

def rename_admin_user(old_username: str, new_username: str, current_password: str):
    """Renombra el usuario admin verificando su contraseña actual."""
    if not new_username.strip():
        return False, "Ingresá el nuevo usuario."
    user = auth_get_user(old_username.strip())
    if not user or user["role"] != "admin":
        return False, "Usuario admin no encontrado."
    if not bcrypt_hash.verify(current_password, user["password_hash"]):
        return False, "Contraseña actual incorrecta."
    try:
        with get_conn() as con:
            con.execute("UPDATE users SET username=? WHERE id=?", (new_username.strip(), user["id"]))
        return True, "Usuario actualizado."
    except sqlite3.IntegrityError:
        return False, "Ya existe un usuario con ese nombre."

# ==== Helpers para normalizar pagos de cuotas (poner antes de la sección Inversores) ====
from datetime import datetime
import pandas as pd

def _paid_bool(cuota_dict) -> bool:
    """True si la cuota está paga (tolera 0/1, 'true', etc.) o si tiene paid_at."""
    if cuota_dict is None:
        return False
    if cuota_dict.get("paid_at"):
        return True
    val = cuota_dict.get("paid", 0)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    s = str(val).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "si", "sí")

def _to_paid_at_dt(x):
    """Convierte paid_at a datetime (o NaT). Acepta 'YYYY-MM-DD' y 'YYYY-MM-DDTHH:MM:SS'."""
    if x is None or x == "":
        return pd.NaT
    s = str(x).strip().replace("Z", "").replace("T", " ")
    try:
        return pd.to_datetime(s, errors="coerce")
    except Exception:
        return pd.NaT
# =============================================================================


def _parse_paid_at(x):
    """Convierte paid_at en datetime naive. Acepta 'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM:SS'."""
    if not x:
        return None
    s = str(x).strip().replace("Z", "")
    try:
        # ISO completo
        return datetime.fromisoformat(s.replace("T", " "))
    except Exception:
        # Solo fecha
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None



# =========================
# UI
# =========================
ensure_ops_cols_weekly_ars()
init_db()
restore_on_boot_once()
require_login()

# Sidebar sesión
with st.sidebar:
    u = st.session_state.get("user") or {}
    st.markdown(f"**Usuario:** {u.get('username','-')}  \n**Rol:** {u.get('role','-')}")
    if u.get("role") == "seller" and u.get("vendedor"):
        st.markdown(f"**Vendedor:** {u['vendedor']}")
    if st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()

# =========================
# Tabs según rol
# =========================
is_admin_user = is_admin()
if is_admin_user:
    tab_crear, tab_listar, tab_inversores, tab_vendedores, tab_reportes, tab_admin, tab_cal, tab_stock, tab_toto = st.tabs(
        ["➕ Nueva venta", "📋 Listado & gestión", "🏦 Inversores", "🧑‍💼 Vendedores", "📊 Reportes KPI", "⚙️ Administración", "📅 Calendario", "📦 Stock", "🟡 TOTO"]
    )
else:
    tab_listar, tab_cal = st.tabs(
        ["📋 Listado & gestión", "📅 Calendario"]
    )


# --------- CREAR / EDITAR VENTA (solo admin crea) ---------
if is_admin_user:
    # === CREAR VENTA (con formulario que se limpia y select de vendedores) ===
    with tab_toto:
        st.subheader("🟡 Panel de TOTO — por mes")

        from datetime import date, datetime
        import pandas as pd

        # ---------- Controles ----------
        hoy = date.today()
        c1, c2 = st.columns(2)
        with c1:
            anio = st.number_input("Año", min_value=2000, max_value=2100, value=hoy.year, step=1, key="toto_year")
        with c2:
            mes = st.number_input("Mes", min_value=1, max_value=12, value=hoy.month, step=1, key="toto_month")

        # ---------- Datos base ----------
        ops = list_operations(user_scope_filters({})) or []

        rows = []
        for op in ops:
            dt = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
            rows.append({
                "id": int(op["id"]),
                "mes": datetime(dt.year, dt.month, 1),              # primer día del mes (datetime)
                "venta": float(op.get("N") or 0.0),
                "costo": float(op.get("L") or 0.0),
                "compra": float(op.get("purchase_price") or 0.0),   # purchase_price (costo + % inversor)
                "comision": float(op.get("comision") or 0.0),
                "cuotas": int(op.get("O") or 0),
                "inversor": (op.get("nombre") or "").strip(),
                "vendedor": (op.get("zona") or "").strip(),
                "currency": (op.get("currency") or "USD"),
            })

        df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
            "id","mes","venta","costo","compra","comision","cuotas","inversor","vendedor"
        ])
        if df.empty:
            st.info("No hay datos todavía.")
            st.stop()

        # asegurar dtype datetime y filtrar mes
        df["mes"] = pd.to_datetime(df["mes"], errors="coerce")
        df = df.dropna(subset=["mes"])
        if "currency" not in df.columns:
            df["currency"] = "USD"
        else:
            df["currency"] = df["currency"].fillna("USD").astype(str)
        df_m = df[(df["mes"].dt.year == int(anio)) & (df["mes"].dt.month == int(mes))].copy()
        df_m_usd = df_m[df_m["currency"].fillna("USD").str.upper() != "ARS"].copy()
        df_m_ars = df_m[df_m["currency"].fillna("USD").str.upper() == "ARS"].copy()
        if df_m.empty:
            st.info(f"Sin datos para {mes:02d}/{anio}.")
            st.stop()

        # ---------- 18% de TOTO inversor (del mes) ----------
        mask_inv_toto_usd = df_m_usd["inversor"].fillna("").str.upper() == TOTO_INV_NAME.upper()
        g1_total_usd = float((df_m_usd.loc[mask_inv_toto_usd, "costo"].astype(float) * float(TOTO_INV_PCT)).sum())

        # ---------- Ganancia por operación (reconocida 100% en el mes de la venta) ----------
        def _gan_vendor_por_op(r):
            cuotas   = int(r["cuotas"] or 0)
            vendedor = (r["vendedor"] or "").strip().upper()
            venta    = float(r["venta"] or 0.0)
            compra   = float(r["compra"] or 0.0)   # purchase_price
            costo    = float(r["costo"] or 0.0)
            comision = float(r["comision"] or 0.0)
            es_toto  = (vendedor == TOTO_VENDOR_NAME.upper())

            if cuotas == 1:
                return (venta - costo) if es_toto else (venta - costo - comision)
            else:
                return (venta - compra) if es_toto else (venta - compra - comision)

        df_m_usd["gan_vendor"] = df_m_usd.apply(_gan_vendor_por_op, axis=1)

        mask_vend_toto_usd = df_m_usd["vendedor"].fillna("").str.upper() == TOTO_VENDOR_NAME.upper()

        # (USD) Toto vendedor 2+ / 1p / total
        g2_total_usd = float(df_m_usd.loc[mask_vend_toto_usd & (df_m_usd["cuotas"] >= 2), "gan_vendor"].sum())
        g3_total_usd = float(df_m_usd.loc[mask_vend_toto_usd & (df_m_usd["cuotas"] == 1), "gan_vendor"].sum())
        gan_toto_vendedor_total_usd = float(df_m_usd.loc[mask_vend_toto_usd, "gan_vendor"].sum())

        # (USD) Vendedores no Toto
        g_no_toto_usd = float(df_m_usd.loc[~mask_vend_toto_usd, "gan_vendor"].sum())

        # (USD) Totales
        g4_total_usd = g1_total_usd + gan_toto_vendedor_total_usd
        g5_total_usd = g4_total_usd + g_no_toto_usd

        # (USD) Ganancia CUOTAS: Toto(2+) + No Toto (2+)
        g_no_toto_2p_usd = float(df_m_usd.loc[(~mask_vend_toto_usd) & (df_m_usd["cuotas"] >= 2), "gan_vendor"].sum())
        g_cuotas_total_usd = g2_total_usd + g_no_toto_2p_usd

        # ---------- KPIs ----------
        m0 = datetime(int(anio), int(mes), 1)
        c1, c2, c3 = st.columns(3)
        c1.metric(f"TOTO inversor (18%) — {m0:%m/%Y}", fmt_money_up(g1_total_usd))
        c2.metric("TOTO vendedor (2+ cuotas)", fmt_money_up(g2_total_usd))
        c3.metric("TOTO vendedor (1 pago)", fmt_money_up(g3_total_usd))

        c4, c5 = st.columns(2)
        c4.metric("Total TOTO (1+2+3)", fmt_money_up(g4_total_usd))
        c5.metric("Vendedores (no Toto)", fmt_money_up(g_no_toto_usd))

        st.metric("Ganancia CUOTAS", fmt_money_up(g_cuotas_total_usd))
        st.metric("Ganancia TOTAL (negocio + 18% TOTO inversor)", fmt_money_up(g5_total_usd))
        
        st.divider()
        st.subheader("💵 ARS — Ganancias del mes (solo pesos)")

        if df_m_ars.empty:
            st.info("No hay ventas en ARS en el mes seleccionado.")
        else:
            # 18% TOTO inversor sobre ARS
            mask_inv_toto_ars = df_m_ars["inversor"].fillna("").str.upper() == TOTO_INV_NAME.upper()
            g1_total_ars = float((df_m_ars.loc[mask_inv_toto_ars, "costo"].astype(float) * float(TOTO_INV_PCT)).sum())

            # Ganancias por operación en ARS (misma regla)
            df_m_ars = df_m_ars.copy()
            df_m_ars["gan_vendor"] = df_m_ars.apply(_gan_vendor_por_op, axis=1)
            mask_vend_toto_ars = df_m_ars["vendedor"].fillna("").str.upper() == TOTO_VENDOR_NAME.upper()

            g2_total_ars = float(df_m_ars.loc[mask_vend_toto_ars & (df_m_ars["cuotas"] >= 2), "gan_vendor"].sum())
            g3_total_ars = float(df_m_ars.loc[mask_vend_toto_ars & (df_m_ars["cuotas"] == 1), "gan_vendor"].sum())
            gan_toto_vendedor_total_ars = float(df_m_ars.loc[mask_vend_toto_ars, "gan_vendor"].sum())
            g_no_toto_ars = float(df_m_ars.loc[~mask_vend_toto_ars, "gan_vendor"].sum())

            g4_total_ars = g1_total_ars + gan_toto_vendedor_total_ars
            g5_total_ars = g4_total_ars + g_no_toto_ars

            g_no_toto_2p_ars = float(df_m_ars.loc[(~mask_vend_toto_ars) & (df_m_ars["cuotas"] >= 2), "gan_vendor"].sum())
            g_cuotas_total_ars = g2_total_ars + g_no_toto_2p_ars

            c1, c2, c3 = st.columns(3)
            c1.metric(f"TOTO inversor (18%) ARS — {m0:%m/%Y}", fmt_money_up(g1_total_ars))
            c2.metric("TOTO vendedor (2+ cuotas) ARS", fmt_money_up(g2_total_ars))
            c3.metric("TOTO vendedor (1 pago) ARS", fmt_money_up(g3_total_ars))

            c4, c5 = st.columns(2)
            c4.metric("Total TOTO ARS (1+2+3)", fmt_money_up(g4_total_ars))
            c5.metric("Vendedores ARS (no Toto)", fmt_money_up(g_no_toto_ars))

            st.metric("Ganancia CUOTAS ARS", fmt_money_up(g_cuotas_total_ars))
            st.metric("Ganancia TOTAL ARS (negocio + 18% TOTO inversor)", fmt_money_up(g5_total_ars))


    with tab_crear:
        with safe_tab("Nueva Venta"):
            with card("Nueva venta", "➕"):
                st.subheader("Crear nueva venta")

                # Traer vendedores activos para asignar la venta
                vend_options = [v["nombre"] for v in list_vendors(active_only=True)]
                if not vend_options:
                    st.warning("No hay vendedores cargados. Cargá uno desde 👤 Administración.")

                with st.form("form_crear_venta", clear_on_submit=True):
                    inversor = st.selectbox(
                        "Inversor",
                        options=INVERSORES,
                        index=(INVERSORES.index("GONZA") if "GONZA" in INVERSORES else 0),
                        key="crear_inversor",
                        placeholder="Elegí un inversor")                       


                    # ahora elegís del listado de vendedores existentes
                    vendedor = st.selectbox(
                        "Vendedor",
                        options=vend_options,
                        placeholder="Elegí un vendedor",
                        key="crear_vendedor"
                    )
                    inv_pct_ui = st.number_input(
                        "Porcentaje del inversor (%)",
                        min_value=0.0, max_value=100.0, step=0.1, value=18.0,
                        key="crear_inv_pct"
                    )
                    revendedor = st.text_input("Revendedor (opcional)", value="", key="crear_revendedor")
                    cliente   = st.text_input("Cliente", value="", key="crear_cliente")
                    proveedor = st.text_input("Proveedor", value="", key="crear_proveedor")
                    descripcion = st.text_input("Descripción (celular vendido)", value="", key="crear_desc")
                    c_mon, c_freq = st.columns(2)
                    with c_mon:
                        moneda = st.selectbox(
                            "Moneda", ["USD", "ARS"],
                            index=0,
                            key="nv_moneda",
                            help="Elegí ARS para ventas en pesos"
                        )
                    with c_freq:
                        # Si elegís ARS, por defecto SEMANAL; si elegís USD, por defecto MENSUAL
                        default_freq = "SEMANAL" if (moneda == "ARS") else "MENSUAL"
                        frecuencia = st.selectbox(
                            "Frecuencia de cuotas", ["MENSUAL", "SEMANAL"],
                            index=(0 if default_freq=="MENSUAL" else 1),
                            key="nv_freq",
                            help="SEMANAL = cuotas cada 7 días"
                        )
                    costo  = st.number_input("Costo (neto)", min_value=0.0, step=0.01, format="%.2f", key="crear_costo")
                    venta  = st.number_input("Venta", min_value=0.0, step=0.01, format="%.2f", key="crear_venta")
                    cuotas = st.number_input("Cuotas", min_value=0, step=1, key="crear_cuotas")
                    fecha  = st.date_input("Fecha de cobro", value=date.today(), key="crear_fecha")

                    inv_pct_effective = 0.0 if int(cuotas or 0) == 1 else float(inv_pct_ui)


                    precio_compra = calcular_precio_compra(costo, inversor, inv_pct_effective / 100.0)
                    comision_auto = calc_comision_auto(venta, costo, purchase_price=precio_compra)
                    ganancia_neta = (venta - precio_compra) - comision_auto

                    # 4) leyenda
                    if int(cuotas or 0) == 1:
                        st.info("Venta de 1 pago: % inversor fijado en 0%.")

                    st.caption(
                        f"**Preview:** Precio compra = {fmt_money_up(precio_compra)}  "
                        f"(costo {fmt_money_up(costo)} + {inv_pct_effective:.1f}% inversor) · "
                        f"Comisión = {fmt_money_up(comision_auto)} · "
                        f"Ganancia neta = {fmt_money_up(ganancia_neta)}"
                    )

                    submitted = st.form_submit_button("💾 Guardar venta", disabled=(len(vend_options) == 0))
                    if submitted:
                        if not vendedor:
                            st.error("Elegí un vendedor antes de guardar.")
                        inv_pct_effective = 0.0 if int(cuotas or 0) == 1 else float(inv_pct_ui)
                        precio_compra = calcular_precio_compra(costo, inversor, inv_pct_effective / 100.0)
                        comision_auto = calc_comision_auto(venta, costo, purchase_price=precio_compra)
                        
                        op = {
                                "tipo": "VENTA",
                                "descripcion": descripcion.strip() or None,
                                "cliente": cliente.strip() or None,
                                "proveedor": proveedor.strip() or None,
                                "zona": vendedor.strip(),              # <- vendedor seleccionado
                                "revendedor": revendedor.strip() or None,
                                "nombre": inversor.strip(),            # inversor
                                "L": float(costo) if costo else 0.0,   # costo neto
                                "N": float(venta) if venta else 0.0,   # venta total
                                "O": int(cuotas) if cuotas else 0,     # cuotas
                                "estado": "VIGENTE",
                                "y_pagado": 0.0,
                                "comision": float(comision_auto),
                                "sale_date": to_iso(fecha),            # guarda sin hora (YYYY-MM-DD)
                                "purchase_price": float(precio_compra)
                            }
                        op["currency"] = moneda or "USD"
                        op["freq"]     = frecuencia or "MENSUAL"
                        new_id = upsert_operation(op)

                            # cuotas
                        delete_installments(new_id, is_purchase=None)
                        if int(cuotas) > 0:
                            # VENTA (cliente): respeta la cantidad elegida
                            create_installments(new_id, distribuir(venta, int(cuotas)), is_purchase=False)

                            # COMPRA (inversor): 6 ó 1 según la regla
                            n_compra = compra_cuotas_count(int(cuotas))
                            create_installments(new_id, distribuir(precio_compra, n_compra), is_purchase=True)
                                            
                        # Si es 1 pago: marcar automáticamente la cuota de VENTA como pagada
                        if int(cuotas or 0) == 1:
                            cuotas_v = list_installments(new_id, is_purchase=False) or []
                            # buscamos la cuota idx==1 por las dudas
                            iid = None
                            for c in cuotas_v:
                                if int(c["idx"]) == 1:
                                    iid = c["id"]
                                    break
                            if not iid and cuotas_v:
                                iid = cuotas_v[0]["id"]
                            if iid:
                                set_installment_paid(iid, True, paid_at_iso=to_iso(fecha))  # usa la fecha de cobro del form


                        recalc_status_for_operation(new_id)
                        st.success(f"Venta #{new_id} creada correctamente.")
                        try:
                                url = backup_snapshot_to_github()
                                st.success("Backup subido a GitHub ✅")
                                if url: st.markdown(f"[Ver commit →]({url})")
                        except Exception as e:
                                st.error(f"Falló el backup: {e}")
                        st.rerun() # vuelve con el formulario limpio

# --------- LISTADO & GESTIÓN ---------
with tab_listar:
    with safe_tab("Listado & gestión"):
        with card("Listado & gestión", "📋"):
            st.subheader("Listado de ventas")

            # Rol (lo usamos en varios lados)
            seller = (st.session_state.get("user") or {}).get("role") == "seller"
            seller_name = (st.session_state.get("user") or {}).get("vendedor")

            # ---- Filtros generales (se aplican a ambos listados) ----
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                filtro_cliente = st.text_input("Filtro Cliente", value="")
            with f2:
                # si seller, el filtro de vendedor queda fijo y deshabilitado
                filtro_vendedor = st.text_input(
                    "Filtro Vendedor",
                    value=(seller_name or "" if seller else ""),
                    disabled=seller
                )
            with f3:
                filtro_inversor = st.text_input("Filtro Inversor", value="")
            with f4:
                filtro_proveedor = st.text_input("Filtro Proveedor", value="")

            busqueda_parcial = st.checkbox("Búsqueda parcial (contiene)", value=True)

            filtros = {}
            if busqueda_parcial:
                if filtro_cliente.strip(): filtros["cliente_like"] = filtro_cliente.strip()
                if (not seller) and filtro_vendedor.strip(): filtros["vendedor_like"] = filtro_vendedor.strip()
                if filtro_inversor.strip(): filtros["inversor_like"] = filtro_inversor.strip()
                if filtro_proveedor.strip(): filtros["proveedor_like"] = filtro_proveedor.strip()
            else:
                if filtro_cliente.strip(): filtros["cliente"] = filtro_cliente.strip()
                if (not seller) and filtro_vendedor.strip(): filtros["vendedor"] = filtro_vendedor.strip()
                if filtro_inversor.strip(): filtros["inversor"] = filtro_inversor.strip()
                if filtro_proveedor.strip(): filtros["proveedor"] = filtro_proveedor.strip()

            # Aplicar scope por rol
            filtros = user_scope_filters(filtros)

            # Traer operaciones una sola vez y dividir por cantidad de cuotas
            ops_all = list_operations(filtros) or []

            def _is_cancelado(op):
                return str(op.get("estado") or "").strip().upper() == "CANCELADO"

            def _cuotas(op) -> int:
                try:
                    return int(op.get("O") or 0)
                except Exception:
                    return 0
            def _is_weekly_ars(op):
                return str(op.get("currency","USD")).upper()=="ARS" and str(op.get("freq","MENSUAL")).upper()=="SEMANAL"

            # 👉 Un pago: SIEMPRE acá, sin importar el estado
            ops_uno    = [op for op in ops_all if (not _is_weekly_ars(op)) and int(op.get("O") or 0) == 1 and not _is_cancelado(op)]
            ops_sem    = [op for op in ops_all if _is_weekly_ars(op) and not _is_cancelado(op)]
            # 👉 Candidatas a 2+ cuotas
            ops_multi_all = [op for op in ops_all if _cuotas(op) >= 2]

            # 👉 Dentro de 2+ cuotas, dividimos vigentes vs canceladas
            ops_cancel = [op for op in ops_all if _is_cancelado(op)]
            ops_multi  = [op for op in ops_all if (not _is_weekly_ars(op)) and int(op.get("O") or 0) >= 2 and not _is_cancelado(op)]

            
            # 👉 Ventas semanales en PESOS (vigentes)
            try:
                ops_sem = [op for op in ops_all
                        if str(op.get("currency","USD")).upper() == "ARS"
                        and str(op.get("freq","MENSUAL")).upper() == "SEMANAL"
                        and not _is_cancelado(op)]
            except Exception:
                # Si no existen esos campos aún, queda vacío sin romper
                ops_sem = []
    # Tabs
            tabs = st.tabs(["Cuotas (2+)", "Un pago (1)", "Cancelados", "Semanal (PESOS)"])

            # ----------- función de render compartida (no toques nada) -----------
            def render_listado(ops, key_prefix: str):
                if not ops:
                    st.info("No hay ventas registradas en este grupo.")
                    return
                # --- Filtro por Revendedor ---
                revendedores_all = sorted({
                    (op.get("revendedor") or "").strip()
                    for op in ops
                    if (op.get("revendedor") or "").strip()
                })
                rev_sel = st.selectbox(
                    "Filtro Revendedor",
                    options=["Todos"] + revendedores_all,
                    index=0,
                    key=f"{key_prefix}_f_rev"
                )
                
                if rev_sel != "Todos":
                    ops = [op for op in ops if ((op.get("revendedor") or "").strip() == rev_sel)]

                rows = []
                def calc_ganancia_neta(venta_total: float, purchase_price: float,
                                    comision_total: float, vendedor: str) -> float:
                    """Si el vendedor es Toto Donofrio, no se descuenta comisión."""
                    if (vendedor or "").strip().upper() == "TOTO DONOFRIO":
                        return venta_total - purchase_price
                    return venta_total - purchase_price - comision_total
                for op in ops:
                    total_cuotas_venta = int(op.get("O") or 0)
                    fecha_mostrar = op.get("sale_date") or op.get("created_at")

                    # --- VENTA (cobros) ---
                    venta_total = float(op.get("N") or 0.0)
                    pagado_venta = sum_paid(op["id"], is_purchase=False)
                    pagadas_venta = count_paid_installments(op["id"], is_purchase=False)
                    pendientes_venta = max(total_cuotas_venta - pagadas_venta, 0)
                    pendiente_venta = venta_total - pagado_venta
                    valor_cuota_venta = (venta_total / total_cuotas_venta) if total_cuotas_venta > 0 else 0.0

                    # --- Comisión, costos, compra ---
                    comision_total = float(op.get("comision") or 0.0)
                    comision_x_cuota = (comision_total / total_cuotas_venta) if total_cuotas_venta > 0 else 0.0
                    price = float(op.get("purchase_price") or 0.0)
                    costo_neto = float(op.get("L") or 0.0)

                    # --- COMPRA (pagos a inversor) ---
                    pagado_compra = sum_paid(op["id"], is_purchase=True)
                    pagadas_compra = count_paid_installments(op["id"], is_purchase=True)
                    # cantidad real de cuotas de COMPRA (6 u 1). Si falla, fallback por regla.
                    try:
                        n_compra_real = len(list_installments(op["id"], is_purchase=True)) or compra_cuotas_count(total_cuotas_venta)
                    except Exception:
                        n_compra_real = compra_cuotas_count(total_cuotas_venta)

                    pendientes_compra = max(n_compra_real - pagadas_compra, 0)
                    pendiente_compra = price - pagado_compra
                    estado_compra = "CANCELADO" if abs(pagado_compra - price) < 0.01 else "VIGENTE"

                    # --- Ganancia (regla Toto) ---
                    vendedor_actual = op.get("zona") or ""
                    ganancia = calc_ganancia_neta(venta_total, price, comision_total, vendedor_actual)

                    # --- Fila VENTA (primero) ---
                    rows.append({
                        "Tipo": "VENTA",
                        "ID venta": op["id"],
                        "Descripción": op.get("descripcion"),
                        "Cliente": op.get("cliente"),
                        "Proveedor": op.get("proveedor") or "",
                        "Inversor": "↓",
                        "Vendedor": vendedor_actual,
                        "Revendedor": op.get("revendedor") or "",
                        "Costo": fmt_money_up(costo_neto),
                        "Precio Compra": "",  # sin flecha en VENTA
                        "Venta": fmt_money_up(venta_total),
                        "Comisión": fmt_money_up(comision_total),
                        "Comisión x cuota": fmt_money_up(comision_x_cuota),
                        "Cuotas": fmt_int(total_cuotas_venta),
                        "Cuotas pendientes": fmt_int(pendientes_venta),
                        "Valor por cuota": fmt_money_up(valor_cuota_venta),
                        "$ Pagado": fmt_money_up(pagado_venta),
                        "$ Pendiente": fmt_money_up(pendiente_venta),
                        "Estado": op.get("estado"),
                        "Fecha de cobro": fmt_date_dmy(fecha_mostrar),
                        "Ganancia": fmt_money_up(ganancia),
                    })

                    # --- Fila COMPRA (segundo) (flechas en celdas vacías) ---
                    def up_arrow_if_empty(val):
                        return val if (isinstance(val, str) and val.strip()) else "↑"

                    if key_prefix != "uno":
                        rows.append({
                            "Tipo": "COMPRA",
                            "ID venta": op["id"],
                            "Descripción": "↑",
                            "Cliente": up_arrow_if_empty(""),
                            "Proveedor": up_arrow_if_empty(""),
                            "Inversor": op.get("nombre"),
                            "Vendedor": up_arrow_if_empty(""),
                            "Revendedor": up_arrow_if_empty(""),
                            "Costo": up_arrow_if_empty(""),
                            "Precio Compra": fmt_money_up(price),
                            "Venta": up_arrow_if_empty(""),
                            "Comisión": up_arrow_if_empty(""),
                            "Comisión x cuota": up_arrow_if_empty(""),
                            "Cuotas": fmt_int(n_compra_real),               # ← 6 u 1 según regla
                            "Cuotas pendientes": fmt_int(pendientes_compra),
                            "Valor por cuota": up_arrow_if_empty(""), 
                            "$ Pagado": fmt_money_up(pagado_compra),
                            "$ Pendiente": fmt_money_up(pendiente_compra),
                            "Estado": estado_compra,
                            "Fecha de cobro": up_arrow_if_empty(""),
                            "Ganancia": up_arrow_if_empty(""),
                        })

                df_ops = pd.DataFrame(rows)

                # En la vista "uno" ocultamos COMPRA (como ya hacías)
                if key_prefix == "uno":
                    df_ops = df_ops[df_ops["Tipo"] != "COMPRA"].reset_index(drop=True)

                # Orden de columnas
                cols_order = [
                    "Elegir","ID venta","Tipo","Descripción","Cliente","Proveedor","Inversor","Vendedor","Revendedor","Costo",
                    "Precio Compra","Venta","Comisión","Comisión x cuota","Cuotas",
                    "Cuotas pendientes","Valor por cuota","$ Pagado","$ Pendiente","Estado","Fecha de cobro","Ganancia"
                ]
                # Armamos la col "Elegir" EN BLANCO por ahora (se completa más abajo con el selid real)
                if "Elegir" not in df_ops.columns:
                    df_ops.insert(0, "Elegir", None)

                # --- helpers mínimos para query params ---
                def _qp_get(name: str):
                    try:
                        v = st.query_params.get(name)
                        if isinstance(v, list):
                            return v[0] if v else None
                        return v
                    except Exception:
                        return None

                def _qp_set(name: str, value):
                    try:
                        d = st.query_params.to_dict()
                    except Exception:
                        d = {}
                    if value is None:
                        d.pop(name, None)
                    else:
                        d[name] = str(value)
                    st.query_params.update(d)

                # selid actual (desde la URL)
                _sel_raw = _qp_get("selid")
                try:
                    current_selid = int(_sel_raw) if _sel_raw is not None else None
                except Exception:
                    current_selid = None

                # Marcar la columna "Elegir": sólo tilda la fila VENTA con ese ID
                def _mark(tipo, idventa, curr):
                    if tipo == "VENTA" and curr is not None and int(idventa) == int(curr):
                        return True
                    return False

                df_ops["Elegir"] = [_mark(t, i, current_selid) for t, i in zip(df_ops["Tipo"], df_ops["ID venta"])]

                # Aplicar orden y ocultaciones
                df_ops = df_ops[[c for c in cols_order if c in df_ops.columns]]

                # Ocultaciones “vendedor”
                try:
                    seller_flag = bool(seller)
                except NameError:
                    seller_flag = not is_admin()

                fullcols = st.toggle("Vista completa (todas las columnas)", value=False, key=f"{key_prefix}_fullcols")

                PERSONAL_HIDE_ALWAYS = ["Proveedor", "Venta", "Costo", "Inversor", "Ganancia"]
                PERSONAL_HIDE_SOLO_UNO = ["Cuotas", "Cuotas pendientes", "Comisión x cuota", "Estado"]
                cols_hide_base = ["Inversor", "Ganancia", "Costo", "Precio Compra"] if (seller_flag and not fullcols) else []
                cols_hide_uno  = ["Cuotas", "Cuotas pendientes", "Comisión x cuota", "Estado"] if (key_prefix == "uno" and not fullcols) else []
                cols_personal  = (PERSONAL_HIDE_ALWAYS + (PERSONAL_HIDE_SOLO_UNO if key_prefix == "uno" else [])) if not fullcols else []
                cols_to_hide   = (cols_hide_base + cols_hide_uno + cols_personal) if not fullcols else []
                df_show = df_ops.drop(columns=cols_to_hide, errors="ignore")

                # --- Clave estable del editor + reset si cambió el selid (evita loops) ---
                editor_key = f"{key_prefix}_listado_editor"
                last_selid = st.session_state.get(f"{editor_key}__last_selid")
                if last_selid != current_selid:
                    # si cambió el selid, limpiamos el estado del widget del editor para evitar que mantenga los checks viejos
                    st.session_state.pop(editor_key, None)
                st.session_state[f"{editor_key}__last_selid"] = current_selid

                # --- Config de columnas: checkbox sólo en "Elegir", resto lectura ---
                colcfg = {
                    "Elegir": st.column_config.CheckboxColumn(
                        label="Elegir",
                        help="Seleccioná esta VENTA para gestionar",
                        default=False
                    )
                }
                for col in df_show.columns:
                    if col == "Elegir":
                        continue
                    colcfg[col] = st.column_config.TextColumn(col, disabled=True)

                # --- Render del editor ---
                edited = st.data_editor(
                    df_show,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="fixed",
                    column_config=colcfg,
                    key=editor_key
                )

                # --- Detectar nueva selección (enforzar selección única) ---
                # mapeamos “Elegir” → ID venta de las filas visibles
                try:
                    elig_flags = edited["Elegir"].fillna(False).tolist()
                    id_vals    = edited["ID venta"].tolist()
                except Exception:
                    elig_flags, id_vals = [], []

                checked_ids = {int(i) for flag, i in zip(elig_flags, id_vals) if bool(flag) and pd.notna(i)}

                # Estado “esperado” anterior (una sola selección)
                prev_true = st.session_state.get(f"{editor_key}__true_ids", {current_selid} if current_selid else set())

                new_sel = current_selid
                if checked_ids != prev_true:
                    if len(checked_ids) == 0:
                        new_sel = None
                    elif len(checked_ids) == 1:
                        new_sel = list(checked_ids)[0]
                    else:
                        # Si marcaron varias, nos quedamos con la última por orden visual (abajo/arriba indistinto)
                        # Elegimos la primera que no estaba antes; si no se puede, tomamos la mayor por estabilidad
                        diff = checked_ids - prev_true
                        new_sel = (list(diff)[0] if len(diff) == 1 else sorted(list(checked_ids))[-1])

                    # Persistimos nueva selección única en URL y en estado
                    _qp_set("selid", None if new_sel is None else int(new_sel))
                    st.session_state[f"{editor_key}__true_ids"] = {new_sel} if new_sel else set()
                else:
                    # no cambió: mantenemos
                    st.session_state[f"{editor_key}__true_ids"] = prev_true


                # ---- Gestión de cuotas / detalle de venta ----
                # Tomar ?selid de la URL si existe
                sel_from_url = None
                try:
                    sel_param = st.query_params.get("selid")
                    # por compatibilidad por si alguna vez llega como lista
                    if isinstance(sel_param, list):
                        sel_param = sel_param[0] if sel_param else None
                    sel_from_url = int(sel_param) if sel_param else None
                except Exception:
                    sel_from_url = None

            # ---- Gestión de cuotas / detalle de venta ----
                # Leer ?selid de la URL (si existe)
                # Marcar la selección actual (si hay ?selid en la URL)
                sel_param = st.query_params.get("selid")
                if isinstance(sel_param, list):
                    sel_param = sel_param[0] if sel_param else None
                try:
                    current_selid = int(sel_param) if sel_param else None
                except Exception:
                    current_selid = None

                # "Elegir": True solo en la VENTA seleccionada; en COMPRA queda vacío
                def _elegir(tipo, idventa, curr):
                    if tipo == "VENTA":
                        return bool(curr and idventa == curr)
                    return None

                df_ops["Elegir"] = [
                    _elegir(t, i, current_selid) for t, i in zip(df_ops["Tipo"], df_ops["ID venta"])
                ]

                # ID por defecto: primera fila VENTA visible
                ventas_ids = df_ops.loc[df_ops["Tipo"] == "VENTA", "ID venta"]
                default_id = int(ventas_ids.iloc[0]) if not ventas_ids.empty else 0

                selected_id = st.number_input(
                    "ID de venta para gestionar",
                    min_value=0,
                    step=1,
                    value=int(sel_from_url or default_id),
                    key=f"{key_prefix}_selid"
                )


                op = get_operation(selected_id) if selected_id else None

                if op:
                    st.markdown(
                        f"### Venta #{op['id']} — **{op.get('descripcion','')}** | "
                        f"Cliente: **{op.get('cliente','')}** | Inversor: **{op.get('nombre','')}** | "
                        f"Vendedor: **{op.get('zona','')}**"
                    )

                    total_cuotas = int(op.get("O") or 0)
                    venta_total = float(op.get("N") or 0.0)
                    y_venta = sum_paid(op["id"], is_purchase=False)
                    pendientes_venta = max(total_cuotas - count_paid_installments(op["id"], is_purchase=False), 0)
                    pendiente_venta = venta_total - y_venta

                    price = float(op.get("purchase_price") or 0.0)
                    y_compra = sum_paid(op["id"], is_purchase=True)
                    pendientes_compra = max(total_cuotas - count_paid_installments(op["id"], is_purchase=True), 0)
                    pendiente_compra = price - y_compra

                    st.markdown(
                        f"**VENTA** — Total: {fmt_money_up(venta_total)} | Cobrado (Y): {fmt_money_up(y_venta)} | "
                        f"Cuotas: {fmt_int(total_cuotas)} | Pendientes: {fmt_int(pendientes_venta)} | "
                        f"Pendiente: {fmt_money_up(pendiente_venta)}"
                    )
                    st.markdown(
                        f"**COMPRA (pago al inversor)** — Precio compra: {fmt_money_up(price)} | Pagado: {fmt_money_up(y_compra)} | "
                        f"Cuotas: {fmt_int(total_cuotas)} | Pendientes: {fmt_int(pendientes_compra)} | "
                        f"Pendiente: {fmt_money_up(pendiente_compra)}"
                    )
                    if total_cuotas > 0:
                        st.markdown(
                            f"**Valor por cuota (VENTA):** {fmt_money_up(venta_total/total_cuotas)} | "
                            f"**Comisión x cuota:** {fmt_money_up((float(op.get('comision') or 0.0)/total_cuotas))}"
                        )

                    # Permisos
                    puede_editar = is_admin()

                    # --- Cuotas de VENTA (cobros) ---
                    with st.expander("💳 Gestión de cuotas — VENTA (cobros)", expanded=False):
                        solo_lectura = not is_admin()
                        if solo_lectura:
                            st.info("Solo un administrador puede registrar/editar cuotas. Visualización en modo lectura.")

                        cuotas_venta = list_installments(op["id"], is_purchase=False) or []
                        if not cuotas_venta:
                            st.info("No hay cuotas de VENTA registradas.")
                        else:
                            # --- armar DF (id como índice) ---
                            total_cuotas = int(op.get("O") or 0)
                            comision_total = float(op.get("comision") or 0.0)
                            comi_x = (comision_total / total_cuotas) if total_cuotas > 0 else 0.0

                            vendedor_actual = (op.get("zona") or "").strip().upper()
                            es_toto = (vendedor_actual == "TOTO DONOFRIO")

                            ensure_notes_table()
                            notes_orig_v = {c["id"]: get_installment_note(c["id"]) for c in cuotas_venta}

                            # ✅ usar el NETO (o BRUTO si Toto) que calculamos en df_qv_rows
                            df_qv_rows = []
                            for c in cuotas_venta:
                                base_amt = float(c["amount"])  # valor por cuota original (bruto)
                                show_amt = base_amt if es_toto else max(base_amt - comi_x, 0.0)  # neto si NO es Toto
                                df_qv_rows.append({
                                    "id": c["id"],
                                    "Cuota": c["idx"],
                                    "Monto": show_amt,  # mostrado neto (o bruto si Toto)
                                    "Pagada": paid_bool_from_dict(c),
                                    "Fecha pago (registrada)": fmt_dmy_from_iso(c["paid_at"]),
                                    "Comentario": notes_orig_v.get(c["id"], "")
                                })

                            df_qv = pd.DataFrame(df_qv_rows)[
                                ["id","Cuota","Monto","Pagada","Fecha pago (registrada)","Comentario"]
                            ].set_index("id", drop=True)

                            edited_qv = st.data_editor(
                                df_qv,
                                hide_index=True,
                                use_container_width=True,
                                num_rows="fixed",
                                column_config={
                                    "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada", disabled=solo_lectura),
                                    "Monto": st.column_config.NumberColumn(
                                        "Monto", step=0.01, format="%.2f",
                                        help=("Se muestra neto de comisión por cuota" if not es_toto else "Se muestra el valor por cuota completo"),
                                        disabled=solo_lectura
                                    ),
                                    "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                                    "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                                    "Comentario": st.column_config.TextColumn("Comentario", help="Descripción / nota de esta cuota", disabled=solo_lectura),
                                },
                                key=f"{key_prefix}_qv_editor_{op['id']}"
                            )

                            fecha_pago_v = st.date_input(
                                "Fecha de cobro a registrar (para las que marques como pagas)",
                                value=date.today(), key=f"{key_prefix}_fpv_{op['id']}"
                            )

                            if (not solo_lectura) and st.button("Guardar estado de cuotas VENTA", key=f"{key_prefix}_btn_pagar_v_{op['id']}"):
                                iso_v = to_iso(fecha_pago_v)
                                orig_by_id = {c["id"]: paid_bool_from_dict(c) for c in cuotas_venta}
                                for iid, row in edited_qv.iterrows():
                                    iid = int(iid)
                                    new_paid = bool(row["Pagada"])
                                    old_paid = orig_by_id.get(iid, False)
                                    if new_paid != old_paid:
                                        set_installment_paid(iid, new_paid, paid_at_iso=(iso_v if new_paid else None))

                                    new_note = (row.get("Comentario") or "").strip()
                                    if new_note != (notes_orig_v.get(iid) or ""):
                                        set_installment_note(iid, new_note, updated_at_iso=iso_v)

                                recalc_status_for_operation(op["id"])
                                st.success("Cuotas de VENTA actualizadas.")
                                try:
                                    url = backup_snapshot_to_github()
                                    st.success("Backup subido a GitHub ✅")
                                    if url: st.markdown(f"[Ver commit →]({url})")
                                except Exception as e:
                                    st.error(f"Falló el backup: {e}")
                                st.rerun()


        
                    # --- Cuotas de COMPRA (pagos al inversor) ---
                    if key_prefix != "uno":
                        with st.expander("💸 Pagos al inversor — COMPRA", expanded=False):
                            solo_lectura = not is_admin()
                            if solo_lectura:
                                st.info("Solo un administrador puede registrar/editar cuotas. Visualización en modo lectura.")

                            cuotas_compra = list_installments(op["id"], is_purchase=True) or []
                            if not cuotas_compra:
                                st.info("No hay cuotas de COMPRA registradas.")
                            else:
                                ensure_notes_table()
                                notes_orig_c = {c["id"]: get_installment_note(c["id"]) for c in cuotas_compra}

                                df_qc = pd.DataFrame([{
                                    "id": c["id"],
                                    "Cuota": c["idx"],
                                    "Monto": float(c["amount"]),
                                    "Pagada": paid_bool_from_dict(c),
                                    "Fecha pago (registrada)": fmt_dmy_from_iso(c["paid_at"]),
                                    "Comentario": notes_orig_c.get(c["id"], "")
                                } for c in cuotas_compra])
                                df_qc = df_qc[["id","Cuota","Monto","Pagada","Fecha pago (registrada)","Comentario"]].set_index("id", drop=True)

                                edited_qc = st.data_editor(
                                    df_qc,
                                    hide_index=True,
                                    use_container_width=True,
                                    num_rows="fixed",
                                    column_config={
                                        "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada", disabled=solo_lectura),
                                        "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f", disabled=solo_lectura),
                                        "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                                        "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                                        "Comentario": st.column_config.TextColumn("Comentario", help="Descripción / nota de esta cuota", disabled=solo_lectura),
                                    },
                                    key=f"{key_prefix}_qc_editor_{op['id']}"
                                )

                                fecha_pago_c = st.date_input(
                                    "Fecha de pago al inversor a registrar (para las que marques como pagas)",
                                    value=date.today(), key=f"{key_prefix}_fpc_{op['id']}"
                                )

                                if (not solo_lectura) and st.button("Guardar estado de cuotas COMPRA", key=f"{key_prefix}_btn_pagar_c_{op['id']}"):
                                    iso_c = to_iso(fecha_pago_c)
                                    orig_by_id = {c["id"]: paid_bool_from_dict(c) for c in cuotas_compra}
                                    for iid, row in edited_qc.iterrows():
                                        iid = int(iid)
                                        new_paid = bool(row["Pagada"])
                                        old_paid = orig_by_id.get(iid, False)
                                        if new_paid != old_paid:
                                            set_installment_paid(iid, new_paid, paid_at_iso=(iso_c if new_paid else None))

                                        new_note = (row.get("Comentario") or "").strip()
                                        if new_note != (notes_orig_c.get(iid) or ""):
                                            set_installment_note(iid, new_note, updated_at_iso=iso_c)

                                    recalc_status_for_operation(op["id"])
                                    st.success("Cuotas de COMPRA actualizadas.")
                                    try:
                                        url = backup_snapshot_to_github()
                                        st.success("Backup subido a GitHub ✅")
                                        if url: st.markdown(f"[Ver commit →]({url})")
                                    except Exception as e:
                                        st.error(f"Falló el backup: {e}")
                                    st.rerun()



                    # --- Editar venta ---
                    with st.expander("✏️ Editar datos de la venta"):
                        puede_editar = is_admin()
                        if not puede_editar:
                            st.info("Solo un administrador puede editar esta venta.")

                        inv_now = op.get("nombre") or "GONZA"
                        new_inversor = st.select_slider(
                            "Inversor", options=INVERSORES,
                            value=inv_now if inv_now in INVERSORES else "GONZA",
                            key=f"{key_prefix}_inv_{op['id']}", disabled=not puede_editar
                        )
                        new_vendedor = st.text_input("Vendedor", value=op.get("zona") or "", key=f"{key_prefix}_vend_{op['id']}", disabled=not puede_editar)
                        new_revendedor = st.text_input("Revendedor", value=op.get("revendedor") or "", key=f"{key_prefix}_rev_{op['id']}", disabled=not puede_editar)
                        new_cliente = st.text_input("Cliente", value=op.get("cliente") or "", key=f"{key_prefix}_cli_{op['id']}", disabled=not puede_editar)
                        new_proveedor = st.text_input("Proveedor", value=op.get("proveedor") or "", key=f"{key_prefix}_prov_{op['id']}", disabled=not puede_editar)

                        new_costo = st.number_input("Costo (neto)", min_value=0.0, value=float(op.get("L") or 0.0), step=0.01, format="%.2f", key=f"{key_prefix}_costo_{op['id']}", disabled=not puede_editar)
                        new_venta = st.number_input("Venta", min_value=0.0, value=float(op.get("N") or 0.0), step=0.01, format="%.2f", key=f"{key_prefix}_venta_{op['id']}", disabled=not puede_editar)
                        new_cuotas = st.number_input("Cuotas", min_value=0, value=int(op.get("O") or 0), step=1, key=f"{key_prefix}_cuotas_{op['id']}", disabled=not puede_editar)
                        default_date = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                        new_fecha = st.date_input("Fecha de cobro", value=default_date, key=f"{key_prefix}_fv_{op['id']}", disabled=not puede_editar)

                        _implied_pct = 0.0
                        try:
                            if float(new_costo) > 0:
                                _implied_pct = max((float(op.get("purchase_price") or 0.0) / float(new_costo)) - 1.0, 0.0) * 100.0
                        except Exception:
                            _implied_pct = 18.0

                        inv_pct_edit = st.number_input(
                            "Porcentaje del inversor (%)",
                            min_value=0.0, max_value=100.0, step=0.1,
                            value=float(_implied_pct if _implied_pct > 0 else 18.0),
                            key=f"{key_prefix}_inv_pct_{op['id']}",
                            disabled=not puede_editar
                        )

                        inv_pct_effective = 0.0 if int(new_cuotas or 0) == 1 else float(inv_pct_edit)

                        new_price = calcular_precio_compra(new_costo, new_inversor, inv_pct_effective / 100.0)
                        new_comision_auto = calc_comision_auto(new_venta, new_costo, purchase_price=new_price)
                        new_ganancia_neta = (new_venta - new_price) - new_comision_auto

                        st.caption(
                            f"**Preview:** Precio compra = {fmt_money_up(new_price)} | "
                            f"Comisión (auto) = {fmt_money_up(new_comision_auto)} | "
                            f"Ganancia neta = {fmt_money_up(new_ganancia_neta)}"
                        )

                        if puede_editar and st.button("Guardar cambios de venta", key=f"{key_prefix}_save_op_{op['id']}"):
                            inv_pct_effective = 0.0 if int(new_cuotas or 0) == 1 else float(inv_pct_edit)
                            new_price = calcular_precio_compra(new_costo, new_inversor, inv_pct_effective / 100.0)
                            new_price = calcular_precio_compra(new_costo, new_inversor)
                            op["nombre"] = new_inversor
                            op["zona"] = new_vendedor
                            op["revendedor"] = new_revendedor
                            op["cliente"] = new_cliente
                            op["proveedor"] = new_proveedor
                            op["L"] = new_costo
                            op["N"] = new_venta
                            op["O"] = int(new_cuotas)
                            op["comision"] = float(new_comision_auto)
                            op["sale_date"] = to_iso(new_fecha)   # guarda sin hora
                            op["purchase_price"] = new_price
                            upsert_operation(op)
                            delete_installments(op["id"], is_purchase=None)
                            if int(new_cuotas) > 0:
                                # VENTA
                                create_installments(op["id"], distribuir(new_venta, int(new_cuotas)), is_purchase=False)

                                # COMPRA (siempre 6, excepto 1 pago)
                                n_compra = compra_cuotas_count(int(new_cuotas))
                                create_installments(op["id"], distribuir(new_price, n_compra), is_purchase=True)
                            # Si ahora la venta quedó en 1 pago, marcar la cuota de VENTA como pagada
                            if int(new_cuotas or 0) == 1:
                                cuotas_v = list_installments(op["id"], is_purchase=False) or []
                                iid = None
                                for c in cuotas_v:
                                    if int(c["idx"]) == 1:
                                        iid = c["id"]
                                        break
                                if not iid and cuotas_v:
                                    iid = cuotas_v[0]["id"]
                                if iid:
                                    set_installment_paid(iid, True, paid_at_iso=to_iso(new_fecha))
                            recalc_status_for_operation(op["id"])
                            st.success("Venta actualizada y cuotas recalculadas.")
                            try:
                                url = backup_snapshot_to_github()
                                st.success("Backup subido a GitHub ✅")
                                if url: st.markdown(f"[Ver commit →]({url})")
                            except Exception as e:
                                st.error(f"Falló el backup: {e}")
                            st.rerun()

                    # --- Eliminar venta ---
                    with st.expander("🗑️ Eliminar esta venta", expanded=False):
                        if not is_admin():
                            st.info("Solo un administrador puede eliminar ventas.")

                        # 1) confirmación visual
                        confirmar = st.checkbox(
                            f"Sí, quiero eliminar la venta #{op['id']}",
                            key=f"{key_prefix}_delchk_{op['id']}"
                        )

                        # 2) contraseña de borrado (pedida)
                        pwd = st.text_input(
                            "Contraseña de borrado",
                            type="password",
                            key=f"{key_prefix}_delpwd_{op['id']}",
                            placeholder="Escribí la contraseña",
                            help="Contraseña requerida para eliminar ventas"
                        )

                        # 3) ejecutar borrado sólo si sos admin + confirmás + contraseña correcta
                        if is_admin() and st.button("Eliminar definitivamente", key=f"{key_prefix}_delbtn_{op['id']}"):
                            if not confirmar:
                                st.error("Marcá la casilla de confirmación para eliminar.")
                            elif pwd != DELETE_SALES_PASSWORD:
                                st.error("Contraseña incorrecta.")
                            else:
                                delete_operation(op["id"])
                                try:
                                    urls = backup_snapshot_to_github()
                                    st.toast("Backup subido a GitHub ✅")
                                except Exception as e:
                                    st.warning(f"No se pudo subir el backup: {e}")
                                st.success("Venta eliminada.")
                                st.rerun()

                else:
                    st.info("Seleccioná un ID de venta para ver el detalle.")

            # ---- Render de cada lista en su pestaña ----
            with tabs[0]:
                st.caption("Ventas en 2 o más cuotas (vigentes)")
                render_listado(ops_multi, key_prefix="multi")

            with tabs[1]:
                st.caption("Ventas en 1 solo pago")
                render_listado(ops_uno, key_prefix="uno")

            with tabs[2]:
                st.caption("Ventas canceladas (solo 2+ cuotas)")
                render_listado(ops_cancel, key_prefix="cancel")


            with tabs[3]:
                st.caption("Ventas en PESOS con cuotas SEMANALES")
                render_listado(ops_sem, key_prefix="sem")

# --------- INVERSORES (DETALLE POR CADA UNO) ---------
# Ocultamos la pestaña a los vendedores para no exponer datos globales
if is_admin_user:
    with tab_inversores:
        with card("Inversores", "🏦"):

            # NEW: imports y datos compartidos necesarios en este scope
            from datetime import date as _date     # para hoy = _date.today()
            import pandas as pd                    # para asegurar tipos de fecha
            try:
                _ = ops_all  # si ya existe arriba, no hacemos nada
            except NameError:
                ops_all = list_operations(user_scope_filters({})) or []   # NEW: fallback

            ops = list_operations()
            if not ops:
                st.info("No hay ventas registradas todavía.")
            else:
                ops_df = build_ops_df(ops)
                ins_df = build_installments_df(ops)

                total_pagado_inv = float(ins_df[(ins_df["tipo"]=="COMPRA") & (ins_df["paid"]==True)]["amount"].sum())
                total_compra = float(ops_df["precio_compra"].sum())
                total_por_pagar_inv = total_compra - total_pagado_inv

                # Ganancia inversores: 18% del costo neto para GONZA, MARTIN y TOBIAS (YO)
                ganancia_inversores = float(
                    ops_df.apply(lambda r: r["costo_neto"]*0.18 if (str(r["inversor"]).upper() in ("GONZA","MARTIN","TOBIAS (YO)")) else 0.0, axis=1).sum()
                )

                # --- Ganancia por inversor (desglosada) ---
                def _ganancia_inv_para(inv_nombre: str) -> float:
                    inv_ops = ops_df[ops_df["inversor"].fillna("").astype(str).str.upper() == inv_nombre.upper()]
                    return float((inv_ops["costo_neto"] * 0.18).sum())
                
                hoy = _date.today()
                st.subheader("Resumen por inversor — próximos meses (Total / Pagado / A pagar)")

                meses_horizonte = st.slider(
                    "Meses a mostrar (desde el mes base)", 1, 12, 6, key="inv_meses_horizonte_mix"
                )

                from datetime import date
                import pandas as pd
                import numpy as np

                # Año/mes base (usa lo que ya tengas; si no existe, toma de session_state o actual)
                try:
                    base_year  = int(inv_year)
                    base_month = int(inv_month)
                except NameError:
                    base_year  = int(st.session_state.get("inv_mes_year",  date.today().year))
                    base_month = int(st.session_state.get("inv_mes_month", date.today().month))

                start   = pd.Timestamp(base_year, base_month, 1)
                periods = int(meses_horizonte)
                meses   = pd.period_range(start=start, periods=periods, freq="M")

                MESES_ES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
                            "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]
                def fmt_period_es(p: pd.Period) -> str:
                    return f"{MESES_ES[p.month-1]} {p.year}"

                dfc = ins_df.copy()
                if not dfc.empty:
                    # Solo COMPRA (pago a inversores)
                    dfc = dfc[dfc["tipo"].astype(str).str.upper().eq("COMPRA")].copy()
                    dfc["inversor"] = dfc["inversor"].fillna("").astype(str).str.upper()

                    # Respetar filtro de inversor si está en la UI
                    if 'inv_sel' in locals() and inv_sel and inv_sel != "Todos":
                        dfc = dfc[dfc["inversor"].eq(inv_sel.strip().upper())]

                    # Normalizar fechas y crear período
                    dfc["due_date"] = pd.to_datetime(dfc["due_date"], errors="coerce")
                    dfc = dfc.dropna(subset=["due_date"])
                    dfc["ym"] = dfc["due_date"].dt.to_period("M")

                    # Filtrar rango
                    dfc = dfc[dfc["ym"].isin(meses)].copy()

                    if dfc.empty:
                        st.info("No hay cuotas de COMPRA en el rango elegido.")
                    else:
                        # Pivot con estado pagado/impago por mes
                        # paid=True -> "Pagado", paid=False -> "A pagar"
                        dfc["estado"] = np.where(dfc["paid"].astype(bool), "Pagado", "A pagar")

                        piv = pd.pivot_table(
                            dfc,
                            index="inversor",
                            columns=["ym", "estado"],
                            values="amount",
                            aggfunc="sum",
                            fill_value=0.0,
                        )

                        # Asegurar todas las combinaciones (mes, estado)
                        col_idx = pd.MultiIndex.from_product([meses, ["Pagado", "A pagar"]])
                        piv = piv.reindex(columns=col_idx, fill_value=0.0)

                        # Construimos salida con columnas: MES(total), Pagado, A pagar, … por cada mes
                        out = pd.DataFrame(index=piv.index)
                        for p in meses:
                            total_col  = f"{fmt_period_es(p)}"
                            pagado_col = f"{fmt_period_es(p)} — PAGADO"
                            ap_col     = f"{fmt_period_es(p)} — A PAGAR"

                            pagado = piv[(p, "Pagado")]
                            apagar = piv[(p, "A pagar")]
                            total  = pagado + apagar

                            out[total_col]  = total
                            out[pagado_col] = pagado
                            out[ap_col]     = apagar

                        # Totales por inversor y fila total general
                        out["TOTAL inversor"] = out.sum(axis=1)
                        total_row = pd.DataFrame(out.sum(numeric_only=True)).T
                        total_row.index = ["TOTAL general"]
                        out = pd.concat([out, total_row], axis=0)

                        # Formato $
                        out_fmt = out.applymap(lambda x: f"${x:,.2f}")

                        st.dataframe(out_fmt, use_container_width=True, hide_index=False)
                else:
                    st.info("No hay datos de cuotas para proyectar.")
                # ===================== Cuotas a inversores por MES =====================
                st.divider()
                st.subheader("💸 Cuotas a inversores por mes")

                # Controles: año/mes, solo impagas, filtro de inversor
                c1, c2, c3, c4 = st.columns([1,1,1,2])
                with c1:
                    inv_year = st.number_input("Año", min_value=2000, max_value=2100, value=hoy.year, step=1, key="inv_mes_year")
                with c2:
                    inv_month = st.number_input("Mes", min_value=1, max_value=12, value=hoy.month, step=1, key="inv_mes_month")
                with c3:
                    solo_impagas = st.toggle("Solo impagas", value=True, key="inv_mes_only_unpaid")
                # lista de inversores a partir de tus operaciones (o usa INVERSORES si ya lo tenés)
                inv_names = sorted({ (op.get("nombre") or "").strip() for op in (ops_all or []) if (op.get("nombre") or "").strip() })
                with c4:
                    inv_sel = st.selectbox("Inversor", options=(["Todos"] + inv_names), index=0, key="inv_mes_filter")

                # helper: vencimiento por cuota (semanal/mensual)
                def _due_for(op, idx: int):
                    try:
                        # si ya creaste due_date_for, usalo
                        return due_date_for(op, int(idx))
                    except Exception:
                        # fallback mensual
                        base = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                        return add_months(base, max(int(idx)-1, 0))

                rows = []
                total_mes = 0.0

                # Recorremos operaciones y cuotas de COMPRA (pagos a inversor)
                for op in (ops_all or []):
                    inv_name = (op.get("nombre") or "").strip()
                    if inv_sel != "Todos" and inv_name.upper() != inv_sel.upper():
                        continue

                    cuotas_compra = list_installments(op["id"], is_purchase=True) or []
                    for c in cuotas_compra:
                        try:
                            idx = int(c["idx"])
                        except Exception:
                            continue
                        venc = _due_for(op, idx)
                        if venc.year == int(inv_year) and venc.month == int(inv_month):
                            pagada = _paid_bool(c)
                            if solo_impagas and pagada:
                                continue
                            monto = float(c["amount"] or 0.0)
                            total_mes += monto
                            rows.append({
                                "Inversor": inv_name or "—",
                                "ID venta": int(op["id"]),
                                "Cuota #": idx,
                                "Vence": venc.strftime("%d/%m/%Y"),
                                "Monto": monto,
                                "Estado": ("Pagada" if pagada else "Impaga")
                            })

                st.metric(
                    f"Total a pagar en {int(inv_month):02d}/{int(inv_year)}" + (" (impagas)" if solo_impagas else ""),
                    f"{total_mes:,.2f}"
                )

                if rows:
                    df_det = pd.DataFrame(rows)
                    # Resumen por inversor
                    df_res = df_det.groupby("Inversor", as_index=False)["Monto"].sum().rename(columns={"Monto":"Total del mes"})
                    cA, cB = st.columns([1,2])
                    with cA:
                        st.markdown("**Resumen por inversor**")
                        st.dataframe(
                            df_res.sort_values("Total del mes", ascending=False),
                            use_container_width=True, hide_index=True
                        )
                    with cB:
                        st.markdown("**Detalle de cuotas del mes**")
                        st.dataframe(
                            df_det.sort_values(["Inversor","Vence","ID venta","Cuota #"]),
                            use_container_width=True, hide_index=True
                        )
                else:
                    st.info("No hay cuotas que coincidan con el filtro seleccionado.")
                # ===================== /Cuotas a inversores por MES =====================

                st.divider()
                st.subheader("Detalle por inversor")

                # NEW: usar el mismo mes/año elegidos arriba para esta métrica
                anio_actual = int(inv_year)   # NEW
                mes_actual  = int(inv_month)  # NEW

                for inv in ["GONZA", "MARTIN", "TOBIAS (YO)"]:
                    st.markdown(f"### {inv}")
                    inv_ops = ops_df[ops_df["inversor"].fillna("").astype(str).str.upper()==inv]
                    if inv_ops.empty:
                        st.info("Sin operaciones con este inversor.")
                        continue

                    inv_ins = ins_df[ins_df["inversor"].fillna("").astype(str).str.upper()==inv]

                    # NEW: asegurar dtype datetime en due_date antes de filtrar por mes
                    if "due_date" in inv_ins.columns:
                        inv_ins = inv_ins.copy()
                        inv_ins["due_date"] = pd.to_datetime(inv_ins["due_date"], errors="coerce")

                    inv_total_compra = float(inv_ops["precio_compra"].sum())
                    inv_pagado = float(inv_ins[(inv_ins["tipo"]=="COMPRA") & (inv_ins["paid"]==True)]["amount"].sum())
                    inv_pendiente = inv_total_compra - inv_pagado
                    inv_ganancia = float((inv_ops["costo_neto"]*0.18).sum())

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total comprado (con 18%)", f"${inv_total_compra:,.2f}")
                    c2.metric("Pagado a este inversor", f"${inv_pagado:,.2f}")
                    c3.metric("Pendiente con este inversor", f"${inv_pendiente:,.2f}")

                    # NEW: métrica mensual impaga usando el mes/año seleccionados arriba
                    try:
                        to_pay_month = float(inv_ins[
                            (inv_ins["tipo"]=="COMPRA")
                            & (inv_ins["paid"]==False)
                            & (inv_ins["due_date"].dt.year==anio_actual)
                            & (inv_ins["due_date"].dt.month==mes_actual)
                        ]["amount"].sum())
                    except Exception:
                        to_pay_month = 0.0

                    st.metric("A pagar este mes (impago)", f"${to_pay_month:,.2f}")
                    st.write(f"**Ganancia acumulada del inversor (18%)**: ${inv_ganancia:,.2f}")
                    # === Pagado del mes SEGÚN FECHA DE PAGO (paid_at) ===
                    inv_ins = ins_df.copy()
                    
                    # Asegurar columna paid_at
                    if "paid_at" not in inv_ins.columns:
                        inv_ins["paid_at"] = None
                    
                    # Parsear a datetime (columna auxiliar)
                    inv_ins["_paid_at_dt"] = inv_ins["paid_at"].apply(_to_paid_at_dt)
                    
                    # Si usás inv_year/inv_month en esa vista:
                    year_f = int(inv_year)   if "inv_year"   in locals() else int(anio_actual)
                    month_f = int(inv_month) if "inv_month"  in locals() else int(mes_actual)
                    
                    pagado_mes = inv_ins[
                        (inv_ins["tipo"] == "COMPRA") &
                        (inv_ins["paid"] == True) &
                        (inv_ins["_paid_at_dt"].dt.year  == year_f) &
                        (inv_ins["_paid_at_dt"].dt.month == month_f)
                    ]["amount"].sum()
                    
                    st.metric(f"Pagado este mes (por fecha de pago)", f"${float(pagado_mes):,.2f}")
                    
                    # (Opcional) Detalle/resumen por inversor
                    df_pag = inv_ins[
                        (inv_ins["tipo"] == "COMPRA") &
                        (inv_ins["paid"] == True) &
                        (inv_ins["_paid_at_dt"].dt.year  == year_f) &
                        (inv_ins["_paid_at_dt"].dt.month == month_f)
                    ][["inversor","operation_id","idx","_paid_at_dt","amount"]].rename(
                        columns={"inversor":"Inversor","operation_id":"ID venta","idx":"Cuota #","_paid_at_dt":"Pagada el","amount":"Monto"}
                    )
                    
                    if not df_pag.empty:
                        df_pag = df_pag.sort_values(["Inversor","Pagada el","ID venta","Cuota #"])
                        c1_, c2_ = st.columns([1,2])
                        with c1_:
                            st.markdown("**Pagado del mes (por paid_at) — resumen**")
                            df_res_pag = df_pag.groupby("Inversor", as_index=False)["Monto"].sum().rename(columns={"Monto":"Pagado del mes"})
                            st.dataframe(df_res_pag.sort_values("Pagado del mes", ascending=False), use_container_width=True, hide_index=True)
                        with c2_:
                            st.markdown("**Detalle de pagos del mes (por paid_at)**")
                            df_pag["Pagada el"] = df_pag["Pagada el"].dt.strftime("%d/%m/%Y")
                            st.dataframe(df_pag, use_container_width=True, hide_index=True)
                    else:
                        st.info("No hay cuotas pagadas en el mes seleccionado (según fecha de pago).")


                st.divider()
                c_exp1, c_exp2 = st.columns([1, 3])

                with c_exp1:
                    if st.button("📤 Preparar y exportar a Sheets (usar sistema existente)", key="btn_export_inv_multimes_existente"):
                        try:
                            # 1) Preparamos un DF numérico y "planito" (sin $), con índice como columna
                            df_export = out.copy().reset_index()  # 'out' es la tabla multimes NUMÉRICA (NO out_fmt)
                
                            # 2) Guardamos en SQLite como tabla dedicada (opcional, lo dejo igual que antes)
                            with sqlite3.connect(DB_PATH) as con:
                                df_export.to_sql("inv_multimes_export", con, if_exists="replace", index=False)
                
                            st.success("Tabla 'inv_multimes_export' guardada en SQLite ✅")
                
                            # 3) Exportar usando tu Apps Script con action="write_tables"
                            #    Armamos "values" = fila de encabezados + filas de datos
                            header = list(df_export.columns)
                            rows = df_export.values.tolist()
                            values = [header] + rows
                
                            url = st.secrets["GS_WEBAPP_URL"]
                            tok = st.secrets.get("GS_WEBAPP_TOKEN", "")
                
                            payload = {
                                "token": tok,
                                "action": "write_tables",                  # 👈 CLAVE: ahora sí hay action
                                "sheets": [
                                    {"name": "inv_multimes_export",        # 👈 nombre de pestaña en Sheets
                                     "values": values}                      #    lo que tu WebApp escribe tal cual
                                ]
                            }
                
                            import requests, textwrap
                            r = requests.post(url, json=payload, timeout=60, allow_redirects=True)
                            st.write("GS status:", r.status_code)
                            st.code(textwrap.shorten(r.text, width=1000, placeholder=" … "), language="json")
                
                            if r.status_code == 200:
                                st.toast("Exportado a Google Sheets ✅")
                            else:
                                st.warning("El WebApp respondió algo inesperado. Revisá el JSON arriba.")
                
                        except Exception as e:
                            st.error("No se pudo preparar/exportar la tabla multimes con el sistema existente.")
                            st.exception(e)
                
                ws_name = "inv_multimes_export"  # ← sigue igual, es la pestaña creada/actualizada en Sheets

                if st.button("🎨 Aplicar formato (opcional)", key="btn_format_inv_multimes"):
                    formatear_hoja_backup(ws_name)

                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Pagado a inversores", f"${total_pagado_inv:,.2f}")
                c2.metric("Por pagar a inversores", f"${total_por_pagar_inv:,.2f}")
                c3.metric("Ganancia de inversores (18%)", f"${ganancia_inversores:,.2f}")

                gan_gonza  = _ganancia_inv_para("GONZA")
                gan_martin = _ganancia_inv_para("MARTIN")
                gan_tobias = _ganancia_inv_para("TOBIAS (YO)")

                g1, g2, g3 = st.columns(3)
                g1.metric("Ganancia GONZA (18%)", f"${gan_gonza:,.2f}")
                g2.metric("Ganancia MARTIN (18%)", f"${gan_martin:,.2f}")
                g3.metric("Ganancia TOBIAS (18%)", f"${gan_tobias:,.2f}")
    with tab_vendedores:
        with tab_vendedores:
            st.subheader("💸 Sueldo mensual por vendedor (solo comisiones)")

            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                anio_s = st.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1, key="vend_year_onlycomi")
            with c2:
                mes_s = st.number_input("Mes", min_value=1, max_value=12, value=date.today().month, step=1, key="vend_month_onlycomi")
            with c3:
                modo = st.radio("Modo", ["Proyección (vencimiento)", "Cobros registrados (pagadas)"], horizontal=False, key="vend_modo_onlycomi")
            modo_pagadas = (modo == "Cobros registrados (pagadas)")

            # Helper para la fecha de vencimiento de cada cuota (igual que usás en KPI)
            def _fecha_cuota_local(op_dict, idx:int):
                base = parse_iso_or_today(op_dict.get("sale_date") or op_dict.get("created_at"))
                return add_months(base, max(int(idx) - 1, 0))

            # Traemos todas las operaciones a las que tenés acceso
            ops = list_operations(user_scope_filters({})) or []

            # Acumuladores por vendedor
            vend_comi_total = {}   # suma de comisiones del mes
            vend_cant_cuotas = {}  # cuántas cuotas (con comisión) caen en el mes

            for op in ops:
                vendedor = (op.get("zona") or "").strip() or "—"
                total_cuotas = int(op.get("O") or 0)
                if total_cuotas <= 0:
                    continue

                comision_total = float(op.get("comision") or 0.0)
                comi_x = (comision_total / total_cuotas) if total_cuotas > 0 else 0.0

                # Solo cuotas de VENTA (las que generan comisión del vendedor)
                cuotas_v = list_installments(op["id"], is_purchase=False) or []

                for c in cuotas_v:
                    idx = int(c["idx"])
                    if not modo_pagadas:
                        # Proyección por vencimiento
                        due = _fecha_cuota_local(op, idx)
                        cond = (due.year == int(anio_s) and due.month == int(mes_s))
                    else:
                        # Solo las pagadas en el mes
                        paid_at = c.get("paid_at")
                        cond = paid_bool_from_dict(c) and paid_at and (
                            parse_iso_or_today(paid_at).year == int(anio_s) and
                            parse_iso_or_today(paid_at).month == int(mes_s)
                        )

                    if cond:
                        vend_comi_total[vendedor] = vend_comi_total.get(vendedor, 0.0) + comi_x
                        vend_cant_cuotas[vendedor] = vend_cant_cuotas.get(vendedor, 0) + 1

            # Lista de vendedores "registrados" si tenés maestro; si no, usamos los que aparecen en las ventas
            try:
                nombres_reg = [v["nombre"] for v in list_vendors(active_only=True)]
            except Exception:
                nombres_reg = []
            todos = sorted(set(nombres_reg) | set(vend_comi_total.keys()))

            rows = []
            for nombre in todos:
                total = float(vend_comi_total.get(nombre, 0.0))
                cant  = int(vend_cant_cuotas.get(nombre, 0))
                rows.append({
                    "Vendedor": nombre,
                    "Cuotas en el mes": cant,
                    "Sueldo (comisiones)": total
                })

            if not rows:
                st.info("No hay comisiones para el período seleccionado.")
            else:
                df_v = pd.DataFrame(rows).sort_values("Sueldo (comisiones)", ascending=False)
                df_v["Sueldo (comisiones)"] = df_v["Sueldo (comisiones)"].apply(fmt_money_up)
                st.dataframe(df_v, use_container_width=True, hide_index=True)
                st.caption("Se suma la comisión por cuota del mes. En 'Proyección' cuenta por vencimiento; en 'Cobros' por fecha de pago.")

                    
else:
    # Si es seller, mantenemos el tab para layout
    pass




# --------- REPORTES KPI (AMPLIADO) ---------
if is_admin_user:
        # === REPORTE: "Sueldo" mensual (GANANCIA por mes) ===
    from streamlit.components.v1 import html as st_html
    from datetime import date as _date

    def _fecha_cuota(op_dict, idx:int):
        base = parse_iso_or_today(op_dict.get("sale_date") or op_dict.get("created_at"))
        return add_months(base, max(int(idx) - 1, 0))

    def calcular_sueldo_mensual(anio: int, mes: int, modo_pagadas: bool = False):
            """
            Devuelve: (gan, v_mes, c_mes, com_mes, vend_gan)
            - gan:     Ventas del mes - Compras del mes - Comisión prorrateada del mes (salvo Toto vendedor)
            - v_mes:   Total cuotas de VENTA del mes (USD)
            - c_mes:   Total cuotas de COMPRA del mes (USD)
            - com_mes: Comisión prorrateada imputada en el mes (USD)
            - vend_gan: dict por vendedor con la misma fórmula de 'gan' aplicada por operación/vendedor
            NOTA: Excluye operaciones en ARS; sólo cuenta USD. Soporta dos modos:
            - modo_pagadas=False → Proyección por vencimiento (usa due date estimado)
            - modo_pagadas=True  → Cobros registrados (usa paid_at de cuotas pagadas)
            """
            try:
                ops_all = list_operations(user_scope_filters({})) or []
            except Exception:
                ops_all = []

            # Consideramos SOLO USD (o lo que no sea ARS)
            ids_usd = set()
            for op in ops_all:
                cur = (op.get("currency") or "USD").upper()
                if cur != "ARS":
                    ids_usd.add(int(op["id"]))

            # Helpers de fecha de vencimiento (mensual) y filtro mensual
            def _due_for(op, idx: int):
                """Vencimiento mensual (base: sale_date o created_at) → add_months(base, idx-1)."""
                base = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                return add_months(base, max(int(idx) - 1, 0))

            def _is_in_month(dt):
                return (dt.year == int(anio)) and (dt.month == int(mes))

            # Acumuladores
            v_mes = 0.0   # ventas
            c_mes = 0.0   # compras
            com_mes = 0.0 # comisión prorrateada
            vend_gan = {} # por vendedor

            for op in ops_all:
                op_id = int(op["id"])
                if op_id not in ids_usd:
                    continue  # excluir ARS

                vendedor_str = (op.get("zona") or "").strip()
                vendedor_up  = vendedor_str.upper()

                total_cuotas_venta = int(op.get("O") or 0)
                comision_total     = float(op.get("comision") or 0.0)
                com_x_cuota        = (comision_total / total_cuotas_venta) if total_cuotas_venta > 0 else 0.0

                # Cuotas de venta/compra
                cuotas_v = list_installments(op_id, is_purchase=False) or []
                cuotas_c = list_installments(op_id, is_purchase=True)  or []

                # Sumas imputadas para esta operación en el mes
                sum_v_op = 0.0
                sum_c_op = 0.0
                n_cuotas_venta_en_mes = 0  # para prorratear comisiones (solo sale)

                if modo_pagadas:
                    # Solo cuotas marcadas como pagadas con paid_at en el mes seleccionado
                    for cv in cuotas_v:
                        if not bool(cv.get("paid")):
                            continue
                        paid_at = cv.get("paid_at")
                        if not paid_at:
                            continue
                        try:
                            dtp = parse_iso_or_today(paid_at)
                        except Exception:
                            continue
                        if _is_in_month(dtp):
                            sum_v_op += float(cv.get("amount") or 0.0)
                            n_cuotas_venta_en_mes += 1

                    for cc in cuotas_c:
                        if not bool(cc.get("paid")):
                            continue
                        paid_at = cc.get("paid_at")
                        if not paid_at:
                            continue
                        try:
                            dtp = parse_iso_or_today(paid_at)
                        except Exception:
                            continue
                        if _is_in_month(dtp):
                            sum_c_op += float(cc.get("amount") or 0.0)

                else:
                    # Proyección por vencimiento (estimamos due date mensual por índice)
                    for cv in cuotas_v:
                        try:
                            idx = int(cv.get("idx"))
                        except Exception:
                            continue
                        due = _due_for(op, idx)
                        if _is_in_month(due):
                            sum_v_op += float(cv.get("amount") or 0.0)
                            n_cuotas_venta_en_mes += 1

                    for cc in cuotas_c:
                        try:
                            idx = int(cc.get("idx"))
                        except Exception:
                            continue
                        due = _due_for(op, idx)
                        if _is_in_month(due):
                            sum_c_op += float(cc.get("amount") or 0.0)

                # Comisión prorrateada: NO se descuenta si el vendedor es TOTO DONOFRIO
                com_op = 0.0 if (vendedor_up == "TOTO DONOFRIO") else (com_x_cuota * n_cuotas_venta_en_mes)

                # Acumular global
                v_mes += sum_v_op
                c_mes += sum_c_op
                com_mes += com_op

                # Acumular por vendedor
                vend_gan.setdefault(vendedor_str, 0.0)
                vend_gan[vendedor_str] += (sum_v_op - sum_c_op - com_op)

            gan = v_mes - c_mes - com_mes
            return float(gan), float(v_mes), float(c_mes), float(com_mes), vend_gan

    with tab_reportes:  # 👈 cambialo si tu tab se llama distinto
        with card("Reportes KPI", "📈"):
            st.subheader("💰 Sueldo mensual (GANANCIA por mes)")

            col_top1, col_top2, col_top3 = st.columns([1,1,1])
            with col_top1:
                anio_s = st.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1, key="rg_year")
            with col_top2:
                mes_s = st.number_input("Mes", min_value=1, max_value=12, value=date.today().month, step=1, key="rg_month")
            with col_top3:
                modo = st.radio("Modo", ["Proyección (vencimiento)", "Cobros registrados (pagadas)"], horizontal=False, key="rg_modo")

            modo_pagadas = (modo == "Cobros registrados (pagadas)")
            meta = st.number_input("Meta mensual (opcional)", min_value=0.0, value=0.0, step=1000.0, format="%.2f", key="rg_meta")
            ops_all = list_operations(user_scope_filters({})) or []

            rows = []
            for op in ops_all:
                venta   = float(op.get("N") or 0.0)
                costo   = float(op.get("L") or 0.0)
                price   = float(op.get("purchase_price") or 0.0)
                comis   = float(op.get("comision") or 0.0)
                vendedor= (op.get("zona") or "").strip()
                fecha   = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                moneda  = (op.get("currency") or "USD").upper()
                cuotas  = int(op.get("O") or 0)

                es_toto = vendedor.strip().upper() == "TOTO DONOFRIO"
                gan_oper = (venta - price) if es_toto else (venta - price - comis)

                rows.append({
                    "id": op["id"],
                    "mes": pd.to_datetime(fecha).to_period("M").to_timestamp(),
                    "venta": venta,
                    "costo": costo,
                    "purchase_price": price,
                    "comision": comis,
                    "vendedor": vendedor,
                    "currency": moneda,
                    "gan_total_oper": gan_oper,
                    "cuotas": cuotas,
                })

            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["id","mes","venta","costo","purchase_price","comision","vendedor","currency","gan_total_oper","cuotas"]
            )

            if not df.empty:
                df["mes"] = pd.to_datetime(df["mes"], errors="coerce")
                df["currency"] = df["currency"].fillna("USD").astype(str).str.upper()

            # filtro del mes elegido (usamos los mismos controles de arriba)
            anio = int(anio_s)
            mes  = int(mes_s)
            df_m = df[(df["mes"].dt.year == anio) & (df["mes"].dt.month == mes)].copy()

            # SEPARACIÓN DE MONEDAS
            df_m_usd = df_m[df_m["currency"] != "ARS"].copy()  # SOLO USD
            df_m_ars = df_m[df_m["currency"] == "ARS"].copy()  # ARS aparte (referencia)
            gan, v_mes, c_mes, com_mes, vend_gan = calcular_sueldo_mensual(int(anio_s), int(mes_s), modo_pagadas=modo_pagadas)

            # ---- Gauge / marcador de sueldo ----
            pct = 0.0
            if meta and meta > 0:
                pct = max(0.0, min(gan / meta, 1.0))
            pct100 = int(round(pct * 100))

            # Tarjeta linda con CSS (sin librerías extras)
            gauge_html = f"""
                <style>
                .card{{ 
                    border:1px solid rgba(255,255,255,.20); border-radius:16px; padding:18px; 
                    box-shadow: 0 8px 28px rgba(0,0,0,.25); 
                    background: radial-gradient(1200px 400px at 10% -10%, rgba(0,160,255,.20), transparent 60%),
                                linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
                    color:#fff; /* 👈 todo el texto en blanco */
                }}
                .title{{ font-size:14px; font-weight:600; opacity:.95; margin-bottom:6px; text-shadow:0 1px 2px rgba(0,0,0,.6); }}
                .value{{ font-size:34px; font-weight:800; margin:2px 0 10px; text-shadow:0 1px 2px rgba(0,0,0,.65); }}
                .row{{ display:flex; gap:16px; flex-wrap:wrap; }}
                .pill{{ 
                    font-size:12px; padding:6px 10px; border-radius:999px; 
                    border:1px solid rgba(255,255,255,.35); background: rgba(0,0,0,.35);
                    font-weight:600; text-shadow:0 1px 2px rgba(0,0,0,.7);
                }}
                .bar-wrap{{ margin-top:8px; height:12px; border-radius:999px; background: rgba(255,255,255,.20); overflow:hidden; }}
                .bar-fill{{ height:100%; width:{int(round((gan/meta if (meta and meta>0) else 0)*100))}%; background: linear-gradient(90deg, #00c6ff, #0072ff); }}
                .meta{{ font-size:12px; opacity:.95; margin-top:6px; text-shadow:0 1px 2px rgba(0,0,0,.6); }}
                </style>
                <div class="card">
                <div class="title">Sueldo mensual — {mes_s:02d}/{anio_s}</div>
                <div class="value">{fmt_money_up(gan)}</div>
                <div class="row">
                    <span class="pill">Ventas: {fmt_money_up(v_mes)}</span>
                    <span class="pill">Compra: {fmt_money_up(c_mes)}</span>
                    <span class="pill">Comisión: {fmt_money_up(com_mes)}</span>
                </div>
                {"<div class='bar-wrap'><div class='bar-fill'></div></div>" if meta and meta>0 else ""}
                {f"<div class='meta'>{int(round((gan/meta)*100))}% de la meta ({fmt_money_up(meta)})</div>" if meta and meta>0 else ""}
                </div>
    """

            st_html(gauge_html, height=(160 if (meta and meta>0) else 130))

            st.caption("Cálculo mensual: suma de cuotas de VENTA del mes − cuotas de COMPRA del mes − comisión prorrateada por cuota. "
                    "En *Proyección (vencimiento)* usa las fechas de vencimiento; en *Cobros registrados* usa la fecha en que marcaste como pagadas.")

            # ---- Detalle por vendedor (para entender tu 'sueldo' por persona) ----
            if vend_gan:
                df_v = pd.DataFrame(
                    [{"Vendedor": k, "Ganancia del mes": v} for k, v in vend_gan.items()]
                ).sort_values("Ganancia del mes", ascending=False)
                df_v["Ganancia del mes"] = df_v["Ganancia del mes"].apply(fmt_money_up)
                st.markdown("**Ganancia por vendedor (mes seleccionado):**")
                st.dataframe(df_v, use_container_width=True)
            else:
                st.info("No hay movimientos para el mes seleccionado.")

            st.divider()
            st.subheader("💵 KPI — Ganancias del mes en ARS")

            from datetime import date, datetime
            hoy = date.today()
            an, me = hoy.year, hoy.month  # o usa los mismos controles de mes que ya tengas

            ops = list_operations(user_scope_filters({})) or []
            rows = []
            for op in ops:
                dt = parse_iso_or_today(op.get("sale_date") or op.get("created_at"))
                rows.append({
                    "mes": datetime(dt.year, dt.month, 1),
                    "venta": float(op.get("N") or 0.0),
                    "costo": float(op.get("L") or 0.0),
                    "compra": float(op.get("purchase_price") or 0.0),
                    "comision": float(op.get("comision") or 0.0),
                    "cuotas": int(op.get("O") or 0),
                    "inversor": (op.get("nombre") or "").strip(),
                    "vendedor": (op.get("zona") or "").strip(),
                    "currency": (op.get("currency") or "").strip().upper(),
                })

            import pandas as pd
            df = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["mes","venta","costo","compra","comision","cuotas","inversor","vendedor","currency"]
            )
            if not df.empty:
                df["mes"] = pd.to_datetime(df["mes"], errors="coerce")
                df["currency"] = df["currency"].fillna("").str.upper()

            # usar el mismo mes/año seleccionados arriba
            an, me = int(anio_s), int(mes_s)

            df_m_ars = df[
                (df["mes"].dt.year == an) &
                (df["mes"].dt.month == me) &
                (df["currency"] == "ARS")
            ].copy()

            def _gan_vendor_por_op_row(r):
                cuotas   = int(r["cuotas"] or 0)
                vendedor = (r["vendedor"] or "").strip().upper()
                venta, compra, costo, comision = float(r["venta"] or 0.0), float(r["compra"] or 0.0), float(r["costo"] or 0.0), float(r["comision"] or 0.0)
                if cuotas == 1:
                    # 1 pago: base costo; si es Toto vendedor no descuenta comisión
                    return (venta - costo) if (vendedor == "TOTO DONOFRIO") else (venta - costo - comision)
                else:
                    # 2+ pagos: base purchase_price; si es Toto vendedor no descuenta comisión
                    return (venta - compra) if (vendedor == "TOTO DONOFRIO") else (venta - compra - comision)

            if df_m_ars.empty:
                st.info(f"No hay ventas ARS en {me:02d}/{an}.")
            else:
                df_m_ars["gan_vendor"] = df_m_ars.apply(_gan_vendor_por_op_row, axis=1)

                mask_inv_toto_ars  = df_m_ars["inversor"].fillna("").str.upper() == TOTO_INV_NAME.upper()
                mask_vend_toto_ars = df_m_ars["vendedor"].fillna("").str.upper() == TOTO_VENDOR_NAME.upper()

                # 18% como inversor (sobre costo) solo de ARS del mes
                g1_total_ars = float((df_m_ars.loc[mask_inv_toto_ars, "costo"].astype(float) * float(TOTO_INV_PCT)).sum())

                # Toto vendedor (2+ cuotas) y en 1 pago, en ARS del mes
                g2_total_ars = float(df_m_ars.loc[mask_vend_toto_ars & (df_m_ars["cuotas"] >= 2), "gan_vendor"].sum())
                g3_total_ars = float(df_m_ars.loc[mask_vend_toto_ars & (df_m_ars["cuotas"] == 1), "gan_vendor"].sum())

                gan_toto_vendedor_total_ars = float(df_m_ars.loc[mask_vend_toto_ars, "gan_vendor"].sum())
                g_no_toto_ars = float(df_m_ars.loc[~mask_vend_toto_ars, "gan_vendor"].sum())

                g4_total_ars = g1_total_ars + gan_toto_vendedor_total_ars
                g5_total_ars = g4_total_ars + g_no_toto_ars

                st.metric("Ganancia TOTAL ARS (negocio + 18% TOTO inversor)", fmt_money_up(g5_total_ars))


# --------- 👤 ADMINISTRACIÓN (solo admin) ---------
if is_admin_user:
    import requests
    import streamlit as st


    with tab_admin:

        with card("Vendedores", "🧑‍💼"):

            # === Alta de vendedor ===
            st.markdown("**Alta de vendedor**")
            c1, c2 = st.columns([3, 1])
            with c1:
                nuevo_vend = st.text_input(
                    "Nombre del vendedor (tal cual querés que figure en las ventas)",
                    key="vendor_new_name",
                    placeholder="Ej.: Juan Pérez"
                )
            with c2:
                if st.button("Agregar vendedor", type="primary", key="btn_add_vendor"):
                    name = (nuevo_vend or "").strip()
                    if not name:
                        st.error("Escribí un nombre.")
                    else:
                        ok, msg = add_vendor(name)  # tu función existente
                        try:
                            url = backup_snapshot_to_github()
                            st.success("Backup subido a GitHub ✅")
                            if url:
                                st.markdown(f"[Ver commit →]({url})")
                        except Exception as e:
                            st.warning(f"Falló el backup: {e}")
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.rerun()

            # separador visual
            st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:10px 0'>", unsafe_allow_html=True)

            # === Listado y acciones ===
            vendors_all = list_vendors(active_only=False) or []

            if len(vendors_all) == 0:
                st.info("No hay vendedores cargados.")
            else:
                st.markdown("**Vendedores cargados**")
                for v in vendors_all:
                    cols = st.columns([5, 2, 2])

                    # nombre + estado (badge)
                    estado_badge = "<span class='badge'>activo</span>" if v.get('activo', 1) == 1 else "<span class='badge badge--danger'>inactivo</span>"
                    cols[0].markdown(f"- {v['nombre']} {estado_badge}", unsafe_allow_html=True)

                    # 🗑️ Eliminar (solo si no tiene ventas)
                    if cols[1].button("Eliminar", key=f"delvend_{v['id']}"):
                        usos = count_ops_for_vendor_name(v['nombre'])
                        if usos > 0:
                            st.error(f"No se puede eliminar: tiene {usos} ventas asociadas. Desactiválo en su lugar.")
                        else:
                            delete_vendor(v["id"])
                            try:
                                url = backup_snapshot_to_github()
                                st.success("Vendedor eliminado y backup subido ✅")
                                if url: st.markdown(f"[Ver commit →]({url})")
                            except Exception as e:
                                st.warning(f"Vendedor eliminado. Falló el backup: {e}")
                            st.rerun()

                    # 🚫 Desactivar (solo si está activo)
                    if v.get('activo', 1) == 1:
                        if cols[2].button("Desactivar", key=f"deact_v_{v['id']}"):
                            deactivate_vendor(v["id"])
                            try:
                                url = backup_snapshot_to_github()
                                st.success("Vendedor desactivado y backup subido ✅")
                                if url: st.markdown(f"[Ver commit →]({url})")
                            except Exception as e:
                                st.warning(f"Desactivado. Falló el backup: {e}")
                            st.rerun()
                    else:
                        cols[2].write("")  # alineación


            
            
                    st.divider()
        st.markdown("<hr style='border:0; border-top:1px solid #1f2937; margin:10px 0'>", unsafe_allow_html=True)
        # --- Usuarios vendedores
        st.markdown("### 👥 Usuarios (vendedores)")
        vend_list = list_vendors(active_only=True)
        vend_names = [v["nombre"] for v in vend_list]
        cu1, cu2, cu3, cu4 = st.columns([2,2,2,1])
        with cu1:
            u_username = st.text_input("Usuario")
        with cu2:
            u_password = st.text_input("Contraseña", type="password")
        with cu3:
            u_vendedor = st.selectbox("Vincular a vendedor", options=vend_names, index=0 if vend_names else None, placeholder="Cargá vendedores primero")
        with cu4:
            if st.button("Crear usuario"):
                if not vend_names:
                    st.error("Primero cargá al menos un vendedor.")
                else:
                    ok, msg = create_user(u_username, u_password, role="seller", vendedor_nombre=u_vendedor)
                    (st.success if ok else st.error)(msg)
                    if ok: st.rerun()
        
        # Listado rápido de usuarios
        with get_conn() as con:
            cur = con.cursor()
            cur.execute("SELECT username, role, vendedor FROM users ORDER BY role DESC, username ASC;")
            rows = cur.fetchall()
        if rows:
            st.markdown("**Usuarios existentes**")
            for (uname, role, vend) in rows:
                cols = st.columns([3,2,3,2])
                cols[0].write(uname)
                cols[1].write(role)
                cols[2].write(vend or "-")
                if role != "admin":
                    if cols[3].button("Eliminar", key=f"deluser_{uname}"):
                        delete_user(uname)
                        st.rerun()

        # --- Seguridad: cuenta de administrador ---
        with st.expander("🔐 Cambiar credenciales de ADMIN"):
            admin_uname = (st.session_state.get("user") or {}).get("username", "admin")

            c1, c2 = st.columns(2)
            with c1:
                st.text_input("Usuario actual", value=admin_uname, disabled=True)
                new_username = st.text_input("Nuevo usuario (opcional)")
                curr_password = st.text_input("Contraseña ACTUAL", type="password")
            with c2:
                new_password = st.text_input("Nueva contraseña", type="password")
                new_password2 = st.text_input("Repetir nueva contraseña", type="password")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("Cambiar contraseña"):
                    if not new_password or new_password != new_password2:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        ok, msg = set_admin_password(admin_uname, curr_password, new_password)
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.success("Volvé a iniciar sesión con la nueva contraseña.")
                            st.session_state.clear()
                            st.rerun()

            with b2:
                if st.button("Cambiar usuario"):
                    if not new_username.strip():
                        st.error("Ingresá el nuevo usuario.")
                    else:
                        ok, msg = rename_admin_user(admin_uname, new_username, curr_password)
                        (st.success if ok else st.error)(msg)
                        if ok:
                            st.success("Volvé a iniciar sesión con el nuevo usuario.")
                            st.session_state.clear()
                            st.rerun()
        with card("Backup & Restore (GitHub)", "💽"):
            c1, c2 = st.columns(2)
            with c1:
                if st.button("💾 Guardar backup ahora"):
                    try:
                        url = backup_snapshot_to_github()
                        st.success("Backup subido a GitHub ✅")
                        if url: st.markdown(f"[Ver commit →]({url})")
                    except Exception as e:
                        st.error(f"Falló el backup: {e}")
            with c2:
                if st.button("♻️ Restaurar último backup"):
                    try:
                        restore_from_github_snapshot()
                        st.success("Restaurado desde GitHub ✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo restaurar: {e}")
        # === Diagnóstico y prueba de Backup a GitHub ===
            import base64, requests
            from datetime import datetime, timezone

            st.markdown("### 🔎 Diagnóstico Backup a GitHub")
            c1, c2 = st.columns(2)

            with c1:
                if st.button("Probar backup ahora (archivo de prueba)"):
                    try:
                        # 1) Chequear secrets básicos
                        faltan = [k for k in ("GH_TOKEN","GH_REPO") if k not in st.secrets]
                        if faltan:
                            st.error("Faltan estos Secrets: " + ", ".join(faltan))
                        else:
                            st.success("Secrets OK")

                        # 2) Chequear acceso al repo
                        repo = st.secrets["GH_REPO"]
                        branch = st.secrets.get("GH_BRANCH", "main")
                        headers = {"Authorization": f"Bearer {st.secrets['GH_TOKEN']}",
                                "Accept": "application/vnd.github+json"}

                        r_repo = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=20)
                        if r_repo.status_code != 200:
                            st.error(f"Repo no accesible: {r_repo.status_code} — {r_repo.text[:160]}")
                        else:
                            st.success("Acceso al repo OK")

                        # 3) Escribir archivo de prueba
                        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                        path = f"data/_probe_{ts}.txt"
                        url  = f"https://api.github.com/repos/{repo}/contents/{path}"
                        payload = {
                            "message": f"probe {ts}",
                            "content": base64.b64encode(f"ok {ts}".encode()).decode(),
                            "branch": branch
                        }
                        r_put = requests.put(url, headers=headers, json=payload, timeout=30)
                        if r_put.status_code in (200, 201):
                            html = r_put.json()["content"]["html_url"]
                            st.success(f"Escritura OK → {html}")
                        else:
                            st.error(f"PUT falló: {r_put.status_code} — {r_put.text[:300]}")

                    except Exception as e:
                        st.exception(e)

            with c2:
                if st.button("Forzar backup real (snapshot.json + CSVs)"):
                    try:
                        urls = backup_snapshot_to_github()
                        st.success("Backup subido a GitHub ✅")
                        for nombre, link in (urls or {}).items():
                            st.write(f"• {nombre}: {link}")
                    except Exception as e:
                        st.error(f"No se pudo subir el backup: {e}")
            st.markdown("### 📤 Exportar a Google Sheets")
            if is_admin():
                c1, c2, c3 = st.columns([1,1,1])
                if c1.button("Probar conexión"):
                    _ping_webapp()
                if c2.button("Exportar ahora"):
                    exportar_a_sheets_webapp_desde_sqlite(DB_PATH)  # usa tu DB_PATH = "ventas.db"
                if c3.button("🧹 Limpiar logs"):
                    st.session_state.export_logs.clear()
                    st.info("Logs limpiados.")
            else:
                st.info("Solo un administrador puede exportar a Google Sheets.")

            with st.expander("🔍 Logs de exportación (persisten en la sesión)"):
                for line in st.session_state.export_logs[-200:]:
                    st.text(line)
        with st.expander("🧮 Recalcular comisiones históricas", expanded=False):
            st.caption("Recalcula la columna 'comision' de TODAS las ventas con la lógica vigente.")

            if not is_admin():
                st.info("Solo un administrador puede ejecutar esta acción.")
            else:
                if st.button("Recalcular ahora (con backup)", type="primary"):
                    try:
                        # 1) Backup antes de tocar nada (si ya tenés esta función)
                        try:
                            url = backup_snapshot_to_github()
                            if url:
                                st.success("Backup subido a GitHub ✅")
                                st.markdown(f"[Ver commit →]({url})")
                        except Exception as e:
                            st.warning(f"No se pudo subir backup: {e}")

                        # 2) Recalcular
                        ops_all = list_operations(user_scope_filters({})) or []
                        total = len(ops_all)
                        cambios = 0

                        prog = st.progress(0, text="Procesando…")
                        for i, op in enumerate(ops_all, start=1):
                            venta   = float(op.get("N") or 0.0)
                            costo   = float(op.get("L") or 0.0)
                            cuotas  = int(op.get("O") or 0)
                            pprice  = op.get("purchase_price")
                            pprice  = float(pprice) if pprice is not None else None

                            # Regla: si es 1 pago → usar costo (como venías haciendo).
                            # Si es 2+ pagos → usar purchase_price (incluye el 18%).
                            if cuotas == 1:
                                nueva = calc_comision_auto(venta=venta, costo_neto=costo, purchase_price=None)
                            else:
                                nueva = calc_comision_auto(venta=venta, costo_neto=costo, purchase_price=pprice)

                            vieja = float(op.get("comision") or 0.0)
                            if abs(nueva - vieja) > 0.009:  # si realmente cambió
                                op["comision"] = float(nueva)
                                upsert_operation(op)
                                cambios += 1

                            if i % 20 == 0 or i == total:
                                prog.progress(i/total, text=f"Procesando… {i}/{total}")

                        prog.empty()
                        st.success(f"Listo. Comisiones actualizadas en {cambios} de {total} ventas.")

                    except Exception as e:
                        st.error("Falló la actualización de comisiones.")
                        st.exception(e)
        # ================== /Recalcular comisiones (histórico) ==================
        with card("Rescate: ventas ocultas (0 cuotas)", "🧰"):
            ops_zero = get_ops_zero_cuotas()
            if not ops_zero:
                st.info("No hay ventas con 0 cuotas. ¡Todo limpio!")
            else:
                st.warning("Estas ventas NO tienen cuotas, por eso no aparecen en el listado. Podés eliminarlas desde acá.")
                for op in ops_zero:
                    c1, c2, c3, c4 = st.columns([1, 3, 2, 2])
                    c1.markdown(f"**#{op['id']}**")
                    c2.markdown(f"{op['descripcion']}  \n<small style='color:#9aa0a6'>Vendedor: {op['vendedor']} — {op['fecha']}</small>", unsafe_allow_html=True)
                    pwd = c3.text_input("Contraseña", type="password", key=f"pwd_zero_{op['id']}", placeholder="totoborrar")
                    if c4.button("Eliminar venta", key=f"btn_zero_{op['id']}"):
                        if pwd != DELETE_SALES_PASSWORD:   # ya la tenés definida como "totoborrar"
                            st.error("Contraseña incorrecta.")
                        else:
                            delete_operation(op["id"])
                            try:
                                backup_snapshot_to_github()
                                st.toast("Backup subido a GitHub ✅")
                            except Exception as e:
                                st.warning(f"No se pudo subir el backup: {e}")
                            st.success(f"Venta #{op['id']} eliminada ✅")
                            st.rerun()
        def _summarize_installments(db_path: str):
            """Devuelve resumen de installments de una DB dada."""
            with closing(sqlite3.connect(db_path)) as con:
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                def _q(q, params=()):
                    cur.execute(q, params)
                    return cur.fetchall()
        
                # Totales
                tot = _q("SELECT COUNT(*) AS n FROM installments")[0]["n"]
                pag = _q("SELECT COUNT(*) AS n FROM installments WHERE paid=1")[0]["n"]
                imp = tot - pag
        
                # Split por tipo
                try:
                    pag_v = _q("SELECT COUNT(*) AS n FROM installments WHERE paid=1 AND is_purchase=0")[0]["n"]
                    pag_c = _q("SELECT COUNT(*) AS n FROM installments WHERE paid=1 AND is_purchase=1")[0]["n"]
                except Exception:
                    # por si el flag se llama distinto
                    pag_v = _q("SELECT COUNT(*) AS n FROM installments WHERE paid=1 AND (is_purchase=0 OR is_purchase IS NULL)")[0]["n"]
                    pag_c = pag - pag_v
        
                # Últimos 10 pagos registrados (para olfatear si es el backup correcto)
                ultimos = _q("""
                    SELECT operation_id, idx, is_purchase, amount, paid, paid_at
                    FROM installments WHERE paid=1
                    ORDER BY COALESCE(paid_at, '') DESC, id DESC
                    LIMIT 10
                """)
        
                # Operaciones con pagos: cuántas distintas
                ops_pag = _q("SELECT COUNT(DISTINCT operation_id) AS k FROM installments WHERE paid=1")[0]["k"]
        
                return {
                    "total": tot,
                    "pagadas": pag,
                    "impagas": imp,
                    "pagadas_venta": pag_v,
                    "pagadas_compra": pag_c,
                    "ops_con_pagadas": ops_pag,
                    "ultimos": [dict(r) for r in ultimos],
                }
        
        def _same_schema_or_intersection(src_con, dst_con, table="installments"):
            """Calcula columnas comunes entre tablas installments de src y dst."""
            def _cols(cnx):
                cnx.row_factory = sqlite3.Row
                cur = cnx.cursor()
                cur.execute(f"PRAGMA table_info({table})")
                return [r["name"] for r in cur.fetchall()]
            src_cols = _cols(src_con)
            dst_cols = _cols(dst_con)
            common = [c for c in dst_cols if c in src_cols]  # preserva orden de destino
            return src_cols, dst_cols, common
        
        def _restore_installments_from_backup_bytes(backup_bytes: bytes, db_path_dest: str):
            """Restaura la tabla installments desde bytes de un .db de backup, sin tocar otras tablas."""
            # Guardar en un archivo temporal en memoria/disco
            tmp = io.BytesIO(backup_bytes)
            # sqlite no abre desde BytesIO directo; lo guardamos a un archivo real
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
                f.write(tmp.getvalue())
                f.flush()
                src_path = f.name
        
            try:
                with closing(sqlite3.connect(src_path)) as src, closing(sqlite3.connect(db_path_dest)) as dst:
                    src.row_factory = sqlite3.Row
                    dst.row_factory = sqlite3.Row
        
                    # Columnas comunes (por si hubo cambios de esquema)
                    src_cols, dst_cols, common = _same_schema_or_intersection(src, dst, "installments")
                    if not common:
                        raise RuntimeError("No hay columnas comunes entre installments (backup vs. actual).")
        
                    cols_csv = ", ".join(common)
        
                    # Transacción segura
                    with dst:
                        dst.execute("DELETE FROM installments")
                        dst.execute(f"INSERT INTO installments ({cols_csv}) SELECT {cols_csv} FROM main.installments", [])
                        # Lo anterior copiaria desde la misma DB, así que hagamos ATTACH y copiamos desde src
                    with dst:
                        dst.execute("ATTACH DATABASE ? AS bkp", (src_path,))
                        dst.execute("DELETE FROM main.installments")
                        dst.execute(f"INSERT INTO main.installments ({cols_csv}) SELECT {cols_csv} FROM bkp.installments")
                        dst.execute("DETACH DATABASE bkp")
                return True, None
            except Exception as e:
                return False, str(e)
            finally:
                try:
                    os.remove(src_path)
                except Exception:
                    pass
        
        with st.expander("🛠 Restaurar cuotas desde backup (.db)", expanded=False):
            st.caption("Subí un archivo .db de tus backups. Primero te muestro un **resumen**; si coincide con lo que recordás, podés restaurar **solo** la tabla de cuotas (installments) sin tocar el resto.")
        
            up = st.file_uploader("Elegí un backup .db", type=["db", "sqlite"], key="restore_db_uploader")
            if up is not None:
                # Guardamos bytes en memoria y previsualizamos
                data = up.read()
                # preview: escribir a tmp para poder abrir con sqlite
                import tempfile, os
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
                    f.write(data)
                    f.flush()
                    tmp_path = f.name
        
                try:
                    prev = _summarize_installments(tmp_path)
                except Exception as e:
                    st.error(f"No pude leer el backup: {e}")
                    prev = None
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        
                if prev:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Cuotas (total)", f"{prev['total']:,}")
                    c2.metric("Pagadas", f"{prev['pagadas']:,}")
                    c3.metric("Impagas", f"{prev['impagas']:,}")
                    c4.metric("Ops con pagadas", f"{prev['ops_con_pagadas']:,}")
        
                    c5, c6 = st.columns(2)
                    c5.metric("Pagadas VENTA", f"{prev['pagadas_venta']:,}")
                    c6.metric("Pagadas COMPRA", f"{prev['pagadas_compra']:,}")
        
                    st.markdown("**Últimos 10 pagos en el backup** (para chequear si es el correcto):")
                    st.dataframe(
                        pd.DataFrame(prev["ultimos"]),
                        use_container_width=True, hide_index=True
                    )
        
                    st.info("Si estos números coinciden con lo que recordás, podés restaurar **solo** la tabla `installments` desde este backup. El resto de tablas quedan intactas.")
        
                    if st.button("⚠️ Restaurar 'installments' desde este backup", type="primary", key="btn_restore_installments"):
                        ok, err = _restore_installments_from_backup_bytes(data, DB_PATH)
                        if ok:
                            try:
                                recalc_all_statuses()  # si tenés una función global; si no, recalc por operación
                            except Exception:
                                pass
                            st.success("¡Listo! Se restauraron las cuotas desde el backup. Actualizo la vista…")
                            st.rerun()
                        else:
                            st.error(f"No pude restaurar: {err}")
            else:
                st.caption("Consejo: en GitHub buscá un backup cercano al momento que sabés que tenía las marcas correctas, descargalo, y probalo acá. Como hay **previsualización**, podés tantear varios sin riesgo hasta encontrar el correcto.")
        # ====== Botón alternativo: FUSIONAR pagos del backup con la DB actual (conservar nuevos) ======
        def _load_installments_as_df(db_path: str) -> pd.DataFrame:
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(db_path)) as con:
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute("""
                    SELECT
                      id, operation_id,
                      CAST(idx AS INTEGER) AS idx,
                      CAST(is_purchase AS INTEGER) AS is_purchase,
                      amount,
                      CAST(paid AS INTEGER) AS paid,
                      paid_at
                    FROM installments
                """)
                rows = [dict(r) for r in cur.fetchall()]
            df = pd.DataFrame(rows)
            if df.empty:
                df = pd.DataFrame(columns=["id","operation_id","idx","is_purchase","amount","paid","paid_at"])
            # normalizo tipos
            for col in ["operation_id","idx","is_purchase","paid"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
            return df
        
        def _merge_paid_flags(backup_bytes: bytes, db_path_dest: str):
            """Fusiona flags paid/paid_at por (operation_id, idx, is_purchase).
            Reglas:
              - paid_final = paid_actual OR paid_backup
              - Si ambas pagadas -> usar SIEMPRE paid_at del backup
              - Si solo backup pagada -> usar fecha del backup
              - Si solo actual pagada -> usar fecha actual
              - No borra filas ni toca montos, solo UPDATE de paid/paid_at
            """
            import sqlite3, tempfile, os
            from contextlib import closing
            import pandas as pd
        
            # 1) Escribimos backup a archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
                f.write(backup_bytes)
                f.flush()
                src_path = f.name
        
            try:
                # 2) Cargamos dataframes
                df_src = _load_installments_as_df(src_path)      # BACKUP
                df_dst = _load_installments_as_df(db_path_dest)  # ACTUAL
        
                if df_dst.empty:
                    return False, "La DB actual no tiene installments para fusionar."
        
                # Asegurar columnas mínimas en backup
                for col in ["paid", "paid_at"]:
                    if col not in df_src.columns:
                        df_src[col] = None if col == "paid_at" else 0
        
                # 3) Clave de fusión
                KEY = ["operation_id", "idx", "is_purchase"]
                for col in KEY:
                    if col not in df_src.columns:
                        df_src[col] = 0  # por si el schema del backup es más viejo
        
                # 4) Merge por clave (left=actual, traemos flags del backup)
                merged = df_dst.merge(
                    df_src[KEY + ["paid", "paid_at"]],
                    on=KEY, how="left", suffixes=("", "_bkp")
                )
        
                # Post-merge: garantizar columnas _bkp
                if "paid_bkp" not in merged.columns:
                    merged["paid_bkp"] = 0
                if "paid_at_bkp" not in merged.columns:
                    merged["paid_at_bkp"] = None
        
                # Normalizar tipos/na
                merged["paid"] = pd.to_numeric(merged["paid"], errors="coerce").fillna(0).astype(int)
                merged["paid_bkp"] = pd.to_numeric(merged["paid_bkp"], errors="coerce").fillna(0).astype(int)
        
                # 5) Resolver flags y fechas (accesos SIEMPRE con default)
                def _resolve(row):
                    p_cur = int(row.get("paid", 0) or 0)
                    p_bkp = int(row.get("paid_bkp", 0) or 0)
                    a_cur = row.get("paid_at", None)
                    a_bkp = row.get("paid_at_bkp", None)
        
                    paid_final = 1 if (p_cur == 1 or p_bkp == 1) else 0
        
                    # Reglas pedidas:
                    # - ambas pagadas -> usar SIEMPRE fecha del backup (si existe)
                    # - solo backup pagada -> fecha backup
                    # - solo actual pagada -> fecha actual
                    # - ninguna -> None
                    if paid_final == 1:
                        if p_bkp == 1 and a_bkp:           # backup tiene fecha -> gana backup
                            paid_at_final = str(a_bkp)
                        elif p_bkp == 1 and not a_bkp:     # backup sin fecha
                            paid_at_final = str(a_cur) if a_cur else None
                        elif p_cur == 1:
                            paid_at_final = str(a_cur) if a_cur else None
                        else:
                            paid_at_final = None
                    else:
                        paid_at_final = None
        
                    return paid_final, paid_at_final
        
                resolved = merged.apply(lambda r: pd.Series(_resolve(r), index=["paid_final","paid_at_final"]), axis=1)
                merged = pd.concat([merged, resolved], axis=1)
        
                # 6) Detectar diferencias a aplicar
                to_update = merged[
                    (merged["paid_final"] != merged["paid"]) |
                    (merged["paid_at_final"].fillna("") != merged["paid_at"].fillna(""))
                ][["id", "paid_final", "paid_at_final"]].copy()
        
                if to_update.empty:
                    return True, "No hay cambios para aplicar (todo ya conciliado)."
        
                # 7) Aplicar updates
                with closing(sqlite3.connect(db_path_dest)) as con:
                    cur = con.cursor()
                    con.execute("BEGIN")
                    try:
                        for _, r in to_update.iterrows():
                            cur.execute(
                                "UPDATE installments SET paid=?, paid_at=? WHERE id=?",
                                (int(r["paid_final"]),
                                 (r["paid_at_final"] if pd.notna(r["paid_at_final"]) else None),
                                 int(r["id"]))
                            )
                        con.commit()
                    except Exception as e:
                        con.rollback()
                        return False, f"Error aplicando updates: {e}"
        
                return True, f"Actualizadas {len(to_update)} cuotas."
            finally:
                try:
                    os.remove(src_path)
                except Exception:
                    pass
        
        with st.expander("🤝 Fusionar pagos desde backup (conservar nuevos)", expanded=False):
            st.caption("Usá esta opción si **registraste pagos recientemente** y no querés perderlos. Fusiona las marcas `paid` y `paid_at` del backup con tu base actual por `(operation_id, idx, is_purchase)`.")
            up2 = st.file_uploader("Elegí un backup .db", type=["db","sqlite"], key="merge_db_uploader")
            if up2 is not None:
                # preview simple
                st.write("Preview backup (últimos pagos):")
                _tmp_preview = None
                try:
                    import tempfile, os, sqlite3
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
                        f.write(up2.read())
                        f.flush()
                        tmp_path = f.name
                    _prev = _summarize_installments(tmp_path)
                    st.dataframe(pd.DataFrame(_prev["ultimos"]), use_container_width=True, hide_index=True)
                    with open(tmp_path, "rb") as fh:
                        _tmp_preview = fh.read()
                except Exception as e:
                    st.error(f"No pude previsualizar el backup: {e}")
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        
                if _tmp_preview:
                    if st.button("🤝 Fusionar pagos (no borra nada)", type="primary", key="btn_merge_paid"):
                        ok, msg = _merge_paid_flags(_tmp_preview, DB_PATH)
                        if ok:
                            try:
                                recalc_all_statuses()
                            except Exception:
                                pass
                            st.success(f"Listo: {msg}")
                            st.rerun()
                        else:
                            st.error(msg)
                
        # ====================== /Restaurar cuotas desde backup (.db) ======================
if is_admin_user:
    with tab_stock:
        with st.expander("⚙️ Opciones"):
            group_esim_sim = st.checkbox("Tratar SIM y eSIM como el mismo modelo",
                                        value=bool(group_esim_sim))
            st.session_state["group_esim_sim"] = group_esim_sim

            show_full = st.checkbox("Mostrar tabla completa de líneas parseadas",
                                    value=bool(show_full))
            st.session_state["show_full"] = show_full

            margin_usd = st.number_input("Ganancia / margen (USD)",
                                        min_value=0.0,
                                        value=float(margin_usd),
                                        step=1.0)
            st.session_state["margin_usd"] = margin_usd
        with st.expander("📇 Gestión de proveedores (opcional)"):
            # Inicializar y mostrar proveedores registrados
            def _init_providers_db():
                con = sqlite3.connect("providers.db")
                cur = con.cursor()
                cur.execute("CREATE TABLE IF NOT EXISTS providers (name TEXT PRIMARY KEY)")
                con.commit()
                cur.execute("INSERT OR IGNORE INTO providers(name) VALUES (?)", ("Belgrano",))
                cur.execute("INSERT OR IGNORE INTO providers(name) VALUES (?)", ("Marco Carola",))
                con.commit()
                con.close()

            def _get_providers():
                with sqlite3.connect("providers.db") as con:
                    return [r[0] for r in con.execute("SELECT name FROM providers ORDER BY name")] 

            def _add_provider(name: str):
                name = (name or "").strip()
                if not name:
                    return False
                with sqlite3.connect("providers.db") as con:
                    cur = con.cursor()
                    cur.execute("INSERT OR IGNORE INTO providers(name) VALUES (?)", (name,))
                    con.commit()
                return True

            _init_providers_db()
            st.caption("Proveedores registrados: " + (", ".join(_get_providers()) or "ninguno"))
            new_name = st.text_input("Agregar proveedor", key="prov_add")
            if st.button("Agregar", key="prov_add_btn"):
                if _add_provider(new_name):
                    st.success(f"Agregado: {new_name}")
                else:
                    st.warning("Ingresá un nombre válido.")
            st.caption("Por ahora el procesamiento usa fijos: Belgrano y Marco Carola.")

        with st.form("pegar_whatsapp"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Proveedor 1:** Belgrano")
                vendor1 = "Belgrano"
                text1 = st.text_area("Texto proveedor 1 (pegá desde WhatsApp)", height=260)
            with c2:
                st.markdown("**Proveedor 2:** Marco Carola")
                vendor2 = "Marco Carola"
                text2 = st.text_area("Texto proveedor 2 (pegá desde WhatsApp)", height=260)
            submitted = st.form_submit_button("Procesar")

        if submitted:
            inputs = []
            if text1.strip():
                inputs.append((vendor1.strip() or "Proveedor 1", text1))
            if text2.strip():
                inputs.append((vendor2.strip() or "Proveedor 2", text2))

            if len(inputs) == 0:
                st.warning("Pegá el texto de al menos un proveedor.")
                st.stop()

            dfs = []
            for vendor, text in inputs:
                df = parse_lines(vendor, text)
                dfs.append(df)

            raw = pd.concat(dfs, ignore_index=True)
            st.success(f"Se parsearon **{len(raw)}** líneas válidas de **{len(inputs)}** proveedor(es).")

            if show_full:
                st.dataframe(raw, use_container_width=True)

            # agrupar por mejor precio
            group_key = "key" if group_esim_sim else "key_with_sim"
            best = raw.sort_values("price_usd").groupby(group_key, as_index=False).first()
            best = best.rename(columns={"vendor": "best_vendor", "sim": "sim_from_best"})
            cov = raw.groupby(group_key)["vendor"].nunique().reset_index().rename(columns={"vendor": "num_vendors"})
            out = best.merge(cov, on=group_key, how="left")

            # ordenar y construir "Modelo" sin columna Variante aparte
            order_cols = ["gen","variant","storage"]
            out = out.sort_values(order_cols).reset_index(drop=True)
            out["model"] = ("Iphone " + out["gen"] + " " + out["variant"] + " " + out["storage"]).str.replace("  ", " ").str.replace("  ", " ").str.strip()
            out["sale_price_usd"] = out["price_usd"] + float(margin_usd)

            show = out[["model","price_usd","sale_price_usd","best_vendor","sim_from_best"]].rename(columns={
                "model":"Modelo",
                "price_usd":"Mejor precio (USD)",
                "sale_price_usd":"Valor Venta (USD)",
                "best_vendor":"Proveedor",
                "sim_from_best":"SIM/eSIM"
            })

            st.subheader("🏆 Mejor precio por modelo")
            st.dataframe(show, use_container_width=True)
            publish_public_view(show)
            
            st.caption("📣 Vista pública actualizada. Compartí tu URL con ?public=1")

            # Botón para generar lista WhatsApp
            # Lista para WhatsApp (persistente, con botón de copiar que NO re-ejecuta el script)
            lines = [f"▪️{r['Modelo']} - $ {int(round(r['Valor Venta (USD)']))}" for _, r in show.iterrows()]
            msg = "\n".join(lines)
            st.session_state['whatsapp_msg'] = msg

            st.subheader("📋 Lista WhatsApp")
            components.html(f"""
        <div style='display:flex;gap:8px;align-items:center;margin-bottom:8px;'>
        <button id='copyBtn'>Copiar Lista Whatsapp</button>
        </div>
        <textarea id='wa' rows='12' style='width:100%;'>{msg}</textarea>
        <script>
        const btn = document.getElementById('copyBtn');
        btn.addEventListener('click', async () => {{
        const ta = document.getElementById('wa');
        ta.select();
        try {{ await navigator.clipboard.writeText(ta.value); }} catch(e) {{ document.execCommand('copy'); }}
        }});
        </script>
        """, height=260)

            # descargar CSV (sin columna Variante)
            csv = show.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Descargar CSV unificado",
                data=csv,
                file_name="iphone_stock_best.csv",
                mime="text/csv"
            )

            st.caption(f"Modelos únicos: {show.shape[0]} • Proveedores procesados: {len(inputs)}")
        else:
            st.info("Pegá el texto de uno o dos proveedores y presioná **Procesar**.")

with tab_cal:
    # --------- 📅 CALENDARIO DE COBROS ---------
    st.markdown("### 🗓️ Calendario de cobros (cuotas impagas de VENTA)")
    st.caption("Calendario mensual en formato cuadriculado. Cada casillero muestra cuántas cuotas impagas vencen ese día.")

    # --- 1) Construcción de eventos impagos (si ya armás event_rows en otra parte, podés usarlo) ---
    from datetime import date as _date
    import calendar as _cal

    ops_all = list_operations(user_scope_filters({})) or []

    event_rows = []
    for op_ in ops_all:
        cuotas = list_installments(op_["id"], is_purchase=False) or []
        for c in cuotas:
            if not paid_bool_from_dict(c):
                # fecha de vencimiento de cada cuota
                base = parse_iso_or_today(op_.get("sale_date") or op_.get("created_at"))
                due = add_months(base, max(int(c["idx"]) - 1, 0))
                event_rows.append({
                    "Fecha": due,                           # datetime/date
                    "Vendedor": op_.get("zona") or "",
                    "Cliente": op_.get("cliente") or "",
                    "VentaID": op_["id"],
                    "Cuota": int(c["idx"]),
                    "Monto": float(c["amount"]),
                    "Desc": op_.get("descripcion") or "",
                })

    if not event_rows:
        st.info("No hay cuotas impagas próximas para mostrar.")
    else:
        cal_df = pd.DataFrame(event_rows)
        # Asegurar datetime
        cal_df["Fecha"] = pd.to_datetime(cal_df["Fecha"], errors="coerce").dt.tz_localize(None)
        cal_df = cal_df.dropna(subset=["Fecha"])

        # --- 2) Selección de mes/año ---
        c1, c2 = st.columns(2)
        with c1:
            anio = st.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1)
        with c2:
            mes = st.number_input("Mes", min_value=1, max_value=12, value=date.today().month, step=1)

        # Filtrar al mes/año elegidos
        cal_df = cal_df[(cal_df["Fecha"].dt.year == anio) & (cal_df["Fecha"].dt.month == mes)]
        sel_day = None
        try:
            _param = st.query_params.get("calday")
            if isinstance(_param, list):
                _param = _param[0] if _param else None
            sel_day = _dt.strptime(_param, "%Y-%m-%d").date() if _param else None
        except Exception:
            sel_day = None
        sel_day = st.session_state.get("calday") or sel_day
        if cal_df.empty:
            st.warning("No hay cuotas impagas en el mes seleccionado.")
        else:
            # --- 3) Agregados por día ---
            # Conteo por día y total monto (para tooltip)
            by_day = (
                cal_df.groupby(cal_df["Fecha"].dt.date)
                    .agg(cuotas=("Cuota", "count"), total=("Monto", "sum"))
                    .reset_index()
            )
            # Diccionarios día -> métricas
            counts = {r["Fecha"]: int(r["cuotas"]) for _, r in by_day.iterrows()}
            totals = {r["Fecha"]: float(r["total"]) for _, r in by_day.iterrows()}
            max_count = max(counts.values()) if counts else 1

            

            # ================== CALENDARIO BONITO + VENDEDORES ==================
            import calendar as _cal
            from collections import Counter
            from datetime import date as _date

            # vendedores por día (y cuántas cuotas tiene cada uno ese día)
            vend_by_day = {}
            for _, r in cal_df.iterrows():
                d = r["Fecha"].date()
                v = (r.get("Vendedor") or "").strip() or "—"
                vend_by_day.setdefault(d, Counter())
                vend_by_day[d][v] += 1

            _cal.setfirstweekday(_cal.MONDAY)
            weeks = _cal.monthcalendar(int(anio), int(mes))
            max_count = max(counts.values()) if counts else 1
            st.write("")

            cols_header = st.columns(7)
            for i, lab in enumerate(["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]):
                cols_header[i].markdown(f"**{lab}**")
            
            # ===== Estilo de tarjetas (solo para el calendario) =====
            st.markdown("""
            <style>
            .cal-card {position:relative; height:116px; border-radius:14px; border:1px solid rgba(255,255,255,0.15);
            padding:10px 12px; background: var(--card-bg, rgba(0,0,0,0.25)); box-shadow: 0 6px 18px rgba(0,0,0,.25);}
            .cal-card .day {font-size:20px; font-weight:800; color:#fff; text-shadow:0 1px 2px rgba(0,0,0,.5);}
            .cal-card .count {position:absolute; right:10px; top:8px; font-size:12px; font-weight:700;
            background: rgba(0,0,0,.35); padding:2px 8px; border-radius:999px; color:#fff;}
            .cal-card .total {position:absolute; left:12px; bottom:10px; font-size:13px; font-weight:800; color:#fff;}
            .cal-card .chips {position:absolute; left:12px; right:12px; bottom:34px; display:flex; gap:6px; flex-wrap:wrap;}
            .cal-card .chip {font-size:11px; padding:3px 8px; border-radius:999px; background: rgba(0,0,0,.35);
            border:1px solid rgba(255,255,255,.25); color:#fff; font-weight:600; white-space:nowrap;}
            .cal-card.empty {border-style:dashed; opacity:.35; background:transparent;}
            .cal-card.selected {outline:2px solid #ffd54f; box-shadow: 0 0 0 3px rgba(255,213,79,.28) inset, 0 8px 24px rgba(0,0,0,.35);}
            .cal-btn {margin-top:6px}
            .cal-btn button {width:100%; border-radius:10px}
            </style>
            """, unsafe_allow_html=True)

            # ===== Grilla por semanas con tarjetas bonitas + botón Ver =====
            for w in weeks:
                cols = st.columns(7, gap="small")
                for j, d in enumerate(w):
                    if d == 0:
                        cols[j].markdown('<div class="cal-card empty"></div>', unsafe_allow_html=True)
                        continue

                    day = _date(int(anio), int(mes), int(d))
                    cnt = counts.get(day, 0)
                    ttl = totals.get(day, 0.0)

                    # chips de vendedores (top 3)
                    vd = vend_by_day.get(day, {})
                    pares = sorted(vd.items(), key=lambda kv: kv[1], reverse=True)
                    chips = []
                    for i2, (name, qty) in enumerate(pares[:3]):
                        label = name if len(name)<=16 else name[:14]+"…"
                        chips.append(f"<span class='chip' title='{name} ({qty})'>{label}{' ×'+str(qty) if qty>1 else ''}</span>")
                    if len(pares) > 3:
                        chips.append(f"<span class='chip'>+{len(pares)-3}</span>")
                    chips_html = "<div class='chips'>" + "".join(chips) + "</div>" if chips else ""

                    # Intensidad según cantidad (fondo sutil)
                    maxc = max(counts.values()) if counts else 1
                    alpha = 0.10 + (0.75 * (cnt / maxc)) if cnt>0 else 0.0
                    bg = f"linear-gradient(180deg, rgba(0,140,255,{alpha}) 0%, rgba(0,140,255,{alpha*0.55}) 100%)" if cnt>0 else "transparent"
                    selected_cls = " selected" if (st.session_state.get("calday") and day == st.session_state["calday"]) else ""

                    cols[j].markdown(
                        f"""
                        <div class="cal-card{selected_cls}" style="--card-bg:{bg}">
                        <div class="day">{d:02d}</div>
                        {'<div class="count">'+str(cnt)+'</div>' if cnt>0 else ''}
                        {chips_html}
                        {'<div class="total">'+fmt_money_up(ttl)+'</div>' if cnt>0 else ''}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    # Botón "Ver" (no navega, setea sesión + query param y rerun)
                    if cols[j].button("Ver", key=f"calbtn_{anio}_{mes}_{d}", help="Ver IDs de este día", type="secondary"):
                        sel_day = day
                        st.session_state["calday"] = day
                        st.query_params.update(calday=day.isoformat())
                        st.rerun()


            def _seller_chips_html(day):
                # hasta 3 chips visibles, el resto como "+N"
                c = vend_by_day.get(day, {})
                if not c:
                    return ""
                # ordenar por más cuotas
                pares = sorted(c.items(), key=lambda kv: kv[1], reverse=True)
                chips = []
                for i, (name, qty) in enumerate(pares):
                    if i >= 3:
                        break
                    # abreviar nombres largos a 16 chars para que no rompan la caja
                    label = name if len(name) <= 16 else (name[:14] + "…")
                    extra = f" ×{qty}" if qty > 1 else ""
                    chips.append(f"<span class='chip' title='{name} ({qty})'>{label}{extra}</span>")
                if len(pares) > 3:
                    chips.append(f"<span class='chip more'>+{len(pares)-3}</span>")
                return "<div class='chips'>" + "".join(chips) + "</div>"

            def _cell_html(d):
                if d == 0:
                    return '<td class="empty"></td>'
                day = _date(int(anio), int(mes), int(d))
                cnt = counts.get(day, 0)
                ttl = totals.get(day, 0.0)

                # Intensidad/gradiente según cantidad
                alpha = 0.10 + (0.75 * (cnt / max_count)) if cnt > 0 else 0.0
                bg = f"linear-gradient(180deg, rgba(0,140,255,{alpha}) 0%, rgba(0,140,255,{alpha*0.55}) 100%)" if cnt > 0 else "var(--cell-bg)"
                border = "rgba(0,140,255,0.35)" if cnt > 0 else "var(--cell-border)"

                chips = _seller_chips_html(day)

                total_text = fmt_money_up(ttl) if cnt > 0 else ""
                count_text = str(cnt) if cnt > 0 else ""

                selected_cls = " selected" if (sel_day and day == sel_day) else ""
                href = f"?calday={day.isoformat()}#cal"

                return f"""
                <td class="cell{selected_cls}" style="--bg:{bg}; --border:{border}">
                    <a class="hit" href="{href}" title="Ver IDs del {d:02d}"></a>
                    <div class="day">{d:02d}</div>
                    <div class="count" title="Cuotas: {count_text}">{count_text}</div>
                    {chips}
                    <div class="total">{total_text}</div>
                </td>
                """

            rows_html = "".join("<tr>" + "".join(_cell_html(d) for d in w) + "</tr>" for w in weeks)

            cal_html = f"""
            <style>
                :root {{
                    --cell-bg: transparent;
                    --cell-border: rgba(255,255,255,0.12);
                    --shadow: 0 4px 16px rgba(0,0,0,0.25);
                }}
                .cal {{
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 10px;
                    table-layout: fixed;
                    margin-top: 6px;
                }}
                .cal th {{
                    text-align:center; font-weight:700; padding:8px; color:#fff;
                }}
                .cal td.cell {{
                    height: 108px;
                    border:1px solid var(--cell-border);
                    border-radius:14px;
                    position:relative;
                    background: var(--bg);
                    box-shadow: var(--shadow);
                    overflow:hidden;
                    transition: transform .08s ease-out, box-shadow .12s ease-out;
                }}
                .cal td.cell:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
                }}
                .cal td.empty {{
                    height: 108px;
                    border:1px dashed rgba(255,255,255,0.10);
                    border-radius:14px; opacity:.35;
                }}
                .cal .day {{
                    position:absolute; left:10px; top:8px;
                    font-size:13px; font-weight:600;
                    color:#fff; text-shadow:0 1px 2px rgba(0,0,0,0.6);
                }}
                .cal .count {{
                    position:absolute; right:10px; top:8px;
                    font-size:13px; font-weight:700;
                    background: rgba(0,0,0,0.35);
                    padding:2px 6px; border-radius:999px;
                    color:#fff; text-shadow:0 1px 2px rgba(0,0,0,0.6);
                }}
                .cal .total {{
                    position:absolute; left:10px; bottom:8px;
                    font-size:13px; font-weight:700;
                    color:#fff; text-shadow:0 1px 2px rgba(0,0,0,0.6);
                }}
                .cal .chips {{
                    position:absolute; left:10px; right:10px; bottom:32px;
                    display:flex; flex-wrap:wrap; gap:6px;
                }}
                .cal .chip {{
                    font-size:11px; padding:3px 8px; border-radius:10px;
                    background: rgba(0,0,0,0.4);
                    border:1px solid rgba(255,255,255,0.25);
                    color:#fff; font-weight:600;
                    white-space:nowrap; max-width: 100%;
                    text-overflow: ellipsis; overflow:hidden;
                    text-shadow:0 1px 2px rgba(0,0,0,0.7);
                }}
                .cal .chip.more {{
                    background: rgba(0,0,0,0.25); font-weight:700; color:#fff;
                }}
                .cal td.cell .hit{{
                    position:absolute; inset:0; z-index:5; cursor:pointer; text-decoration:none;
                }}
                .cal td.cell.selected{{
                    outline:2px solid #ffd54f; box-shadow: 0 0 0 3px rgba(255,213,79,.28) inset, var(--shadow);
                }}
                </style>

            <table class="cal">
            <thead><tr>
                <th>Lun</th><th>Mar</th><th>Mié</th><th>Jue</th><th>Vie</th><th>Sáb</th><th>Dom</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
            </table>
            """
            st.markdown('<a id="cal"></a>', unsafe_allow_html=True)
            st_html(cal_html, height=(len(weeks) * 140 + 120))
            # === Listado de IDs para el día seleccionado ===
            if sel_day:
                df_day = cal_df[cal_df["Fecha"].dt.date == sel_day].copy()
                if df_day.empty:
                    st.info(f"No hay cuotas impagas para el {sel_day.strftime('%d/%m/%Y')}.")
                else:
                    ids_unicos = sorted(df_day["VentaID"].unique().tolist())
                    st.markdown("**IDs el " + sel_day.strftime("%d/%m/%Y") + ":** " + ", ".join(str(i) for i in ids_unicos))

                    # id previamente seleccionado (de la URL o de la sesión)
                    selid_param = st.query_params.get("selid")
                    if isinstance(selid_param, list):
                        selid_param = selid_param[0] if selid_param else None
                    prev_selid = int(selid_param) if (selid_param and str(selid_param).isdigit()) else st.session_state.get("cal_selid")

                    # tabla base
                    show = df_day[["VentaID","Cuota","Monto","Cliente","Vendedor","Desc"]].rename(
                        columns={"VentaID":"ID venta","Desc":"Descripción"}
                    ).sort_values(["ID venta","Cuota"]).reset_index(drop=True)

                    # columna Elegir (una sola True)
                    show["Elegir"] = show["ID venta"].apply(lambda i: bool(prev_selid and int(i) == int(prev_selid)))

                    edited = st.data_editor(
                        show,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        column_config={
                            "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f"),
                            "Elegir": st.column_config.CheckboxColumn(
                                "Elegir",
                                help="Selecciona este ID para gestionar",
                                default=False
                            ),
                        },
                        key="cal_ids_del_dia_editor",
                    )

                    # detectar selección nueva (enforce radio-like: una sola marcada)
                    # tomamos la marcada que sea distinta del previo; si hay varias, nos quedamos con la primera
                    marked = edited[edited["Elegir"]]
                    new_selid = None

                    # === Gestión de cuotas del ID seleccionado (en Calendario) ===
                    selected_id = st.session_state.get("cal_selid")
                    if selected_id:
                        op = get_operation(int(selected_id))
                    else:
                        op = None

                    if op:
                        st.divider()
                        st.markdown(
                            f"### Venta #{op['id']} — **{op.get('descripcion','')}** | "
                            f"Cliente: **{op.get('cliente','')}** | Inversor: **{op.get('nombre','')}** | "
                            f"Vendedor: **{op.get('zona','')}**"
                        )

                        total_cuotas = int(op.get("O") or 0)
                        venta_total  = float(op.get("N") or 0.0)
                        y_venta      = sum_paid(op["id"], is_purchase=False)
                        pendientes_v = max(total_cuotas - count_paid_installments(op["id"], is_purchase=False), 0)
                        pendiente_v  = venta_total - y_venta

                        price        = float(op.get("purchase_price") or 0.0)
                        y_compra     = sum_paid(op["id"], is_purchase=True)
                        pagadas_c    = count_paid_installments(op["id"], is_purchase=True)
                        # cantidad real de cuotas de COMPRA (6 u 1)
                        try:
                            n_compra_real = len(list_installments(op["id"], is_purchase=True)) or (1 if total_cuotas==1 else 6)
                        except Exception:
                            n_compra_real = (1 if total_cuotas==1 else 6)
                        pendientes_c  = max(n_compra_real - pagadas_c, 0)
                        pendiente_c   = price - y_compra

                        st.markdown(
                            f"**VENTA** — Total: {fmt_money_up(venta_total)} | Cobrado: {fmt_money_up(y_venta)} | "
                            f"Cuotas: {fmt_int(total_cuotas)} | Pendientes: {fmt_int(pendientes_v)} | "
                            f"Pendiente: {fmt_money_up(pendiente_v)}"
                        )
                        st.markdown(
                            f"**COMPRA (pago al inversor)** — Precio compra: {fmt_money_up(price)} | Pagado: {fmt_money_up(y_compra)} | "
                            f"Cuotas: {fmt_int(n_compra_real)} | Pendientes: {fmt_int(pendientes_c)} | "
                            f"Pendiente: {fmt_money_up(pendiente_c)}"
                        )
                        if total_cuotas > 0:
                            st.caption(f"**Valor por cuota (VENTA):** {fmt_money_up(venta_total/max(total_cuotas,1))} "
                                    f"| **Comisión x cuota:** {fmt_money_up((float(op.get('comision') or 0.0)/max(total_cuotas,1)))}")

                        # ---------- VENTA (cobros) ----------
                        with st.expander("💳 Gestión de cuotas — VENTA (cobros)", expanded=False):
                            solo_lectura = not is_admin()
                            if solo_lectura:
                                st.info("Solo un administrador puede registrar/editar cuotas. Visualización en modo lectura.")

                            cuotas_venta = list_installments(op["id"], is_purchase=False) or []
                            if not cuotas_venta:
                                st.info("No hay cuotas de VENTA registradas.")
                            else:
                                comision_total = float(op.get("comision") or 0.0)
                                comi_x = (comision_total / max(total_cuotas,1)) if total_cuotas > 0 else 0.0
                                vendedor_actual = (op.get("zona") or "").strip().upper()
                                es_toto = (vendedor_actual == "TOTO DONOFRIO")

                                ensure_notes_table()
                                notes_orig_v = {c["id"]: get_installment_note(c["id"]) for c in cuotas_venta}

                                rows_v = []
                                for c in cuotas_venta:
                                    base_amt = float(c["amount"])          # bruto
                                    show_amt = base_amt if es_toto else max(base_amt - comi_x, 0.0)  # neto si NO es Toto
                                    rows_v.append({
                                        "id": c["id"], "Cuota": c["idx"], "Monto": show_amt,
                                        "Pagada": paid_bool_from_dict(c), "Fecha pago (registrada)": fmt_dmy_from_iso(c["paid_at"]),
                                        "Comentario": notes_orig_v.get(c["id"], "")
                                    })
                                df_qv = pd.DataFrame(rows_v)[["id","Cuota","Monto","Pagada","Fecha pago (registrada)","Comentario"]].set_index("id", drop=True)

                                edited_qv = st.data_editor(
                                    df_qv, hide_index=True, use_container_width=True, num_rows="fixed",
                                    column_config={
                                        "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada", disabled=solo_lectura),
                                        "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f",
                                                                            help=("Se muestra neto de comisión por cuota" if not es_toto else "Valor por cuota bruto"),
                                                                            disabled=solo_lectura),
                                        "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                                        "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                                        "Comentario": st.column_config.TextColumn("Comentario", help="Descripción / nota de esta cuota", disabled=solo_lectura),
                                    },
                                    key=f"cal_qv_editor_{op['id']}"
                                )

                                fecha_pago_v = st.date_input("Fecha de cobro a registrar (para las que marques como pagas)",
                                                            value=date.today(), key=f"cal_fpv_{op['id']}")
                                if (not solo_lectura) and st.button("Guardar estado de cuotas VENTA", key=f"cal_btn_pagar_v_{op['id']}"):
                                    iso_v = to_iso(fecha_pago_v)
                                    orig_by_id = {c["id"]: paid_bool_from_dict(c) for c in cuotas_venta}
                                    for iid, row in edited_qv.iterrows():
                                        iid = int(iid)
                                        new_paid = bool(row["Pagada"])
                                        old_paid = orig_by_id.get(iid, False)
                                        if new_paid != old_paid:
                                            set_installment_paid(iid, new_paid, paid_at_iso=(iso_v if new_paid else None))
                                        new_note = (row.get("Comentario") or "").strip()
                                        if new_note != (notes_orig_v.get(iid) or ""):
                                            set_installment_note(iid, new_note, updated_at_iso=iso_v)
                                    recalc_status_for_operation(op["id"])
                                    st.success("Cuotas de VENTA actualizadas.")
                                    try:
                                        url = backup_snapshot_to_github()
                                        st.success("Backup subido a GitHub ✅")
                                        if url: st.markdown(f"[Ver commit →]({url})")
                                    except Exception as e:
                                        st.error(f"Falló el backup: {e}")
                                    st.rerun()

                        # ---------- COMPRA (pagos al inversor) ----------
                        with st.expander("💸 Pagos al inversor — COMPRA", expanded=False):
                            solo_lectura = not is_admin()
                            if solo_lectura:
                                st.info("Solo un administrador puede registrar/editar cuotas. Visualización en modo lectura.")

                            cuotas_compra = list_installments(op["id"], is_purchase=True) or []
                            if not cuotas_compra:
                                st.info("No hay cuotas de COMPRA registradas.")
                            else:
                                ensure_notes_table()
                                notes_orig_c = {c["id"]: get_installment_note(c["id"]) for c in cuotas_compra}

                                df_qc = pd.DataFrame([{
                                    "id": c["id"], "Cuota": c["idx"], "Monto": float(c["amount"]),
                                    "Pagada": paid_bool_from_dict(c), "Fecha pago (registrada)": fmt_dmy_from_iso(c["paid_at"]),
                                    "Comentario": notes_orig_c.get(c["id"], "")
                                } for c in cuotas_compra])[["id","Cuota","Monto","Pagada","Fecha pago (registrada)","Comentario"]].set_index("id", drop=True)

                                edited_qc = st.data_editor(
                                    df_qc, hide_index=True, use_container_width=True, num_rows="fixed",
                                    column_config={
                                        "Pagada": st.column_config.CheckboxColumn("Pagada", help="Marcar si la cuota está pagada", disabled=solo_lectura),
                                        "Monto": st.column_config.NumberColumn("Monto", step=0.01, format="%.2f", disabled=solo_lectura),
                                        "Cuota": st.column_config.NumberColumn("Cuota", disabled=True),
                                        "Fecha pago (registrada)": st.column_config.TextColumn("Fecha pago (registrada)", disabled=True),
                                        "Comentario": st.column_config.TextColumn("Comentario", help="Descripción / nota de esta cuota", disabled=solo_lectura),
                                    },
                                    key=f"cal_qc_editor_{op['id']}"
                                )

                                fecha_pago_c = st.date_input("Fecha de pago al inversor a registrar (para las que marques como pagas)",
                                                            value=date.today(), key=f"cal_fpc_{op['id']}")
                                if (not solo_lectura) and st.button("Guardar estado de cuotas COMPRA", key=f"cal_btn_pagar_c_{op['id']}"):
                                    iso_c = to_iso(fecha_pago_c)
                                    orig_by_id = {c["id"]: paid_bool_from_dict(c) for c in cuotas_compra}
                                    for iid, row in edited_qc.iterrows():
                                        iid = int(iid)
                                        new_paid = bool(row["Pagada"])
                                        old_paid = orig_by_id.get(iid, False)
                                        if new_paid != old_paid:
                                            set_installment_paid(iid, new_paid, paid_at_iso=(iso_c if new_paid else None))
                                        new_note = (row.get("Comentario") or "").strip()
                                        if new_note != (notes_orig_c.get(iid) or ""):
                                            set_installment_note(iid, new_note, updated_at_iso=iso_c)
                                    recalc_status_for_operation(op["id"])
                                    st.success("Cuotas de COMPRA actualizadas.")
                                    try:
                                        url = backup_snapshot_to_github()
                                        st.success("Backup subido a GitHub ✅")
                                        if url: st.markdown(f"[Ver commit →]({url})")
                                    except Exception as e:
                                        st.error(f"Falló el backup: {e}")
                                    st.rerun()

                    if not marked.empty:
                        # si hay varias marcadas, intentamos priorizar la que cambió (≠ prev_selid)
                        if prev_selid is not None and (marked["ID venta"] != int(prev_selid)).any():
                            new_selid = int(marked[marked["ID venta"] != int(prev_selid)]["ID venta"].iloc[0])
                        else:
                            new_selid = int(marked["ID venta"].iloc[0])

                    # si hay un nuevo seleccionado distinto del anterior, persistimos y rerun
                    if new_selid is not None and new_selid != current_selid:
                        _set_selid(int(new_selid))
                    elif new_selid is None and current_selid is not None:
                        _clear_selid()

            # ================== /CALENDARIO BONITO ==================



        # --- 6) Descargar .ics (no se escribe archivo, solo memoria) ---
        def make_ics(df):
            lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//GestionVentas//CalendarioCobros//ES"]
            for _, r in df.iterrows():
                val = r["Fecha"]
                if hasattr(val, "date"):   # Timestamp/datetime
                    f = val.date()
                elif isinstance(val, _date):
                    f = val
                else:
                    f = parse_iso_or_today(str(val)).date()
                dtstart = f.strftime("%Y%m%d")                    # evento de día completo
                uid = f"venta{r['VentaID']}-c{r['Cuota']}-{dtstart}@gestion"
                titulo = f"COBRO #{r['VentaID']} • Cuota {r['Cuota']} • {r['Cliente']}"
                desc = f"Vendedor: {r['Vendedor']} | {r['Desc']} | Monto: {fmt_money_up(float(r['Monto']))}"
                lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTART;VALUE=DATE:{dtstart}", f"SUMMARY:{titulo}", f"DESCRIPTION:{desc}", "END:VEVENT"]
            lines.append("END:VCALENDAR")
            return "\n".join(lines)

        ics_text = make_ics(cal_df)
        st.download_button("⬇️ Descargar calendario (.ics)", data=ics_text, file_name="calendario_cobros.ics", mime="text/calendar")

# ========= BACKUP A GITHUB (JSON + CSVs) =========
import base64, json, requests, io, zipfile
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

def _gh_headers():
    return {
        "Authorization": f"Bearer {st.secrets['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }

def _gh_api_path(path_in_repo):
    repo   = st.secrets["GH_REPO"]
    branch = st.secrets.get("GH_BRANCH", "main")
    return f"https://api.github.com/repos/{repo}/contents/{path_in_repo}", branch

def gh_upsert_file(path_in_repo: str, content_bytes: bytes, commit_msg: str) -> str:
    api, branch = _gh_api_path(path_in_repo)

    # Buscar SHA si el archivo ya existe (para update)
    r = requests.get(api, headers=_gh_headers(), params={"ref": branch})
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": commit_msg,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r2 = requests.put(api, headers=_gh_headers(), json=payload, timeout=30)
    r2.raise_for_status()
    return r2.json()["content"]["html_url"]

def _json_default(o):
    # Por si aparece algo no serializable (Timestamp, date, Decimal…)
    try:
        return o.isoformat()
    except Exception:
        return str(o)

def _snapshot_dataframes():
    """Arma los DataFrames crudos que vamos a subir (operations + installments)."""
    ops = list_operations(user_scope_filters({})) or []

    rows_iv, rows_ic = [], []
    for op in ops:
        vid = op["id"]
        # Cuotas de VENTA
        for c in (list_installments(vid, is_purchase=False) or []):
            r = {"operation_id": vid}
            r.update(c)
            rows_iv.append(r)
        # Cuotas de COMPRA (inversor)
        for c in (list_installments(vid, is_purchase=True) or []):
            r = {"operation_id": vid}
            r.update(c)
            rows_ic.append(r)

    df_ops = pd.DataFrame(ops)
    df_iv  = pd.DataFrame(rows_iv)  # installments_venta
    df_ic  = pd.DataFrame(rows_ic)  # installments_compra
    return df_ops, df_iv, df_ic

def backup_snapshot_to_github():
    """Sube 1 JSON y 3 CSVs al repo (se sobreescriben en /data). Devuelve URLs."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit_msg = f"backup: snapshot {ts}"

    df_ops, df_iv, df_ic = _snapshot_dataframes()

    # JSON único con todo
    json_blob = {
        "generated_at": ts,
        "operations": df_ops.to_dict(orient="records"),
        "installments_venta": df_iv.to_dict(orient="records"),
        "installments_compra": df_ic.to_dict(orient="records"),
    }
    json_bytes = json.dumps(json_blob, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")

    urls = {}
    urls["snapshot.json"] = gh_upsert_file("data/snapshot.json", json_bytes, commit_msg)

    # CSVs (útiles para Excel/Sheets)
    urls["operations.csv"]          = gh_upsert_file("data/operations.csv", df_ops.to_csv(index=False).encode("utf-8"), commit_msg)
    urls["installments_venta.csv"]  = gh_upsert_file("data/installments_venta.csv", df_iv.to_csv(index=False).encode("utf-8"), commit_msg)
    urls["installments_compra.csv"] = gh_upsert_file("data/installments_compra.csv", df_ic.to_csv(index=False).encode("utf-8"), commit_msg)

    return urls

# ===== Exportar listados (Cuotas 2+ y Un pago 1) a CSV y subirlos al repo =====
def _build_listado_rows(ops):
    """Devuelve filas tipo listado (VENTA y COMPRA) con números crudos (sin $) para Sheets."""
    rows = []
    for op in ops:
        total_cuotas = int(op.get("O") or 0)
        venta_total  = float(op.get("N") or 0.0)
        price        = float(op.get("purchase_price") or 0.0)
        costo_neto   = float(op.get("L") or 0.0)
        com_total    = float(op.get("comision") or 0.0)
        com_x        = (com_total / total_cuotas) if total_cuotas > 0 else 0.0

        # pagos
        pagado_venta   = sum_paid(op["id"], is_purchase=False)
        pagadas_venta  = count_paid_installments(op["id"], is_purchase=False)
        pend_venta_cnt = max(total_cuotas - pagadas_venta, 0)
        pendiente_venta = venta_total - pagado_venta

        pagado_compra   = sum_paid(op["id"], is_purchase=True)
        pagadas_compra  = count_paid_installments(op["id"], is_purchase=True)
        pend_compra_cnt = max(total_cuotas - pagadas_compra, 0)
        pendiente_compra = price - pagado_compra
        estado_compra    = "CANCELADO" if abs(pagado_compra - price) < 0.01 else "VIGENTE"

        fecha_mostrar = parse_iso_or_today(op.get("sale_date") or op.get("created_at")).strftime("%d/%m/%Y")
        ganancia = (venta_total - price - com_total)

        # VENTA
        rows.append({
            "Tipo":"VENTA","ID venta":op["id"],"Descripción":op.get("descripcion"),
            "Cliente":op.get("cliente"),"Proveedor":op.get("proveedor") or "",
            "Inversor":op.get("nombre"),"Vendedor":op.get("zona"),
            "Revendedor": op.get("revendedor") or "",
            "Costo": round(costo_neto),
            "Precio Compra": "",  # en VENTA va vacío
            "Venta": round(venta_total),
            "Comisión": round(com_total),
            "Comisión x cuota": round(com_x),
            "Cuotas": total_cuotas,
            "Cuotas pendientes": pend_venta_cnt,
            "$ Pagado": round(pagado_venta),
            "$ Pendiente": round(pendiente_venta),
            "Estado": op.get("estado"),
            "Fecha de cobro": fecha_mostrar,
            "Ganancia": round(ganancia),
        })
        # COMPRA
        rows.append({
            "Tipo":"COMPRA","ID venta":op["id"],"Descripción":"↑",
            "Cliente":"↑","Proveedor":op.get("proveedor") or "",
            "Inversor":op.get("nombre"),"Vendedor":"↑",
            "Revendedor": "↑",
            "Costo":"↑",
            "Precio Compra": round(price),
            "Venta":"↑",
            "Comisión":"↑",
            "Comisión x cuota":"↑",
            "Cuotas": total_cuotas,
            "Cuotas pendientes": pend_compra_cnt,
            "$ Pagado": round(pagado_compra),
            "$ Pendiente": round(pendiente_compra),
            "Estado": estado_compra,
            "Fecha de cobro": fecha_mostrar,
            "Ganancia":"↑",
        })
    return rows

def _build_listado_dataframes_for_export():
    filtros = user_scope_filters({})
    ops_all = list_operations(filtros) or []
    ops_multi = [op for op in ops_all if int(op.get("O") or 0) >= 2]
    ops_uno   = [op for op in ops_all if int(op.get("O") or 0) == 1]

    cols_order = ["Tipo","ID venta","Descripción","Cliente","Proveedor","Inversor","Vendedor","Revendedor","Costo",
                  "Precio Compra","Venta","Comisión","Comisión x cuota","Cuotas",
                  "Cuotas pendientes","$ Pagado","$ Pendiente","Estado","Fecha de cobro","Ganancia"]

    import pandas as pd
    df_multi = pd.DataFrame(_build_listado_rows(ops_multi))
    df_uno   = pd.DataFrame(_build_listado_rows(ops_uno))
    if not df_multi.empty: df_multi = df_multi[cols_order]
    if not df_uno.empty:   df_uno   = df_uno[cols_order]
    return df_multi, df_uno

# >>> Actualiza tu backup para subir también los listados:
def backup_snapshot_to_github():
    """Sube snapshot.json + CSVs crudos + listados_multi/unopago a /data del repo."""
    from datetime import datetime, timezone
    import json, pandas as pd

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit_msg = f"backup: snapshot {ts}"

    # lo que ya subías:
    df_ops, df_iv, df_ic = _snapshot_dataframes()
    json_blob = {
        "generated_at": ts,
        "operations": df_ops.to_dict(orient="records"),
        "installments_venta": df_iv.to_dict(orient="records"),
        "installments_compra": df_ic.to_dict(orient="records"),
    }
    json_bytes = json.dumps(json_blob, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")

    urls = {}
    urls["snapshot.json"] = gh_upsert_file("data/snapshot.json", json_bytes, commit_msg)
    urls["operations.csv"]          = gh_upsert_file("data/operations.csv", df_ops.to_csv(index=False).encode("utf-8"), commit_msg)
    urls["installments_venta.csv"]  = gh_upsert_file("data/installments_venta.csv", df_iv.to_csv(index=False).encode("utf-8"), commit_msg)
    urls["installments_compra.csv"] = gh_upsert_file("data/installments_compra.csv", df_ic.to_csv(index=False).encode("utf-8"), commit_msg)

    # NUEVO: subir listados listos para Sheets
    df_multi, df_uno = _build_listado_dataframes_for_export()
    urls["listado_multi.csv"] = gh_upsert_file("data/listado_multi.csv", df_multi.to_csv(index=False).encode("utf-8"), commit_msg)
    urls["listado_uno.csv"]   = gh_upsert_file("data/listado_uno.csv", df_uno.to_csv(index=False).encode("utf-8"), commit_msg)

    return urls


def backup_zip_bytes():
    """Por si querés un ZIP descargable además (opcional)."""
    df_ops, df_iv, df_ic = _snapshot_dataframes()
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("operations.csv", df_ops.to_csv(index=False))
        zf.writestr("installments_venta.csv", df_iv.to_csv(index=False))
        zf.writestr("installments_compra.csv", df_ic.to_csv(index=False))
    mem.seek(0)
    return mem.getvalue()
# ========= /BACKUP A GITHUB =========
