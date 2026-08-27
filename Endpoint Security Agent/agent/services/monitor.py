"""Background monitor: polls Trend Vision One periodically and emits AgentEvents."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent.clients.trend_vision_one import TrendVisionOneClient
from agent.core.config import Settings
from agent.models.domain import AgentEvent, AlertRecord

log = logging.getLogger(__name__)


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self._settings = settings
        self._on_event = on_event or self._default_handler
        self._state_path = Path(settings.monitor_state_path)
        self._seen_alert_ids: set[str] = self._load_seen_ids()

    # ── Public ────────────────────────────────────────────────────────────────

    def run_once(self) -> list[AgentEvent]:
        """Single polling cycle. Returns emitted events."""
        events: list[AgentEvent] = []
        try:
            with TrendVisionOneClient(self._settings) as client:
                events += self._check_workbench_alerts(client)
                events += self._check_oat_detections(client)
        except Exception as exc:
            log.error("Monitor cycle failed: %s", exc)
            events.append(AgentEvent(kind="info", summary=f"Monitor error: {exc}", severity="low"))

        for e in events:
            self._on_event(e)

        self._persist_seen_ids()
        return events

    def run_loop(self) -> None:
        """Block forever, polling on the configured interval."""
        interval = self._settings.monitor_poll_interval_seconds
        log.info("Monitor started — interval=%ds", interval)
        while True:
            self.run_once()
            time.sleep(interval)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_workbench_alerts(self, client: TrendVisionOneClient) -> list[AgentEvent]:
        s = self._settings
        path = s.trend_vision_one_workbench_alerts_path or "/v3.0/workbench/alerts"
        events: list[AgentEvent] = []
        try:
            for item in client.fetch_collection(path, {"top": "50"}):
                alert_id = item.get("id") or item.get("workbenchId", "")
                if alert_id in self._seen_alert_ids:
                    continue
                self._seen_alert_ids.add(alert_id)
                alert = AlertRecord(
                    id=alert_id,
                    title=item.get("description") or item.get("title", "Unknown alert"),
                    severity=item.get("severity", "unknown"),
                    source="workbench",
                    detected_at=datetime.now(timezone.utc),
                )
                events.append(
                    AgentEvent(
                        kind="alert_new",
                        summary=f"[Workbench] {alert.severity.upper()} — {alert.title}",
                        severity=self._map_severity(alert.severity),
                        payload=item,
                        timestamp=alert.detected_at,
                    )
                )
        except Exception as exc:
            log.warning("Workbench alerts fetch failed: %s", exc)
        return events

    def _check_oat_detections(self, client: TrendVisionOneClient) -> list[AgentEvent]:
        s = self._settings
        path = s.trend_vision_one_oat_detections_path or "/v3.0/oat/detections"
        events: list[AgentEvent] = []
        try:
            for item in client.fetch_collection(path, {"top": "50"}):
                det_id = item.get("uuid") or item.get("id", "")
                if det_id in self._seen_alert_ids:
                    continue
                self._seen_alert_ids.add(det_id)
                events.append(
                    AgentEvent(
                        kind="alert_new",
                        summary=f"[OAT] {item.get('name', 'Detection')} on {item.get('endpointName', '?')}",
                        severity=self._map_severity(item.get("riskLevel", "low")),
                        payload=item,
                        timestamp=datetime.now(timezone.utc),
                    )
                )
        except Exception as exc:
            log.warning("OAT detections fetch failed: %s", exc)
        return events

    @staticmethod
    def _map_severity(raw: str) -> str:
        mapping = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "info"}
        return mapping.get(raw.lower(), "info")

    @staticmethod
    def _default_handler(event: AgentEvent) -> None:
        log.info("[EVENT] %s — %s", event.kind, event.summary)

    def _load_seen_ids(self) -> set[str]:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                return set(data.get("seen_ids", []))
            except Exception:
                pass
        return set()

    def _persist_seen_ids(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({"seen_ids": list(self._seen_alert_ids), "updated_at": datetime.now(timezone.utc).isoformat()})
        )
