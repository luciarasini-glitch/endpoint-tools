import streamlit as st
import json
from pathlib import Path
from datetime import datetime

REPORTS_DIR = Path(__file__).parent.parent / "reports"
META_FILE   = REPORTS_DIR / ".meta.json"

# ── Registro de reportes conocidos ───────────────────────────────────────────
# Cada entry describe un reporte: qué archivo genera, nombre visible, descripción.
REPORT_CATALOG = {
    "laptops_in_use_sin_owner": {
        "title":       "Laptops sin owner asignado",
        "description": "Equipos de tipo Laptop con estado In Use que no tienen un owner asignado en JumpCloud Asset Management.",
        "icon":        "💻",
    },
    "trend_endpoints_sin_conexion_10d": {
        "title":       "Endpoints sin conexión hace +10 días",
        "description": "Endpoints registrados en Trend Vision One que no se han conectado en los últimos 10 días.",
        "icon":        "📡",
    },
    "trend_not_in_jumpcloud": {
        "title":       "Trend sin JumpCloud",
        "description": "Endpoints presentes en Trend Vision One que no se encuentran registrados en JumpCloud.",
        "icon":        "🔍",
    },
    "jumpcloud_not_in_trend": {
        "title":       "JumpCloud sin Trend",
        "description": "Laptops In Use registradas en JumpCloud que no tienen agente en Trend Vision One.",
        "icon":        "⚠️",
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_meta() -> dict:
    if META_FILE.exists():
        try:
            return json.loads(META_FILE.read_text())
        except Exception:
            pass
    return {}


def find_latest(report_key: str):
    """Return the most recent file whose stem starts with report_key."""
    files = sorted(REPORTS_DIR.glob(f"{report_key}*.xlsx"), reverse=True)
    return files[0] if files else None


def format_ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso


# ── UI ────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Endpoint Security Agent",
    page_icon="🛡️",
    layout="wide",
)

# Header
col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.markdown("## 🛡️")
with col_title:
    st.markdown("## Endpoint Security Agent")
    st.caption("Reportes automáticos de seguridad — Cashea")

st.divider()

meta = load_meta()

if not REPORT_CATALOG:
    st.info("No hay reportes configurados aún.")
else:
    for key, info in REPORT_CATALOG.items():
        latest = find_latest(key)
        report_meta = meta.get(key, {})
        last_run = format_ts(report_meta.get("generated_at", "")) if report_meta else None

        with st.container(border=True):
            col_info, col_action = st.columns([7, 3])

            with col_info:
                st.markdown(f"### {info['icon']} {info['title']}")
                st.caption(info["description"])

                if last_run:
                    row_count = report_meta.get("row_count")
                    count_str = f" · **{row_count} equipos**" if row_count else ""
                    st.markdown(f"🕐 Última generación: **{last_run}**{count_str}")
                else:
                    st.markdown("🕐 Nunca generado")

            with col_action:
                st.markdown("<br>", unsafe_allow_html=True)
                if latest:
                    with open(latest, "rb") as f:
                        st.download_button(
                            label="⬇️ Descargar Excel",
                            data=f.read(),
                            file_name=latest.name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    st.caption(f"📄 `{latest.name}`")
                else:
                    st.button("Sin archivo disponible", disabled=True, use_container_width=True)
                    st.caption("El cron aún no ha corrido.")

st.divider()
st.caption("Los reportes se generan automáticamente cada lunes a las 10:00 AM (GMT-3).")
