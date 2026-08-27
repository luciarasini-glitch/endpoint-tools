from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.clients.jumpcloud import JumpCloudClient
from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import get_settings
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.dashboard import DashboardService
from app.services.ingestion import IngestionService
from app.services.jumpcloud_inventory import JumpCloudInventoryService
from app.services.normalizer import NormalizationService


DEFAULT_REPORT_PREFIX = "jumpcloud_windows_macos_trend_match_grid"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _single_or_join(values: set[str] | None) -> str:
    if not values:
        return ""
    return " | ".join(sorted(value for value in values if value))


def _cell(value: object) -> str:
    return f'<Cell><Data ss:Type="String">{escape(_text(value))}</Data></Cell>'


def _worksheet(name: str, data_rows: list[dict[str, str]], headers: list[str]) -> str:
    parts = [f'<Worksheet ss:Name="{escape(name)}"><Table>']
    parts.append("<Row>" + "".join(_cell(header) for header in headers) + "</Row>")
    for row in data_rows:
        parts.append("<Row>" + "".join(_cell(row.get(header, "")) for header in headers) + "</Row>")
    parts.append("</Table></Worksheet>")
    return "".join(parts)


def _write_xls(path: Path, devices_rows: list[dict[str, str]], summary_rows: list[dict[str, str]]) -> None:
    device_headers = [
        "JumpCloud Device Name",
        "JumpCloud Hostname",
        "Platform",
        "OS Version",
        "Owner Email",
        "Owner Name",
        "User State",
        "Serial Number",
        "Active",
        "Last Contact",
        "Trend Installed",
        "Trend Hostname Match",
        "JumpCloud Trend App Version",
        "Match Method",
    ]
    summary_headers = ["Metric", "Value"]
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
            _worksheet("Devices", devices_rows, device_headers),
            _worksheet("Summary", summary_rows, summary_headers),
            "</Workbook>",
        ]
    )
    path.write_text(workbook, encoding="utf-8")


def _sync_trend_inventory(settings) -> object:  # noqa: ANN001
    repository = SnapshotRepository(settings.db_abspath)
    client = TrendVisionOneClient(settings)
    service = DashboardService(
        repository,
        IngestionService(settings, client),
        NormalizationService(),
        settings.app_cache_ttl_minutes,
    )
    return service.sync_inventory(force=True)


def generate_matches_report(*, output_path: Path | None = None, sync_trend: bool = True) -> Path:
    settings = get_settings()
    repository = SnapshotRepository(settings.db_abspath)

    if sync_trend:
        snapshot = _sync_trend_inventory(settings)
    else:
        snapshot = repository.get_latest_snapshot()

    if snapshot is None:
        raise RuntimeError("No Trend snapshot available. Run with sync enabled first.")

    jumpcloud_client = JumpCloudClient(settings)
    inventory_service = JumpCloudInventoryService(jumpcloud_client, repository, None)

    systems = jumpcloud_client.list_all_systems(limit=100)
    users = jumpcloud_client.list_all_users(limit=100)
    users_by_id: dict[str, dict[str, str]] = {}
    for user in users:
        user_id = _text(user.get("id"))
        if not user_id:
            continue
        users_by_id[user_id] = {
            "email": _text(user.get("email")),
            "name": inventory_service._build_user_name(user),
            "state": _text(user.get("state")),
        }

    trend_by_hostname: dict[str, set[str]] = {}
    trend_by_serial: dict[str, set[str]] = {}
    for device in snapshot.devices:
        hostname = _text(device.hostname)
        serial = _text(device.serial_number)
        if hostname:
            trend_by_hostname.setdefault(hostname.casefold(), set()).add(hostname)
        if serial:
            trend_by_serial.setdefault(inventory_service._normalize_serial(serial), set()).add(hostname or serial)

    def is_jumpcloud_trend_app(app: dict[str, object]) -> bool:
        app_name = _text(
            app.get("display_name")
            or app.get("bundle_name")
            or app.get("name")
            or ""
        ).casefold()
        if app_name in {"trendmicrosecurity", "trendmicrosecurity.app"}:
            return True
        path = _text(app.get("path")).casefold()
        return path.endswith("/trendmicrosecurity.app") or path.endswith("\\trendmicrosecurity.exe")

    def extract_app_system_id(app: dict[str, object]) -> str:
        return _text(app.get("system_id") or app.get("systemId") or app.get("system"))

    def extract_app_version(app: dict[str, object]) -> str:
        for key in (
            "bundle_short_version",
            "version",
            "display_version",
            "bundle_version",
            "package_version",
            "current_version",
        ):
            value = _text(app.get(key))
            if value:
                return value
        return ""

    trend_app_versions_by_system_id: dict[str, str] = {}
    for filter_expression in (
        "bundle_name:eq:TrendMicroSecurity",
        "display_name:eq:TrendMicroSecurity",
        "name:eq:TrendMicroSecurity",
        "name:eq:TrendMicroSecurity.app",
    ):
        for app in jumpcloud_client.list_all_apps(limit=200, filter_expression=filter_expression):
            if not is_jumpcloud_trend_app(app):
                continue
            system_id = extract_app_system_id(app)
            if not system_id or system_id in trend_app_versions_by_system_id:
                continue
            trend_app_versions_by_system_id[system_id] = extract_app_version(app)

    def resolve_owner(system: dict[str, object]) -> tuple[str, str, str]:
        primary_user = system.get("primarySystemUser") if isinstance(system.get("primarySystemUser"), dict) else {}
        user_id = _text(primary_user.get("id"))
        if not user_id:
            return "Unassigned", "", ""
        user = users_by_id.get(user_id)
        if not user:
            return "Unassigned", "", user_id
        return user.get("email") or "Unassigned", user.get("name", ""), user.get("state", "")

    def resolve_trend_match(device_name: str, hostname: str, serial: str, system_id: str) -> tuple[str, str, str, str]:
        matched: set[str] = set()
        methods: list[str] = []

        for candidate in (hostname, device_name):
            candidate = _text(candidate)
            if not candidate:
                continue
            hostname_matches = trend_by_hostname.get(candidate.casefold())
            if hostname_matches:
                matched.update(hostname_matches)
                if "hostname" not in methods:
                    methods.append("hostname")

        normalized_serial = inventory_service._normalize_serial(serial) if serial else ""
        if normalized_serial:
            serial_matches = trend_by_serial.get(normalized_serial)
            if serial_matches:
                matched.update(serial_matches)
                methods.append("serial_number")

        expected_exception = inventory_service.WINDOWS_TREND_HOSTNAME_EXCEPTIONS.get(device_name.upper(), "")
        if expected_exception:
            exception_matches = trend_by_hostname.get(expected_exception.casefold())
            if exception_matches:
                matched.update(exception_matches)
                methods.append("hostname_exception")

        trend_hostname = _single_or_join(matched)
        trend_app_version = trend_app_versions_by_system_id.get(system_id, "")
        if trend_app_version or trend_hostname:
            if trend_app_version and "jumpcloud_apps" not in methods:
                methods.append("jumpcloud_apps")
            return ("Yes", trend_hostname, trend_app_version, " + ".join(dict.fromkeys(methods)))
        return ("No", "", "", "")

    report_rows: list[dict[str, str]] = []
    platform_counts = Counter()
    trend_counts = Counter()
    for system in systems:
        platform = inventory_service._normalize_platform(system)
        if platform not in {"Windows", "macOS"}:
            continue

        display_name = _text(system.get("displayName"))
        hostname = _text(system.get("hostname"))
        device_name = display_name or hostname
        serial = _text(system.get("serialNumber"))
        system_id = _text(system.get("id"))
        owner_email, owner_name, user_state = resolve_owner(system)
        trend_installed, trend_hostname, trend_app_version, match_method = resolve_trend_match(
            device_name,
            hostname,
            serial,
            system_id,
        )

        platform_counts[platform] += 1
        trend_counts[trend_installed] += 1
        report_rows.append(
            {
                "JumpCloud Device Name": device_name,
                "JumpCloud Hostname": hostname,
                "Platform": platform,
                "OS Version": inventory_service._resolve_os_version(system),
                "Owner Email": owner_email,
                "Owner Name": owner_name,
                "User State": user_state,
                "Serial Number": serial,
                "Active": _text(system.get("active")) if "active" in system else "",
                "Last Contact": _text(system.get("lastContact")),
                "Trend Installed": trend_installed,
                "Trend Hostname Match": trend_hostname,
                "JumpCloud Trend App Version": trend_app_version,
                "Match Method": match_method,
            }
        )

    report_rows.sort(
        key=lambda row: (
            row["Platform"].lower(),
            row["JumpCloud Device Name"].lower(),
            row["Serial Number"].lower(),
        )
    )

    summary_rows = [
        {"Metric": "Generated At", "Value": datetime.now().isoformat(timespec="seconds")},
        {"Metric": "Trend Snapshot Generated At", "Value": snapshot.generated_at.isoformat()},
        {"Metric": "JumpCloud Systems Total", "Value": str(len(systems))},
        {"Metric": "Rows In Report Windows/macOS", "Value": str(len(report_rows))},
        {"Metric": "Windows Rows", "Value": str(platform_counts["Windows"])},
        {"Metric": "macOS Rows", "Value": str(platform_counts["macOS"])},
        {"Metric": "Trend Installed Yes", "Value": str(trend_counts["Yes"])},
        {"Metric": "Trend Installed No", "Value": str(trend_counts["No"])},
        {
            "Metric": "Match Rule",
            "Value": "Trend inventory hostname/displayName or serial number; saved hostname exceptions; JumpCloud Apps TrendMicroSecurity fallback",
        },
        {
            "Metric": "Owner Rule",
            "Value": "Owner Email from JumpCloud primarySystemUser; Unassigned when no assigned email/user",
        },
    ]

    if output_path is None:
        report_date = datetime.now().strftime("%Y-%m-%d")
        output_path = Path("reports") / f"{DEFAULT_REPORT_PREFIX}_{report_date}.xls"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xls(output_path, report_rows, summary_rows)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JumpCloud Windows/macOS to Trend match report.")
    parser.add_argument("--output", type=Path, default=None, help="Output .xls path.")
    parser.add_argument("--skip-trend-sync", action="store_true", help="Use the existing Trend snapshot instead of syncing first.")
    args = parser.parse_args()

    output_path = generate_matches_report(output_path=args.output, sync_trend=not args.skip_trend_sync)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
