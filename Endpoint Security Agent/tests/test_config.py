"""Smoke tests for Settings and endpoint registry."""
import pytest

from agent.core.config import Settings, REGIONAL_DOMAINS
from agent.clients.endpoints import get_endpoint_registry


def make_settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        trend_vision_one_api_token="test-token",
        **overrides,
    )


def test_resolved_base_url_defaults_to_us():
    s = make_settings()
    assert s.resolved_base_url == REGIONAL_DOMAINS["us"].rstrip("/")


def test_resolved_base_url_uses_region():
    s = make_settings(app_region="eu")
    assert "eu.xdr" in s.resolved_base_url


def test_resolved_base_url_uses_explicit_override():
    s = make_settings(trend_vision_one_base_url="https://my.custom.api")
    assert s.resolved_base_url == "https://my.custom.api"


def test_has_trend_token():
    s = Settings(_env_file=None, trend_vision_one_api_token="abc123")
    assert s.has_trend_token is True


def test_endpoint_registry_returns_all_keys():
    s = make_settings()
    registry = get_endpoint_registry(s)
    expected = {"users", "endpoint_inventory", "risk_insights", "connected_products",
                "eiqs_endpoints", "workbench_alerts", "oat_detections", "search"}
    assert set(registry.keys()) == expected


def test_verified_endpoints():
    s = make_settings()
    registry = get_endpoint_registry(s)
    assert registry["users"].verified is True
    assert registry["endpoint_inventory"].verified is True
    assert registry["workbench_alerts"].verified is True
    assert registry["oat_detections"].verified is True


def test_unverified_without_path():
    s = make_settings(trend_vision_one_risk_insights_path="")
    registry = get_endpoint_registry(s)
    assert registry["risk_insights"].verified is False
