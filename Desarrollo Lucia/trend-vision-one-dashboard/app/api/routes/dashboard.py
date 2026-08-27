from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.clients.jumpcloud import JumpCloudClient
from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import Settings, get_settings
from app.models.api import SyncStatusResponse
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.dashboard import DashboardService
from app.services.ingestion import IngestionService
from app.services.jumpcloud_inventory import JumpCloudInventoryService
from app.services.normalizer import NormalizationService

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def get_dashboard_service(settings: Settings = Depends(get_settings)) -> DashboardService:
    repository = SnapshotRepository(settings.db_abspath)
    client = TrendVisionOneClient(settings)
    ingestion = IngestionService(settings, client)
    normalizer = NormalizationService()
    return DashboardService(repository, ingestion, normalizer, settings.app_cache_ttl_minutes)


def get_jumpcloud_inventory_service(settings: Settings = Depends(get_settings)) -> JumpCloudInventoryService:
    repository = SnapshotRepository(settings.db_abspath)
    return JumpCloudInventoryService(JumpCloudClient(settings), repository, TrendVisionOneClient(settings))


@router.get("/metadata/endpoints")
def endpoint_metadata(settings: Settings = Depends(get_settings)) -> list[dict]:
    return TrendVisionOneClient(settings).metadata()


@router.post("/sync")
def sync_dashboard(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    service: DashboardService = Depends(get_dashboard_service),
):
    background_tasks.add_task(service.sync, force=force)
    return {
        "started": True,
        "force": force,
        "scope": "full",
        "message": "Sync started in background.",
    }


@router.post("/sync/inventory")
def sync_inventory(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    service: DashboardService = Depends(get_dashboard_service),
):
    background_tasks.add_task(service.sync_inventory, force=force)
    return {
        "started": True,
        "force": force,
        "scope": "inventory",
        "message": "Inventory sync started in background.",
    }


@router.post("/sync/alerts")
def sync_alerts(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    service: DashboardService = Depends(get_dashboard_service),
):
    background_tasks.add_task(service.sync_alerts, force=force)
    return {
        "started": True,
        "force": force,
        "scope": "alerts",
        "message": "Alerts sync started in background.",
    }


@router.get("/sync/status", response_model=SyncStatusResponse)
def sync_status(service: DashboardService = Depends(get_dashboard_service)) -> SyncStatusResponse:
    return service.status()


@router.get("/overview")
def overview(service: DashboardService = Depends(get_dashboard_service)):
    return service.overview()


@router.get("/users")
def list_users(
    search: str = Query(default="", max_length=120),
    risk_level: str = Query(default="", max_length=20),
    service: DashboardService = Depends(get_dashboard_service),
):
    return service.list_users(search=search, risk_level=risk_level)


@router.get("/endpoint-cards")
def endpoint_cards(
    search: str = Query(default="", max_length=120),
    platform: str = Query(default="", max_length=40),
    isolation_status: str = Query(default="", max_length=20),
    service: DashboardService = Depends(get_dashboard_service),
):
    return service.endpoint_cards(search=search, platform=platform, isolation_status=isolation_status)


@router.get("/trend/devices")
def trend_devices(
    search: str = Query(default="", max_length=120),
    service: DashboardService = Depends(get_dashboard_service),
):
    return service.list_trend_devices(search=search)


@router.get("/alerts")
def list_alerts(
    search: str = Query(default="", max_length=120),
    severity: str = Query(default="", max_length=20),
    status: str = Query(default="", max_length=20),
    service: DashboardService = Depends(get_dashboard_service),
):
    return service.list_alerts(search=search, severity=severity, status=status)


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: str, service: DashboardService = Depends(get_dashboard_service)):
    return service.alert_detail(alert_id)


@router.get("/users/{user_id}")
def user_detail(user_id: str, service: DashboardService = Depends(get_dashboard_service)):
    snapshot = service.user_detail(user_id)
    return {
        "user_id": user_id,
        "snapshot": snapshot,
    }


@router.get("/jumpcloud/inventory")
def jumpcloud_inventory(
    force: bool = Query(default=False),
    service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service),
):
    return service.list_active_users_inventory(force_refresh=force)


@router.get("/jumpcloud/machines")
def jumpcloud_machines(service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service)):
    return service.list_machine_inventory()


@router.get("/jumpcloud/apps")
def jumpcloud_apps(service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service)):
    return service.list_apps_inventory()


@router.get("/jumpcloud/cloudflare")
def jumpcloud_cloudflare(
    force: bool = Query(default=False),
    service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service),
):
    return service.list_cloudflare_inventory(force_refresh=force)


@router.get("/jumpcloud/phones")
def jumpcloud_phones(
    force: bool = Query(default=False),
    service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service),
):
    return service.list_phones_inventory(force_refresh=force)


@router.get("/jumpcloud/ai-saas-management")
def jumpcloud_ai_saas_management(
    search: str = Query(default="", max_length=120),
    service: JumpCloudInventoryService = Depends(get_jumpcloud_inventory_service),
):
    return service.list_ai_saas_accounts(search=search)
