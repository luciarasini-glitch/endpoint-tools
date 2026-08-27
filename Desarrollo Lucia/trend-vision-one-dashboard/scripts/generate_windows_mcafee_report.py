from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from typing import Any
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.clients.jumpcloud import JumpCloudClient
from app.core.config import get_settings
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.jumpcloud_inventory import JumpCloudInventoryService


DEFAULT_REPORT_PREFIX = "jumpcloud_windows_assigned_mcafee_programs"
MCAFEE_TERM = "mcafee"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell(value: object) -> str:
    return f'<Cell><Data ss:Type="String">{escape(_text(value))}</Data></Cell>'


def _worksheet(name: str, rows: list[dict[str, str]], headers: list[str]) -> str:
    parts = [f'<Worksheet ss:Name="{escape(name)}"><Table>']
    parts.append("<Row>" + "".join(_cell(header) for header in headers) + "</Row>")
    for row in rows:
        parts.append("<Row>" + "".join(_cell(row.get(header, "")) for header in headers) + "</Row>")
    parts.append("</Table></Worksheet>")
    return "".join(parts)


def _write_xls(path: Path, rows: list[dict[str, str]], summary_rows: list[dict[str, str]]) -> None:
    workbook = "".join(
        [
            '<?xml version="1.0"?>',
            '<?mso-application progid="Excel.Sheet"?>',
            '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" ',
            'xmlns:o="urn:schemas-microsoft-com:office:office" ',
            'xmlns:x="urn:schemas-microsoft-com:office:excel" ',
            'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet" ',
            'xmlns:html="http://www.w3.org/TR/REC-html40">',
            '<Styles><Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Top"/></Style></Styles>',
            _worksheet("McAfee Programs", rows, ["hostname", "username", "program name"]),
            _worksheet("Summary", summary_rows, ["Metric", "Value"]),
            "</Workbook>",
        ]
    )
    path.write_text(workbook, encoding="utf-8")


def _extract_list_payload(payload: dict | list) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "data", "value", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _list_all_programs(client: JumpCloudClient, *, limit: int = 10000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        payload = client.get_json(
            "/v2/systeminsights/programs",
            params={"limit": limit, "skip": skip},
            timeout=120.0,
        )
        batch = _extract_list_payload(payload)
        if not batch:
            break
        rows.extend(batch)
        skip += len(batch)
        if len(batch) < limit:
            break
    return rows


def _is_mcafee_program(program: dict[str, Any]) -> bool:
    search_text = " ".join(
        [
            _text(program.get("name")),
            _text(program.get("publisher")),
            _text(program.get("install_location")),
            _text(program.get("install_source")),
            _text(program.get("uninstall_string")),
        ]
    ).casefold()
    return MCAFEE_TERM in search_text


def _system_id(system: dict[str, object]) -> str:
    return _text(system.get("id") or system.get("_id"))


def _primary_user_id(system: dict[str, object]) -> str:
    primary_user = system.get("primarySystemUser")
    if not isinstance(primary_user, dict):
        return ""
    return _text(primary_user.get("id"))


def _username(user: dict[str, object], fallback: str) -> str:
    return (
        _text(user.get("username"))
        or _text(user.get("email"))
        or JumpCloudInventoryService._build_user_name(user)
        or fallback
    )


def generate_windows_mcafee_report(output_path: Path | None = None) -> Path:
    settings = get_settings()
    client = JumpCloudClient(settings)
    service = JumpCloudInventoryService(client, SnapshotRepository(settings.db_abspath), None)

    users = client.list_all_users(limit=100)
    users_by_id = {_text(user.get("id")): user for user in users if _text(user.get("id"))}
    systems = client.list_all_systems(limit=100)

    assigned_windows_by_id: dict[str, dict[str, str]] = {}
    windows_total = 0
    assigned_windows_total = 0
    for system in systems:
        if service._normalize_platform(system) != "Windows":
            continue
        windows_total += 1
        user_id = _primary_user_id(system)
        if not user_id:
            continue
        system_id = _system_id(system)
        if not system_id:
            continue
        user = users_by_id.get(user_id, {})
        assigned_windows_total += 1
        assigned_windows_by_id[system_id] = {
            "hostname": _text(system.get("hostname")) or _text(system.get("displayName")),
            "username": _username(user, user_id),
        }

    programs = _list_all_programs(client)
    rows: list[dict[str, str]] = []
    for program in programs:
        system_id = _text(program.get("system_id") or program.get("systemId") or program.get("system"))
        system_info = assigned_windows_by_id.get(system_id)
        if not system_info or not _is_mcafee_program(program):
            continue
        rows.append(
            {
                "hostname": system_info["hostname"],
                "username": system_info["username"],
                "program name": _text(program.get("name")) or _text(program.get("publisher")) or "McAfee",
            }
        )

    rows.sort(key=lambda row: (row["hostname"].casefold(), row["username"].casefold(), row["program name"].casefold()))

    matched_hostnames = {row["hostname"].casefold() for row in rows if row["hostname"]}
    summary_rows = [
        {"Metric": "Generated At", "Value": datetime.now().isoformat(timespec="seconds")},
        {"Metric": "Windows Systems Total", "Value": str(windows_total)},
        {"Metric": "Assigned Windows Systems", "Value": str(assigned_windows_total)},
        {"Metric": "System Insights Programs Read", "Value": str(len(programs))},
        {"Metric": "Rows With McAfee Programs", "Value": str(len(rows))},
        {"Metric": "Assigned Windows Hosts With McAfee", "Value": str(len(matched_hostnames))},
        {"Metric": "Match Rule", "Value": "program name/publisher/install path/uninstall string contains McAfee"},
        {"Metric": "Source", "Value": "JumpCloud /systems, /systemusers, /v2/systeminsights/programs"},
    ]

    if output_path is None:
        report_date = datetime.now().strftime("%Y-%m-%d")
        output_path = Path("reports") / f"{DEFAULT_REPORT_PREFIX}_{report_date}.xls"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xls(output_path, rows, summary_rows)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a JumpCloud Windows assigned hosts McAfee programs report.")
    parser.add_argument("--output", type=Path, default=None, help="Output .xls path.")
    args = parser.parse_args()

    output_path = generate_windows_mcafee_report(args.output)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
