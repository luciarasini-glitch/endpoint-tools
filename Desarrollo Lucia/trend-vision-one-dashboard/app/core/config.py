from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REGIONAL_DOMAINS = {
    "au": "https://api.au.xdr.trendmicro.com",
    "eu": "https://api.eu.xdr.trendmicro.com",
    "in": "https://api.in.xdr.trendmicro.com",
    "jp": "https://api.xdr.trendmicro.co.jp",
    "sg": "https://api.sg.xdr.trendmicro.com",
    "mea": "https://api.mea.xdr.trendmicro.com",
    "uk": "https://api.uk.xdr.trendmicro.com",
    "us": "https://api.xdr.trendmicro.com",
    "usgov": "https://api.usgov.xdr.trendmicro.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    app_demo_mode: bool = True
    app_backend_host: str = "127.0.0.1"
    app_backend_port: int = 8000
    app_streamlit_port: int = 8501
    app_cache_ttl_minutes: int = 30
    app_db_path: Path = Path("data/trend_dashboard.db")
    app_log_level: str = "INFO"
    app_region: str = Field(default="us", min_length=2)

    trend_vision_one_base_url: str = ""
    trend_vision_one_api_token: str = ""
    trend_vision_one_timeout_seconds: float = 30.0
    trend_vision_one_max_retries: int = 4
    trend_vision_one_backoff_seconds: float = 1.5
    trend_vision_one_user_agent: str = "trend-vision-one-dashboard/0.1.0"
    trend_vision_one_default_page_size: int = 100
    trend_vision_one_max_pages: int = 10
    trend_vision_one_endpoint_inventory_max_pages: int = 25
    trend_vision_one_collection_max_duration_seconds: int = 360

    trend_vision_one_users_path: str = ""
    trend_vision_one_endpoints_path: str = ""
    trend_vision_one_risk_insights_path: str = ""
    trend_vision_one_connected_products_path: str = ""
    trend_vision_one_workbench_alerts_path: str = "/v3.0/workbench/alerts"
    trend_vision_one_workbench_alerts_filter: str = ""
    trend_vision_one_workbench_alerts_lookback_hours: int = 24
    trend_vision_one_workbench_alerts_date_time_target: str = "createdDateTime"
    trend_vision_one_workbench_alerts_order_by: str = "createdDateTime desc"
    trend_vision_one_workbench_alerts_max_duration_seconds: int = 180
    trend_vision_one_oat_detections_path: str = "/v3.0/oat/detections"
    trend_vision_one_oat_detections_lookback_hours: int = 24
    trend_vision_one_oat_detections_order_by: str = "detectedDateTime desc"
    trend_vision_one_oat_detections_max_pages: int = 2
    trend_vision_one_oat_detections_max_duration_seconds: int = 240
    trend_vision_one_search_path: str = "/v3.0/search"
    trend_vision_one_endpoint_inventory_order_by: str = ""
    trend_vision_one_endpoint_inventory_select: str = ""
    trend_vision_one_endpoint_inventory_filter: str = ""
    trend_vision_one_eiqs_endpoints_path: str = "/v3.0/eiqs/endpoints"
    trend_vision_one_eiqs_endpoints_query: str = ""

    jumpcloud_base_url: str = "https://console.jumpcloud.com/api"
    jumpcloud_client_id: str = ""
    jumpcloud_client_secret: str = ""
    jumpcloud_access_token: str = ""
    jumpcloud_saas_applications_path: str = ""
    jumpcloud_saas_accounts_path: str = ""

    @property
    def resolved_base_url(self) -> str:
        if self.trend_vision_one_base_url:
            base_url = self.trend_vision_one_base_url.strip().strip('"').strip("'")
            if not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"
            return base_url.rstrip("/")
        return REGIONAL_DOMAINS.get(self.app_region.lower(), REGIONAL_DOMAINS["us"]).rstrip("/")

    @property
    def db_abspath(self) -> Path:
        return self.app_db_path if self.app_db_path.is_absolute() else Path.cwd() / self.app_db_path

    @property
    def workbench_alerts_lookback(self) -> timedelta:
        return timedelta(hours=max(self.trend_vision_one_workbench_alerts_lookback_hours, 1))

    @property
    def oat_detections_lookback(self) -> timedelta:
        return timedelta(hours=max(self.trend_vision_one_oat_detections_lookback_hours, 1))


@lru_cache
def get_settings() -> Settings:
    return Settings()
