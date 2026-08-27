from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from datetime import datetime, timedelta, timezone

from app.clients.jumpcloud import JumpCloudClient
from app.clients.trend_vision_one import TrendVisionOneClient
from app.repositories.snapshot_repository import SnapshotRepository


AI_SAAS_CACHE_TTL_SECONDS = 300
ACTIVE_USERS_INVENTORY_CACHE_TTL_SECONDS = 300
PHONE_INVENTORY_CACHE_TTL_SECONDS = 300
CLOUDFLARE_INVENTORY_CACHE_TTL_SECONDS = 300
PHONE_EMM_LOOKUP_TIMEOUT_SECONDS = 10.0
PHONE_EMM_LOOKUP_WORKERS = 8
PHONE_ASSET_FIELD_LABELS = (
    "Name",
    "Type",
    "Owner",
    "Status",
    "OS Family",
    "Operating System (OS)",
    "OS",
    "OS Version",
    "Model",
    "Vendor",
    "Serial Number",
    "IMEI",
    "MFA Status",
    "Agent Status",
    "MDM Status",
    "MDM Provider",
    "Last Contact",
    "Last Updated Time",
)
_ai_saas_rows_cache: dict[str, object] = {"expires_at": 0.0, "rows": []}
_active_users_inventory_rows_cache: dict[str, object] = {"expires_at": 0.0, "rows": [], "key": ""}
_phones_inventory_rows_cache: dict[str, object] = {"expires_at": 0.0, "rows": []}
_cloudflare_inventory_rows_cache: dict[str, object] = {"expires_at": 0.0, "rows": []}
_google_emm_info_cache: dict[str, dict[str, str]] = {}


class JumpCloudInventoryService:
    TREND_HOSTNAME_EXCEPTIONS_BY_SERIAL = {
        "HKC65F0WFP": "MacBook-Pro-de-Monica",
        "MQF7V04CWW": "MacBook-Air-de-avjavegagmailcom",
    }
    WINDOWS_TREND_HOSTNAME_EXCEPTIONS = {
        "DESKTOP-337115140": "DESKTOP-3371151",
        "DESKTOP-1460049066": "DESKTOP-1460049",
        "DESKTOP-0D556808419": "DESKTOP-0D55680",
        "DESKTOP-1255978111": "DESKTOP-1255978",
        "DESKTOP-481888821": "DESKTOP-4818888",
        "DESKTOP-1278503138": "DESKTOP-1278503",
        "DESKTOP-0DH12NMK": "DESKTOP-0DH12NM",
        "LAPTOP-LV4AEI86": "LALTOP-LV4AEI86",
        "CONTRATACIONMASIVA": "VICTORIAFERRO-C",
    }
    INVENTORY_MATCH_CACHE_VERSION = "trend-real-match-only-v9"
    ACTIVITY_LOOKBACK_DAYS = 30

    def __init__(
        self,
        client: JumpCloudClient,
        repository: SnapshotRepository,
        trend_client: TrendVisionOneClient | None = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.trend_client = trend_client
        self._chrome_version_cache: dict[str, str] = {}
        self._chrome_versions_loaded = False
        self._cloudflare_warp_version_cache: dict[str, str] = {}
        self._cloudflare_warp_versions_loaded = False
        self._cloudflare_windows_version_cache: dict[str, str] = {}
        self._cloudflare_windows_versions_loaded = False
        self._google_emm_info_cache = _google_emm_info_cache

    def _active_users_inventory_cache_key(self) -> str:
        settings = getattr(self.client, "settings", None)
        if settings is None:
            return ""
        snapshot_key = "no-snapshot"
        try:
            last_sync_at = self.repository.last_sync_at()
            if last_sync_at is not None:
                snapshot_key = last_sync_at.isoformat()
        except AttributeError:
            try:
                snapshot = self.repository.get_latest_snapshot()
                if snapshot is not None:
                    snapshot_key = snapshot.generated_at.isoformat()
            except Exception:  # noqa: BLE001
                snapshot_key = "unknown-snapshot"
        return "|".join(
            [
                self.INVENTORY_MATCH_CACHE_VERSION,
                str(getattr(settings, "jumpcloud_base_url", "")),
                str(getattr(settings, "jumpcloud_client_id", "")),
                str(getattr(settings, "trend_vision_one_base_url", "")),
                str(getattr(settings, "trend_vision_one_eiqs_endpoints_path", "")),
                str(getattr(settings, "trend_vision_one_eiqs_endpoints_query", "")),
                snapshot_key,
            ]
        )

    def _get_cached_active_users_inventory_rows(self, *, force_refresh: bool) -> list[dict[str, str]] | None:
        cache_key = self._active_users_inventory_cache_key()
        if force_refresh or not cache_key:
            return None
        cached_rows = _active_users_inventory_rows_cache.get("rows", [])
        cached_expires_at = float(_active_users_inventory_rows_cache.get("expires_at") or 0.0)
        cached_key = str(_active_users_inventory_rows_cache.get("key") or "")
        if time.time() < cached_expires_at and cached_key == cache_key and isinstance(cached_rows, list):
            return [row.copy() for row in cached_rows if isinstance(row, dict)]
        return None

    def _cache_active_users_inventory_rows(self, rows: list[dict[str, str]]) -> None:
        cache_key = self._active_users_inventory_cache_key()
        if not cache_key:
            return
        _active_users_inventory_rows_cache["rows"] = [row.copy() for row in rows]
        _active_users_inventory_rows_cache["expires_at"] = time.time() + ACTIVE_USERS_INVENTORY_CACHE_TTL_SECONDS
        _active_users_inventory_rows_cache["key"] = cache_key

    @staticmethod
    def _normalize_serial(value: str) -> str:
        return value.strip().upper()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.strip().lower())

    @staticmethod
    def _normalize_hostname_exact(value: str) -> str:
        return value.strip().casefold()

    @staticmethod
    def _normalize_mac(value: str) -> str:
        hex_only = re.sub(r"[^0-9a-f]", "", value.strip().lower())
        if len(hex_only) != 12 or hex_only == "000000000000":
            return ""
        return ":".join(hex_only[index : index + 2] for index in range(0, 12, 2))

    @staticmethod
    def _normalize_platform(system: dict[str, object]) -> str:
        raw_platform = str(system.get("os") or system.get("osFamily") or system.get("platform") or "").strip()
        normalized = raw_platform.lower()
        if normalized in {"darwin", "mac", "macos", "os x", "mac os x"}:
            return "macOS"
        if normalized == "windows":
            return "Windows"
        if normalized == "linux":
            return "Linux"
        if normalized == "ios":
            return "iOS"
        if normalized == "android":
            return "Android"
        return raw_platform

    @staticmethod
    def _resolve_os_version(system: dict[str, object]) -> str:
        for key in ("osVersion", "version", "osBuildVersion", "kernelVersion", "build"):
            value = str(system.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_encryption(system: dict[str, object]) -> str:
        fde = system.get("fde")
        if isinstance(fde, dict):
            return "True" if fde.get("active") is True else "False"
        return "False"

    @staticmethod
    def _resolve_manufacturer(system: dict[str, object]) -> str:
        for key in ("manufacturer", "hwVendor", "hardwareVendor", "vendor", "systemVendor"):
            value = str(system.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _asset_field_value(asset: dict[str, object], *labels: str) -> object:
        fields = asset.get("fields")
        if not isinstance(fields, dict):
            return None

        for label in labels:
            field = fields.get(label)
            if isinstance(field, dict) and "value" in field:
                return field.get("value")
            if field is not None:
                return field

        labels_by_casefold = {str(key).casefold(): value for key, value in fields.items()}
        for label in labels:
            field = labels_by_casefold.get(label.casefold())
            if isinstance(field, dict) and "value" in field:
                return field.get("value")
            if field is not None:
                return field

        return None

    @classmethod
    def _asset_value_text(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, dict):
            for key in ("name", "displayName", "displayname", "email", "username", "value", "id"):
                nested_value = value.get(key)
                text = cls._asset_value_text(nested_value)
                if text:
                    return text
            return ""
        if isinstance(value, list):
            return ", ".join(text for text in (cls._asset_value_text(item) for item in value) if text)
        return str(value).strip()

    @classmethod
    def _asset_field_text(cls, asset: dict[str, object], *labels: str) -> str:
        return cls._asset_value_text(cls._asset_field_value(asset, *labels))

    @classmethod
    def _is_mobile_asset(cls, asset: dict[str, object]) -> bool:
        return cls._asset_field_text(asset, "Type", "Device Type").casefold() == "mobile"

    @classmethod
    def _is_recently_active(cls, system: dict[str, object]) -> bool:
        text = str(system.get("lastContact") or "").strip()
        if not text:
            return False
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            last_contact = datetime.fromisoformat(text)
        except ValueError:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(days=cls.ACTIVITY_LOOKBACK_DAYS)
        return last_contact >= cutoff

    @staticmethod
    def _format_iso_date(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            return datetime.fromisoformat(normalized).date().isoformat()
        except ValueError:
            return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else text

    @classmethod
    def _hostname_variants(cls, value: str) -> set[str]:
        raw = value.strip().lower()
        variants = {cls._normalize_text(raw)}
        for suffix in (".local", ".localdomain", ".lan"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)]
                variants.add(cls._normalize_text(raw))
        for suffix in (
            "-macbook-pro",
            "-macbook-air",
            "-macbook",
            "macbook-pro",
            "macbook-air",
            "macbook",
        ):
            if raw.endswith(suffix):
                variants.add(cls._normalize_text(raw[: -len(suffix)]))
        return {variant for variant in variants if variant}

    @staticmethod
    def _build_user_name(user: dict[str, object]) -> str:
        first_name = str(user.get("firstname") or "").strip()
        last_name = str(user.get("lastname") or "").strip()
        fallback_name = " ".join(part for part in [first_name, last_name] if part).strip()
        return (
            str(user.get("displayname") or "").strip()
            or fallback_name
            or str(user.get("username") or "").strip()
            or str(user.get("email") or "").strip()
        )

    def _extract_jc_mac_addresses(self, system_id: str) -> list[str]:
        rows = self.client.list_all_interface_details_for_system(system_id)
        macs: list[str] = []
        for row in rows:
            normalized = self._normalize_mac(str(row.get("mac") or ""))
            if normalized:
                macs.append(normalized)
        return list(dict.fromkeys(macs))

    @staticmethod
    def _is_google_chrome_app(app: dict[str, object]) -> bool:
        primary_name = str(
            app.get("display_name")
            or app.get("bundle_name")
            or app.get("name")
            or ""
        ).strip().lower()
        if primary_name in {"google chrome", "google chrome.app"}:
            return True
        path = str(app.get("path") or "").strip().lower()
        return path.endswith("/google chrome.app") or path.endswith("\\chrome.exe")

    @staticmethod
    def _is_cloudflare_warp_app(app: dict[str, object]) -> bool:
        primary_name = str(
            app.get("display_name")
            or app.get("bundle_name")
            or app.get("name")
            or ""
        ).strip().lower()
        if primary_name in {"cloudflare warp", "cloudflare warp.app"}:
            return True
        path = str(app.get("path") or "").strip().lower()
        return path.endswith("/cloudflare warp.app") or path.endswith("\\cloudflare warp.exe")

    @staticmethod
    def _is_cloudflare_windows_program(program: dict[str, object]) -> bool:
        name = str(
            program.get("name")
            or program.get("display_name")
            or program.get("displayName")
            or ""
        ).strip().lower()
        return "cloudflare" in name

    @staticmethod
    def _extract_app_version(app: dict[str, object]) -> str:
        for key in (
            "bundle_short_version",
            "version",
            "display_version",
            "bundle_version",
            "package_version",
            "current_version",
        ):
            value = str(app.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _extract_app_system_id(app: dict[str, object]) -> str:
        return str(
            app.get("system_id")
            or app.get("systemId")
            or app.get("system")
            or ""
        ).strip()

    def _chrome_version_for_system(self, system_id: str) -> str:
        if not system_id.strip():
            return ""
        if not self._chrome_versions_loaded:
            for app in self.client.list_all_apps(limit=200, filter_expression="display_name:eq:Google Chrome"):
                if not self._is_google_chrome_app(app):
                    continue
                app_system_id = self._extract_app_system_id(app)
                if not app_system_id or app_system_id in self._chrome_version_cache:
                    continue
                self._chrome_version_cache[app_system_id] = self._extract_app_version(app)
            self._chrome_versions_loaded = True
        if system_id in self._chrome_version_cache:
            return self._chrome_version_cache[system_id]
        return ""

    def _cloudflare_warp_version_for_system(self, system_id: str) -> str:
        if not system_id.strip():
            return ""
        if not self._cloudflare_warp_versions_loaded:
            for filter_expression in (
                "bundle_name:eq:Cloudflare WARP",
                "display_name:eq:Cloudflare WARP",
                "name:eq:Cloudflare WARP",
            ):
                for app in self.client.list_all_apps(limit=200, filter_expression=filter_expression):
                    if not self._is_cloudflare_warp_app(app):
                        continue
                    app_system_id = self._extract_app_system_id(app)
                    if not app_system_id or app_system_id in self._cloudflare_warp_version_cache:
                        continue
                    self._cloudflare_warp_version_cache[app_system_id] = self._extract_app_version(app)
            self._cloudflare_warp_versions_loaded = True
        if system_id in self._cloudflare_warp_version_cache:
            return self._cloudflare_warp_version_cache[system_id]
        return ""

    def _cloudflare_windows_version_for_system(self, system_id: str) -> str:
        if not system_id.strip():
            return ""
        if not self._cloudflare_windows_versions_loaded:
            for filter_expression in (
                "name:eq:Cloudflare One Client",
                "name:eq:Cloudflare WARP",
            ):
                for program in self.client.list_all_programs(limit=200, filter_expression=filter_expression):
                    if not self._is_cloudflare_windows_program(program):
                        continue
                    program_system_id = self._extract_app_system_id(program)
                    if not program_system_id or program_system_id in self._cloudflare_windows_version_cache:
                        continue
                    self._cloudflare_windows_version_cache[program_system_id] = self._extract_app_version(program)
            self._cloudflare_windows_versions_loaded = True
        if system_id in self._cloudflare_windows_version_cache:
            return self._cloudflare_windows_version_cache[system_id]
        return ""

    @staticmethod
    def _is_honor_device(system: dict[str, object]) -> bool:
        display_name = str(system.get("displayName") or "").strip().upper()
        hostname = str(system.get("hostname") or "").strip().upper()
        return display_name.startswith("HONOR") or hostname.startswith("HONOR")

    @classmethod
    def _is_phone_device(cls, system: dict[str, object]) -> bool:
        platform = str(system.get("osFamily") or system.get("os") or "").strip().lower()
        return cls._is_honor_device(system) or platform == "android"

    @staticmethod
    def _resolve_android_version(system: dict[str, object]) -> str:
        os_version_detail = system.get("osVersionDetail")
        if isinstance(os_version_detail, dict):
            version = str(os_version_detail.get("version") or "").strip()
            if version:
                return version
        for key in ("version", "osVersion", "osBuildVersion"):
            value = str(system.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_device_state(system: dict[str, object]) -> str:
        return ""

    @staticmethod
    def _google_emm_device_id(system: dict[str, object]) -> str:
        mdm = system.get("mdm")
        if not isinstance(mdm, dict):
            return ""
        internal = mdm.get("internal")
        if not isinstance(internal, dict):
            return ""
        return str(internal.get("deviceId") or "").strip()

    @staticmethod
    def _extract_google_emm_device_info(payload: dict | list) -> dict[str, str]:
        device_information = payload.get("deviceInformation") if isinstance(payload, dict) else {}
        device_state_info = device_information.get("deviceStateInfo") if isinstance(device_information, dict) else {}
        emm_enrollment_info = (
            device_information.get("emmEnrollmentInfo")
            if isinstance(device_information, dict)
            else {}
        )
        enrollment_type = (
            str(emm_enrollment_info.get("enrollmentType") or "").strip()
            if isinstance(emm_enrollment_info, dict)
            else ""
        )
        if not isinstance(device_state_info, dict):
            return {"Device State": "", "Policy Compliant": "", "Enrollment Type": enrollment_type}
        device_state = str(
            device_state_info.get("deviceState")
            or device_state_info.get("appliedDeviceState")
            or ""
        ).strip()
        policy_compliant = device_state_info.get("policyCompliant")
        policy_compliant_text = "" if policy_compliant is None else str(policy_compliant)
        return {
            "Device State": device_state,
            "Policy Compliant": policy_compliant_text,
            "Enrollment Type": enrollment_type,
        }

    def _fetch_google_emm_device_info(self, device_id: str) -> dict[str, str]:
        try:
            payload = self.client.get_google_emm_device(
                device_id,
                timeout=PHONE_EMM_LOOKUP_TIMEOUT_SECONDS,
            )
        except TypeError:
            payload = self.client.get_google_emm_device(device_id)
        except Exception:  # noqa: BLE001
            return {"Device State": "", "Policy Compliant": "", "Enrollment Type": ""}
        return self._extract_google_emm_device_info(payload)

    def _load_google_emm_device_info(self, systems: list[dict[str, object]]) -> None:
        device_ids = sorted(
            device_id
            for device_id in (self._google_emm_device_id(system) for system in systems)
            if device_id
        )
        missing_device_ids = [device_id for device_id in device_ids if device_id not in self._google_emm_info_cache]
        if not missing_device_ids:
            return

        max_workers = min(PHONE_EMM_LOOKUP_WORKERS, len(missing_device_ids))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._fetch_google_emm_device_info, device_id): device_id
                for device_id in missing_device_ids
            }
            for future in as_completed(futures):
                device_id = futures[future]
                try:
                    info = future.result()
                except Exception:  # noqa: BLE001
                    info = {"Device State": "", "Policy Compliant": "", "Enrollment Type": ""}
                self._google_emm_info_cache[device_id] = info

    def _resolve_google_emm_device_info(self, system: dict[str, object]) -> dict[str, str]:
        device_id = self._google_emm_device_id(system)
        if not device_id:
            return {"Device State": "", "Policy Compliant": "", "Enrollment Type": ""}
        if device_id in self._google_emm_info_cache:
            return self._google_emm_info_cache[device_id]
        info = self._fetch_google_emm_device_info(device_id)
        self._google_emm_info_cache[device_id] = info
        return info

    @staticmethod
    def _single_trend_match(candidates: set[str] | None) -> str:
        if not candidates:
            return ""
        hostnames = {candidate for candidate in candidates if candidate}
        if len(hostnames) != 1:
            return ""
        return next(iter(hostnames))

    def _extract_trend_eiqs_mac_index(self) -> dict[str, set[str]]:
        if self.trend_client is None:
            return {}
        try:
            payload, _issues = self.trend_client.fetch_collection("eiqs_endpoints")
        except KeyError:
            return {}
        items: list[dict[str, object]] = []
        if isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            for key in ("items", "data", "value", "records", "results", "endpoints"):
                value = payload.get(key)
                if isinstance(value, list):
                    items = [item for item in value if isinstance(item, dict)]
                    break
            if not items:
                items = [payload]

        trend_by_mac: dict[str, set[str]] = {}
        for item in items:
            endpoint_name = item.get("endpointName")
            if isinstance(endpoint_name, dict):
                endpoint_name = endpoint_name.get("value")
            hostname = str(
                endpoint_name
                or item.get("displayName")
                or item.get("hostname")
                or item.get("name")
                or ""
            ).strip()
            if not hostname:
                continue
            for key, value in item.items():
                if "mac" not in key.lower():
                    continue
                if isinstance(value, dict):
                    nested_value = value.get("value")
                    candidates = nested_value if isinstance(nested_value, list) else [nested_value]
                else:
                    candidates = value if isinstance(value, list) else [value]
                for candidate in candidates:
                    normalized_mac = self._normalize_mac(str(candidate or ""))
                    if normalized_mac:
                        trend_by_mac.setdefault(normalized_mac, set()).add(hostname)
        return trend_by_mac

    @classmethod
    def _windows_jumpcloud_name(cls, system_info: dict[str, str]) -> str:
        return str(
            system_info.get("device_name")
            or system_info.get("display_name")
            or system_info.get("hostname")
            or ""
        ).strip()

    @classmethod
    def _trend_hostname_matches_windows_name(cls, trend_hostname: str, system_info: dict[str, str]) -> bool:
        jumpcloud_name = cls._windows_jumpcloud_name(system_info)
        if not trend_hostname.strip() or not jumpcloud_name:
            return False
        return cls._normalize_hostname_exact(trend_hostname) == cls._normalize_hostname_exact(jumpcloud_name)

    def _resolve_windows_trend_match(
        self,
        system_info: dict[str, str],
        trend_by_serial: dict[str, set[str]],
        trend_by_hostname_exact: dict[str, set[str]],
    ) -> str:
        jumpcloud_name = self._windows_jumpcloud_name(system_info)
        if not jumpcloud_name:
            return ""

        matched_hostname = self._single_trend_match(
            trend_by_hostname_exact.get(self._normalize_hostname_exact(jumpcloud_name))
        )
        if matched_hostname:
            return matched_hostname

        expected_trend_hostname = self.WINDOWS_TREND_HOSTNAME_EXCEPTIONS.get(jumpcloud_name.upper(), "")
        if expected_trend_hostname:
            exception_match = self._single_trend_match(
                trend_by_hostname_exact.get(self._normalize_hostname_exact(expected_trend_hostname))
            )
            if exception_match:
                return exception_match

        serial_number = system_info.get("serial_number", "")
        normalized_serial = self._normalize_serial(serial_number) if serial_number else ""
        serial_match = self.TREND_HOSTNAME_EXCEPTIONS_BY_SERIAL.get(normalized_serial, "")
        if not serial_match and normalized_serial:
            serial_match = self._single_trend_match(trend_by_serial.get(normalized_serial))
        if self._trend_hostname_matches_windows_name(serial_match, system_info):
            return serial_match

        return ""

    def _resolve_trend_match(
        self,
        system_info: dict[str, str],
        trend_by_serial: dict[str, set[str]],
        trend_by_mac: dict[str, set[str]],
        trend_by_hostname_variant: dict[str, set[str]],
        trend_by_hostname_exact: dict[str, set[str]],
    ) -> str:
        if system_info.get("platform") == "Windows":
            return self._resolve_windows_trend_match(
                system_info,
                trend_by_serial,
                trend_by_hostname_exact,
            )

        serial_number = system_info.get("serial_number", "")
        normalized_serial = self._normalize_serial(serial_number) if serial_number else ""
        matched_hostname = self.TREND_HOSTNAME_EXCEPTIONS_BY_SERIAL.get(normalized_serial, "")
        if not matched_hostname and normalized_serial:
            matched_hostname = self._single_trend_match(trend_by_serial.get(normalized_serial))
        if not matched_hostname:
            hostname_candidates: set[str] = set()
            for candidate in (system_info.get("hostname", ""), system_info.get("display_name", ""), system_info.get("device_name", "")):
                if not candidate:
                    continue
                for variant in self._hostname_variants(candidate):
                    hostname_candidates.update(trend_by_hostname_variant.get(variant, set()))
            matched_hostname = self._single_trend_match(hostname_candidates)
        if not matched_hostname and trend_by_mac:
            for mac_address in self._extract_jc_mac_addresses(system_info.get("system_id", "")):
                matched_hostname = self._single_trend_match(trend_by_mac.get(mac_address))
                if matched_hostname:
                    break
        return matched_hostname

    def _build_trend_indexes(
        self,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
        snapshot = self.repository.get_latest_snapshot()
        trend_by_serial: dict[str, set[str]] = {}
        trend_by_mac: dict[str, set[str]] = self._extract_trend_eiqs_mac_index()
        trend_by_hostname_variant: dict[str, set[str]] = {}
        trend_by_hostname_exact: dict[str, set[str]] = {}
        for device in (snapshot.devices if snapshot else []):
            if device.serial_number and device.hostname:
                trend_by_serial.setdefault(self._normalize_serial(device.serial_number), set()).add(device.hostname)
            for mac_address in device.mac_addresses:
                normalized_mac = self._normalize_mac(mac_address)
                if normalized_mac and device.hostname:
                    trend_by_mac.setdefault(normalized_mac, set()).add(device.hostname)
            if device.hostname:
                trend_by_hostname_exact.setdefault(self._normalize_hostname_exact(device.hostname), set()).add(device.hostname)
                for variant in self._hostname_variants(device.hostname):
                    trend_by_hostname_variant.setdefault(variant, set()).add(device.hostname)
        return trend_by_serial, trend_by_mac, trend_by_hostname_variant, trend_by_hostname_exact

    @staticmethod
    def _first_non_empty(*values: object) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _value_from_path(payload: dict[str, object], *keys: str) -> str:
        current: object = payload
        for key in keys:
            if not isinstance(current, dict):
                return ""
            current = current.get(key)
        return str(current).strip() if current not in (None, "") else ""

    def _build_ai_saas_rows(self) -> list[dict[str, str]]:
        cached_rows = _ai_saas_rows_cache.get("rows", [])
        cached_expires_at = float(_ai_saas_rows_cache.get("expires_at") or 0.0)
        if time.time() < cached_expires_at and isinstance(cached_rows, list):
            return [row for row in cached_rows if isinstance(row, dict)]

        applications = self.client.list_all_saas_applications(limit=500, max_pages=5)
        accounts = self.client.list_all_saas_accounts(limit=2000, max_pages=None)

        apps_by_id: dict[str, str] = {}
        for application in applications:
            app_id = self._first_non_empty(
                application.get("id"),
                application.get("applicationId"),
                application.get("appId"),
                self._value_from_path(application, "application", "id"),
            )
            app_name = self._first_non_empty(
                application.get("name"),
                application.get("displayName"),
                application.get("applicationName"),
                application.get("appName"),
                self._value_from_path(application, "application", "name"),
            )
            if app_id and app_name:
                apps_by_id[app_id] = app_name

        rows: list[dict[str, str]] = []
        for account in accounts:
            account_email = self._first_non_empty(
                account.get("email"),
                account.get("account"),
                account.get("accountEmail"),
                account.get("username"),
                account.get("login"),
                self._value_from_path(account, "account", "email"),
                self._value_from_path(account, "account", "username"),
                self._value_from_path(account, "account", "name"),
                self._value_from_path(account, "user", "email"),
            )
            application_id = self._first_non_empty(
                account.get("applicationId"),
                account.get("appId"),
                self._value_from_path(account, "application", "id"),
            )
            app_name = self._first_non_empty(
                account.get("applicationName"),
                account.get("appName"),
                self._value_from_path(account, "application", "name"),
                apps_by_id.get(application_id, ""),
            )
            user_name = self._first_non_empty(
                self._value_from_path(account, "user", "name"),
                self._value_from_path(account, "user", "displayName"),
                self._value_from_path(account, "jumpcloudUser", "name"),
                self._value_from_path(account, "jumpcloudUser", "displayName"),
            )

            rows.append(
                {
                    "Usuario": user_name or "Unknown",
                    "Correo": account_email or "Unknown",
                    "App": app_name or "Unknown",
                }
            )

        rows.sort(key=lambda item: (item["Usuario"].lower(), item["Correo"].lower(), item["App"].lower()))
        _ai_saas_rows_cache["rows"] = rows
        _ai_saas_rows_cache["expires_at"] = time.time() + AI_SAAS_CACHE_TTL_SECONDS
        return rows

    def list_ai_saas_accounts(self, search: str = "") -> list[dict[str, str]]:
        if not self.client.settings.jumpcloud_saas_applications_path.strip() or not self.client.settings.jumpcloud_saas_accounts_path.strip():
            return []

        try:
            rows = self._build_ai_saas_rows()
        except Exception:  # noqa: BLE001
            return []

        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle in row["Usuario"].lower() or needle in row["Correo"].lower() or needle in row["App"].lower()
            ]

        rows.sort(key=lambda item: (item["Usuario"].lower(), item["Correo"].lower(), item["App"].lower()))
        return rows

    def list_active_users_inventory(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        cached_rows = self._get_cached_active_users_inventory_rows(force_refresh=force_refresh)
        if cached_rows is not None:
            return cached_rows

        try:
            users = self.client.list_all_users()
        except Exception:  # noqa: BLE001
            users = []
        try:
            systems = self.client.list_all_systems()
        except Exception:  # noqa: BLE001
            return []
        trend_by_serial, trend_by_mac, trend_by_hostname_variant, trend_by_hostname_exact = self._build_trend_indexes()

        systems_by_user_id: dict[str, list[dict[str, str]]] = {}
        for system in systems:
            primary_user = system.get("primarySystemUser")
            if not isinstance(primary_user, dict):
                continue
            user_id = primary_user.get("id")
            if not user_id:
                continue

            display_name = str(system.get("displayName") or "").strip()
            hostname = str(system.get("hostname") or "").strip()
            device_name = display_name or hostname
            if not device_name:
                continue
            if device_name.upper().startswith("HONOR") or hostname.upper().startswith("HONOR"):
                continue

            serial_number = str(system.get("serialNumber") or "").strip()
            platform = self._normalize_platform(system)
            if platform == "Android":
                continue
            os_version = self._resolve_os_version(system)
            encryption = self._resolve_encryption(system)
            manufacturer = self._resolve_manufacturer(system)
            systems_by_user_id.setdefault(user_id, []).append(
                {
                    "system_id": str(system.get("id") or "").strip(),
                    "device_name": device_name,
                    "display_name": display_name,
                    "hostname": hostname,
                    "serial_number": serial_number,
                    "platform": platform,
                    "os_version": os_version,
                    "encryption": encryption,
                    "manufacturer": manufacturer,
                    "last_contact": str(system.get("lastContact") or "").strip(),
                }
            )

        rows: list[dict[str, str]] = []
        if not users:
            for user_systems in systems_by_user_id.values():
                for system_info in sorted(
                    user_systems,
                    key=lambda item: (
                        item["device_name"].lower(),
                        item["hostname"].lower(),
                        item["serial_number"].lower(),
                    ),
                ):
                    rows.append(
                        {
                            "User ID": "",
                            "Name": "Unknown",
                            "Email": "",
                            "Display name": system_info["display_name"],
                            "Device name": system_info["device_name"],
                            "Platform": system_info["platform"],
                            "OS Version": system_info["os_version"],
                            "Encryption": system_info["encryption"],
                            "Manufacturer": system_info["manufacturer"],
                            "Serial number": system_info["serial_number"],
                            "Trend Micro": "",
                            "Last Contact": system_info["last_contact"],
                        }
                    )
            rows.sort(
                key=lambda item: (
                    item["Name"].lower(),
                    item["Display name"].lower(),
                    item["Device name"].lower(),
                    item["Serial number"].lower(),
                )
            )
            self._cache_active_users_inventory_rows(rows)
            return rows

        for user in users:
            user_state = str(user.get("state") or "").upper()
            if user_state != "ACTIVATED":
                continue

            name = self._build_user_name(user)
            email = str(user.get("email") or "").strip()
            user_systems = systems_by_user_id.get(str(user.get("id") or ""), [])

            if not user_systems:
                continue

            for system_info in sorted(
                user_systems,
                key=lambda item: (
                    item["device_name"].lower(),
                    item["hostname"].lower(),
                    item["serial_number"].lower(),
                ),
            ):
                if not system_info["display_name"]:
                    continue
                serial_number = system_info["serial_number"]
                matched_hostname = self._resolve_trend_match(
                    system_info,
                    trend_by_serial,
                    trend_by_mac,
                    trend_by_hostname_variant,
                    trend_by_hostname_exact,
                )
                rows.append(
                    {
                        "User ID": str(user.get("id") or "").strip(),
                        "Name": name,
                        "Email": email,
                        "Display name": system_info["display_name"],
                        "Device name": system_info["device_name"],
                        "Platform": system_info["platform"],
                        "OS Version": system_info["os_version"],
                        "Encryption": system_info["encryption"],
                        "Manufacturer": system_info["manufacturer"],
                        "Serial number": serial_number,
                        "Trend Micro": matched_hostname,
                        "Last Contact": system_info["last_contact"],
                    }
                )

        rows.sort(
            key=lambda item: (
                item["Name"].lower(),
                item["Email"].lower(),
                item["Display name"].lower(),
                item["Device name"].lower(),
                item["Platform"].lower(),
                item["OS Version"].lower(),
                item["Encryption"].lower(),
                item["Manufacturer"].lower(),
                item["Serial number"].lower(),
            )
        )
        self._cache_active_users_inventory_rows(rows)
        return rows

    def list_machine_inventory(self) -> list[dict[str, str]]:
        try:
            systems = self.client.list_all_systems()
        except Exception:  # noqa: BLE001
            return []
        try:
            users = self.client.list_all_users()
        except Exception:  # noqa: BLE001
            users = []
        trend_by_serial, trend_by_mac, trend_by_hostname_variant, trend_by_hostname_exact = self._build_trend_indexes()
        users_by_id: dict[str, dict[str, str]] = {}
        for user in users:
            user_id = str(user.get("id") or "").strip()
            if not user_id:
                continue
            users_by_id[user_id] = {
                "name": self._build_user_name(user),
                "email": str(user.get("email") or "").strip(),
                "username": str(user.get("username") or "").strip(),
            }

        rows: list[dict[str, str]] = []
        for system in systems:
            if not self._is_recently_active(system):
                continue
            os_family = str(system.get("osFamily") or "").strip().lower()
            if os_family == "android":
                continue
            if system.get("active") is False:
                continue

            display_name = str(system.get("displayName") or "").strip()
            hostname = str(system.get("hostname") or "").strip()
            device_name = display_name or hostname
            if not device_name:
                continue
            if device_name.upper().startswith("HONOR") or hostname.upper().startswith("HONOR"):
                continue

            serial_number = str(system.get("serialNumber") or "").strip()
            system_id = str(system.get("id") or "").strip()
            primary_user = system.get("primarySystemUser") if isinstance(system.get("primarySystemUser"), dict) else {}
            primary_user_id = str(primary_user.get("id") or "").strip()
            primary_user_info = users_by_id.get(primary_user_id, {})
            primary_user_name = primary_user_info.get("name", "")
            primary_user_email = primary_user_info.get("email", "")
            primary_user_username = primary_user_info.get("username", "")
            primary_user_label = primary_user_email or primary_user_username or primary_user_name or primary_user_id or "Unknown"
            matched_hostname = self._resolve_trend_match(
                {
                    "system_id": system_id,
                    "device_name": device_name,
                    "display_name": display_name,
                    "hostname": hostname,
                    "serial_number": serial_number,
                    "platform": self._normalize_platform(system),
                },
                trend_by_serial,
                trend_by_mac,
                trend_by_hostname_variant,
                trend_by_hostname_exact,
            )

            rows.append(
                {
                    "Display name": display_name,
                    "Hostname": hostname,
                    "Serial number": serial_number,
                    "Primary user": primary_user_label,
                    "Trend Micro": matched_hostname,
                    "Last Contact": str(system.get("lastContact") or "").strip(),
                }
            )

        rows.sort(
            key=lambda item: (
                item["Display name"].lower(),
                item["Hostname"].lower(),
                item["Serial number"].lower(),
            )
        )
        return rows

    def list_apps_inventory(self) -> list[dict[str, str]]:
        try:
            users = self.client.list_all_users()
        except Exception:  # noqa: BLE001
            users = []
        try:
            systems = self.client.list_all_systems()
        except Exception:  # noqa: BLE001
            return []

        users_by_id: dict[str, dict[str, str]] = {}
        for user in users:
            user_id = str(user.get("id") or "").strip()
            if not user_id:
                continue
            users_by_id[user_id] = {
                "name": self._build_user_name(user),
                "state": str(user.get("state") or "").strip().upper(),
            }

        rows: list[dict[str, str]] = []
        for system in systems:
            if not self._is_recently_active(system):
                continue
            if self._normalize_platform(system) == "Android":
                continue

            primary_user = system.get("primarySystemUser")
            if not isinstance(primary_user, dict):
                continue

            primary_user_id = str(primary_user.get("id") or "").strip()
            if not primary_user_id:
                continue

            user_info = users_by_id.get(primary_user_id)
            if not user_info:
                user_info = {"name": "Unknown", "state": "ACTIVATED"}
            elif user_info.get("state") != "ACTIVATED":
                continue

            hostname = str(system.get("hostname") or "").strip()
            display_name = str(system.get("displayName") or "").strip()
            device = hostname or display_name
            if not device:
                continue
            if device.upper().startswith("HONOR") or hostname.upper().startswith("HONOR"):
                continue

            rows.append(
                {
                    "Usuario": user_info["name"],
                    "Device": device,
                    "Chrome": self._chrome_version_for_system(str(system.get("id") or "").strip()),
                }
            )

        rows.sort(key=lambda item: (item["Usuario"].lower(), item["Device"].lower(), item["Chrome"].lower()))
        return rows

    def list_cloudflare_inventory(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        cached_rows = _cloudflare_inventory_rows_cache.get("rows", [])
        cached_expires_at = float(_cloudflare_inventory_rows_cache.get("expires_at") or 0.0)
        if (
            not force_refresh
            and time.time() < cached_expires_at
            and isinstance(cached_rows, list)
        ):
            return [row.copy() for row in cached_rows if isinstance(row, dict)]

        try:
            users = self.client.list_all_users()
        except Exception:  # noqa: BLE001
            users = []
        try:
            systems = self.client.list_all_systems()
        except Exception:  # noqa: BLE001
            return []

        users_by_id: dict[str, dict[str, str]] = {}
        for user in users:
            user_id = str(user.get("id") or "").strip()
            if not user_id:
                continue
            users_by_id[user_id] = {
                "name": self._build_user_name(user),
                "email": str(user.get("email") or "").strip(),
                "state": str(user.get("state") or "").strip().upper(),
            }

        rows: list[dict[str, str]] = []
        for system in systems:
            platform = self._normalize_platform(system)
            if platform not in {"macOS", "Windows"}:
                continue

            primary_user = system.get("primarySystemUser")
            if not isinstance(primary_user, dict):
                continue

            primary_user_id = str(primary_user.get("id") or "").strip()
            if not primary_user_id:
                continue

            user_info = users_by_id.get(primary_user_id)
            if not user_info:
                user_info = {"name": "Unknown", "email": "", "state": "ACTIVATED"}
            elif user_info.get("state") != "ACTIVATED":
                continue

            display_name = str(system.get("displayName") or "").strip()
            if not display_name:
                continue
            system_id = str(system.get("id") or "").strip()
            last_contact = self._format_iso_date(system.get("lastContact"))
            cloudflare_version = (
                self._cloudflare_warp_version_for_system(system_id)
                if platform == "macOS"
                else self._cloudflare_windows_version_for_system(system_id)
            )

            rows.append(
                {
                    "Usuario": user_info["name"],
                    "Correo": user_info["email"],
                    "Endpoint": display_name,
                    "Ultima Conexion": last_contact,
                    "Sistema operativo": platform,
                    "Cloudflare": cloudflare_version,
                }
            )

        rows.sort(
            key=lambda item: (
                item["Usuario"].lower(),
                item["Correo"].lower(),
                item["Sistema operativo"].lower(),
                item["Endpoint"].lower(),
                item["Ultima Conexion"].lower(),
                item["Cloudflare"].lower(),
            )
        )
        _cloudflare_inventory_rows_cache["rows"] = [row.copy() for row in rows]
        _cloudflare_inventory_rows_cache["expires_at"] = time.time() + CLOUDFLARE_INVENTORY_CACHE_TTL_SECONDS
        return rows

    def list_phones_inventory(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        cached_rows = _phones_inventory_rows_cache.get("rows", [])
        cached_expires_at = float(_phones_inventory_rows_cache.get("expires_at") or 0.0)
        if (
            not force_refresh
            and time.time() < cached_expires_at
            and isinstance(cached_rows, list)
        ):
            return [row.copy() for row in cached_rows if isinstance(row, dict)]

        try:
            assets = self.client.list_all_asset_devices(fields=PHONE_ASSET_FIELD_LABELS)
        except Exception:  # noqa: BLE001
            try:
                assets = self.client.list_all_asset_devices()
            except Exception:  # noqa: BLE001
                return []

        rows: list[dict[str, str]] = []
        for asset in assets:
            if not self._is_mobile_asset(asset):
                continue

            device_name = self._asset_field_text(asset, "Name", "Device", "Device Name")
            if not device_name:
                continue

            rows.append(
                {
                    "Device": device_name,
                    "User": self._asset_field_text(asset, "Owner", "Assigned To", "Primary User", "User"),
                    "Type": self._asset_field_text(asset, "Type", "Device Type"),
                    "OS Family": self._asset_field_text(asset, "OS Family"),
                    "OS": self._asset_field_text(asset, "Operating System (OS)", "Operating System", "OS"),
                    "OS Version": self._asset_field_text(asset, "OS Version"),
                    "Model": self._asset_field_text(asset, "Model"),
                    "Vendor": self._asset_field_text(asset, "Vendor"),
                    "Serial Number": self._asset_field_text(asset, "Serial Number"),
                    "IMEI": self._asset_field_text(asset, "IMEI"),
                    "Status": self._asset_field_text(asset, "Status"),
                    "MDM Status": self._asset_field_text(
                        asset,
                        "MDM Enrollment Status",
                        "MDM enrollment status",
                        "MDM Status",
                    ),
                    "Contact Time": self._asset_field_text(
                        asset,
                        "Last Sync Time",
                        "Last Sync Date",
                        "Last Contact",
                        "Last Updated Time",
                    ),
                    "Asset ID": str(asset.get("id") or "").strip(),
                }
            )

        rows.sort(
            key=lambda item: (
                item["Device"].lower(),
                item["User"].lower(),
                item["Type"].lower(),
                item["OS Family"].lower(),
                item["OS"].lower(),
                item["OS Version"].lower(),
                item["Model"].lower(),
                item["Serial Number"].lower(),
                item["Contact Time"].lower(),
            )
        )
        _phones_inventory_rows_cache["rows"] = [row.copy() for row in rows]
        _phones_inventory_rows_cache["expires_at"] = time.time() + PHONE_INVENTORY_CACHE_TTL_SECONDS
        return rows
