from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.models.domain import DashboardSnapshot


class SnapshotRepository:
    STALE_SYNC_TIMEOUT = timedelta(minutes=30)

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generated_at TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    in_progress INTEGER NOT NULL DEFAULT 0,
                    scope TEXT NULL,
                    started_at TEXT NULL,
                    finished_at TEXT NULL,
                    last_error TEXT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(sync_state)").fetchall()
            }
            if "scope" not in columns:
                conn.execute("ALTER TABLE sync_state ADD COLUMN scope TEXT NULL")
            conn.execute(
                """
                INSERT OR IGNORE INTO sync_state (id, in_progress, scope, started_at, finished_at, last_error)
                VALUES (1, 0, NULL, NULL, NULL, NULL)
                """
            )
            conn.commit()

    def save_snapshot(self, snapshot: DashboardSnapshot) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dashboard_snapshots (generated_at, source_mode, payload) VALUES (?, ?, ?)",
                (
                    snapshot.generated_at.isoformat(),
                    snapshot.source_mode,
                    snapshot.model_dump_json(),
                ),
            )
            conn.commit()

    def get_latest_snapshot(self) -> DashboardSnapshot | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM dashboard_snapshots ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return DashboardSnapshot.model_validate(json.loads(row[0]))

    def last_sync_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generated_at FROM dashboard_snapshots ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row[0])

    def get_sync_state(self) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT in_progress, scope, started_at, finished_at, last_error FROM sync_state WHERE id = 1"
            ).fetchone()
        if not row:
            return {
                "in_progress": False,
                "scope": None,
                "started_at": None,
                "finished_at": None,
                "last_error": None,
            }
        return {
            "in_progress": bool(row[0]),
            "scope": row[1],
            "started_at": datetime.fromisoformat(row[2]) if row[2] else None,
            "finished_at": datetime.fromisoformat(row[3]) if row[3] else None,
            "last_error": row[4],
        }

    def mark_sync_started(self, scope: str) -> bool:
        started_at = datetime.utcnow().isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT in_progress, started_at FROM sync_state WHERE id = 1").fetchone()
            if row and row[0]:
                previous_started_at = datetime.fromisoformat(row[1]) if row[1] else None
                if previous_started_at and datetime.utcnow() - previous_started_at < self.STALE_SYNC_TIMEOUT:
                    return False
            conn.execute(
                """
                UPDATE sync_state
                SET in_progress = 1,
                    scope = ?,
                    started_at = ?,
                    last_error = NULL
                WHERE id = 1
                """,
                (scope, started_at),
            )
            conn.commit()
        return True

    def mark_sync_finished(self, *, error: str | None = None) -> None:
        finished_at = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_state
                SET in_progress = 0,
                    scope = scope,
                    finished_at = ?,
                    last_error = ?
                WHERE id = 1
                """,
                (finished_at, error),
            )
            conn.commit()
