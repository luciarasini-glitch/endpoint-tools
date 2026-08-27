from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


DOCS_BASE = "https://automation.trendmicro.com/xdr/Guides/"
API_REFERENCE_NOTE = (
    "Validate the exact read-only path in Trend Vision One Automation Center API Reference "
    "for the configured region and tenant."
)
USER_DETAILS_NOTE = "Account detail endpoint pattern confirmed by user input: GET /v3.0/accounts/{accountId}."
ENDPOINT_DETAILS_NOTE = "Endpoint detail endpoint pattern confirmed by user input: GET /v3.0/endpoints/{endpointId}."


@dataclass(frozen=True)
class EndpointDefinition:
    name: str
    path: str
    verified: bool
    docs_url: str
    category: str
    note: str
    default_params: dict[str, str] | None = None
    collection_like: bool = True


def get_endpoint_registry(settings: Settings) -> dict[str, EndpointDefinition]:
    endpoint_inventory_params = {"top": str(settings.trend_vision_one_default_page_size)}
    if settings.trend_vision_one_endpoint_inventory_order_by.strip():
        endpoint_inventory_params["orderBy"] = settings.trend_vision_one_endpoint_inventory_order_by.strip()
    if settings.trend_vision_one_endpoint_inventory_select.strip():
        endpoint_inventory_params["select"] = settings.trend_vision_one_endpoint_inventory_select.strip()

    endpoint_inventory_note = (
        "Path verified by user input. Official request example includes query params "
        "`orderBy`, `top`, `select` and optional header `TMV1-Filter`."
    )
    return {
        "users": EndpointDefinition(
            name="users",
            path=settings.trend_vision_one_users_path.strip() or "/v3.0/accounts",
            verified=True,
            docs_url=f"{DOCS_BASE}Authentication/",
            category="Accounts",
            note=f"Verified by user input. {USER_DETAILS_NOTE}",
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "endpoint_inventory": EndpointDefinition(
            name="endpoint_inventory",
            path=settings.trend_vision_one_endpoints_path.strip() or "/v3.0/endpointSecurity/endpoints",
            verified=True,
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Search / Endpoint Inventory",
            note=f"{endpoint_inventory_note} {ENDPOINT_DETAILS_NOTE}",
            default_params=endpoint_inventory_params,
        ),
        "risk_insights": EndpointDefinition(
            name="risk_insights",
            path=settings.trend_vision_one_risk_insights_path.strip(),
            verified=bool(settings.trend_vision_one_risk_insights_path.strip()),
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Risk Insights",
            note=API_REFERENCE_NOTE,
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "connected_products": EndpointDefinition(
            name="connected_products",
            path=settings.trend_vision_one_connected_products_path.strip(),
            verified=bool(settings.trend_vision_one_connected_products_path.strip()),
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Connected Products",
            note=API_REFERENCE_NOTE,
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "eiqs_endpoints": EndpointDefinition(
            name="eiqs_endpoints",
            path=settings.trend_vision_one_eiqs_endpoints_path.strip(),
            verified=bool(
                settings.trend_vision_one_eiqs_endpoints_path.strip()
                and settings.trend_vision_one_eiqs_endpoints_query.strip()
            ),
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Endpoint Information Query Service",
            note="Requires header `TMV1-Query` with a tenant-valid query expression.",
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "workbench_alerts": EndpointDefinition(
            name="workbench_alerts",
            path=settings.trend_vision_one_workbench_alerts_path.strip() or "/v3.0/workbench/alerts",
            verified=True,
            docs_url=f"{DOCS_BASE}Authentication/",
            category="Alerts / Workbench",
            note="Verified in the official authentication guide example request.",
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "oat_detections": EndpointDefinition(
            name="oat_detections",
            path=settings.trend_vision_one_oat_detections_path.strip() or "/v3.0/oat/detections",
            verified=True,
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Observed Attack Techniques",
            note="Verified by live request. Returns OAT detections with detail, filters, and pagination.",
            default_params={"top": str(settings.trend_vision_one_default_page_size)},
        ),
        "search": EndpointDefinition(
            name="search",
            path=settings.trend_vision_one_search_path.strip() or "/v3.0/search",
            verified=True,
            docs_url=f"{DOCS_BASE}Resource-types/",
            category="Search",
            note="Verified by user input. Read-only search capability via POST for correlation and advanced queries.",
            default_params={},
            collection_like=False,
        ),
    }
