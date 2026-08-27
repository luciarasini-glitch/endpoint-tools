"""Slack notifier — sube el reporte .xlsx y envía un mensaje de resumen."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import httpx

from agent.core.config import get_settings

log = logging.getLogger(__name__)

ICONS = {
    "laptops_in_use_sin_owner":        "💻",
    "trend_endpoints_sin_conexion_10d": "📡",
    "trend_not_in_jumpcloud":           "🔍",
    "jumpcloud_not_in_trend":           "⚠️",
}

TITLES = {
    "laptops_in_use_sin_owner":        "Laptops sin owner asignado — JumpCloud",
    "trend_endpoints_sin_conexion_10d": "Endpoints sin conexión +10 días — Trend Vision One",
    "trend_not_in_jumpcloud":           "Endpoints en Trend que no están en JumpCloud",
    "jumpcloud_not_in_trend":           "Laptops en JumpCloud que no están en Trend",
}


def _upload_file(bot_token: str, channel_id: str, file_path: Path, initial_comment: str) -> bool:
    """Sube un archivo a Slack usando files.upload v2 (getUploadURLExternal + completeUploadExternal)."""
    file_size = file_path.stat().st_size
    headers = {"Authorization": f"Bearer {bot_token}"}

    # Step 1: obtener URL de upload
    try:
        r1 = httpx.post(
            "https://slack.com/api/files.getUploadURLExternal",
            headers=headers,
            data={"filename": file_path.name, "length": file_size},
            timeout=15,
        )
        r1.raise_for_status()
        d1 = r1.json()
        if not d1.get("ok"):
            log.error("files.getUploadURLExternal error: %s", d1.get("error"))
            return False
        upload_url = d1["upload_url"]
        file_id    = d1["file_id"]
    except Exception as exc:
        log.error("Error obteniendo URL de upload: %s", exc)
        return False

    # Step 2: subir el contenido binario
    try:
        with open(file_path, "rb") as fh:
            r2 = httpx.post(upload_url, content=fh.read(), timeout=30)
        r2.raise_for_status()
    except Exception as exc:
        log.error("Error subiendo archivo a Slack: %s", exc)
        return False

    # Step 3: completar y publicar en el canal
    try:
        r3 = httpx.post(
            "https://slack.com/api/files.completeUploadExternal",
            headers=headers,
            json={
                "files": [{"id": file_id}],
                "channel_id": channel_id,
                "initial_comment": initial_comment,
            },
            timeout=15,
        )
        r3.raise_for_status()
        d3 = r3.json()
        if not d3.get("ok"):
            log.error("files.completeUploadExternal error: %s", d3.get("error"))
            return False
        return True
    except Exception as exc:
        log.error("Error completando upload: %s", exc)
        return False


def notify(
    report_key: str,
    row_count: int,
    output_path: Path,
    extra_lines: list[str] | None = None,
) -> None:
    if os.environ.get("SKIP_SLACK_NOTIFY") == "1":
        return
    settings = get_settings()
    bot_token  = settings.slack_bot_token.strip()  if hasattr(settings, "slack_bot_token")  else ""
    channel_id = settings.slack_channel_id.strip() if hasattr(settings, "slack_channel_id") else ""
    webhook_url = settings.slack_webhook_url.strip() if hasattr(settings, "slack_webhook_url") else ""

    icon  = ICONS.get(report_key, "📋")
    title = TITLES.get(report_key, report_key)
    now   = datetime.now().strftime("%d/%m/%Y %H:%M")

    lines = [f"*{icon} {title}*", f"🕐 Generado: {now}", f"📊 Total registros: *{row_count}*"]
    if extra_lines:
        lines += extra_lines
    summary_text = "\n".join(lines)

    # Preferir upload del archivo si tenemos bot token + channel
    if bot_token and channel_id and output_path.exists():
        success = _upload_file(bot_token, channel_id, output_path, summary_text)
        if success:
            log.info("Archivo subido a Slack para %s", report_key)
            return
        log.warning("Upload fallido, intentando con webhook de texto...")

    # Fallback: mensaje de texto por webhook
    if webhook_url:
        fallback_lines = lines + [f"📁 Archivo: `{output_path.name}`",
                                  "_El reporte está disponible en el dashboard: http://localhost:8503_"]
        try:
            resp = httpx.post(webhook_url, json={"text": "\n".join(fallback_lines)}, timeout=10)
            resp.raise_for_status()
            log.info("Notificación Slack (texto) enviada para %s", report_key)
        except Exception as exc:
            log.error("Error enviando notificación Slack: %s", exc)
        return

    log.warning("SLACK_BOT_TOKEN / SLACK_WEBHOOK_URL no configurados — notificación omitida.")
