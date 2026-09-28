"""`GET /api/meta` (§6). Vertical-slice endpoint frozen in T0."""
from __future__ import annotations

from fastapi import APIRouter

from app.api_schemas.meta import CsvAliasesOut, DemandEntry, MetaOut
from app.scheduling.types import DEFAULT_DEMAND

router = APIRouter(prefix="/api", tags=["meta"])

_HEADER_ALIASES = {
    "national_id": ["id", "israeli_id", "id_number"],
    "full_name": ["name"],
    "hourly_rate_ils": ["hourly_rate", "hourly_cost"],
    "min_monthly_hours": ["min_hours"],
    "max_monthly_hours": ["max_hours"],
    "available_days": ["days"],
    "available_shifts": ["shifts"],
}
_ROLE_ALIASES = {
    "GENERAL_GUARD": ["General Guard", "general-guard", "Guard"],
    "SCREENER": ["Screener"],
    "SUPERVISOR": ["Supervisor"],
}
_STATUS_ALIASES = {
    "ACTIVE": ["Active"],
    "INACTIVE": ["Inactive"],
}


@router.get("/meta", response_model=MetaOut)
async def get_meta() -> MetaOut:
    demand = [
        DemandEntry(shift=shift.value, role=role.value, headcount=count)
        for (shift, role), count in DEFAULT_DEMAND.items()
    ]
    return MetaOut(
        shifts=["A", "B", "C"],
        roles=["GENERAL_GUARD", "SCREENER", "SUPERVISOR"],
        demand=demand,
        csv_aliases=CsvAliasesOut(
            header_aliases=_HEADER_ALIASES,
            role_aliases=_ROLE_ALIASES,
            status_aliases=_STATUS_ALIASES,
        ),
    )
