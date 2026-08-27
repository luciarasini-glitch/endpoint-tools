from app.models.domain import SyncIssue
from app.services.normalizer import NormalizationService


def test_normalizer_correlates_user_and_device() -> None:
    payload = {
        "users": [
            {"id": "u-1", "displayName": "Alice", "email": "alice@example.com"},
        ],
        "endpoint_inventory": [
            {
                "id": "d-1",
                "hostname": "alice-laptop",
                "owner": "alice@example.com",
                "eppAgent": {"productNames": ["Endpoint Sensor"], "status": "on"},
            },
        ],
        "risk_insights": [
            {"id": "s-1", "title": "Credential risk", "severity": "high", "userId": "u-1"},
        ],
        "connected_products": [],
        "workbench_alerts": [],
    }
    snapshot = NormalizationService().build_snapshot(payload, [SyncIssue(source="test", severity="info", message="ok")], "demo")
    assert len(snapshot.users) == 1
    assert snapshot.users[0].device_ids == ["d-1"]
    assert snapshot.users[0].risk_level == "high"
    assert snapshot.correlations[0].confidence == "deterministic"
    assert snapshot.coverage[0].name == "Endpoint Sensor"


def test_normalizer_infers_user_from_last_logged_on_user() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [
            {
                "agentGuid": "d-2",
                "endpointName": "desktop-1",
                "osName": "Windows 11",
                "lastUsedIp": "10.0.0.2",
                "lastLoggedOnUser": "DESKTOP-1\\andresrodriguez",
                "eppAgent": {"productNames": ["Standard Endpoint Protection"], "status": "off"},
            }
        ],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [],
    }
    snapshot = NormalizationService().build_snapshot(payload, [], "live")
    assert len(snapshot.users) == 1
    assert snapshot.users[0].source == "endpoint_inventory"
    assert snapshot.users[0].status == "inferred"
    assert snapshot.users[0].device_ids == ["d-2"]
    assert snapshot.devices[0].last_logged_on_user == "DESKTOP-1\\andresrodriguez"
    assert snapshot.correlations[0].confidence == "deterministic"


def test_normalizer_extracts_mac_addresses_from_endpoint_inventory() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [
            {
                "agentGuid": "d-mac",
                "endpointName": "macbook-pro",
                "serialNumber": "",
                "network": {
                    "primaryMacAddress": "AA-BB-CC-DD-EE-FF",
                    "secondaryMacAddress": "00:00:00:00:00:00",
                },
            }
        ],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [],
    }

    snapshot = NormalizationService().build_snapshot(payload, [], "live")

    assert snapshot.devices[0].mac_addresses == ["aa:bb:cc:dd:ee:ff"]


def test_normalizer_merges_mac_addresses_from_eiqs_payload() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [
            {
                "agentGuid": "trend-1",
                "endpointName": "macbook-pro",
            }
        ],
        "eiqs_endpoints": [
            {
                "agentGuid": "trend-1",
                "endpointName": {"value": "macbook-pro"},
                "macAddress": {"value": ["11:22:33:44:55:66"]},
            }
        ],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [],
    }

    snapshot = NormalizationService().build_snapshot(payload, [], "live")

    assert snapshot.devices[0].mac_addresses == ["11:22:33:44:55:66"]


def test_normalizer_extracts_workbench_alert_endpoint_name() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [
            {
                "id": "wb-1",
                "description": "Suspicious upload",
                "severity": "medium",
                "status": "Open",
                "createdDateTime": "2026-04-07T13:11:46Z",
                "impactScope": {
                    "entities": [
                        {
                            "entityId": "F662B8C6-1373-4F58-855F-1ECF491D1592",
                            "entityType": "host",
                            "entityValue": {
                                "guid": "F662B8C6-1373-4F58-855F-1ECF491D1592",
                                "name": "DESKTOP-DINTE72",
                            },
                        }
                    ]
                },
            }
        ],
    }

    snapshot = NormalizationService().build_snapshot(payload, [], "live")

    assert snapshot.signals[0].device_id == "F662B8C6-1373-4F58-855F-1ECF491D1592"
    assert snapshot.signals[0].device_name == "DESKTOP-DINTE72"


def test_normalizer_adds_oat_detection_as_signal() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [],
        "oat_detections": [
            {
                "uuid": "oat-1",
                "detectedDateTime": "2026-04-07T13:57:06Z",
                "entityName": "DESKTOP-MMIEU7B",
                "entityType": "endpoint",
                "source": "observedAttackTechniques",
                "filters": [{"riskLevel": "info"}],
                "endpoint": {
                    "agentGuid": "22cf188d-8ac9-4dbf-bd00-b946e0b06b21",
                    "endpointName": "DESKTOP-MMIEU7B",
                },
                "detail": {
                    "filterRiskLevel": "info",
                    "endpointHostName": "DESKTOP-MMIEU7B",
                },
            }
        ],
    }

    snapshot = NormalizationService().build_snapshot(payload, [], "live")

    assert snapshot.signals[0].source == "oat_detections"
    assert snapshot.signals[0].id == "oat-1"
    assert snapshot.signals[0].device_id == "22cf188d-8ac9-4dbf-bd00-b946e0b06b21"
    assert snapshot.signals[0].device_name == "DESKTOP-MMIEU7B"
    assert snapshot.signals[0].detail_payload["entityType"] == "endpoint"


def test_normalizer_skips_oat_messaging_entities() -> None:
    payload = {
        "users": [],
        "endpoint_inventory": [],
        "risk_insights": [],
        "connected_products": [],
        "workbench_alerts": [],
        "oat_detections": [
            {
                "uuid": "oat-msg-1",
                "detectedDateTime": "2026-04-07T13:57:06Z",
                "entityName": "user@example.com",
                "entityType": "messaging",
                "source": "emailActivityData",
                "detail": {"mailbox": "user@example.com"},
            },
            {
                "uuid": "oat-endpoint-1",
                "detectedDateTime": "2026-04-07T13:58:06Z",
                "entityName": "DESKTOP-01",
                "entityType": "endpoint",
                "source": "observedAttackTechniques",
                "endpoint": {"agentGuid": "agent-1", "endpointName": "DESKTOP-01"},
                "detail": {"endpointHostName": "DESKTOP-01"},
            },
        ],
    }

    snapshot = NormalizationService().build_snapshot(payload, [], "live")

    assert len(snapshot.signals) == 1
    assert snapshot.signals[0].id == "oat-endpoint-1"
