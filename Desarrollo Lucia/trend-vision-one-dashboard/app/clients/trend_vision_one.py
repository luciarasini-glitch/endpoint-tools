from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.clients.endpoints import get_endpoint_registry
from app.core.config import Settings
from app.models.domain import SyncIssue

logger = logging.getLogger(__name__)


def _should_retry_request(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class TrendVisionOneClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = get_endpoint_registry(settings)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.settings.trend_vision_one_user_agent,
        }
        if self.settings.trend_vision_one_api_token:
            headers["Authorization"] = f"Bearer {self.settings.trend_vision_one_api_token}"
        return headers

    def _headers_for_endpoint(self, endpoint_name: str) -> dict[str, str]:
        headers = self._headers()
        if endpoint_name == "endpoint_inventory" and self.settings.trend_vision_one_endpoint_inventory_filter.strip():
            headers["TMV1-Filter"] = self.settings.trend_vision_one_endpoint_inventory_filter.strip()
        if endpoint_name == "eiqs_endpoints" and self.settings.trend_vision_one_eiqs_endpoints_query.strip():
            headers["TMV1-Query"] = self.settings.trend_vision_one_eiqs_endpoints_query.strip()
        if endpoint_name == "workbench_alerts" and self.settings.trend_vision_one_workbench_alerts_filter.strip():
            headers["TMV1-Filter"] = self.settings.trend_vision_one_workbench_alerts_filter.strip()
        return headers

    def _client(self, endpoint_name: str | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.resolved_base_url,
            timeout=self.settings.trend_vision_one_timeout_seconds,
            headers=self._headers_for_endpoint(endpoint_name) if endpoint_name else self._headers(),
            follow_redirects=True,
        )

    @retry(
        retry=retry_if_exception(_should_retry_request),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        endpoint_name: str | None = None,
    ) -> Any:
        with self._client(endpoint_name) as client:
            response = client.request(method, path, params=params, json=json_body)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(min(int(retry_after), 30))
                    except ValueError:
                        pass
                response.raise_for_status()
            response.raise_for_status()
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise httpx.HTTPStatusError(
                    "Unexpected content type received from Trend Vision One",
                    request=response.request,
                    response=response,
                )
            return response.json()

    def _merge_params(self, endpoint_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        endpoint = self.registry[endpoint_name]
        merged: dict[str, Any] = {}
        if endpoint.default_params:
            merged.update(endpoint.default_params)
        if endpoint_name == "workbench_alerts":
            merged.update(self._default_workbench_alerts_params())
        if endpoint_name == "oat_detections":
            merged.update(self._default_oat_detections_params())
        if params:
            merged.update({key: value for key, value in params.items() if value not in (None, "")})
        return merged

    def _default_workbench_alerts_params(self) -> dict[str, str]:
        end = datetime.now(timezone.utc).replace(microsecond=0)
        start = end - self.settings.workbench_alerts_lookback
        return {
            "startDateTime": start.isoformat().replace("+00:00", "Z"),
            "endDateTime": end.isoformat().replace("+00:00", "Z"),
            "dateTimeTarget": self.settings.trend_vision_one_workbench_alerts_date_time_target,
            "orderBy": self.settings.trend_vision_one_workbench_alerts_order_by,
        }

    def _default_oat_detections_params(self) -> dict[str, str]:
        end = datetime.now(timezone.utc).replace(microsecond=0)
        start = end - self.settings.oat_detections_lookback
        return {
            "detectedStartDateTime": start.isoformat().replace("+00:00", "Z"),
            "detectedEndDateTime": end.isoformat().replace("+00:00", "Z"),
            "orderBy": self.settings.trend_vision_one_oat_detections_order_by,
        }

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request_json("GET", path, params=params)

    def _extract_items(self, payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("items", "data", "value", "records", "results", "users", "devices", "alerts", "products"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _extract_next_request(self, payload: Any, current_params: dict[str, Any], page_number: int) -> tuple[str | None, dict[str, Any] | None]:
        if not isinstance(payload, dict):
            return None, None

        for key in ("nextLink", "next_link", "next", "@odata.nextLink"):
            next_value = payload.get(key)
            if isinstance(next_value, str) and next_value.strip():
                parsed = urlparse(next_value)
                path = parsed.path or next_value
                params = dict(parse_qsl(parsed.query))
                return path, params or None

        if payload.get("hasMore") is True or payload.get("hasNext") is True or payload.get("more") is True:
            if "offset" in current_params and "limit" in current_params:
                return None, {
                    **current_params,
                    "offset": str(int(current_params["offset"]) + int(current_params["limit"])),
                }
            if "skip" in current_params and "top" in current_params:
                return None, {
                    **current_params,
                    "skip": str(int(current_params["skip"]) + int(current_params["top"])),
                }
            if "page" in current_params:
                return None, {**current_params, "page": str(page_number + 1)}

        cursor = payload.get("nextCursor") or payload.get("cursor") or payload.get("nextPageToken")
        if cursor:
            key = "cursor" if payload.get("nextCursor") or payload.get("cursor") else "pageToken"
            return None, {**current_params, key: str(cursor)}

        return None, None

    def _max_pages_for_endpoint(self, endpoint_name: str) -> int:
        if endpoint_name == "endpoint_inventory":
            return max(self.settings.trend_vision_one_endpoint_inventory_max_pages, 1)
        if endpoint_name == "oat_detections":
            return max(self.settings.trend_vision_one_oat_detections_max_pages, 1)
        return max(self.settings.trend_vision_one_max_pages, 1)

    def _max_duration_for_endpoint(self, endpoint_name: str) -> int:
        if endpoint_name == "oat_detections":
            return max(self.settings.trend_vision_one_oat_detections_max_duration_seconds, 30)
        if endpoint_name == "workbench_alerts":
            return max(self.settings.trend_vision_one_workbench_alerts_max_duration_seconds, 30)
        return max(self.settings.trend_vision_one_collection_max_duration_seconds, 30)

    def fetch_endpoint(self, endpoint_name: str, params: dict[str, Any] | None = None) -> tuple[Any | None, list[SyncIssue]]:
        endpoint = self.registry[endpoint_name]
        issues: list[SyncIssue] = []
        if not self.settings.trend_vision_one_api_token:
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="warning",
                    message="No Trend Vision One API token configured. Live sync skipped.",
                )
            )
            return None, issues

        if endpoint_name == "eiqs_endpoints" and not self.settings.trend_vision_one_eiqs_endpoints_query.strip():
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="warning",
                    message="No TMV1-Query configured for eiqs_endpoints. EIQS enrichment skipped.",
                )
            )
            return None, issues

        if not endpoint.path:
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="warning",
                    message=f"No exact path configured for {endpoint.category}. {endpoint.note}",
                )
            )
            return None, issues

        try:
            merged_params = self._merge_params(endpoint_name, params=params)
            return self._request_json("GET", endpoint.path, params=merged_params, endpoint_name=endpoint_name), issues
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            logger.warning("Trend Vision One request failed for %s with status=%s", endpoint_name, status_code)
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="error",
                    message=f"HTTP error while calling {endpoint.path}: {status_code}",
                )
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("Trend Vision One network failure for %s: %s", endpoint_name, exc.__class__.__name__)
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="error",
                    message=f"Network error while calling {endpoint.path}: {exc.__class__.__name__}",
                )
            )
        return None, issues

    def fetch_collection(self, endpoint_name: str, params: dict[str, Any] | None = None) -> tuple[Any | None, list[SyncIssue]]:
        endpoint = self.registry[endpoint_name]
        payload, issues = self.fetch_endpoint(endpoint_name, params=params)
        if payload is None or not endpoint.collection_like:
            return payload, issues
        if not isinstance(payload, dict):
            return payload, issues

        aggregated_items = self._extract_items(payload)
        current_path = endpoint.path
        current_params = self._merge_params(endpoint_name, params=params)
        started_at = time.monotonic()
        max_duration_seconds = self._max_duration_for_endpoint(endpoint_name)
        max_pages = self._max_pages_for_endpoint(endpoint_name)

        for page_number in range(2, max_pages + 1):
            elapsed_seconds = int(time.monotonic() - started_at)
            if elapsed_seconds >= max_duration_seconds:
                issues.append(
                    SyncIssue(
                        source=endpoint_name,
                        severity="warning",
                        message=(
                            f"Pagination stopped after {elapsed_seconds}s "
                            f"(max duration {max_duration_seconds}s)."
                        ),
                    )
                )
                break

            next_path, next_params = self._extract_next_request(payload, current_params, page_number)
            if next_path is None and next_params is None:
                break

            try:
                payload = self._request_json(
                    "GET",
                    next_path or current_path,
                    params=next_params or current_params,
                    endpoint_name=endpoint_name,
                )
            except httpx.HTTPError as exc:
                issues.append(
                    SyncIssue(
                        source=endpoint_name,
                        severity="warning",
                        message=f"Pagination stopped on page {page_number} because of {exc.__class__.__name__}.",
                    )
                )
                break

            aggregated_items.extend(self._extract_items(payload))
            if next_path:
                current_path = next_path
            if next_params:
                current_params = next_params

        merged_payload = dict(payload)
        merged_payload["items"] = aggregated_items
        merged_payload["_aggregated_count"] = len(aggregated_items)
        total_count_raw = merged_payload.get("totalCount")
        if isinstance(total_count_raw, int):
            total_count = total_count_raw
        elif isinstance(total_count_raw, str) and total_count_raw.isdigit():
            total_count = int(total_count_raw)
        else:
            total_count = None
        if total_count is not None and len(aggregated_items) < total_count:
            issues.append(
                SyncIssue(
                    source=endpoint_name,
                    severity="warning",
                    message=(
                        f"Collection truncated at {len(aggregated_items)} of {total_count} items. "
                        f"Increase the page limit for {endpoint_name}."
                    ),
                )
            )
        return merged_payload, issues

    def fetch_workbench_alert_detail(self, alert_id: str) -> tuple[Any | None, list[SyncIssue]]:
        issues: list[SyncIssue] = []
        if not self.settings.trend_vision_one_api_token:
            issues.append(
                SyncIssue(
                    source="workbench_alert_detail",
                    severity="warning",
                    message="No Trend Vision One API token configured. Alert detail skipped.",
                )
            )
            return None, issues

        endpoint = self.registry["workbench_alerts"]
        try:
            payload = self._request_json(
                "GET",
                f"{endpoint.path.rstrip('/')}/{alert_id}",
                endpoint_name="workbench_alerts",
            )
            return payload, issues
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            issues.append(
                SyncIssue(
                    source="workbench_alert_detail",
                    severity="error",
                    message=f"HTTP error while calling {endpoint.path}/{alert_id}: {status_code}",
                )
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            issues.append(
                SyncIssue(
                    source="workbench_alert_detail",
                    severity="error",
                    message=f"Network error while calling {endpoint.path}/{alert_id}: {exc.__class__.__name__}",
                )
            )
        return None, issues

    def fetch_oat_detection_detail(self, detection_id: str) -> tuple[Any | None, list[SyncIssue]]:
        issues: list[SyncIssue] = []
        if not self.settings.trend_vision_one_api_token:
            issues.append(
                SyncIssue(
                    source="oat_detection_detail",
                    severity="warning",
                    message="No Trend Vision One API token configured. OAT detail skipped.",
                )
            )
            return None, issues

        endpoint = self.registry["oat_detections"]
        try:
            payload = self._request_json(
                "GET",
                f"{endpoint.path.rstrip('/')}/{detection_id}",
                endpoint_name="oat_detections",
            )
            return payload, issues
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            issues.append(
                SyncIssue(
                    source="oat_detection_detail",
                    severity="error",
                    message=f"HTTP error while calling {endpoint.path}/{detection_id}: {status_code}",
                )
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            issues.append(
                SyncIssue(
                    source="oat_detection_detail",
                    severity="error",
                    message=f"Network error while calling {endpoint.path}/{detection_id}: {exc.__class__.__name__}",
                )
            )
        return None, issues

    def search(self, query: dict[str, Any]) -> tuple[Any | None, list[SyncIssue]]:
        issues: list[SyncIssue] = []
        endpoint = self.registry["search"]
        if not self.settings.trend_vision_one_api_token:
            issues.append(
                SyncIssue(
                    source="search",
                    severity="warning",
                    message="No Trend Vision One API token configured. Search skipped.",
                )
            )
            return None, issues
        try:
            payload = self._request_json("POST", endpoint.path, json_body=query, endpoint_name="search")
            return payload, issues
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            issues.append(
                SyncIssue(
                    source="search",
                    severity="error",
                    message=f"HTTP error while calling {endpoint.path}: {status_code}",
                )
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            issues.append(
                SyncIssue(
                    source="search",
                    severity="error",
                    message=f"Network error while calling {endpoint.path}: {exc.__class__.__name__}",
                )
            )
        return None, issues

    def metadata(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for endpoint in self.registry.values():
            items.append(
                {
                    "name": endpoint.name,
                    "category": endpoint.category,
                    "path": endpoint.path or None,
                    "verified": endpoint.verified,
                    "docs_url": endpoint.docs_url,
                    "note": endpoint.note,
                    "default_params": endpoint.default_params or {},
                    "collection_like": endpoint.collection_like,
                }
            )
        return items
