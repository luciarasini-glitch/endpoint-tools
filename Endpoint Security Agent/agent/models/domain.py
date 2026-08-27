from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class EndpointRecord:
    id: str
    hostname: str
    platform: str = ""
    os_version: str = ""
    ip_address: str = ""
    mac_addresses: list[str] = field(default_factory=list)
    last_seen: datetime | None = None
    last_logged_on_user: str = ""
    isolation_status: str = ""
    agent_version: str = ""
    risk_level: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class UserRecord:
    id: str
    display_name: str
    email: str = ""
    department: str = ""
    title: str = ""
    risk_level: str = ""
    status: str = ""
    device_ids: list[str] = field(default_factory=list)


@dataclass
class AlertRecord:
    id: str
    title: str
    severity: str
    source: Literal["workbench", "oat", "unknown"] = "unknown"
    status: str = ""
    detected_at: datetime | None = None
    device_name: str = ""
    user_id: str = ""
    mitre_technique: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class AgentEvent:
    """Emitted by the monitor service when something notable happens."""
    kind: Literal["alert_new", "alert_updated", "endpoint_offline", "risk_change", "info"]
    summary: str
    severity: Literal["critical", "high", "medium", "low", "info"] = "info"
    payload: dict = field(default_factory=dict)
    timestamp: datetime | None = None
