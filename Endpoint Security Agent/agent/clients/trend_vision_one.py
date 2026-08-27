from __future__ import annotations

import logging
import time
from typing import Any, Generator

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from agent.core.config import Settings

log = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


class TrendVisionOneClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.resolved_base_url
        self._headers = {
            "Authorization": f"Bearer {settings.trend_vision_one_api_token}",
            "Accept": "application/json",
            "User-Agent": settings.trend_vision_one_user_agent,
        }
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=settings.trend_vision_one_timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TrendVisionOneClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1.5, min=1, max=20),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        resp = self._client.get(path, params=params)
        if resp.status_code == 429:
            wait = min(int(resp.headers.get("Retry-After", 5)), 30)
            log.warning("Rate limited — waiting %ds", wait)
            time.sleep(wait)
            resp.raise_for_status()
        resp.raise_for_status()
        return resp.json()

    def fetch_collection(
        self,
        path: str,
        params: dict[str, str] | None = None,
        max_pages: int | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Yield every item from a paginated collection endpoint."""
        s = self._settings
        limit = max_pages or s.trend_vision_one_max_pages
        current_params = dict(params or {})

        for _ in range(limit):
            data = self._get(path, current_params)

            items = (
                data.get("items")
                or data.get("data")
                or data.get("value")
                or data.get("records")
                or (data if isinstance(data, list) else [])
            )
            yield from items

            # Advance pagination
            next_link = data.get("nextLink") or data.get("next")
            if next_link:
                # Extract path+query from nextLink
                parsed = httpx.URL(next_link)
                path = parsed.path
                current_params = dict(parsed.params)
                continue

            cursor = data.get("cursor") or data.get("nextCursor")
            if cursor:
                current_params["cursor"] = cursor
                continue

            break

    def fetch_one(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._get(path, params)
