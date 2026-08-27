from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.clients.jumpcloud import JumpCloudClient
from app.core.config import get_settings
from app.services.jumpcloud_inventory import JumpCloudInventoryService


def _read_hostnames(path: Path) -> tuple[list[str], list[str]]:
    rows: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if row and row[0].strip():
                rows.append(row[0].strip())

    seen: set[str] = set()
    unique: list[str] = []
    duplicates: list[str] = []
    for hostname in rows:
        key = hostname.casefold()
        if key in seen:
            duplicates.append(hostname)
            continue
        seen.add(key)
        unique.append(hostname)
    return unique, duplicates


def _system_id(system: dict[str, object]) -> str:
    return str(system.get("id") or system.get("_id") or "").strip()


def run_command(command_id: str, csv_path: Path, output_prefix: str, target_platform: str = "Windows") -> Path:
    requested, duplicates = _read_hostnames(csv_path)
    client = JumpCloudClient(get_settings())
    command = client.get_json(f"/commands/{command_id}")
    systems = client.list_all_systems(limit=100)

    by_hostname: dict[str, dict[str, object]] = {}
    for system in systems:
        for key in ("displayName", "hostname"):
            value = str(system.get(key) or "").strip()
            if value:
                by_hostname.setdefault(value.casefold(), system)

    matched: list[dict[str, object]] = []
    missing: list[str] = []
    platform_mismatches: list[dict[str, str]] = []
    normalized_target_platform = target_platform.strip()
    for hostname in requested:
        system = by_hostname.get(hostname.casefold())
        if not system:
            missing.append(hostname)
            continue
        platform = JumpCloudInventoryService._normalize_platform(system)
        if normalized_target_platform.casefold() not in {"all", "any"} and platform != normalized_target_platform:
            platform_mismatches.append(
                {
                    "requested_hostname": hostname,
                    "system_id": _system_id(system),
                    "os": str(system.get("os") or system.get("osFamily") or system.get("platform") or ""),
                    "platform": platform,
                }
            )
            continue
        matched.append(
            {
                "requested_hostname": hostname,
                "system_id": _system_id(system),
                "display_name": str(system.get("displayName") or ""),
                "hostname": str(system.get("hostname") or ""),
                "os": str(system.get("os") or system.get("osFamily") or system.get("platform") or ""),
                "active": system.get("active"),
                "last_contact": str(system.get("lastContact") or ""),
                "agent_version": str(system.get("agentVersion") or ""),
            }
        )

    system_ids = [str(item["system_id"]) for item in matched if item["system_id"]]
    if missing or platform_mismatches or len(system_ids) != len(matched):
        raise RuntimeError(
            "Validation failed before command run: "
            f"missing={len(missing)} platform_mismatches={len(platform_mismatches)} "
            f"ids={len(system_ids)} matched={len(matched)} target_platform={normalized_target_platform}"
        )

    started_at = datetime.now(timezone.utc)
    response = client.request(
        "POST",
        "/runCommand",
        json_body={"_id": command_id, "systemIds": system_ids},
        timeout=60.0,
    )
    try:
        run_response = response.json()
    except ValueError:
        run_response = {"raw_text": response.text}

    metadata = {
        "command_id": command_id,
        "command_name": command.get("name") if isinstance(command, dict) else "",
        "command_type": command.get("commandType") if isinstance(command, dict) else "",
        "target_platform": normalized_target_platform,
        "started_at_utc": started_at.isoformat(),
        "csv_path": str(csv_path),
        "requested_count": len(requested),
        "executed_count": len(system_ids),
        "http_status": response.status_code,
        "run_response": run_response,
        "systems": matched,
        "skipped": {
            "missing": missing,
            "duplicates": duplicates,
            "nonwindows": platform_mismatches if normalized_target_platform == "Windows" else [],
            "platform_mismatches": platform_mismatches,
        },
    }

    output_path = Path("reports") / f"{output_prefix}_{started_at.strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a JumpCloud command against Windows hostnames from a CSV.")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output-prefix", default="jumpcloud_command_run_meta")
    parser.add_argument("--platform", default="Windows", help="Required normalized platform: Windows, macOS, or any.")
    args = parser.parse_args()

    output_path = run_command(args.command_id, args.csv, args.output_prefix, args.platform)
    print(output_path.resolve())


if __name__ == "__main__":
    main()
