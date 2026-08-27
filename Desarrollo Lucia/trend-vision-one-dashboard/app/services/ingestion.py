from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import Settings
from app.models.domain import SyncIssue


class IngestionService:
    INVENTORY_ENDPOINTS = ("users", "endpoint_inventory", "eiqs_endpoints", "risk_insights", "connected_products")
    ALERT_ENDPOINTS = ("workbench_alerts", "oat_detections")

    def __init__(self, settings: Settings, client: TrendVisionOneClient) -> None:
        self.settings = settings
        self.client = client

    def _load_demo_payload(self) -> dict[str, Any]:
        demo_path = Path(__file__).resolve().parents[1] / "data" / "demo_snapshot.json"
        return json.loads(demo_path.read_text(encoding="utf-8"))

    def fetch_all(self) -> tuple[dict[str, Any], list[SyncIssue], str]:
        return self.fetch_subset(self.INVENTORY_ENDPOINTS + self.ALERT_ENDPOINTS)

    def fetch_inventory(self) -> tuple[dict[str, Any], list[SyncIssue], str]:
        return self.fetch_subset(self.INVENTORY_ENDPOINTS)

    def fetch_alerts(self) -> tuple[dict[str, Any], list[SyncIssue], str]:
        return self.fetch_subset(self.ALERT_ENDPOINTS)

    def fetch_subset(self, endpoint_names: tuple[str, ...]) -> tuple[dict[str, Any], list[SyncIssue], str]:
        issues: list[SyncIssue] = []

        if self.settings.app_demo_mode and not self.settings.trend_vision_one_api_token:
            demo_payload = self._load_demo_payload()
            issues.append(
                SyncIssue(
                    source="demo",
                    severity="info",
                    message="Running in demo mode because no API token was configured.",
                )
            )
            return {name: demo_payload.get(name) for name in endpoint_names}, issues, "demo"

        payload: dict[str, Any] = {}
        for name in endpoint_names:
            data, endpoint_issues = self.client.fetch_collection(name)
            issues.extend(endpoint_issues)
            payload[name] = data

        if all(payload.get(key) is None for key in payload):
            if self.settings.app_demo_mode:
                issues.append(
                    SyncIssue(
                        source="demo",
                        severity="warning",
                        message="Live sync returned no usable payloads. Falling back to demo data.",
                    )
                )
                return self._load_demo_payload(), issues, "demo"
            issues.append(
                SyncIssue(
                    source="ingestion",
                    severity="error",
                    message="Live sync returned no usable payloads and demo mode is disabled.",
                )
            )
        return payload, issues, "live"
