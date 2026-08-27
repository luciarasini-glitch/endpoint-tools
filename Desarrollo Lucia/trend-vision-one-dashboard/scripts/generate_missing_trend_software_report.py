from __future__ import annotations

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


MAC_TREND_APP = "TrendMicroSecurity"
WINDOWS_TREND_PROGRAM = "Trend Micro Apex One Security Agent"
DEFAULT_REPORT_PREFIX = "jumpcloud_windows_macos_sin_trend_software"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell(value: object) -> str:
    return '<Cell><Data ss:Type="String">{}</Data></Cell>'.format(escape(_text(value)))


def _worksheet(name: str, rows: list[dict[str, str]], headers: list[str]) -> str:
    parts = [f'<Worksheet ss:Name="{escape(name)}"><Table>']
    parts.append("<Row>" + "".join(_cell(header) for header in headers) + "</Row>")
    for row in rows:
        parts.append("<Row>" + "".join(_cell(row.get(header, "")) for header in headers) + "</Row>")
    parts.append("</Table></Worksheet>")
    return "".join(parts)


def _write_xls(path: Path, rows: list[dict[str, str]], summary_rows: list[dict[str, str]]) -> None:
    headers = [
        "Platform",
        "Usuario",
        "Correo",
        "Endpoint",
        "Hostname",
        "Serial",
        "OS Version",
        "Active",
        "Last Contact",
        "Expected Software",
    ]
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
            _worksheet("Missing Trend Software", rows, headers),
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


def _list_all_programs(client: JumpCloudClient, *, filter_expression: str, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        payload = client.get_json(
            "/v2/systeminsights/programs",
            params={"limit": limit, "skip": skip, "filter": filter_expression},
        )
        batch = _extract_list_payload(payload)
        if not batch:
            break
        rows.extend(batch)
        skip += len(batch)
        if len(batch) < limit:
            break
    return rows


def _app_system_id(app: dict[str, Any]) -> str:
    return _text(app.get("system_id") or app.get("systemId") or app.get("system"))


def _is_mac_trend_app(app: dict[str, Any]) -> bool:
    app_name = _text(app.get("display_name") or app.get("bundle_name") or app.get("name")).casefold()
    path = _text(app.get("path")).casefold()
    return app_name in {"trendmicrosecurity", "trendmicrosecurity.app"} or path.endswith("/trendmicrosecurity.app")


def _is_windows_trend_program(program: dict[str, Any]) -> bool:
    return _text(program.get("name")).casefold() == WINDOWS_TREND_PROGRAM.casefold()


def _normalize_name(value: str) -> str:
    return value.strip().casefold()


def generate_missing_trend_software_report(output_path: Path | None = None) -> Path:
    settings = get_settings()
    client = JumpCloudClient(settings)
    repository = SnapshotRepository(settings.db_abspath)
    service = JumpCloudInventoryService(client, repository, None)
    snapshot = repository.get_latest_snapshot()

    users = client.list_all_users(limit=100)
    systems = client.list_all_systems(limit=100)

    users_by_id: dict[str, dict[str, str]] = {}
    for user in users:
        user_id = _text(user.get("id"))
        if not user_id:
            continue
        users_by_id[user_id] = {
            "Usuario": service._build_user_name(user),
            "Correo": _text(user.get("email")),
        }

    mac_installed_system_ids: set[str] = set()
    for filter_expression in (
        "bundle_name:eq:TrendMicroSecurity",
        "display_name:eq:TrendMicroSecurity",
        "name:eq:TrendMicroSecurity.app",
    ):
        for app in client.list_all_apps(limit=200, filter_expression=filter_expression):
            if _is_mac_trend_app(app):
                system_id = _app_system_id(app)
                if system_id:
                    mac_installed_system_ids.add(system_id)

    windows_installed_system_ids: set[str] = set()
    for program in _list_all_programs(client, filter_expression=f"name:eq:{WINDOWS_TREND_PROGRAM}", limit=200):
        if _is_windows_trend_program(program):
            system_id = _app_system_id(program)
            if system_id:
                windows_installed_system_ids.add(system_id)

    trend_windows_by_name: dict[str, str] = {}
    if snapshot is not None:
        for device in snapshot.devices:
            if device.platform.strip().casefold() != "windows":
                continue
            hostname = _text(device.hostname)
            if hostname:
                trend_windows_by_name[_normalize_name(hostname)] = hostname

    rows: list[dict[str, str]] = []
    platform_counts = {"Windows": 0, "macOS": 0}
    windows_found_in_trend_by_name = 0
    for system in systems:
        platform = service._normalize_platform(system)
        if platform not in {"Windows", "macOS"}:
            continue

        platform_counts[platform] += 1
        system_id = _text(system.get("id"))
        display_name = _text(system.get("displayName"))
        hostname = _text(system.get("hostname"))
        if platform == "macOS":
            expected_software = MAC_TREND_APP
            if system_id in mac_installed_system_ids:
                continue
        else:
            expected_software = WINDOWS_TREND_PROGRAM
            if system_id in windows_installed_system_ids:
                continue
            trend_name_match = ""
            for candidate in (display_name, hostname):
                if not candidate:
                    continue
                trend_name_match = trend_windows_by_name.get(_normalize_name(candidate), "")
                if trend_name_match:
                    break
            if trend_name_match:
                windows_found_in_trend_by_name += 1
                continue

        primary_user = system.get("primarySystemUser") if isinstance(system.get("primarySystemUser"), dict) else {}
        user_info = users_by_id.get(_text(primary_user.get("id")), {})
        endpoint = display_name or hostname
        if not endpoint:
            continue

        rows.append(
            {
                "Platform": platform,
                "Usuario": user_info.get("Usuario", "Unassigned"),
                "Correo": user_info.get("Correo", ""),
                "Endpoint": endpoint,
                "Hostname": hostname,
                "Serial": _text(system.get("serialNumber")),
                "OS Version": service._resolve_os_version(system),
                "Active": _text(system.get("active")) if "active" in system else "",
                "Last Contact": _text(system.get("lastContact")),
                "Expected Software": expected_software,
            }
        )

    rows.sort(key=lambda row: (row["Platform"].lower(), row["Usuario"].lower(), row["Endpoint"].lower()))
    summary_rows = [
        {"Metric": "Generated At", "Value": datetime.now().isoformat(timespec="seconds")},
        {"Metric": "Windows Systems Total", "Value": str(platform_counts["Windows"])},
        {"Metric": "macOS Systems Total", "Value": str(platform_counts["macOS"])},
        {"Metric": "Windows Apex One Installed", "Value": str(len(windows_installed_system_ids))},
        {"Metric": "Windows Found In Trend By Name", "Value": str(windows_found_in_trend_by_name)},
        {"Metric": "macOS TrendMicroSecurity Installed", "Value": str(len(mac_installed_system_ids))},
        {"Metric": "Missing Trend Software", "Value": str(len(rows))},
        {"Metric": "Windows Expected Software", "Value": WINDOWS_TREND_PROGRAM},
        {"Metric": "macOS Expected Software", "Value": MAC_TREND_APP},
        {
            "Metric": "Source",
            "Value": "JumpCloud System Insights Apps/Programs with Windows Trend inventory name fallback",
        },
        {
            "Metric": "Trend Snapshot Generated At",
            "Value": snapshot.generated_at.isoformat() if snapshot is not None else "",
        },
    ]

    if output_path is None:
        report_date = datetime.now().strftime("%Y-%m-%d")
        output_path = Path("reports") / f"{DEFAULT_REPORT_PREFIX}_{report_date}.xls"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xls(output_path, rows, summary_rows)
    return output_path


def main() -> None:
    output_path = generate_missing_trend_software_report()
    print(output_path.resolve())


if __name__ == "__main__":
    main()
