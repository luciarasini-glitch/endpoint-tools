from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from app.core.security import sanitize_text
from app.models.domain import (
    CorrelationLink,
    CoverageRecord,
    DashboardSnapshot,
    DeviceRecord,
    SignalRecord,
    SyncIssue,
    UserRecord,
)

BLOCKED_OAT_PARENT_NAMES = {
    r"c:\program files\jumpcloud\jumpcloud-agent.exe",
    r"c:\program files\jumpcloud\jumpcloud-agent-updater.exe",
    r"c:\windows\system32\services.exe",
}
BLOCKED_OAT_PARENT_SUBSTRINGS = (
    r"\jumpcloud\jumpcloud-agent",
)


def _items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "value", "records", "users", "devices", "alerts", "products"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _pick(item: dict[str, Any], *keys: str, default: str | None = None) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return sanitize_text(value)
    return default


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raw_text = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(raw_text, fmt)
            except ValueError:
                continue
        return None


def _extract_workbench_host(item: dict[str, Any]) -> str | None:
    impact_scope = item.get("impactScope")
    if isinstance(impact_scope, dict):
        entities = impact_scope.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                entity_value = entity.get("entityValue")
                if isinstance(entity_value, dict):
                    name = entity_value.get("name")
                    if name not in (None, ""):
                        return sanitize_text(name)
                name = entity.get("name")
                if name not in (None, ""):
                    return sanitize_text(name)

    indicators = item.get("indicators")
    if isinstance(indicators, list):
        for indicator in indicators:
            if not isinstance(indicator, dict):
                continue
            field_name = str(indicator.get("field") or "").strip().lower()
            if field_name == "endpointhostname":
                value = indicator.get("value")
                if value not in (None, ""):
                    return sanitize_text(value)
    return None


def _clean_endpoint_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = sanitize_text(value).strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip()
    return cleaned or None


def _normalize_mac(value: Any) -> str | None:
    text = sanitize_text(value).strip().lower() if value not in (None, "") else ""
    if not text:
        return None
    hex_only = re.sub(r"[^0-9a-f]", "", text)
    if len(hex_only) != 12:
        return None
    if hex_only == "000000000000":
        return None
    return ":".join(hex_only[index : index + 2] for index in range(0, 12, 2))


def _extract_mac_addresses(payload: Any) -> list[str]:
    matches: list[str] = []

    def walk(value: Any, key_hint: str = "") -> None:
        if isinstance(value, dict) and key_hint:
            lowered_key = key_hint.lower()
            if any(token in lowered_key for token in ("mac", "ethernet", "physicaladdress", "hardwareaddress")):
                nested_value = value.get("value")
                if isinstance(nested_value, list):
                    for item in nested_value:
                        normalized = _normalize_mac(item)
                        if normalized:
                            matches.append(normalized)
                else:
                    normalized = _normalize_mac(nested_value)
                    if normalized:
                        matches.append(normalized)
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, str(key))
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested, key_hint)
            return
        if not key_hint:
            return
        lowered_key = key_hint.lower()
        if not any(token in lowered_key for token in ("mac", "ethernet", "physicaladdress", "hardwareaddress")):
            return
        normalized = _normalize_mac(value)
        if normalized:
            matches.append(normalized)

    walk(payload)
    return list(dict.fromkeys(matches))


def _extract_device_identifier(item: dict[str, Any]) -> str | None:
    return _pick(item, "id", "deviceId", "endpointId", "agentGuid", "guid")


def _extract_workbench_device_id(item: dict[str, Any]) -> str | None:
    direct_id = _pick(item, "deviceId", "endpointId", "agentGuid")
    if direct_id:
        return direct_id

    impact_scope = item.get("impactScope")
    if isinstance(impact_scope, dict):
        entities = impact_scope.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                entity_id = entity.get("entityId")
                if entity_id not in (None, ""):
                    return sanitize_text(entity_id)
                entity_value = entity.get("entityValue")
                if isinstance(entity_value, dict):
                    guid = entity_value.get("guid")
                    if guid not in (None, ""):
                        return sanitize_text(guid)
    return None


def _is_blocked_oat_detection(item: dict[str, Any]) -> bool:
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    parent_name = str(detail.get("parentName") or "").strip().lower()
    if not parent_name:
        return False
    if parent_name in BLOCKED_OAT_PARENT_NAMES:
        return True
    return any(token in parent_name for token in BLOCKED_OAT_PARENT_SUBSTRINGS)
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _identity_variants(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = sanitize_text(value).strip()
    if not cleaned:
        return []
    lowered = cleaned.lower()
    variants = {lowered}
    if "\\" in lowered:
        variants.add(lowered.split("\\", 1)[1])
    if "@" in lowered:
        local_part = lowered.split("@", 1)[0]
        variants.add(local_part)
        if "\\" in local_part:
            variants.add(local_part.split("\\", 1)[1])
    return [variant for variant in variants if variant]


def _build_inferred_user(owner: str) -> UserRecord:
    normalized = sanitize_text(owner).strip()
    lowered = normalized.lower()
    display_name = normalized.split("\\", 1)[1] if "\\" in normalized else normalized.split("@", 1)[0]
    return UserRecord(
        id=f"inferred:{lowered}",
        display_name=display_name or normalized,
        email=normalized if "@" in normalized else None,
        status="inferred",
        source="endpoint_inventory",
    )


class NormalizationService:
    def build_snapshot(self, payload: dict[str, Any], issues: list[SyncIssue], source_mode: str) -> DashboardSnapshot:
        raw_devices = _items(payload.get("endpoint_inventory"))
        users = self._normalize_users(payload.get("users"))
        devices = self._normalize_devices(raw_devices)
        self._merge_eiqs_devices(devices, payload.get("eiqs_endpoints"))
        signals = self._normalize_signals(
            payload.get("risk_insights"),
            payload.get("workbench_alerts"),
            payload.get("oat_detections"),
        )
        coverage = self._normalize_coverage(payload.get("connected_products"), raw_devices)
        users = self._merge_inferred_users(users, devices)

        user_index = {user.id: user for user in users}
        device_index = {device.id: device for device in devices}
        signal_index = {signal.id: signal for signal in signals}

        correlations = self._correlate(user_index, device_index)

        for link in correlations:
            if link.device_id in device_index and link.user_id in user_index:
                device = device_index[link.device_id]
                user = user_index[link.user_id]
                if link.user_id not in device.owner_user_ids:
                    device.owner_user_ids.append(link.user_id)
                if link.device_id not in user.device_ids:
                    user.device_ids.append(link.device_id)

        for signal in signals:
            if signal.user_id and signal.user_id in user_index and signal.id not in user_index[signal.user_id].signal_ids:
                user_index[signal.user_id].signal_ids.append(signal.id)
            if signal.device_id and signal.device_id in device_index and signal.id not in device_index[signal.device_id].signal_ids:
                device_index[signal.device_id].signal_ids.append(signal.id)

        for cov in coverage:
            if cov.user_id and cov.user_id in user_index and cov.id not in user_index[cov.user_id].coverage_ids:
                user_index[cov.user_id].coverage_ids.append(cov.id)
            if cov.device_id and cov.device_id in device_index and cov.id not in device_index[cov.device_id].coverage_ids:
                device_index[cov.device_id].coverage_ids.append(cov.id)

        for user in users:
            if user.signal_ids:
                user.risk_level = self._derive_risk_level([signal_index[sid].severity for sid in user.signal_ids if sid in signal_index])

        return DashboardSnapshot(
            generated_at=datetime.utcnow(),
            source_mode=source_mode,
            users=sorted(users, key=lambda item: item.display_name.lower()),
            devices=sorted(devices, key=lambda item: item.hostname.lower()),
            signals=signals,
            coverage=coverage,
            correlations=correlations,
            issues=issues,
        )

    def _merge_eiqs_devices(self, devices: list[DeviceRecord], payload: Any) -> None:
        if not devices:
            return
        items = _items(payload)
        if not items:
            return

        devices_by_id = {device.id: device for device in devices}
        devices_by_hostname = {device.hostname.lower(): device for device in devices if device.hostname}
        devices_by_serial = {
            device.serial_number.strip().upper(): device
            for device in devices
            if device.serial_number and device.serial_number.strip()
        }

        for item in items:
            target = None
            device_id = _extract_device_identifier(item)
            if device_id and device_id in devices_by_id:
                target = devices_by_id[device_id]
            if target is None:
                hostname = _pick(item, "endpointName", "displayName", "hostname", "name")
                if hostname:
                    target = devices_by_hostname.get(hostname.lower())
            if target is None:
                serial_number = _pick(item, "serialNumber")
                if serial_number:
                    target = devices_by_serial.get(serial_number.strip().upper())
            if target is None:
                continue

            mac_addresses = _extract_mac_addresses(item)
            if mac_addresses:
                target.mac_addresses = list(dict.fromkeys(target.mac_addresses + mac_addresses))

    def _normalize_users(self, payload: Any) -> list[UserRecord]:
        users: list[UserRecord] = []
        for item in _items(payload):
            user_id = _pick(item, "id", "userId", "accountId", "mail", "email")
            if not user_id:
                continue
            users.append(
                UserRecord(
                    id=user_id,
                    display_name=_pick(item, "displayName", "name", "accountName", default=user_id) or user_id,
                    email=_pick(item, "email", "mail", "userPrincipalName"),
                    department=_pick(item, "department"),
                    title=_pick(item, "title", "jobTitle"),
                    status=_pick(item, "status", default="unknown") or "unknown",
                    risk_level=_pick(item, "riskLevel", default="unknown") or "unknown",
                    source="accounts",
                )
            )
        return users

    def _normalize_devices(self, items: list[dict[str, Any]]) -> list[DeviceRecord]:
        devices: list[DeviceRecord] = []
        for item in items:
            device_id = _pick(item, "id", "deviceId", "endpointId", "agentGuid")
            hostname = _pick(item, "hostname", "name", "endpointName", "displayName", default=device_id or "unknown-host")
            if not device_id:
                continue
            owners: list[str] = []
            for key in ("owner", "user", "email", "lastLoggedOnUser"):
                value = _pick(item, key)
                if value:
                    owners.append(value)
            if isinstance(item.get("lastLoggedOnUsers"), list):
                owners.extend(
                    sanitize_text(entry)
                    for entry in item["lastLoggedOnUsers"]
                    if entry not in (None, "")
                )
            epp_agent = item.get("eppAgent") if isinstance(item.get("eppAgent"), dict) else {}
            devices.append(
                DeviceRecord(
                    id=device_id,
                    hostname=hostname or device_id,
                    platform=_pick(item, "platform", "os", "osPlatform", "osName", default="unknown") or "unknown",
                    os_version=_pick(item, "osVersion"),
                    ip_address=_pick(item, "ip", "ipAddress", "lastIpAddress", "lastUsedIp"),
                    mac_addresses=_extract_mac_addresses(item),
                    last_seen=_parse_dt(
                        item.get("lastSeen")
                        or item.get("lastSeenAt")
                        or item.get("updatedAt")
                        or item.get("lastConnectedDateTime")
                        or epp_agent.get("lastConnectedDateTime")
                    ),
                    last_logged_on_user=_pick(item, "lastLoggedOnUser"),
                    isolation_status=_pick(item, "isolationStatus"),
                    serial_number=_pick(item, "serialNumber"),
                    service_gateway_or_proxy=_pick(item, "serviceGatewayOrProxy"),
                    version_control_policy=_pick(item, "versionControlPolicy"),
                    owner_user_ids=list(dict.fromkeys(owner for owner in owners if owner)),
                )
            )
        return devices

    def _normalize_signals(self, risk_payload: Any, alerts_payload: Any, oat_payload: Any) -> list[SignalRecord]:
        signals: list[SignalRecord] = []
        for item in _items(risk_payload):
            signal_id = _pick(item, "id", "riskId", "entityId")
            if not signal_id:
                continue
            signals.append(
                SignalRecord(
                    id=signal_id,
                    title=_pick(item, "title", "name", "description", default=signal_id) or signal_id,
                    severity=_pick(item, "severity", "riskLevel", default="medium") or "medium",
                    source="risk_insights",
                    status=_pick(item, "status", default="open") or "open",
                    user_id=_pick(item, "userId", "accountId", "email"),
                    device_id=_pick(item, "deviceId", "endpointId", "agentGuid"),
                    detected_at=_parse_dt(item.get("detectedAt") or item.get("createdAt")),
                    detail_payload=item,
                )
            )
        for item in _items(alerts_payload):
            signal_id = _pick(item, "id", "alertId")
            if not signal_id:
                continue
            signals.append(
                SignalRecord(
                    id=signal_id,
                    title=_pick(item, "title", "alertName", "description", default=signal_id) or signal_id,
                    severity=_pick(item, "severity", "impactScope", default="medium") or "medium",
                    source="workbench_alerts",
                    status=_pick(item, "status", "investigationStatus", default="open") or "open",
                    user_id=_pick(item, "userId", "accountId", "email"),
                    device_id=_extract_workbench_device_id(item),
                    device_name=_extract_workbench_host(item),
                    detected_at=_parse_dt(item.get("createdDateTime") or item.get("createdAt")),
                    detail_payload=item,
                )
            )
        for item in _items(oat_payload):
            entity_type = str(item.get("entityType") or "").strip().lower()
            if entity_type == "messaging":
                continue
            if _is_blocked_oat_detection(item):
                continue
            signal_id = _pick(item, "uuid", "id")
            if not signal_id:
                continue
            endpoint = item.get("endpoint") if isinstance(item.get("endpoint"), dict) else {}
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            signals.append(
                SignalRecord(
                    id=signal_id,
                    title=_clean_endpoint_name(_pick(item, "description", "entityName")) or signal_id,
                    severity=_pick(detail, "filterRiskLevel")
                    or (
                        str(item.get("filters")[0].get("riskLevel"))
                        if isinstance(item.get("filters"), list)
                        and item.get("filters")
                        and isinstance(item.get("filters")[0], dict)
                        and item.get("filters")[0].get("riskLevel")
                        else "unknown"
                    ),
                    source="oat_detections",
                    status="Observed",
                    user_id=_pick(detail, "mailbox", "logonUser", "userName", "account"),
                    device_id=_pick(endpoint, "agentGuid")
                    or _pick(detail, "endpointGuid")
                    or _pick(item, "entityName"),
                    device_name=_clean_endpoint_name(
                        _pick(endpoint, "endpointName")
                        or _pick(detail, "endpointHostName")
                        or _pick(item, "entityName")
                    ),
                    detected_at=_parse_dt(item.get("detectedDateTime") or item.get("ingestedDateTime")),
                    detail_payload=item,
                )
            )
        return signals

    def _normalize_coverage(self, payload: Any, endpoint_items: list[dict[str, Any]]) -> list[CoverageRecord]:
        coverage: list[CoverageRecord] = []
        for item in _items(payload):
            cov_id = _pick(item, "id", "productId", "connectorId", default=None)
            if not cov_id:
                continue
            coverage.append(
                CoverageRecord(
                    id=cov_id,
                    name=_pick(item, "name", "productName", default=cov_id) or cov_id,
                    category=_pick(item, "category", "type", default="connected_product") or "connected_product",
                    status=_pick(item, "status", default="unknown") or "unknown",
                    source="connected_products",
                    device_id=_pick(item, "deviceId", "endpointId", "agentGuid"),
                    user_id=_pick(item, "userId", "accountId", "email"),
                )
            )

        for item in endpoint_items:
            device_id = _pick(item, "id", "deviceId", "endpointId", "agentGuid")
            if not device_id:
                continue
            epp_agent = item.get("eppAgent") if isinstance(item.get("eppAgent"), dict) else {}
            product_names = epp_agent.get("productNames")
            if not isinstance(product_names, list):
                continue
            for product_name in product_names:
                if not product_name:
                    continue
                product = sanitize_text(product_name)
                coverage.append(
                    CoverageRecord(
                        id=f"coverage:{device_id}:{product.lower()}",
                        name=product,
                        category="endpoint_protection",
                        status=_pick(epp_agent, "status", default="unknown") or "unknown",
                        source="endpoint_inventory",
                        device_id=device_id,
                    )
                )
        return coverage

    def _merge_inferred_users(self, users: list[UserRecord], devices: list[DeviceRecord]) -> list[UserRecord]:
        merged = list(users)
        existing_variants: dict[str, str] = {}
        for user in merged:
            for variant in _identity_variants(user.id) + _identity_variants(user.email) + _identity_variants(user.display_name):
                existing_variants.setdefault(variant, user.id)

        for device in devices:
            resolved_owner_ids: list[str] = []
            for owner in device.owner_user_ids:
                matched_user_id: Optional[str] = None
                for variant in _identity_variants(owner):
                    if variant in existing_variants:
                        matched_user_id = existing_variants[variant]
                        break
                if not matched_user_id:
                    inferred_user = _build_inferred_user(owner)
                    merged.append(inferred_user)
                    matched_user_id = inferred_user.id
                    for variant in _identity_variants(owner) + _identity_variants(inferred_user.id) + _identity_variants(inferred_user.display_name):
                        existing_variants.setdefault(variant, inferred_user.id)
                resolved_owner_ids.append(matched_user_id)
            device.owner_user_ids = list(dict.fromkeys(resolved_owner_ids))

        return list({user.id: user for user in merged}.values())

    def _correlate(self, users: dict[str, UserRecord], devices: dict[str, DeviceRecord]) -> list[CorrelationLink]:
        links: list[CorrelationLink] = []
        identity_index: dict[str, str] = {}
        for user in users.values():
            for variant in _identity_variants(user.id) + _identity_variants(user.email) + _identity_variants(user.display_name):
                identity_index.setdefault(variant, user.id)

        for device in devices.values():
            seen: set[str] = set()
            candidates = list(device.owner_user_ids)
            if device.last_logged_on_user:
                candidates.append(device.last_logged_on_user)
            for owner in candidates:
                matched_user_id = owner if owner in users else None
                if not matched_user_id:
                    for variant in _identity_variants(owner):
                        if variant in identity_index:
                            matched_user_id = identity_index[variant]
                            break
                if not matched_user_id or matched_user_id in seen:
                    continue
                links.append(
                    CorrelationLink(
                        user_id=matched_user_id,
                        device_id=device.id,
                        confidence="deterministic" if matched_user_id == owner else "inferred",
                        rationale="Matched device owner or last logged on user to user identity.",
                    )
                )
                seen.add(matched_user_id)
        return links

    def _derive_risk_level(self, severities: list[str]) -> str:
        ordered = ["critical", "high", "medium", "low"]
        severity_set = {severity.lower() for severity in severities}
        for severity in ordered:
            if severity in severity_set:
                return severity
        return "unknown"
