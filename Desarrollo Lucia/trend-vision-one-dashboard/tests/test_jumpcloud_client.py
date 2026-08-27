from __future__ import annotations

from app.clients.jumpcloud import JumpCloudClient
from app.core.config import Settings


class StubJumpCloudClient(JumpCloudClient):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.calls: list[int] = []

    def list_apps(self, *, limit: int = 100, skip: int = 0, filter_expression: str = ""):  # type: ignore[override]
        self.calls.append(skip)
        if skip == 0:
            return [{"system_id": "sys-1", "display_name": "Alpha"}]
        if skip == 1:
            return [{"system_id": "sys-2", "display_name": "Beta"}]
        return []


def test_list_all_apps_continues_paging_for_plain_list_payloads() -> None:
    client = StubJumpCloudClient()

    rows = client.list_all_apps(limit=1)

    assert rows == [
        {"system_id": "sys-1", "display_name": "Alpha"},
        {"system_id": "sys-2", "display_name": "Beta"},
    ]
    assert client.calls == [0, 1, 2]


class StubJumpCloudAssetClient(JumpCloudClient):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.calls: list[tuple[int, tuple[str, ...]]] = []

    def list_asset_devices(  # type: ignore[override]
        self,
        *,
        limit: int = 100,
        skip: int = 0,
        fields: tuple[str, ...] = (),
    ):
        self.calls.append((skip, fields))
        if skip == 0:
            return {"results": [{"id": "asset-1"}], "totalCount": 2}
        if skip == 1:
            return {"results": [{"id": "asset-2"}], "totalCount": 2}
        return {"results": [], "totalCount": 2}


def test_list_all_asset_devices_continues_paging_and_passes_fields() -> None:
    client = StubJumpCloudAssetClient()

    rows = client.list_all_asset_devices(limit=1, fields=("Name", "Type"))

    assert rows == [{"id": "asset-1"}, {"id": "asset-2"}]
    assert client.calls == [(0, ("Name", "Type")), (1, ("Name", "Type"))]
