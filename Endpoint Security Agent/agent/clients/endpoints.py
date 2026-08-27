from __future__ import annotations

from dataclasses import dataclass, field

from agent.core.config import Settings


DOCS_BASE = "https://automation.trendmicro.com/xdr/Guides/"


@dataclass(frozen=True)
class EndpointDefinition:
    name: str
    path: str
    verified: bool
    category: str
    docs_url: str = ""
    note: str = ""
    default_params: dict[str, str] = field(default_factory=dict)
    collection_like: bool = True


def get_endpoint_registry(settings: Settings) -> dict[str, EndpointDefinition]:
    page = str(settings.trend_vision_one_default_page_size)

    inventory_params: dict[str, str] = {"top": page}
    if settings.trend_vision_one_endpoint_inventory_order_by.strip():
        inventory_params["orderBy"] = settings.trend_vision_one_endpoint_inventory_order_by.strip()
    if settings.trend_vision_one_endpoint_inventory_select.strip():
        inventory_params["select"] = settings.trend_vision_one_endpoint_inventory_select.strip()

    return {
        # ── Accounts / Users ─────────────────────────────────────────────────
        "users": EndpointDefinition(
            name="users",
            path=settings.trend_vision_one_users_path or "/v3.0/accounts",
            verified=True,
            category="Accounts",
            docs_url=f"{DOCS_BASE}Authentication/",
            note="Returns user accounts. Supports top/skip pagination.",
            default_params={"top": page},
        ),
        # ── Endpoint inventory ────────────────────────────────────────────────
        "endpoint_inventory": EndpointDefinition(
            name="endpoint_inventory",
            path=settings.trend_vision_one_endpoints_path or "/v3.0/endpointSecurity/endpoints",
            verified=True,
            category="Endpoint Security",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Full endpoint inventory. Supports orderBy, top, select, TMV1-Filter.",
            default_params=inventory_params,
        ),
        # ── Risk insights ─────────────────────────────────────────────────────
        "risk_insights": EndpointDefinition(
            name="risk_insights",
            path=settings.trend_vision_one_risk_insights_path,
            verified=bool(settings.trend_vision_one_risk_insights_path.strip()),
            category="Risk Insights",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Requires path override via TREND_VISION_ONE_RISK_INSIGHTS_PATH.",
            default_params={"top": page},
        ),
        # ── Connected products ────────────────────────────────────────────────
        "connected_products": EndpointDefinition(
            name="connected_products",
            path=settings.trend_vision_one_connected_products_path,
            verified=bool(settings.trend_vision_one_connected_products_path.strip()),
            category="Connected Products",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Requires path override via TREND_VISION_ONE_CONNECTED_PRODUCTS_PATH.",
            default_params={"top": page},
        ),
        # ── EIQS endpoints ────────────────────────────────────────────────────
        "eiqs_endpoints": EndpointDefinition(
            name="eiqs_endpoints",
            path=settings.trend_vision_one_eiqs_endpoints_path or "/v3.0/eiqs/endpoints",
            verified=bool(
                settings.trend_vision_one_eiqs_endpoints_path.strip()
                and settings.trend_vision_one_eiqs_endpoints_query.strip()
            ),
            category="Endpoint Information Query Service",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Requires TMV1-Query header. Set TREND_VISION_ONE_EIQS_ENDPOINTS_QUERY.",
            default_params={"top": page},
        ),
        # ── Workbench alerts ──────────────────────────────────────────────────
        "workbench_alerts": EndpointDefinition(
            name="workbench_alerts",
            path=settings.trend_vision_one_workbench_alerts_path or "/v3.0/workbench/alerts",
            verified=True,
            category="Alerts / Workbench",
            docs_url=f"{DOCS_BASE}Authentication/",
            note="Security incidents correlated by Vision One. Supports time window and ordering.",
            default_params={"top": page},
        ),
        # ── OAT detections ────────────────────────────────────────────────────
        "oat_detections": EndpointDefinition(
            name="oat_detections",
            path=settings.trend_vision_one_oat_detections_path or "/v3.0/oat/detections",
            verified=True,
            category="Observed Attack Techniques",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Real-time attack technique detections with MITRE ATT&CK mapping.",
            default_params={"top": page},
        ),
        # ── Search ────────────────────────────────────────────────────────────
        "search": EndpointDefinition(
            name="search",
            path=settings.trend_vision_one_search_path or "/v3.0/search",
            verified=True,
            category="Search",
            docs_url=f"{DOCS_BASE}Resource-types/",
            note="Advanced read-only search via POST. Used for correlation queries.",
            default_params={},
            collection_like=False,
        ),
    }
