from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from app.core.config import Settings


class JumpCloudClient:
    SAAS_APPLICATION_CANDIDATE_PATHS = (
        "/saas/applications",
        "/v2/saas/applications",
        "/ai-saas-management/applications",
        "/v2/ai-saas-management/applications",
        "/applications",
        "/v2/applications",
    )
    SAAS_ACCOUNT_CANDIDATE_PATHS = (
        "/saas/accounts",
        "/v2/saas/accounts",
        "/ai-saas-management/accounts",
        "/v2/ai-saas-management/accounts",
        "/accounts",
        "/v2/accounts",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._oauth_token: str | None = None
        self._oauth_token_expires_at: float = 0.0

    @property
    def base_url(self) -> str:
        return self.settings.jumpcloud_base_url.strip().rstrip("/")

    def _decode_exp(self, token: str) -> float:
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return 0.0
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
            return float(data.get("exp", 0))
        except Exception:
            return 0.0

    def _request_oauth_token(self) -> tuple[str, float]:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.post(
                "https://admin-oauth.id.jumpcloud.com/oauth2/token",
                auth=(self.settings.jumpcloud_client_id, self.settings.jumpcloud_client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": "api"},
            )
            response.raise_for_status()
            payload = response.json()

        access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        # Refresh a minute early to avoid racing expiry on live requests.
        expires_at = time.time() + max(expires_in - 60, 0)
        return access_token, expires_at

    def _get_bearer_token(self) -> str:
        now = time.time()
        if self._oauth_token and now < self._oauth_token_expires_at:
            return self._oauth_token

        static_token = self.settings.jumpcloud_access_token.strip()
        if self.settings.jumpcloud_client_id and self.settings.jumpcloud_client_secret:
            self._oauth_token, self._oauth_token_expires_at = self._request_oauth_token()
            return self._oauth_token

        if static_token:
            return static_token

        raise ValueError("JumpCloud credentials are not configured.")

    def _client(self, *, timeout: float = 30.0) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._get_bearer_token()}",
            },
            follow_redirects=True,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        with self._client(timeout=timeout) as client:
            response = client.request(method, path, params=params, json=json_body)
            response.raise_for_status()
            return response

    def get_json(self, path: str, *, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict | list:
        return self.request("GET", path, params=params, timeout=timeout).json()

    def list_users(self, *, limit: int = 100, skip: int = 0) -> dict | list:
        return self.get_json("/systemusers", params={"limit": limit, "skip": skip})

    def list_systems(self, *, limit: int = 100, skip: int = 0) -> dict | list:
        return self.get_json("/systems", params={"limit": limit, "skip": skip})

    def list_interface_details(self, *, limit: int = 100, filter_expression: str = "") -> dict | list:
        params: dict[str, Any] = {"limit": limit}
        if filter_expression.strip():
            params["filter"] = filter_expression.strip()
        return self.get_json("/v2/systeminsights/interface_details", params=params)

    def list_apps(self, *, limit: int = 100, skip: int = 0, filter_expression: str = "") -> dict | list:
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if filter_expression.strip():
            params["filter"] = filter_expression.strip()
        return self.get_json("/v2/systeminsights/apps", params=params)

    def list_programs(self, *, limit: int = 100, skip: int = 0, filter_expression: str = "") -> dict | list:
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if filter_expression.strip():
            params["filter"] = filter_expression.strip()
        return self.get_json("/v2/systeminsights/programs", params=params)

    def list_asset_devices(
        self,
        *,
        limit: int = 100,
        skip: int = 0,
        fields: tuple[str, ...] = (),
    ) -> dict | list:
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if fields:
            params["fields"] = ",".join(fields)
        return self.get_json("/v2/assets/devices", params=params)

    def get_google_emm_device(self, device_id: str, *, timeout: float = 30.0) -> dict | list:
        return self.get_json(f"/v2/google-emm/devices/{device_id.strip()}", timeout=timeout)

    def list_all_users(self, *, limit: int = 100) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_users(limit=limit, skip=skip)
            batch = payload.get("results", []) if isinstance(payload, dict) else payload
            if not isinstance(batch, list) or not batch:
                break
            users.extend(item for item in batch if isinstance(item, dict))
            total_count = payload.get("totalCount", len(users)) if isinstance(payload, dict) else len(users)
            skip += len(batch)
            if skip >= total_count:
                break
        return users

    def list_all_systems(self, *, limit: int = 100) -> list[dict[str, Any]]:
        systems: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_systems(limit=limit, skip=skip)
            batch = payload.get("results", []) if isinstance(payload, dict) else payload
            if not isinstance(batch, list) or not batch:
                break
            systems.extend(item for item in batch if isinstance(item, dict))
            total_count = payload.get("totalCount", len(systems)) if isinstance(payload, dict) else len(systems)
            skip += len(batch)
            if skip >= total_count:
                break
        return systems

    def list_all_interface_details_for_system(self, system_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not system_id.strip():
            return []
        payload = self.list_interface_details(limit=limit, filter_expression=f"system_id:eq:{system_id.strip()}")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("results", "items", "data", "value", "records"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def list_all_apps_for_system(self, system_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if not system_id.strip():
            return []
        rows: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_apps(
                limit=limit,
                skip=skip,
                filter_expression=f"system_id:eq:{system_id.strip()}",
            )
            batch: list[dict[str, Any]] = []
            if isinstance(payload, list):
                batch = [item for item in payload if isinstance(item, dict)]
                total_count = None
            elif isinstance(payload, dict):
                for key in ("results", "items", "data", "value", "records"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        batch = [item for item in value if isinstance(item, dict)]
                        break
                total_count = int(payload.get("totalCount") or payload.get("count") or len(rows) + len(batch))
            else:
                batch = []
                total_count = None

            if not batch:
                break

            rows.extend(batch)
            skip += len(batch)
            if (total_count is not None and skip >= total_count) or len(batch) < limit:
                break

        return rows

    def list_all_apps(self, *, limit: int = 100, filter_expression: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_apps(limit=limit, skip=skip, filter_expression=filter_expression)
            batch: list[dict[str, Any]] = []
            if isinstance(payload, list):
                batch = [item for item in payload if isinstance(item, dict)]
                total_count = None
            elif isinstance(payload, dict):
                for key in ("results", "items", "data", "value", "records"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        batch = [item for item in value if isinstance(item, dict)]
                        break
                total_count = int(payload.get("totalCount") or payload.get("count") or len(rows) + len(batch))
            else:
                batch = []
                total_count = None

            if not batch:
                break

            rows.extend(batch)
            skip += len(batch)
            if (total_count is not None and skip >= total_count) or len(batch) < limit:
                break

        return rows

    def list_all_programs(self, *, limit: int = 100, filter_expression: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_programs(limit=limit, skip=skip, filter_expression=filter_expression)
            batch: list[dict[str, Any]] = []
            if isinstance(payload, list):
                batch = [item for item in payload if isinstance(item, dict)]
                total_count = None
            elif isinstance(payload, dict):
                for key in ("results", "items", "data", "value", "records"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        batch = [item for item in value if isinstance(item, dict)]
                        break
                total_count = int(payload.get("totalCount") or payload.get("count") or len(rows) + len(batch))
            else:
                batch = []
                total_count = None

            if not batch:
                break

            rows.extend(batch)
            skip += len(batch)
            if (total_count is not None and skip >= total_count) or len(batch) < limit:
                break

        return rows

    def list_all_asset_devices(
        self,
        *,
        limit: int = 100,
        fields: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        skip = 0
        while True:
            payload = self.list_asset_devices(limit=limit, skip=skip, fields=fields)
            batch, total_count = self._extract_list_payload(payload)
            if not batch:
                break

            rows.extend(batch)
            skip += len(batch)
            if (total_count is not None and skip >= total_count) or len(batch) < limit:
                break

        return rows

    @staticmethod
    def _extract_list_payload(payload: dict | list) -> tuple[list[dict[str, Any]], int | None]:
        if isinstance(payload, list):
            batch = [item for item in payload if isinstance(item, dict)]
            return batch, None
        if isinstance(payload, dict):
            for key in ("results", "items", "data", "value", "records", "applications", "accounts"):
                value = payload.get(key)
                if isinstance(value, list):
                    batch = [item for item in value if isinstance(item, dict)]
                    total = payload.get("totalCount") or payload.get("count") or payload.get("total")
                    total_count: int | None = None
                    if isinstance(total, (int, float)):
                        total_count = int(total)
                    elif str(total).isdigit():
                        total_count = int(str(total))
                    return batch, total_count
        return [], None

    def _list_all_from_candidate_paths(
        self,
        candidate_paths: tuple[str, ...],
        *,
        configured_path: str = "",
        limit: int = 100,
        max_pages: int | None = None,
        extra_params: dict[str, Any] | None = None,
        probe_timeout: float = 1.5,
        page_timeout: float = 5.0,
    ) -> list[dict[str, Any]]:
        paths = [configured_path.strip()] if configured_path.strip() else list(candidate_paths)
        last_error: Exception | None = None

        for path in paths:
            rows: list[dict[str, Any]] = []
            skip = 0
            pages_loaded = 0
            try:
                probe_params: dict[str, Any] = {"limit": 1, "skip": 0}
                if extra_params:
                    probe_params.update(extra_params)
                probe_payload = self.get_json(path, params=probe_params, timeout=probe_timeout)
                probe_batch, _probe_total = self._extract_list_payload(probe_payload)
                if not probe_batch:
                    continue
                rows.extend(probe_batch)
                skip = len(probe_batch)
                pages_loaded = 1
                while True:
                    if max_pages is not None and pages_loaded >= max_pages:
                        break
                    page_params: dict[str, Any] = {"limit": limit, "skip": skip}
                    if extra_params:
                        page_params.update(extra_params)
                    payload = self.get_json(path, params=page_params, timeout=page_timeout)
                    batch, total_count = self._extract_list_payload(payload)
                    if not batch:
                        break
                    rows.extend(batch)
                    skip += len(batch)
                    pages_loaded += 1
                    if (total_count is not None and skip >= total_count) or len(batch) < limit:
                        break
                return rows
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        return []

    def list_all_saas_applications(
        self,
        *,
        limit: int = 100,
        search: str = "",
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._list_all_from_candidate_paths(
            self.SAAS_APPLICATION_CANDIDATE_PATHS,
            configured_path=self.settings.jumpcloud_saas_applications_path,
            limit=limit,
            max_pages=max_pages,
            extra_params={"search": search} if search.strip() else None,
            probe_timeout=3.0,
            page_timeout=15.0,
        )

    def list_all_saas_accounts(
        self,
        *,
        limit: int = 100,
        search: str = "",
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._list_all_from_candidate_paths(
            self.SAAS_ACCOUNT_CANDIDATE_PATHS,
            configured_path=self.settings.jumpcloud_saas_accounts_path,
            limit=limit,
            max_pages=max_pages,
            extra_params={"search": search} if search.strip() else None,
            probe_timeout=3.0,
            page_timeout=20.0,
        )
