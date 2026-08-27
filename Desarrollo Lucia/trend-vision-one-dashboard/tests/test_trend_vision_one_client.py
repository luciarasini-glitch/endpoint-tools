from __future__ import annotations

from datetime import datetime, timezone

from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import Settings


def test_workbench_alerts_default_params_include_time_window() -> None:
    settings = Settings(
        trend_vision_one_api_token="test-token",
        trend_vision_one_workbench_alerts_lookback_hours=24,
        trend_vision_one_workbench_alerts_date_time_target="createdDateTime",
        trend_vision_one_workbench_alerts_order_by="createdDateTime desc",
    )
    client = TrendVisionOneClient(settings)

    params = client._merge_params("workbench_alerts")

    assert params["top"] == str(settings.trend_vision_one_default_page_size)
    assert params["dateTimeTarget"] == "createdDateTime"
    assert params["orderBy"] == "createdDateTime desc"
    start = datetime.fromisoformat(params["startDateTime"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(params["endDateTime"].replace("Z", "+00:00"))
    assert start.tzinfo == timezone.utc
    assert end.tzinfo == timezone.utc
    assert int((end - start).total_seconds()) == 24 * 3600


def test_workbench_alerts_filter_header_is_applied() -> None:
    settings = Settings(
        trend_vision_one_workbench_alerts_filter="severity eq 'high'",
    )
    client = TrendVisionOneClient(settings)

    headers = client._headers_for_endpoint("workbench_alerts")

    assert headers["TMV1-Filter"] == "severity eq 'high'"


def test_oat_detections_default_params_include_time_window() -> None:
    settings = Settings(
        trend_vision_one_oat_detections_lookback_hours=168,
        trend_vision_one_oat_detections_order_by="detectedDateTime desc",
    )
    client = TrendVisionOneClient(settings)

    params = client._merge_params("oat_detections")

    assert params["top"] == str(settings.trend_vision_one_default_page_size)
    assert params["orderBy"] == "detectedDateTime desc"
    start = datetime.fromisoformat(params["detectedStartDateTime"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(params["detectedEndDateTime"].replace("Z", "+00:00"))
    assert start.tzinfo == timezone.utc
    assert end.tzinfo == timezone.utc
    assert int((end - start).total_seconds()) == 168 * 3600
