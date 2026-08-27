from app.clients.endpoints import get_endpoint_registry
from app.core.config import Settings


def test_workbench_alerts_is_verified() -> None:
    settings = Settings()
    registry = get_endpoint_registry(settings)
    assert registry["workbench_alerts"].verified is True
    assert registry["workbench_alerts"].path == "/v3.0/workbench/alerts"
    assert registry["workbench_alerts"].default_params == {"top": "100"}


def test_accounts_and_endpoints_defaults_are_set() -> None:
    settings = Settings(
        trend_vision_one_risk_insights_path="",
        trend_vision_one_connected_products_path="",
    )
    registry = get_endpoint_registry(settings)
    assert registry["users"].verified is True
    assert registry["users"].path == "/v3.0/accounts"
    assert registry["endpoint_inventory"].path == "/v3.0/endpointSecurity/endpoints"
    assert registry["search"].path == "/v3.0/search"
