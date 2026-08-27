from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import Settings


def test_extract_next_request_from_next_link() -> None:
    client = TrendVisionOneClient(Settings())
    path, params = client._extract_next_request(
        {"nextLink": "/v3.0/workbench/alerts?skip=100&top=100"},
        {"top": "100"},
        2,
    )
    assert path == "/v3.0/workbench/alerts"
    assert params == {"skip": "100", "top": "100"}


def test_extract_next_request_from_has_more_skip_top() -> None:
    client = TrendVisionOneClient(Settings())
    path, params = client._extract_next_request(
        {"hasMore": True},
        {"skip": "0", "top": "100"},
        2,
    )
    assert path is None
    assert params == {"skip": "100", "top": "100"}


def test_endpoint_inventory_uses_dedicated_max_pages_setting() -> None:
    client = TrendVisionOneClient(
        Settings(
            trend_vision_one_max_pages=10,
            trend_vision_one_endpoint_inventory_max_pages=25,
        )
    )

    assert client._max_pages_for_endpoint("endpoint_inventory") == 25
    assert client._max_pages_for_endpoint("workbench_alerts") == 10


def test_fetch_collection_warns_when_total_count_exceeds_aggregated_items() -> None:
    client = TrendVisionOneClient(
        Settings(
            trend_vision_one_max_pages=2,
            trend_vision_one_endpoint_inventory_max_pages=2,
        )
    )

    payloads = [
        {
            "items": [{"id": "1"}],
            "nextLink": "/v3.0/endpointSecurity/endpoints?skip=1&top=1",
            "totalCount": 3,
        },
        {
            "items": [{"id": "2"}],
            "nextLink": "/v3.0/endpointSecurity/endpoints?skip=2&top=1",
            "totalCount": 3,
        },
    ]

    def fake_fetch_endpoint(endpoint_name: str, params=None):  # noqa: ANN001
        return payloads[0], []

    def fake_request_json(method: str, path: str, *, params=None, json_body=None, endpoint_name=None):  # noqa: ANN001
        return payloads[1]

    client.fetch_endpoint = fake_fetch_endpoint  # type: ignore[method-assign]
    client._request_json = fake_request_json  # type: ignore[method-assign]

    payload, issues = client.fetch_collection("endpoint_inventory")

    assert payload is not None
    assert payload["_aggregated_count"] == 2
    assert any("Collection truncated at 2 of 3 items" in issue.message for issue in issues)
