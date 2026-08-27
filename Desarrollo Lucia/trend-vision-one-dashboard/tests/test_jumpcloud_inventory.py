from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.domain import DashboardSnapshot, DeviceRecord
from app.services.jumpcloud_inventory import JumpCloudInventoryService


class StubJumpCloudClient:
    def list_all_users(self):
        return [
            {
                "id": "user-1",
                "state": "ACTIVATED",
                "email": "alice@example.com",
                "username": "alice",
                "displayname": "Alice",
            }
        ]

    def list_all_systems(self):
        return [
            {
                "id": "sys-1",
                "displayName": "Alice MacBook",
                "hostname": "alice-mac.local",
                "serialNumber": "JC-SERIAL-1",
                "os": "Mac OS X",
                "primarySystemUser": {"id": "user-1"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            }
        ]

    def list_all_interface_details_for_system(self, system_id: str):
        assert system_id == "sys-1"
        return [
            {"interface": "en0", "mac": "AA-BB-CC-DD-EE-FF"},
            {"interface": "lo0", "mac": "00:00:00:00:00:00"},
        ]

    def list_all_apps_for_system(self, system_id: str):
        assert system_id == "sys-1"
        return []

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return []


class StubRepository:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 4, 13, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


class StubTrendClient:
    def fetch_collection(self, endpoint_name: str, params=None):  # noqa: ANN001
        assert endpoint_name == "eiqs_endpoints"
        return (
            {
                "items": [
                    {
                        "endpointName": {"value": "trend-host-1"},
                        "macAddress": {"value": ["aa:bb:cc:dd:ee:ff"]},
                    }
                ]
            },
            [],
        )


def test_jumpcloud_inventory_matches_trend_by_mac_when_serial_match_is_unavailable() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClient(), StubRepository(), StubTrendClient())

    rows = service.list_active_users_inventory()

    assert len(rows) == 1
    assert rows[0]["Trend Micro"] == "trend-host-1"
    assert rows[0]["Last Contact"].endswith("Z")


class StubJumpCloudClientWithTrendApp(StubJumpCloudClient):
    def list_all_interface_details_for_system(self, system_id: str):
        assert system_id == "sys-1"
        return []

    def list_all_apps_for_system(self, system_id: str):
        assert system_id == "sys-1"
        return [
            {
                "name": "TrendMicroSecurity.app",
                "display_name": "TrendMicroSecurity",
                "path": "/Applications/TrendMicroSecurity.app",
            }
        ]


class StubTrendClientNoData:
    def fetch_collection(self, endpoint_name: str, params=None):  # noqa: ANN001
        assert endpoint_name == "eiqs_endpoints"
        return ({"items": []}, [])


def test_jumpcloud_inventory_does_not_mark_trend_from_jumpcloud_apps_when_no_match_exists() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClientWithTrendApp(), StubRepository(), StubTrendClientNoData())

    rows = service.list_active_users_inventory()

    assert len(rows) == 1
    assert rows[0]["Trend Micro"] == ""


class StubJumpCloudClientWithDifferentDeviceForSameUser:
    def list_all_users(self):
        return [
            {
                "id": "user-angie",
                "state": "ACTIVATED",
                "email": "angiedasilva@cashea.app",
                "username": "angiedasilva",
                "displayname": "Angie Da Silva",
            }
        ]

    def list_all_systems(self):
        return [
            {
                "id": "sys-angie",
                "displayName": "DESKTOP-JDE392J",
                "hostname": "DESKTOP-JDE392J",
                "serialNumber": "JC-SERIAL-ANGIE",
                "os": "Windows",
                "primarySystemUser": {"id": "user-angie"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            }
        ]

    def list_all_interface_details_for_system(self, system_id: str):
        assert system_id == "sys-angie"
        return []

    def list_all_apps_for_system(self, system_id: str):
        assert system_id == "sys-angie"
        return []

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return []


class StubRepositoryWithDifferentTrendDeviceForSameUser:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 5, 7, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[
                DeviceRecord(
                    id="trend-angie-old",
                    hostname="DESKTOP-6F096SP",
                    platform="windows",
                    serial_number="5CD3141KC9",
                    last_logged_on_user=r"DESKTOP-6F096SP\angiedasilva",
                    owner_user_ids=[r"inferred:desktop-6f096sp\angiedasilva"],
                )
            ],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


def test_jumpcloud_inventory_does_not_match_trend_by_user_only() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithDifferentDeviceForSameUser(),
        StubRepositoryWithDifferentTrendDeviceForSameUser(),
        StubTrendClientNoData(),
    )

    rows = service.list_active_users_inventory()

    assert len(rows) == 1
    assert rows[0]["Device name"] == "DESKTOP-JDE392J"
    assert rows[0]["Trend Micro"] == ""
    assert service.list_machine_inventory()[0]["Trend Micro"] == ""


class StubJumpCloudClientWithWindowsNameMismatches:
    def list_all_users(self):
        return [
            {
                "id": "user-be93",
                "state": "ACTIVATED",
                "email": "be93@example.com",
                "displayname": "BE93 User",
            },
            {
                "id": "user-r6i",
                "state": "ACTIVATED",
                "email": "r6i@example.com",
                "displayname": "R6I User",
            },
        ]

    def list_all_systems(self):
        recent_contact = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        return [
            {
                "id": "sys-be93",
                "displayName": "DESKTOP-BE93JJ0",
                "hostname": "DESKTOP-BE93JJ0",
                "serialNumber": "SERIAL-BE93",
                "os": "Windows",
                "primarySystemUser": {"id": "user-be93"},
                "lastContact": recent_contact,
            },
            {
                "id": "sys-r6i",
                "displayName": "DESKTOP-R6IGUPR",
                "hostname": "DESKTOP-R6IGUPR",
                "serialNumber": "SERIAL-R6I",
                "os": "Windows",
                "primarySystemUser": {"id": "user-r6i"},
                "lastContact": recent_contact,
            },
        ]

    def list_all_interface_details_for_system(self, system_id: str):
        return {
            "sys-be93": [{"mac": "AA:AA:AA:AA:AA:01"}],
            "sys-r6i": [{"mac": "AA:AA:AA:AA:AA:02"}],
        }[system_id]

    def list_all_apps_for_system(self, system_id: str):
        return []

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return []


class StubRepositoryWithWindowsNameMismatches:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 5, 20, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[
                DeviceRecord(
                    id="trend-be93-other",
                    hostname="DESKTOP-OTHER-BE93",
                    platform="windows",
                    serial_number="SERIAL-BE93",
                    mac_addresses=["AA:AA:AA:AA:AA:01"],
                ),
                DeviceRecord(
                    id="trend-r6i-other",
                    hostname="DESKTOP-OTHER-R6I",
                    platform="windows",
                    serial_number="SERIAL-R6I",
                    mac_addresses=["AA:AA:AA:AA:AA:02"],
                ),
            ],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


def test_windows_inventory_requires_trend_hostname_to_equal_jumpcloud_name() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithWindowsNameMismatches(),
        StubRepositoryWithWindowsNameMismatches(),
        StubTrendClientNoData(),
    )

    active_rows = {
        row["Device name"]: row["Trend Micro"]
        for row in service.list_active_users_inventory(force_refresh=True)
    }
    machine_rows = {
        row["Display name"]: row["Trend Micro"]
        for row in service.list_machine_inventory()
    }

    assert active_rows == {
        "DESKTOP-BE93JJ0": "",
        "DESKTOP-R6IGUPR": "",
    }
    assert machine_rows == {
        "DESKTOP-BE93JJ0": "",
        "DESKTOP-R6IGUPR": "",
    }


class StubRepositoryWithWindowsCaseOnlyMatch:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 5, 20, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[
                DeviceRecord(
                    id="trend-be93",
                    hostname="desktop-be93jj0",
                    platform="windows",
                )
            ],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


def test_windows_inventory_allows_case_only_hostname_difference() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithWindowsNameMismatches(),
        StubRepositoryWithWindowsCaseOnlyMatch(),
        StubTrendClientNoData(),
    )

    rows = {
        row["Device name"]: row["Trend Micro"]
        for row in service.list_active_users_inventory(force_refresh=True)
    }

    assert rows["DESKTOP-BE93JJ0"] == "desktop-be93jj0"
    assert rows["DESKTOP-R6IGUPR"] == ""


WINDOWS_HOSTNAME_EXCEPTION_PAIRS = {
    "DESKTOP-337115140": "DESKTOP-3371151",
    "DESKTOP-1460049066": "DESKTOP-1460049",
    "DESKTOP-0D556808419": "DESKTOP-0D55680",
    "DESKTOP-1255978111": "DESKTOP-1255978",
    "DESKTOP-481888821": "DESKTOP-4818888",
    "DESKTOP-1278503138": "DESKTOP-1278503",
    "DESKTOP-0DH12NMK": "DESKTOP-0DH12NM",
    "LAPTOP-LV4AEI86": "LALTOP-LV4AEI86",
    "contratacionmasiva": "VICTORIAFERRO-C",
}


class StubJumpCloudClientWithWindowsHostnameExceptions:
    def list_all_users(self):
        return [
            {
                "id": f"user-{index}",
                "state": "ACTIVATED",
                "email": f"user-{index}@example.com",
                "displayname": f"User {index}",
            }
            for index, _hostname in enumerate(WINDOWS_HOSTNAME_EXCEPTION_PAIRS, start=1)
        ]

    def list_all_systems(self):
        recent_contact = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        return [
            {
                "id": f"sys-{index}",
                "displayName": hostname,
                "hostname": hostname,
                "serialNumber": f"SERIAL-{index}",
                "os": "Windows",
                "primarySystemUser": {"id": f"user-{index}"},
                "lastContact": recent_contact,
            }
            for index, hostname in enumerate(WINDOWS_HOSTNAME_EXCEPTION_PAIRS, start=1)
        ]

    def list_all_interface_details_for_system(self, system_id: str):
        return []

    def list_all_apps_for_system(self, system_id: str):
        return []

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return []


class StubRepositoryWithWindowsHostnameExceptions:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 5, 21, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[
                DeviceRecord(
                    id=f"trend-{index}",
                    hostname=trend_hostname,
                    platform="windows",
                )
                for index, trend_hostname in enumerate(WINDOWS_HOSTNAME_EXCEPTION_PAIRS.values(), start=1)
            ],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


def test_windows_inventory_allows_configured_hostname_exceptions() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithWindowsHostnameExceptions(),
        StubRepositoryWithWindowsHostnameExceptions(),
        StubTrendClientNoData(),
    )

    active_rows = {
        row["Device name"]: row["Trend Micro"]
        for row in service.list_active_users_inventory(force_refresh=True)
    }
    machine_rows = {
        row["Display name"]: row["Trend Micro"]
        for row in service.list_machine_inventory()
    }

    assert active_rows == WINDOWS_HOSTNAME_EXCEPTION_PAIRS
    assert machine_rows == WINDOWS_HOSTNAME_EXCEPTION_PAIRS


class StubRepositoryMissingWindowsHostnameException:
    def get_latest_snapshot(self):
        return DashboardSnapshot(
            generated_at=datetime(2026, 5, 21, 12, 0, 0),
            source_mode="live",
            users=[],
            devices=[],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )


def test_windows_hostname_exception_requires_trend_hostname_to_exist() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithWindowsHostnameExceptions(),
        StubRepositoryMissingWindowsHostnameException(),
        StubTrendClientNoData(),
    )

    rows = service.list_active_users_inventory(force_refresh=True)

    assert all(row["Trend Micro"] == "" for row in rows)


class StubJumpCloudClientWithCacheSettings:
    settings = SimpleNamespace(
        jumpcloud_base_url="https://jumpcloud.example/cache-test",
        jumpcloud_client_id="cache-test-client",
        trend_vision_one_base_url="https://trend.example/cache-test",
        trend_vision_one_eiqs_endpoints_path="/eiqs/cache-test",
        trend_vision_one_eiqs_endpoints_query="",
    )

    def list_all_users(self):
        return [
            {
                "id": "user-cache",
                "state": "ACTIVATED",
                "firstname": "Cache",
                "lastname": "Test",
                "email": "cache@example.com",
            }
        ]

    def list_all_systems(self):
        return [
            {
                "id": "sys-cache",
                "displayName": "LAPTOP-GPGFUPGH",
                "hostname": "LAPTOP-GPGFUPGH",
                "serialNumber": "5CD3282KY9",
                "os": "Windows",
                "primarySystemUser": {"id": "user-cache"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            }
        ]

    def list_all_interface_details_for_system(self, system_id: str):
        assert system_id == "sys-cache"
        return []

    def list_all_apps_for_system(self, system_id: str):
        assert system_id == "sys-cache"
        return []


class MutableSnapshotRepository:
    def __init__(self) -> None:
        self.snapshot = DashboardSnapshot(
            generated_at=datetime(2026, 5, 8, 10, 0, 0),
            source_mode="live",
            users=[],
            devices=[],
            signals=[],
            coverage=[],
            correlations=[],
            issues=[],
        )

    def get_latest_snapshot(self):
        return self.snapshot

    def last_sync_at(self):
        return self.snapshot.generated_at


def test_jumpcloud_inventory_cache_invalidates_when_trend_snapshot_changes() -> None:
    repository = MutableSnapshotRepository()
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithCacheSettings(),
        repository,
        StubTrendClientNoData(),
    )

    first_rows = service.list_active_users_inventory(force_refresh=True)
    assert first_rows[0]["Trend Micro"] == ""

    repository.snapshot = repository.snapshot.model_copy(
        update={
            "generated_at": datetime(2026, 5, 8, 10, 1, 0),
            "devices": [
                DeviceRecord(
                    id="trend-cache",
                    hostname="LAPTOP-GPGFUPGH",
                    platform="windows",
                    serial_number="5CD3282KY9",
                )
            ],
        }
    )

    second_rows = service.list_active_users_inventory()
    assert second_rows[0]["Trend Micro"] == "LAPTOP-GPGFUPGH"


class StubJumpCloudClientWithOldContact(StubJumpCloudClient):
    def list_all_systems(self):
        systems = super().list_all_systems()
        systems[0]["lastContact"] = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
        return systems


def test_jumpcloud_inventory_includes_assigned_systems_without_recent_activity() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClientWithOldContact(), StubRepository(), StubTrendClientNoData())

    rows = service.list_active_users_inventory(force_refresh=True)

    assert len(rows) == 1
    assert rows[0]["Device name"] == "Alice MacBook"
    assert rows[0]["Last Contact"]


class StubJumpCloudClientWithRecentAndroid(StubJumpCloudClient):
    def list_all_systems(self):
        systems = super().list_all_systems()
        systems.append(
            {
                "id": "sys-android",
                "displayName": "Pixel 8",
                "hostname": "pixel-8",
                "serialNumber": "ANDROID-SERIAL-1",
                "os": "Android",
                "osFamily": "android",
                "version": "15",
                "primarySystemUser": {"id": "user-1"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            }
        )
        return systems


def test_jumpcloud_inventory_excludes_android_systems() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientWithRecentAndroid(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_active_users_inventory(force_refresh=True)

    assert [row["Device name"] for row in rows] == ["Alice MacBook"]
    assert all(row["Platform"] != "Android" for row in rows)


class StubJumpCloudClientForApps:
    def list_all_users(self):
        return [
            {
                "id": "user-1",
                "state": "ACTIVATED",
                "firstname": "Alice",
                "lastname": "Doe",
                "email": "alice@example.com",
            },
            {
                "id": "user-2",
                "state": "ACTIVATED",
                "firstname": "Bob",
                "lastname": "Smith",
                "email": "bob@example.com",
            },
        ]

    def list_all_systems(self):
        return [
            {
                "id": "sys-1",
                "hostname": "alice-mac.local",
                "displayName": "Alice MacBook",
                "os": "Mac OS X",
                "primarySystemUser": {"id": "user-1"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            },
            {
                "id": "sys-2",
                "hostname": "bob-win",
                "displayName": "Bob Laptop",
                "os": "Windows",
                "primarySystemUser": {"id": "user-2"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat().replace("+00:00", "Z"),
            },
        ]

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return [
            {
                "system_id": "sys-1",
                "display_name": "Google Chrome",
                "bundle_short_version": "135.0.7049.85",
                "path": "/Applications/Google Chrome.app",
            },
            {
                "system_id": "sys-1",
                "display_name": "Slack",
                "bundle_short_version": "4.0.0",
                "path": "/Applications/Slack.app",
            },
        ]

    def list_all_programs(self, *, limit: int = 100, filter_expression: str = ""):
        return []


def test_apps_inventory_includes_google_chrome_version_for_recent_primary_device() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClientForApps(), StubRepository(), StubTrendClientNoData())

    rows = service.list_apps_inventory()

    assert rows == [
        {
            "Usuario": "Alice Doe",
            "Device": "alice-mac.local",
            "Chrome": "135.0.7049.85",
        }
    ]


class StubJumpCloudClientForAppsWithoutChrome(StubJumpCloudClientForApps):
    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return [
            {
                "system_id": "sys-1",
                "display_name": "Slack",
                "bundle_short_version": "4.0.0",
                "path": "/Applications/Slack.app",
            }
        ]


def test_apps_inventory_leaves_chrome_blank_when_google_chrome_is_not_installed() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientForAppsWithoutChrome(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_apps_inventory()

    assert rows == [
        {
            "Usuario": "Alice Doe",
            "Device": "alice-mac.local",
            "Chrome": "",
        }
    ]


class StubJumpCloudClientForAppsWithChromeHelpers(StubJumpCloudClientForApps):
    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return [
            {
                "system_id": "sys-1",
                "display_name": "Google Chrome Helper",
                "bundle_short_version": "999.0.0.0",
                "path": "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper.app",
            },
            {
                "system_id": "sys-1",
                "display_name": "Google Chrome",
                "bundle_short_version": "147.0.7727.56",
                "path": "/Applications/Google Chrome.app",
            },
        ]


def test_apps_inventory_prefers_google_chrome_over_helper_entries() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientForAppsWithChromeHelpers(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_apps_inventory()

    assert rows == [
        {
            "Usuario": "Alice Doe",
            "Device": "alice-mac.local",
            "Chrome": "147.0.7727.56",
        }
    ]


class StubJumpCloudClientForCloudflare(StubJumpCloudClientForApps):
    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return [
            {
                "system_id": "sys-1",
                "display_name": "Cloudflare WARP",
                "bundle_short_version": "2026.4.1350.0",
                "path": "/Applications/Cloudflare WARP.app",
            },
            {
                "system_id": "sys-2",
                "display_name": "Cloudflare WARP",
                "bundle_short_version": "2026.4.1350.0",
                "path": "/Applications/Cloudflare WARP.app",
            },
        ]


def _without_ultima_conexion(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{key: value for key, value in row.items() if key != "Ultima Conexion"} for row in rows]


def _find_cloudflare_row(rows: list[dict[str, str]], expected: dict[str, str]) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in expected.items()):
            return row
    raise AssertionError(f"Expected Cloudflare row not found: {expected}")


def _is_short_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def test_cloudflare_inventory_includes_warp_version_for_recent_macos_primary_device() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClientForCloudflare(), StubRepository(), StubTrendClientNoData())

    rows = service.list_cloudflare_inventory(force_refresh=True)

    assert all(_is_short_iso_date(row["Ultima Conexion"]) for row in rows)
    assert _without_ultima_conexion(rows) == [
        {
            "Usuario": "Alice Doe",
            "Correo": "alice@example.com",
            "Endpoint": "Alice MacBook",
            "Sistema operativo": "macOS",
            "Cloudflare": "2026.4.1350.0",
        },
        {
            "Usuario": "Bob Smith",
            "Correo": "bob@example.com",
            "Endpoint": "Bob Laptop",
            "Sistema operativo": "Windows",
            "Cloudflare": "",
        },
    ]


class StubJumpCloudClientForCloudflareWithOldMac(StubJumpCloudClientForCloudflare):
    def list_all_systems(self):
        systems = super().list_all_systems()
        systems.append(
            {
                "id": "sys-old-mac",
                "hostname": "bob-old-mac.local",
                "displayName": "Bob Old Mac",
                "os": "Mac OS X",
                "primarySystemUser": {"id": "user-2"},
                "lastContact": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat().replace("+00:00", "Z"),
            }
        )
        return systems

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        apps = super().list_all_apps(limit=limit, filter_expression=filter_expression)
        apps.append(
            {
                "system_id": "sys-old-mac",
                "display_name": "Cloudflare WARP",
                "bundle_short_version": "2026.4.1350.0",
                "path": "/Applications/Cloudflare WARP.app",
            }
        )
        return apps


def test_cloudflare_inventory_includes_assigned_macos_without_recent_contact() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientForCloudflareWithOldMac(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_cloudflare_inventory(force_refresh=True)

    row = _find_cloudflare_row(
        rows,
        {
            "Usuario": "Bob Smith",
            "Correo": "bob@example.com",
            "Endpoint": "Bob Old Mac",
            "Sistema operativo": "macOS",
            "Cloudflare": "2026.4.1350.0",
        },
    )
    assert _is_short_iso_date(row["Ultima Conexion"])


class StubJumpCloudClientForCloudflareWithWindowsProgram(StubJumpCloudClientForCloudflare):
    def list_all_programs(self, *, limit: int = 100, filter_expression: str = ""):
        if filter_expression != "name:eq:Cloudflare One Client":
            return []
        return [
            {
                "system_id": "sys-2",
                "name": "Cloudflare One Client",
                "version": "26.6.850.0",
                "install_date": "20260713",
            }
        ]


def test_cloudflare_inventory_detects_windows_cloudflare_one_client_program() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientForCloudflareWithWindowsProgram(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_cloudflare_inventory(force_refresh=True)

    row = _find_cloudflare_row(
        rows,
        {
            "Usuario": "Bob Smith",
            "Correo": "bob@example.com",
            "Endpoint": "Bob Laptop",
            "Sistema operativo": "Windows",
            "Cloudflare": "26.6.850.0",
        },
    )
    assert _is_short_iso_date(row["Ultima Conexion"])


class StubJumpCloudClientForCloudflareWithoutWarp(StubJumpCloudClientForApps):
    def list_all_apps(self, *, limit: int = 100, filter_expression: str = ""):
        return [
            {
                "system_id": "sys-1",
                "display_name": "Slack",
                "bundle_short_version": "4.0.0",
                "path": "/Applications/Slack.app",
            }
        ]


def test_cloudflare_inventory_leaves_cloudflare_blank_when_warp_is_not_installed() -> None:
    service = JumpCloudInventoryService(
        StubJumpCloudClientForCloudflareWithoutWarp(),
        StubRepository(),
        StubTrendClientNoData(),
    )

    rows = service.list_cloudflare_inventory(force_refresh=True)

    assert all(_is_short_iso_date(row["Ultima Conexion"]) for row in rows)
    assert _without_ultima_conexion(rows) == [
        {
            "Usuario": "Alice Doe",
            "Correo": "alice@example.com",
            "Endpoint": "Alice MacBook",
            "Sistema operativo": "macOS",
            "Cloudflare": "",
        },
        {
            "Usuario": "Bob Smith",
            "Correo": "bob@example.com",
            "Endpoint": "Bob Laptop",
            "Sistema operativo": "Windows",
            "Cloudflare": "",
        },
    ]


class StubJumpCloudClientForPhones:
    @staticmethod
    def field(value):
        return {"editable": True, "value": value}

    def list_all_asset_devices(self, *, fields=()):  # noqa: ANN001
        return [
            {
                "id": "asset-1",
                "jcSystemId": "phone-1",
                "fields": {
                    "Name": self.field("HONOR NIC-LX3"),
                    "Type": self.field({"id": "type-mobile", "name": "Mobile", "type": "select"}),
                    "Owner": self.field({"id": "user-1", "name": "Paula Gomez", "type": "user"}),
                    "OS Family": self.field("Android"),
                    "Operating System (OS)": self.field("Android"),
                    "OS Version": self.field("15.0.0"),
                    "Model": self.field("NIC-LX3"),
                    "Vendor": self.field("HONOR"),
                    "Serial Number": self.field("SN-1"),
                    "IMEI": self.field("111111111111111"),
                    "Status": self.field({"id": "status-in-use", "name": "In Use", "type": "select"}),
                    "MDM Enrollment Status": self.field("Enrolled"),
                    "Last Sync Time": self.field("2026-08-20T12:00:00Z"),
                },
            },
            {
                "id": "asset-2",
                "jcSystemId": "phone-2",
                "fields": {
                    "Name": self.field("iPhone 15"),
                    "Type": self.field("mobile"),
                    "Owner": self.field({"id": "user-2", "name": "Ana Perez", "type": "user"}),
                    "OS Family": self.field("iOS"),
                    "OS": self.field("iOS"),
                    "OS Version": self.field("18.5"),
                    "Model": self.field("iPhone 15"),
                    "Vendor": self.field("Apple"),
                    "Serial Number": self.field("SN-2"),
                    "IMEI": self.field("222222222222222"),
                    "Status": self.field("In Use"),
                    "MDM enrollment status": self.field("Enrolled"),
                    "Last Updated Time": self.field("2026-08-21T09:30:00Z"),
                },
            },
            {
                "id": "asset-3",
                "jcSystemId": "laptop-1",
                "fields": {
                    "Name": self.field("MacBook Pro"),
                    "Type": self.field({"id": "type-laptop", "name": "Laptop", "type": "select"}),
                    "Owner": self.field({"id": "user-3", "name": "Carlos Ruiz", "type": "user"}),
                },
            },
        ]


def test_phones_inventory_includes_asset_management_mobile_devices() -> None:
    service = JumpCloudInventoryService(StubJumpCloudClientForPhones(), StubRepository(), StubTrendClientNoData())

    rows = service.list_phones_inventory(force_refresh=True)

    assert rows == [
        {
            "Device": "HONOR NIC-LX3",
            "User": "Paula Gomez",
            "Type": "Mobile",
            "OS Family": "Android",
            "OS": "Android",
            "OS Version": "15.0.0",
            "Model": "NIC-LX3",
            "Vendor": "HONOR",
            "Serial Number": "SN-1",
            "IMEI": "111111111111111",
            "Status": "In Use",
            "MDM Status": "Enrolled",
            "Contact Time": "2026-08-20T12:00:00Z",
            "Asset ID": "asset-1",
        },
        {
            "Device": "iPhone 15",
            "User": "Ana Perez",
            "Type": "mobile",
            "OS Family": "iOS",
            "OS": "iOS",
            "OS Version": "18.5",
            "Model": "iPhone 15",
            "Vendor": "Apple",
            "Serial Number": "SN-2",
            "IMEI": "222222222222222",
            "Status": "In Use",
            "MDM Status": "Enrolled",
            "Contact Time": "2026-08-21T09:30:00Z",
            "Asset ID": "asset-2",
        },
    ]
