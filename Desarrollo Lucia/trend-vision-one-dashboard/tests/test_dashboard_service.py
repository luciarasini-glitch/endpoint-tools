from __future__ import annotations

from datetime import datetime
from app.models.domain import DashboardSnapshot, DeviceRecord, SignalRecord, UserRecord
from app.services.dashboard import DashboardService


class StubRepository:
    def __init__(self, snapshot: DashboardSnapshot) -> None:
        self.snapshot = snapshot
        self.sync_started_scope: str | None = None
        self.sync_finished_error: str | None = None

    def get_latest_snapshot(self) -> DashboardSnapshot | None:
        return self.snapshot

    def mark_sync_started(self, scope: str) -> bool:
        self.sync_started_scope = scope
        return True

    def mark_sync_finished(self, *, error: str | None = None) -> None:
        self.sync_finished_error = error

    def save_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self.snapshot = snapshot

    def get_sync_state(self) -> dict[str, object]:
        return {
            "in_progress": False,
            "scope": None,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
        }


class StubIngestion:
    def __init__(self, inventory_snapshot: DashboardSnapshot | None = None, alerts_snapshot: DashboardSnapshot | None = None) -> None:
        self.inventory_snapshot = inventory_snapshot
        self.alerts_snapshot = alerts_snapshot

    def fetch_inventory(self):
        assert self.inventory_snapshot is not None
        return {}, self.inventory_snapshot.issues, self.inventory_snapshot.source_mode

    def fetch_alerts(self):
        assert self.alerts_snapshot is not None
        return {}, self.alerts_snapshot.issues, self.alerts_snapshot.source_mode


class StubNormalizer:
    def __init__(self, snapshot: DashboardSnapshot) -> None:
        self.snapshot = snapshot

    def build_snapshot(self, payload, issues, source_mode):  # noqa: ANN001
        return self.snapshot


def test_list_alerts_returns_oat_and_workbench_alerts_with_context() -> None:
    snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 7, 12, 0, 0),
        source_mode="live",
        users=[UserRecord(id="u-1", display_name="Alice", email="alice@example.com")],
        devices=[DeviceRecord(id="d-1", hostname="alice-macbook")],
            signals=[
                SignalRecord(
                    id="a-1",
                    title="Suspicious process detected",
                    severity="high",
                    source="oat_detections",
                    status="Observed",
                    user_id="u-1",
                    device_id="d-1",
                    detected_at=datetime(2026, 4, 7, 11, 30, 0),
                    detail_payload={"detail": {"logonUser": ["alice"], "parentName": "powershell.exe"}},
                ),
                SignalRecord(
                    id="r-1",
                    title="Possible Exfiltration",
                    severity="medium",
                    source="workbench_alerts",
                    status="Open",
                    user_id="u-1",
                    device_id="d-1",
                    detected_at=datetime(2026, 4, 7, 11, 45, 0),
                    detail_payload={
                        "indicators": [
                            {"field": "ruleName", "value": "Sensitive Files Upload to Personal Cloud"},
                            {"field": "logonUsers", "value": ["alice"]},
                        ],
                    },
                ),
                SignalRecord(
                    id="r-1",
                    title="Risk insight",
                    severity="medium",
                    source="risk_insights",
                    status="open",
                ),
            ],
        coverage=[],
        correlations=[],
        issues=[],
    )
    service = DashboardService(StubRepository(snapshot), ingestion=None, normalizer=None, cache_ttl_minutes=30)

    alerts = service.list_alerts()

    assert len(alerts) == 2
    oat_alert = next(alert for alert in alerts if alert["id"] == "a-1")
    workbench_alert = next(alert for alert in alerts if alert["id"] == "r-1")

    assert oat_alert["user_display_name"] == "Alice"
    assert oat_alert["user_email"] == "alice@example.com"
    assert oat_alert["device_name"] == "alice-macbook"
    assert oat_alert["logon_user"] == "alice"
    assert oat_alert["parent_name"] == "powershell.exe"
    assert oat_alert["rule_name"] == ""

    assert workbench_alert["user_display_name"] == "Alice"
    assert workbench_alert["device_name"] == "alice-macbook"
    assert workbench_alert["logon_user"] == "alice"
    assert workbench_alert["rule_name"] == "Sensitive Files Upload to Personal Cloud"


def test_list_alerts_filters_by_search_and_severity() -> None:
    snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 7, 12, 0, 0),
        source_mode="live",
        users=[UserRecord(id="u-1", display_name="Alice")],
        devices=[DeviceRecord(id="d-1", hostname="alice-macbook")],
            signals=[
                SignalRecord(
                    id="a-1",
                    title="Suspicious process detected",
                    severity="high",
                    source="oat_detections",
                    status="Observed",
                    user_id="u-1",
                    device_id="d-1",
                    detail_payload={"detail": {"logonUser": ["alice"], "parentName": "powershell.exe"}},
                ),
                SignalRecord(
                    id="a-2",
                    title="Informational detection",
                    severity="low",
                    source="oat_detections",
                    status="Observed",
                    detail_payload={"detail": {"logonUser": ["bob"], "parentName": "finder"}},
                ),
            ],
        coverage=[],
        correlations=[],
        issues=[],
    )
    service = DashboardService(StubRepository(snapshot), ingestion=None, normalizer=None, cache_ttl_minutes=30)

    alerts = service.list_alerts(search="alice", severity="high")

    assert len(alerts) == 1
    assert alerts[0]["id"] == "a-1"


def test_sync_inventory_preserves_existing_signals() -> None:
    existing_snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 7, 12, 0, 0),
        source_mode="live",
        users=[UserRecord(id="u-1", display_name="Alice")],
        devices=[DeviceRecord(id="d-1", hostname="old-host")],
        signals=[SignalRecord(id="a-1", title="Old alert", source="oat_detections")],
        coverage=[],
        correlations=[],
        issues=[],
    )
    fresh_inventory_snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 8, 12, 0, 0),
        source_mode="live",
        users=[UserRecord(id="u-2", display_name="Bob")],
        devices=[DeviceRecord(id="d-2", hostname="new-host")],
        signals=[],
        coverage=[],
        correlations=[],
        issues=[],
    )
    repository = StubRepository(existing_snapshot)
    service = DashboardService(
        repository,
        ingestion=StubIngestion(inventory_snapshot=fresh_inventory_snapshot),
        normalizer=StubNormalizer(fresh_inventory_snapshot),
        cache_ttl_minutes=0,
    )

    snapshot = service.sync_inventory(force=True)

    assert repository.sync_started_scope == "inventory"
    assert [device.hostname for device in snapshot.devices] == ["new-host"]
    assert [signal.id for signal in snapshot.signals] == ["a-1"]


def test_sync_alerts_preserves_existing_inventory_context() -> None:
    existing_snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 7, 12, 0, 0),
        source_mode="live",
        users=[UserRecord(id="u-1", display_name="Alice")],
        devices=[DeviceRecord(id="d-1", hostname="existing-host")],
        signals=[],
        coverage=[],
        correlations=[],
        issues=[],
    )
    fresh_alert_snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 8, 12, 0, 0),
        source_mode="live",
        users=[],
        devices=[],
        signals=[SignalRecord(id="a-2", title="Fresh alert", source="oat_detections")],
        coverage=[],
        correlations=[],
        issues=[],
    )
    repository = StubRepository(existing_snapshot)
    service = DashboardService(
        repository,
        ingestion=StubIngestion(alerts_snapshot=fresh_alert_snapshot),
        normalizer=StubNormalizer(fresh_alert_snapshot),
        cache_ttl_minutes=0,
    )

    snapshot = service.sync_alerts(force=True)

    assert repository.sync_started_scope == "alerts"
    assert [user.display_name for user in snapshot.users] == ["Alice"]
    assert [device.hostname for device in snapshot.devices] == ["existing-host"]
    assert [signal.id for signal in snapshot.signals] == ["a-2"]
