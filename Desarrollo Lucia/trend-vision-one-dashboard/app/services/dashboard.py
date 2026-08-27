from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.models.domain import DashboardSnapshot
from app.models.api import OverviewResponse, SyncStatusResponse, UserListItem
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizationService

BLOCKED_ALERT_PARENT_SUBSTRINGS = (
    r"\jumpcloud\jumpcloud-agent",
    r"\windows\system32\services.exe",
)

EVENT_SOURCE_TYPE_LABELS = {
    1: "EVENT_SOURCE_TELEMETRY",
    2: "EVENT_SOURCE_JAGUAR",
    3: "EVENT_SOURCE_EVENT_LOG",
    5: "EVENT_SOURCE_EMAIL_META",
    6: "EVENT_SOURCE_NETWORK_ACTIVITY",
    7: "EVENT_SOURCE_MOBILE_ACTIVITY",
    8: "EVENT_SOURCE_CONTAINER_ACTIVITY",
    9: "EVENT_SOURCE_IDENTITY_ACTIVITY",
    10: "EVENT_SOURCE_COLLABORATION_APP_ACTIVITY",
}


def _clean_alert_endpoint(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\([^)]*\)$", "", value).strip()


def _resolve_event_source_type_label(detail_payload: dict) -> str:
    raw_value = detail_payload.get("eventSourceType")
    if raw_value in (None, ""):
        return ""
    try:
        numeric_value = int(raw_value)
    except (TypeError, ValueError):
        return str(raw_value).strip()
    return EVENT_SOURCE_TYPE_LABELS.get(numeric_value, str(numeric_value))


class DashboardService:
    INVENTORY_SYNC_SCOPE = "inventory"
    ALERTS_SYNC_SCOPE = "alerts"

    def __init__(
        self,
        repository: SnapshotRepository,
        ingestion: IngestionService,
        normalizer: NormalizationService,
        cache_ttl_minutes: int,
    ) -> None:
        self.repository = repository
        self.ingestion = ingestion
        self.normalizer = normalizer
        self.cache_ttl_minutes = cache_ttl_minutes

    def sync(self, force: bool = False) -> DashboardSnapshot:
        return self._sync_scope("full", force=force)

    def sync_inventory(self, force: bool = False) -> DashboardSnapshot:
        return self._sync_scope(self.INVENTORY_SYNC_SCOPE, force=force)

    def sync_alerts(self, force: bool = False) -> DashboardSnapshot:
        return self._sync_scope(self.ALERTS_SYNC_SCOPE, force=force)

    def _sync_scope(self, scope: str, *, force: bool) -> DashboardSnapshot:
        if not self.repository.mark_sync_started(scope):
            existing = self.repository.get_latest_snapshot()
            if existing is not None:
                return existing.model_copy(update={"source_mode": "cache"})
            raise HTTPException(status_code=409, detail="Sync already in progress.")

        existing = self.repository.get_latest_snapshot()
        try:
            if existing and not force:
                max_age = timedelta(minutes=self.cache_ttl_minutes)
                if datetime.utcnow() - existing.generated_at.replace(tzinfo=None) < max_age:
                    self.repository.mark_sync_finished()
                    return existing.model_copy(update={"source_mode": "cache"})

            if scope == self.INVENTORY_SYNC_SCOPE:
                payload, issues, source_mode = self.ingestion.fetch_inventory()
            elif scope == self.ALERTS_SYNC_SCOPE:
                payload, issues, source_mode = self.ingestion.fetch_alerts()
            else:
                payload, issues, source_mode = self.ingestion.fetch_all()

            snapshot = self.normalizer.build_snapshot(payload, issues, source_mode)
            merged_snapshot = self._merge_snapshot_scope(existing, snapshot, scope)
            self.repository.save_snapshot(merged_snapshot)
            self.repository.mark_sync_finished()
            return merged_snapshot
        except Exception as exc:
            self.repository.mark_sync_finished(error=str(exc))
            raise

    def _merge_snapshot_scope(
        self,
        existing: DashboardSnapshot | None,
        snapshot: DashboardSnapshot,
        scope: str,
    ) -> DashboardSnapshot:
        if existing is None or scope == "full":
            return snapshot
        if scope == self.INVENTORY_SYNC_SCOPE:
            return snapshot.model_copy(
                update={
                    "signals": existing.signals,
                }
            )
        if scope == self.ALERTS_SYNC_SCOPE:
            return snapshot.model_copy(
                update={
                    "users": existing.users,
                    "devices": existing.devices,
                    "coverage": existing.coverage,
                    "correlations": existing.correlations,
                }
            )
        return snapshot

    def status(self) -> SyncStatusResponse:
        snapshot = self.repository.get_latest_snapshot()
        sync_state = self.repository.get_sync_state()
        return SyncStatusResponse(
            has_snapshot=snapshot is not None,
            last_sync_at=snapshot.generated_at if snapshot else None,
            source_mode=snapshot.source_mode if snapshot else None,
            issue_count=len(snapshot.issues) if snapshot else 0,
            sync_in_progress=bool(sync_state["in_progress"]),
            sync_scope=sync_state["scope"],
            sync_started_at=sync_state["started_at"],
            sync_finished_at=sync_state["finished_at"],
            last_sync_error=sync_state["last_error"],
        )

    def latest_snapshot(self) -> DashboardSnapshot:
        snapshot = self.repository.get_latest_snapshot()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No dashboard snapshot found. Run a sync first.")
        return snapshot

    def overview(self) -> OverviewResponse:
        snapshot = self.latest_snapshot()
        top_risk_users = [
            {
                "id": user.id,
                "display_name": user.display_name,
                "risk_level": user.risk_level,
            }
            for user in sorted(
                snapshot.users,
                key=lambda item: (item.risk_level not in {"critical", "high"}, item.display_name.lower()),
            )[:5]
        ]
        return OverviewResponse(
            generated_at=snapshot.generated_at,
            source_mode=snapshot.source_mode,
            totals={
                "users": len(snapshot.users),
                "devices": len(snapshot.devices),
                "signals": len(snapshot.signals),
                "coverage": len(snapshot.coverage),
            },
            top_risk_users=top_risk_users,
            recent_issues=snapshot.issues[:5],
        )

    def list_users(self, search: str = "", risk_level: str = "") -> list[UserListItem]:
        snapshot = self.latest_snapshot()
        users = snapshot.users
        if search:
            search_lc = search.lower()
            users = [
                user
                for user in users
                if search_lc in user.display_name.lower() or (user.email and search_lc in user.email.lower())
            ]
        if risk_level:
            users = [user for user in users if user.risk_level.lower() == risk_level.lower()]
        return [
            UserListItem(
                id=user.id,
                display_name=user.display_name,
                email=user.email,
                department=user.department,
                risk_level=user.risk_level,
                status=user.status,
                source=user.source,
                device_count=len(user.device_ids),
                signal_count=len(user.signal_ids),
            )
            for user in users
        ]

    def user_detail(self, user_id: str) -> DashboardSnapshot:
        snapshot = self.latest_snapshot()
        if not any(user.id == user_id for user in snapshot.users):
            raise HTTPException(status_code=404, detail=f"User {user_id} was not found in the current snapshot.")
        return snapshot

    def endpoint_cards(
        self,
        search: str = "",
        platform: str = "",
        isolation_status: str = "",
    ) -> list[dict]:
        snapshot = self.latest_snapshot()
        user_index = {user.id: user for user in snapshot.users}
        signal_index = {signal.id: signal for signal in snapshot.signals}
        coverage_index = {coverage.id: coverage for coverage in snapshot.coverage}

        devices = snapshot.devices
        if search:
            needle = search.lower()
            filtered_devices = []
            for device in devices:
                haystack = [
                    device.hostname,
                    device.platform,
                    device.ip_address or "",
                    device.last_logged_on_user or "",
                    device.serial_number or "",
                    " ".join(device.owner_user_ids),
                ]
                if any(needle in value.lower() for value in haystack if value):
                    filtered_devices.append(device)
            devices = filtered_devices
        if platform:
            devices = [device for device in devices if platform.lower() in device.platform.lower()]
        if isolation_status:
            devices = [
                device
                for device in devices
                if (device.isolation_status or "unknown").lower() == isolation_status.lower()
            ]

        cards: list[dict] = []
        for device in devices:
            related_users = [user_index[user_id] for user_id in device.owner_user_ids if user_id in user_index]
            related_signals = [signal_index[signal_id] for signal_id in device.signal_ids if signal_id in signal_index]
            related_coverage = [coverage_index[cov_id] for cov_id in device.coverage_ids if cov_id in coverage_index]
            cards.append(
                {
                    "id": device.id,
                    "hostname": device.hostname,
                    "platform": device.platform,
                    "os_version": device.os_version,
                    "ip_address": device.ip_address,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                    "last_logged_on_user": device.last_logged_on_user,
                    "isolation_status": device.isolation_status or "unknown",
                    "serial_number": device.serial_number,
                    "service_gateway_or_proxy": device.service_gateway_or_proxy,
                    "version_control_policy": device.version_control_policy,
                    "users": [
                        {
                            "id": user.id,
                            "display_name": user.display_name,
                            "email": user.email,
                            "source": user.source,
                            "risk_level": user.risk_level,
                        }
                        for user in related_users
                    ],
                    "signals": [
                        {
                            "id": signal.id,
                            "title": signal.title,
                            "severity": signal.severity,
                            "status": signal.status,
                            "source": signal.source,
                        }
                        for signal in related_signals
                    ],
                    "coverage": [
                        {
                            "id": coverage.id,
                            "name": coverage.name,
                            "category": coverage.category,
                            "status": coverage.status,
                            "source": coverage.source,
                        }
                        for coverage in related_coverage
                    ],
                    "stats": {
                        "user_count": len(related_users),
                        "signal_count": len(related_signals),
                        "coverage_count": len(related_coverage),
                    },
                }
            )
        return cards

    def list_trend_devices(self, search: str = "") -> list[dict]:
        snapshot = self.latest_snapshot()
        user_index = {user.id: user for user in snapshot.users}

        devices = snapshot.devices
        if search:
            needle = search.lower()
            filtered_devices = []
            for device in devices:
                owner_labels = []
                for user_id in device.owner_user_ids:
                    user = user_index.get(user_id)
                    if user:
                        owner_labels.extend([user.display_name, user.email or ""])
                haystack = [
                    device.hostname,
                    device.platform,
                    device.os_version or "",
                    device.ip_address or "",
                    device.last_logged_on_user or "",
                    device.serial_number or "",
                    device.isolation_status or "",
                    *owner_labels,
                ]
                if any(needle in value.lower() for value in haystack if value):
                    filtered_devices.append(device)
            devices = filtered_devices

        rows: list[dict] = []
        for device in devices:
            owner_names = []
            owner_emails = []
            for user_id in device.owner_user_ids:
                user = user_index.get(user_id)
                if not user:
                    continue
                if user.display_name:
                    owner_names.append(user.display_name)
                if user.email:
                    owner_emails.append(user.email)
            rows.append(
                {
                    "Hostname": device.hostname,
                    "Platform": device.platform,
                    "OS Version": device.os_version or "",
                    "IP Address": device.ip_address or "",
                    "Last Seen": device.last_seen.isoformat() if device.last_seen else "",
                    "Last Logged On User": device.last_logged_on_user or "",
                    "Isolation Status": device.isolation_status or "",
                    "Serial Number": device.serial_number or "",
                    "Service Gateway Or Proxy": device.service_gateway_or_proxy or "",
                    "Version Control Policy": device.version_control_policy or "",
                    "Owners": " | ".join(owner_names),
                    "Owner Emails": " | ".join(owner_emails),
                }
            )

        rows.sort(key=lambda item: (item["Hostname"].lower(), item["Serial Number"].lower()))
        return rows

    def list_alerts(
        self,
        search: str = "",
        severity: str = "",
        status: str = "",
    ) -> list[dict]:
        snapshot = self.latest_snapshot()
        user_index = {user.id: user for user in snapshot.users}
        device_index = {device.id: device for device in snapshot.devices}

        alerts = [signal for signal in snapshot.signals if signal.source in {"oat_detections", "workbench_alerts"}]
        if severity:
            alerts = [alert for alert in alerts if alert.severity.lower() == severity.lower()]
        if status:
            alerts = [alert for alert in alerts if alert.status.lower() == status.lower()]

        rows: list[dict] = []
        for alert in alerts:
            user = user_index.get(alert.user_id or "")
            device = device_index.get(alert.device_id or "")
            detail_payload = alert.detail_payload if isinstance(alert.detail_payload, dict) else {}
            detail_block = detail_payload.get("detail") if isinstance(detail_payload.get("detail"), dict) else {}
            logon_user = detail_block.get("logonUser")
            if isinstance(logon_user, list):
                logon_user = " | ".join(str(item) for item in logon_user if item)
            if alert.source == "workbench_alerts" and not logon_user:
                indicators = detail_payload.get("indicators")
                if isinstance(indicators, list):
                    for indicator in indicators:
                        if not isinstance(indicator, dict):
                            continue
                        if str(indicator.get("field") or "").strip() != "logonUsers":
                            continue
                        indicator_value = indicator.get("value")
                        if isinstance(indicator_value, list):
                            logon_user = " | ".join(str(item) for item in indicator_value if item)
                        else:
                            logon_user = str(indicator_value or "").strip()
                        if logon_user:
                            break
            parent_name = detail_block.get("parentName")
            if alert.source == "oat_detections" and not parent_name:
                highlighted_objects = detail_payload.get("highlightedObjects")
                if isinstance(highlighted_objects, list):
                    for highlighted in highlighted_objects:
                        if not isinstance(highlighted, dict):
                            continue
                        highlighted_value = str(highlighted.get("value") or "").strip()
                        if highlighted_value:
                            parent_name = highlighted_value
                            break
            parent_name_lc = str(parent_name or "").strip().lower()
            if parent_name_lc and any(token in parent_name_lc for token in BLOCKED_ALERT_PARENT_SUBSTRINGS):
                continue
            rule_name = ""
            if alert.source == "workbench_alerts":
                indicators = detail_payload.get("indicators")
                if isinstance(indicators, list):
                    for indicator in indicators:
                        if not isinstance(indicator, dict):
                            continue
                        if str(indicator.get("field") or "").strip() == "ruleName":
                            rule_name = str(indicator.get("value") or "").strip()
                            if rule_name:
                                break
                if not rule_name:
                    matched_rules = detail_payload.get("matchedRules")
                    if isinstance(matched_rules, list) and matched_rules:
                        first_rule = matched_rules[0]
                        if isinstance(first_rule, dict):
                            matched_filters = first_rule.get("matchedFilters")
                            if isinstance(matched_filters, list) and matched_filters:
                                first_filter = matched_filters[0]
                                if isinstance(first_filter, dict):
                                    rule_name = str(first_filter.get("name") or "").strip()
                            if not rule_name:
                                rule_name = str(first_rule.get("name") or "").strip()
            else:
                rule_name = str(detail_block.get("ruleName") or "")
            event_name = ""
            filters = detail_payload.get("filters")
            if isinstance(filters, list) and filters:
                first_filter = filters[0]
                if isinstance(first_filter, dict):
                    event_name = str(first_filter.get("name") or "").strip()
            event_source_type = _resolve_event_source_type_label(detail_payload)
            row = {
                "id": alert.id,
                "title": alert.title,
                "event_name": event_name,
                "event_source_type": event_source_type,
                "severity": alert.severity,
                "status": alert.status,
                "detected_at": alert.detected_at.isoformat() if alert.detected_at else None,
                "user_id": alert.user_id,
                "user_display_name": user.display_name if user else "",
                "user_email": user.email if user and user.email else "",
                "device_id": alert.device_id,
                "device_name": _clean_alert_endpoint(device.hostname if device else (alert.device_name or "")),
                "logon_user": str(logon_user or ""),
                "parent_name": str(parent_name or ""),
                "rule_name": rule_name,
                "search_blob": json.dumps(detail_payload, ensure_ascii=False),
                "source": alert.source,
            }
            rows.append(row)

        if search:
            needle = search.lower()
            rows = [
                row
                for row in rows
                if any(
                    needle in str(value).lower()
                    for value in (
                        row["title"],
                        row["severity"],
                        row["status"],
                        row["user_display_name"],
                        row["user_email"],
                        row["device_name"],
                        row["logon_user"],
                        row["parent_name"],
                        row["rule_name"],
                        row["search_blob"],
                        row["id"],
                        row["device_id"],
                        row["user_id"],
                    )
                    if value
                )
            ]

        for row in rows:
            row.pop("search_blob", None)

        rows.sort(
            key=lambda item: (
                item["detected_at"] is None,
                item["detected_at"] or "",
                item["severity"].lower(),
                item["title"].lower(),
            ),
            reverse=True,
        )
        return rows

    def alert_detail(self, alert_id: str) -> dict:
        snapshot = self.latest_snapshot()
        signal = next((item for item in snapshot.signals if item.id == alert_id and item.source in {"workbench_alerts", "oat_detections"}), None)
        if signal is None:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} was not found in the current snapshot.")
        if signal.source == "oat_detections":
            payload, issues = self.ingestion.client.fetch_oat_detection_detail(alert_id)
            if payload is not None:
                return payload
            return signal.detail_payload

        payload, issues = self.ingestion.client.fetch_workbench_alert_detail(alert_id)
        if payload is None:
            issue_message = issues[0].message if issues else f"Alert {alert_id} could not be loaded."
            raise HTTPException(status_code=502, detail=issue_message)
        return payload
