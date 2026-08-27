from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

try:
    from ui.backend import BACKEND_URL
except ModuleNotFoundError:
    from backend import BACKEND_URL

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
BACKGROUND_IMAGE = ASSETS_DIR / "cashea-bg.png"


def fetch(path: str, method: str = "GET", params: dict | None = None, timeout: int = 20) -> dict | list:
    response = requests.request(method, f"{BACKEND_URL}{path}", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60, show_spinner=False)
def cached_fetch(path: str, params_key: tuple[tuple[str, str], ...] = (), timeout: int = 60) -> dict | list:
    params = dict(params_key)
    return fetch(path, params=params or None, timeout=timeout)


def image_to_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def sync_scope_label(scope: str | None) -> str:
    if scope == "inventory":
        return "inventario"
    if scope == "alerts":
        return "alertas"
    return "general"


def sync_elapsed_text(started_at: str | None) -> str:
    if not started_at:
        return ""
    try:
        normalized = started_at.replace("Z", "+00:00")
        started = datetime.fromisoformat(normalized)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
        seconds = max(int(elapsed.total_seconds()), 0)
    except ValueError:
        return ""
    minutes, rem = divmod(seconds, 60)
    return f"{minutes}m {rem:02d}s"


def filter_rows(rows: list[dict], needle: str, columns: tuple[str, ...] | None = None) -> list[dict]:
    needle = needle.strip()
    if not needle:
        return rows
    needle_lc = needle.casefold()
    filtered_rows = []
    for row in rows:
        values = (row.get(column) for column in columns) if columns else row.values()
        haystack = " ".join(str(value).casefold() for value in values if value not in (None, ""))
        if needle_lc in haystack:
            filtered_rows.append(row)
    return filtered_rows


def render_csv_download(rows: list[dict], filename: str, key: str) -> None:
    if not rows:
        return
    csv_data = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Exportar CSV",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def render_trend_inventory() -> None:
    search = st.text_input("Buscar en equipos con Trend", key="trend_machine_search")
    try:
        with st.spinner("Cargando inventario de Trend..."):
            params_key = (("search", search),) if search else ()
            rows = cached_fetch("/api/v1/trend/devices", params_key=params_key)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar el inventario de Trend: {exc}")
        return

    rows = rows if isinstance(rows, list) else []

    st.markdown(
        """
        <div class="summary-card">
          <h3 style="margin-top:0; margin-bottom:0.35rem;">TrendAI Vision One</h3>
          <p style="margin-bottom:0;">
            Inventario de máquinas administradas en Trend Vision One.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"{len(rows)} máquinas con Trend")
    if rows:
        render_csv_download(rows, "trend_inventory.csv", "trend_inventory_export_csv")
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No hay máquinas con Trend para los filtros actuales.")


def render_inventory() -> None:
    params_key: tuple[tuple[str, str], ...] = ()
    if st.session_state.pop("inventory_force_reload", False):
        params_key = (("force", "true"),)
    try:
        with st.spinner("Cargando inventario..."):
            rows = cached_fetch("/api/v1/jumpcloud/inventory", params_key=params_key, timeout=180)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar inventario: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    search = st.text_input("Buscar en inventario", key="inventory_search")
    filtered = filter_rows(rows, search)
    visible_rows = [
        {key: value for key, value in row.items() if key not in {"User ID", "Display name"}}
        for row in filtered
    ]
    st.caption(f"{len(filtered)} equipos visibles")
    render_csv_download(visible_rows, "inventario.csv", "inventory_export_csv")
    st.dataframe(visible_rows, use_container_width=True, hide_index=True)


def render_apps() -> None:
    try:
        rows = cached_fetch("/api/v1/jumpcloud/apps")
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar apps: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    search = st.text_input("Buscar en apps", key="apps_search")
    filtered = filter_rows(rows, search)
    st.caption(f"{len(filtered)} registros de apps")
    render_csv_download(filtered, "apps.csv", "apps_export_csv")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


def render_cloudflare() -> None:
    params_key: tuple[tuple[str, str], ...] = ()
    if st.session_state.pop("cloudflare_force_reload", False):
        params_key = (("force", "true"),)
    try:
        with st.spinner("Cargando Cloudflare..."):
            rows = cached_fetch("/api/v1/jumpcloud/cloudflare", params_key=params_key, timeout=180)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar Cloudflare: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    installed_count = sum(1 for row in rows if row.get("Cloudflare"))
    macos_rows = [row for row in rows if row.get("Sistema operativo") == "macOS"]
    windows_rows = [row for row in rows if row.get("Sistema operativo") == "Windows"]
    macos_count = len(macos_rows)
    windows_count = len(windows_rows)
    macos_installed_count = sum(1 for row in macos_rows if row.get("Cloudflare"))
    windows_installed_count = sum(1 for row in windows_rows if row.get("Cloudflare"))
    total_count = len(rows)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Cloudflare instalado", installed_count)
    metric_cols[1].metric("Endpoints", total_count)
    metric_cols[2].metric("macOS", f"{macos_installed_count}/{macos_count}")
    metric_cols[3].metric("Windows", f"{windows_installed_count}/{windows_count}")

    search = st.text_input(
        "Buscar en Cloudflare",
        key="cloudflare_search",
        placeholder="Usuario, correo o endpoint",
    )
    filtered = filter_rows(rows, search, columns=("Usuario", "Correo", "Endpoint", "Sistema operativo"))
    st.caption(f"{len(filtered)} endpoints visibles")
    render_csv_download(filtered, "cloudflare.csv", "cloudflare_export_csv")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


def render_phones() -> None:
    params_key: tuple[tuple[str, str], ...] = ()
    if st.session_state.pop("phones_force_reload", False):
        params_key = (("force", "true"),)
    try:
        with st.spinner("Cargando dispositivos Mobile desde Asset Management..."):
            rows = cached_fetch("/api/v1/jumpcloud/phones", params_key=params_key, timeout=180)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar phones: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    search = st.text_input("Buscar en phones", key="phones_search")
    filtered = filter_rows(rows, search)
    st.caption(f"{len(filtered)} dispositivos Mobile visibles")
    render_csv_download(filtered, "phones.csv", "phones_export_csv")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


def render_ai_saas_management() -> None:
    search = st.text_input("Buscar en AI & SaaS Management", key="ai_saas_search")
    try:
        with st.spinner("Cargando AI & SaaS Management..."):
            params_key = (("search", search),) if search else ()
            rows = cached_fetch("/api/v1/jumpcloud/ai-saas-management", params_key=params_key, timeout=120)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo cargar AI & SaaS Management: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    st.caption(f"{len(rows)} cuentas descubiertas")
    if rows:
        render_csv_download(rows, "ai_saas_management.csv", "ai_saas_export_csv")
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No hay datos para AI & SaaS Management con la configuracion actual.")


def render_alerts() -> None:
    search = st.text_input("Buscar alertas", key="alerts_search")
    severity = st.selectbox("Severity", options=["", "critical", "high", "medium", "low", "info"], key="alerts_severity")
    params_key = tuple(
        (key, value)
        for key, value in (
            ("search", search),
            ("severity", severity),
        )
        if value
    )

    try:
        rows = cached_fetch("/api/v1/alerts", params_key=params_key)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudieron cargar alertas: {exc}")
        return

    rows = rows if isinstance(rows, list) else []
    st.caption(f"{len(rows)} alertas")
    if not rows:
        st.info("No hay alertas para los filtros actuales.")
        return

    summary_rows = [
        {
            "id": row["id"],
            "hostname": row.get("device_name") or "unknown",
            "usuario": row.get("logon_user") or row.get("user_display_name") or row.get("user_email") or row.get("user_id") or "unknown",
            "severidad": row.get("severity") or "unknown",
            "fecha": row.get("detected_at") or "unknown",
            "evento": row.get("event_name") or row.get("title") or row.get("rule_name") or "unknown",
            "source": row.get("source") or "unknown",
            "parentName": row.get("parent_name") or "unknown",
        }
        for row in rows
    ]
    summary_df = pd.DataFrame(
        [
            {
                "id": row["id"],
                "hostname": row["hostname"],
                "usuario": row["usuario"],
                "severidad": row["severidad"],
                "fecha": row["fecha"],
                "evento": row["evento"],
                "source": row["source"],
                "parentName": row["parentName"],
            }
            for row in summary_rows
        ]
    )
    render_csv_download(
        summary_df[["hostname", "usuario", "severidad", "fecha", "evento", "source", "parentName"]].to_dict(orient="records"),
        "alertas.csv",
        "alerts_export_csv",
    )
    event = st.dataframe(
        summary_df[["hostname", "usuario", "severidad", "fecha", "evento", "source", "parentName"]],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="alerts_table",
    )
    selected_rows = event.selection.rows if event and event.selection else []
    selected_index = selected_rows[0] if selected_rows else 0
    selected_id = summary_df.iloc[selected_index]["id"]
    selected_summary = next((row for row in rows if row["id"] == selected_id), None)
    if selected_summary is None:
        st.info("No se pudo encontrar la alerta seleccionada.")
        return

    st.subheader("Detalle de alerta")
    d1, d2, d3, d4 = st.columns(4)
    d1.markdown(f"**Hostname:** {selected_summary.get('device_name') or 'unknown'}")
    d2.markdown(
        f"**Usuario:** {selected_summary.get('logon_user') or selected_summary.get('user_display_name') or selected_summary.get('user_email') or selected_summary.get('user_id') or 'unknown'}"
    )
    d3.markdown(f"**Severidad:** {selected_summary.get('severity') or 'unknown'}")
    d4.markdown(f"**Estado:** {selected_summary.get('status') or 'unknown'}")

    st.markdown(f"**Titulo:** {selected_summary.get('title') or 'unknown'}")
    st.markdown(f"**Rule name:** {selected_summary.get('rule_name') or 'unknown'}")
    st.markdown(f"**Source:** {selected_summary.get('source') or 'unknown'}")
    st.markdown(f"**Detected at:** {selected_summary.get('detected_at') or 'unknown'}")

    try:
        detail = fetch(f"/api/v1/alerts/{selected_id}", timeout=60)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"No se pudo cargar el detalle completo de la alerta: {exc}")
        return

    st.subheader("Detalles completos")
    st.json(detail)


st.set_page_config(page_title="Endpoint Security Dashboard", layout="wide")
background_data_uri = image_to_data_uri(BACKGROUND_IMAGE)

style_block = """
    <style>
    .stApp {
        background:
            linear-gradient(135deg, rgba(0, 0, 0, 0.28) 0%, rgba(0, 0, 0, 0.08) 38%, rgba(255, 230, 0, 0.15) 100%),
            radial-gradient(circle at 12% 18%, rgba(0, 255, 225, 0.18) 0%, rgba(0, 255, 225, 0) 22%),
            url("__BG__");
        background-size: cover;
        background-position: center center;
        background-attachment: fixed;
        color: #111111;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        position: relative;
        z-index: 1;
    }
    .brand-shell {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 1.5rem;
    }
    .brand-badge {
        width: 250px;
        height: 86px;
        border-radius: 22px;
        border: 1px solid rgba(0, 0, 0, 0.12);
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.15);
        background:
            linear-gradient(135deg, rgba(0, 0, 0, 0.18), rgba(0, 0, 0, 0.02)),
            url("__BG__");
        background-size: cover;
        background-position: center center;
    }
    .hero-panel {
        background: rgba(255, 247, 102, 0.55);
        border: 1px solid rgba(17, 17, 17, 0.18);
        border-radius: 24px;
        padding: 1.25rem 1.4rem 1rem 1.4rem;
        margin-bottom: 1.15rem;
        backdrop-filter: blur(6px);
        box-shadow: 0 14px 40px rgba(0, 0, 0, 0.14);
    }
    .hero-title {
        font-size: 3rem;
        line-height: 0.95;
        font-weight: 900;
        color: #0b0b0b;
        margin: 0;
        letter-spacing: -0.04em;
        text-transform: uppercase;
    }
    .summary-card {
        background: rgba(255, 252, 184, 0.72);
        border: 1px solid rgba(17, 17, 17, 0.16);
        border-radius: 18px;
        padding: 1rem 1.1rem;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.12);
        margin-top: 1rem;
        margin-bottom: 1rem;
    }
    div[data-testid="stMetric"] {
        background: rgba(255, 250, 201, 0.86);
        border: 1px solid rgba(17, 17, 17, 0.14);
        border-radius: 18px;
        padding: 1rem 1.1rem;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.10);
        backdrop-filter: blur(4px);
    }
    div[data-testid="stMetricLabel"],
    div[data-testid="stMetricValue"] {
        color: #111111;
    }
    div[data-testid="stDataFrame"] {
        background: rgba(255, 255, 248, 0.90);
        border: 1px solid rgba(17, 17, 17, 0.12);
        border-radius: 18px;
        padding: 0.35rem;
        box-shadow: 0 14px 34px rgba(0, 0, 0, 0.10);
    }
    div[data-testid="stAlert"] {
        border-radius: 16px;
        border: 1px solid rgba(17, 17, 17, 0.10);
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
    }
    h3 {
        color: #111111;
    }
    </style>
"""

st.markdown(style_block.replace("__BG__", background_data_uri), unsafe_allow_html=True)

st.markdown(
    """
    <div class="brand-shell">
      <div class="brand-badge"></div>
    </div>
    <div class="hero-panel">
      <h1 class="hero-title">Endpoint Security Dashboard</h1>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.fragment(run_every="5s")
def render_sync_status() -> None:
    try:
        status = fetch("/api/v1/sync/status")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backend unavailable or no snapshot exists yet: {exc}")
        return

    if status.get("sync_in_progress"):
        started_at = status.get("sync_started_at") or "N/A"
        scope_label = sync_scope_label(status.get("sync_scope"))
        elapsed = sync_elapsed_text(status.get("sync_started_at"))
        if elapsed:
            st.info(f"Sync de {scope_label} en progreso desde {started_at} ({elapsed})")
        else:
            st.info(f"Sync de {scope_label} en progreso desde {started_at}")
    elif status.get("last_sync_error"):
        st.error(f"Ultimo error de sync: {status['last_sync_error']}")


with st.sidebar:
    st.markdown("### Inventario")
    current_view = st.radio(
        "Vista",
        options=["TrendAI Vision One", "Inventario", "Apps", "Cloudflare", "Phones", "AI & SaaS Management", "Alertas"],
        index=0,
        label_visibility="collapsed",
    )

render_sync_status()

toolbar = st.columns([1, 1, 1, 1, 1])
if current_view == "Inventario":
    with toolbar[0]:
        if st.button("Recargar inventario", type="primary"):
            cached_fetch.clear()
            st.session_state["inventory_force_reload"] = True
            st.rerun()
    with toolbar[1]:
        if st.button("Sync Trend"):
            try:
                fetch("/api/v1/sync/inventory", method="POST", params={"force": "true"}, timeout=10)
                st.success("Sync de Trend iniciado en segundo plano.")
            except Exception as exc:
                st.error(f"Sync failed: {exc}")
elif current_view == "Alertas":
    with toolbar[0]:
        if st.button("Sync alertas", type="primary"):
            try:
                fetch("/api/v1/sync/alerts", method="POST", params={"force": "true"}, timeout=10)
                st.success("Sync de alertas iniciado en segundo plano.")
            except Exception as exc:
                st.error(f"Sync failed: {exc}")
elif current_view == "Apps":
    with toolbar[0]:
        if st.button("Recargar apps", type="primary"):
            st.rerun()
elif current_view == "Cloudflare":
    with toolbar[0]:
        if st.button("Recargar Cloudflare", type="primary"):
            cached_fetch.clear()
            st.session_state["cloudflare_force_reload"] = True
            st.rerun()
elif current_view == "Phones":
    with toolbar[0]:
        if st.button("Recargar phones", type="primary"):
            cached_fetch.clear()
            st.session_state["phones_force_reload"] = True
            st.rerun()
elif current_view == "AI & SaaS Management":
    with toolbar[0]:
        if st.button("Recargar AI & SaaS", type="primary"):
            st.rerun()
else:
    with toolbar[0]:
        if st.button("Sync inventario", type="primary"):
            try:
                fetch("/api/v1/sync/inventory", method="POST", params={"force": "true"}, timeout=10)
                st.success("Sync de inventario iniciado en segundo plano.")
            except Exception as exc:
                st.error(f"Sync failed: {exc}")
    with toolbar[1]:
        if st.button("Sync alertas"):
            try:
                fetch("/api/v1/sync/alerts", method="POST", params={"force": "true"}, timeout=10)
                st.success("Sync de alertas iniciado en segundo plano.")
            except Exception as exc:
                st.error(f"Sync failed: {exc}")

if current_view == "TrendAI Vision One":
    render_trend_inventory()
elif current_view == "Inventario":
    render_inventory()
elif current_view == "Apps":
    render_apps()
elif current_view == "Cloudflare":
    render_cloudflare()
elif current_view == "Phones":
    render_phones()
elif current_view == "AI & SaaS Management":
    render_ai_saas_management()
elif current_view == "Alertas":
    render_alerts()
