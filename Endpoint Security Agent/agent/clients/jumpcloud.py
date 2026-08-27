from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Generator

import httpx

from agent.core.config import Settings

log = logging.getLogger(__name__)


class JumpCloudClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.jumpcloud_base_url.rstrip("/")
        self._oauth_token: str | None = None
        self._oauth_token_expires_at: float = 0.0
        self._client = httpx.Client(base_url=self._base_url, timeout=30, follow_redirects=True)

    def _bearer_token(self) -> str:
        s = self._settings
        if s.jumpcloud_client_id and s.jumpcloud_client_secret:
            now = time.time()
            if self._oauth_token and now < self._oauth_token_expires_at:
                return self._oauth_token
            resp = httpx.post(
                "https://admin-oauth.id.jumpcloud.com/oauth2/token",
                auth=(s.jumpcloud_client_id, s.jumpcloud_client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": "api"},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._oauth_token = payload["access_token"]
            self._oauth_token_expires_at = time.time() + max(int(payload.get("expires_in", 3600)) - 60, 0)
            return self._oauth_token
        if s.jumpcloud_access_token.strip():
            return s.jumpcloud_access_token.strip()
        raise ValueError("JumpCloud credentials not configured.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JumpCloudClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._client.get(path, params=params, headers=self._headers())
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            log.warning("JumpCloud rate limited — waiting %ds", wait)
            time.sleep(wait)
            resp = self._client.get(path, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def fetch_collection(
        self,
        path: str,
        limit: int = 100,
        max_pages: int = 20,
    ) -> Generator[dict[str, Any], None, None]:
        skip = 0
        for _ in range(max_pages):
            data = self._get(path, params={"limit": limit, "skip": skip})
            items = data if isinstance(data, list) else data.get("results", data.get("data", []))
            if not items:
                break
            yield from items
            if len(items) < limit:
                break
            skip += limit

    def fetch_one(self, path: str) -> dict[str, Any]:
        return self._get(path)
