from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.models.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)

