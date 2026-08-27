from __future__ import annotations

from app.clients.trend_vision_one import TrendVisionOneClient
from app.core.config import get_settings
from app.repositories.snapshot_repository import SnapshotRepository
from app.services.dashboard import DashboardService
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizationService


def main() -> None:
    settings = get_settings()
    repository = SnapshotRepository(settings.db_abspath)
    client = TrendVisionOneClient(settings)
    ingestion = IngestionService(settings, client)
    normalizer = NormalizationService()
    service = DashboardService(repository, ingestion, normalizer, settings.app_cache_ttl_minutes)
    snapshot = service.sync(force=True)
    print(
        {
            "generated_at": snapshot.generated_at.isoformat(),
            "source_mode": snapshot.source_mode,
            "users": len(snapshot.users),
            "devices": len(snapshot.devices),
            "signals": len(snapshot.signals),
            "coverage": len(snapshot.coverage),
            "issues": [issue.model_dump() for issue in snapshot.issues],
        }
    )


if __name__ == "__main__":
    main()

