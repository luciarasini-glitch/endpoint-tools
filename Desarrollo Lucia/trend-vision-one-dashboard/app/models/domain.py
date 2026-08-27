from __future__ import annotations

from typing import Any
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SyncIssue(BaseModel):
    source: str
    severity: Literal["info", "warning", "error"]
    message: str


class CorrelationLink(BaseModel):
    user_id: str
    device_id: str
    confidence: Literal["deterministic", "inferred"]
    rationale: str


class CoverageRecord(BaseModel):
    id: str
    name: str
    category: str
    status: str = "unknown"
    source: str
    device_id: Optional[str] = None
    user_id: Optional[str] = None


class SignalRecord(BaseModel):
    id: str
    title: str
    severity: str = "unknown"
    source: str
    status: str = "unknown"
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    detected_at: Optional[datetime] = None
    detail_payload: dict[str, Any] = Field(default_factory=dict)


class DeviceRecord(BaseModel):
    id: str
    hostname: str
    platform: str = "unknown"
    os_version: Optional[str] = None
    ip_address: Optional[str] = None
    mac_addresses: list[str] = Field(default_factory=list)
    last_seen: Optional[datetime] = None
    last_logged_on_user: Optional[str] = None
    isolation_status: Optional[str] = None
    serial_number: Optional[str] = None
    service_gateway_or_proxy: Optional[str] = None
    version_control_policy: Optional[str] = None
    owner_user_ids: list[str] = Field(default_factory=list)
    coverage_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)


class UserRecord(BaseModel):
    id: str
    display_name: str
    email: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None
    risk_level: str = "unknown"
    status: str = "unknown"
    source: str = "accounts"
    device_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    coverage_ids: list[str] = Field(default_factory=list)


class DashboardSnapshot(BaseModel):
    generated_at: datetime
    source_mode: Literal["live", "demo", "cache"]
    users: list[UserRecord]
    devices: list[DeviceRecord]
    signals: list[SignalRecord]
    coverage: list[CoverageRecord]
    correlations: list[CorrelationLink]
    issues: list[SyncIssue] = Field(default_factory=list)
