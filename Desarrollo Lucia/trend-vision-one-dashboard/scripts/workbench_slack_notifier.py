from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import sanitize_text
from app.services.normalizer import _extract_workbench_device_id, _extract_workbench_host, _items


LOGGER = logging.getLogger("workbench_slack_notifier")
DEFAULT_STATE_PATH = Path("data/workbench_slack_notifier_state.json")
DEFAULT_POLL_SECONDS = 120
MAX_SLACK_TEXT_LENGTH = 2900


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def load_local_env() -> None:
    load_env_file(PROJECT_ROOT / ".env", override=False)
    load_env_file(PROJECT_ROOT / ".env.local", override=True)


def pick_text(item: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = sanitize_text(value)
        if text:
            return text
    return default


def truncate(value: str, limit: int = MAX_SLACK_TEXT_LENGTH) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def alert_key(item: dict[str, Any]) -> str:
    explicit_id = pick_text(item, "id", "alertId", "workbenchId", "modelId")
    if explicit_id:
        return explicit_id
    serialized = json.dumps(item, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def alert_timestamp(item: dict[str, Any]) -> str:
    return pick_text(
        item,
        "createdDateTime",
        "createdAt",
        "updatedDateTime",
        "detectedDateTime",
        "firstObservedDateTime",
        default="",
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent_alerts": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("State file could not be read; starting with an empty state: %s", path)
        return {"sent_alerts": {}}
    if not isinstance(state, dict):
        return {"sent_alerts": {}}
    sent_alerts = state.get("sent_alerts")
    if not isinstance(sent_alerts, dict):
        state["sent_alerts"] = {}
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def prune_state(state: dict[str, Any], *, max_sent_alerts: int) -> None:
    sent_alerts = state.get("sent_alerts")
    if not isinstance(sent_alerts, dict) or len(sent_alerts) <= max_sent_alerts:
        return
    sorted_items = sorted(sent_alerts.items(), key=lambda item: str(item[1]))
    state["sent_alerts"] = dict(sorted_items[-max_sent_alerts:])


def slack_message(item: dict[str, Any]) -> dict[str, Any]:
    key = alert_key(item)
    title = pick_text(item, "title", "alertName", "description", default=key)
    severity = pick_text(item, "severity", "riskLevel", default="unknown")
    status = pick_text(item, "status", "investigationStatus", default="unknown")
    investigation_status = pick_text(item, "investigationStatus", default="")
    score = pick_text(item, "score", "riskScore", default="")
    created_at = alert_timestamp(item) or "unknown"
    model = pick_text(item, "model", "modelName", "ruleName", "detectionName", default="")
    device_name = _extract_workbench_host(item) or ""
    device_id = _extract_workbench_device_id(item) or ""
    url = pick_text(item, "url", "link", "workbenchLink", "investigationLink", default="")

    fields = [
        f"*Alert ID:*\n`{key}`",
        f"*Severity:*\n{severity}",
        f"*Status:*\n{status}",
        f"*Created:*\n{created_at}",
    ]
    if investigation_status and investigation_status != status:
        fields.append(f"*Investigation:*\n{investigation_status}")
    if score:
        fields.append(f"*Score:*\n{score}")
    if device_name:
        fields.append(f"*Host:*\n{device_name}")
    if device_id:
        fields.append(f"*Device ID:*\n`{device_id}`")
    if model:
        fields.append(f"*Model:*\n{model}")

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": truncate(f"{key} | {severity.title()} | {model or title}", 140),
                "emoji": False,
            },
        },
        {"type": "section", "fields": [{"type": "mrkdwn", "text": field} for field in fields[:10]]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Description:*\n{truncate(title, 700)}"}},
    ]
    if url:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Link:*\n<{url}|Open in Trend Vision One>"}})

    fallback = truncate(
        f"Trend Workbench alert: {key} | severity={severity} | score={score or 'unknown'} | "
        f"status={status} | model={model or title}"
    )
    return {"text": fallback, "blocks": blocks}


def post_to_slack(webhook_url: str, payload: dict[str, Any], *, dry_run: bool = False) -> None:
    if dry_run:
        LOGGER.info("Dry run: would send Slack message: %s", payload["text"])
        return
    for attempt in range(1, 4):
        try:
            response = httpx.post(webhook_url, json=payload, timeout=30.0)
            response.raise_for_status()
            return
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt == 3:
                raise RuntimeError(f"Slack post failed after {attempt} attempts: {exc.__class__.__name__}") from None
            LOGGER.warning("Slack post failed on attempt %s: %s", attempt, exc.__class__.__name__)
            time.sleep(2**attempt)


def fetch_workbench_alerts() -> tuple[list[dict[str, Any]], int]:
    settings = get_settings()
    client = TrendVisionOneClient(settings)
    payload, issues = client.fetch_collection("workbench_alerts")
    for issue in issues:
        LOGGER.warning("%s: %s", issue.source, issue.message)
    if payload is None:
        return [], len(issues)
    items = _items(payload)
    items.sort(key=alert_timestamp)
    return items, len(issues)


def run_once(
    *,
    webhook_url: str,
    state_path: Path,
    max_sent_alerts: int,
    dry_run: bool,
    send_delay_seconds: float,
) -> int:
    state = load_state(state_path)
    sent_alerts = state.setdefault("sent_alerts", {})
    if not isinstance(sent_alerts, dict):
        sent_alerts = {}
        state["sent_alerts"] = sent_alerts

    alerts, issue_count = fetch_workbench_alerts()
    sent_count = 0
    skipped_count = 0
    for item in alerts:
        key = alert_key(item)
        if key in sent_alerts:
            skipped_count += 1
            continue
        post_to_slack(webhook_url, slack_message(item), dry_run=dry_run)
        LOGGER.info("Sent Workbench alert id=%s dry_run=%s", key, dry_run)
        if not dry_run:
            sent_alerts[key] = datetime.now(timezone.utc).isoformat()
            save_state(state_path, state)
        sent_count += 1
        if send_delay_seconds > 0:
            time.sleep(send_delay_seconds)

    if not dry_run:
        state["last_success_at"] = datetime.now(timezone.utc).isoformat()
        state["last_seen_count"] = len(alerts)
        prune_state(state, max_sent_alerts=max_sent_alerts)
        save_state(state_path, state)
    LOGGER.info(
        "Workbench scan finished: fetched=%s sent=%s already_seen=%s issues=%s",
        len(alerts),
        sent_count,
        skipped_count,
        issue_count,
    )
    return sent_count


def resend_alert_id(*, alert_id: str, webhook_url: str, dry_run: bool) -> None:
    alerts, issue_count = fetch_workbench_alerts()
    for item in alerts:
        if alert_key(item) == alert_id:
            post_to_slack(webhook_url, slack_message(item), dry_run=dry_run)
            LOGGER.info("Re-sent Workbench alert id=%s dry_run=%s issues=%s", alert_id, dry_run, issue_count)
            return
    raise RuntimeError(f"Workbench alert not found in current lookback window: {alert_id}")


def positive_int_env(name: str, default: int) -> int:
    try:
        return max(int(os.environ.get(name, default)), 1)
    except ValueError:
        return default


def positive_float_env(name: str, default: float) -> float:
    try:
        return max(float(os.environ.get(name, default)), 0.0)
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forward Trend Vision One Workbench alerts to Slack.")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch alerts and log what would be sent without posting to Slack.")
    parser.add_argument("--resend-alert-id", default="", help="Send a specific Workbench alert ID even if it is already in state.")
    return parser.parse_args()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    load_local_env()
    args = parse_args()
    configure_logging(os.environ.get("WORKBENCH_SLACK_LOG_LEVEL", "INFO"))
    logging.getLogger("httpx").setLevel(logging.WARNING)

    webhook_url = os.environ.get("SLACK_WORKBENCH_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WORKBENCH_WEBHOOK_URL is not configured.")

    if args.resend_alert_id.strip():
        resend_alert_id(alert_id=args.resend_alert_id.strip(), webhook_url=webhook_url, dry_run=args.dry_run)
        return

    state_path = Path(os.environ.get("WORKBENCH_SLACK_STATE_PATH", str(DEFAULT_STATE_PATH)))
    if not state_path.is_absolute():
        state_path = PROJECT_ROOT / state_path
    poll_seconds = positive_int_env("WORKBENCH_SLACK_POLL_SECONDS", DEFAULT_POLL_SECONDS)
    max_sent_alerts = positive_int_env("WORKBENCH_SLACK_MAX_SENT_ALERTS", 5000)
    send_delay_seconds = positive_float_env("WORKBENCH_SLACK_SEND_DELAY_SECONDS", 0.5)

    while True:
        try:
            run_once(
                webhook_url=webhook_url,
                state_path=state_path,
                max_sent_alerts=max_sent_alerts,
                dry_run=args.dry_run,
                send_delay_seconds=send_delay_seconds,
            )
        except Exception:
            LOGGER.exception("Workbench Slack notifier cycle failed")
            if args.once:
                raise
        if args.once:
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
