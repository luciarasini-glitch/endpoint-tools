from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.domain import DashboardSnapshot, SyncIssue


class HealthResponse(BaseModel):
    status: str
    version: str


class SyncStatusResponse(BaseModel):
    has_snapshot: bool
    last_sync_at: Optional[datetime] = None
    source_mode: Optional[str] = None
    issue_count: int = 0
    sync_in_progress: bool = False
    sync_scope: Optional[str] = None
    sync_started_at: Optional[datetime] = None
    sync_finished_at: Optional[datetime] = None
    last_sync_error: Optional[str] = None


class OverviewResponse(BaseModel):
    generated_at: datetime
    source_mode: str
    totals: dict[str, int]
    top_risk_users: list[dict[str, str]]
    recent_issues: list[SyncIssue] = Field(default_factory=list)


class UserListItem(BaseModel):
    id: str
    display_name: str
    email: Optional[str] = None
    department: Optional[str] = None
    risk_level: str = "unknown"
    status: str = "unknown"
    source: str = "accounts"
    device_count: int = 0
    signal_count: int = 0


class UserDetailResponse(BaseModel):
    snapshot: DashboardSnapshot
    user_id: str
