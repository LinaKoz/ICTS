"""`GET /api/meta` (§6). Vertical-slice endpoint frozen in T0."""
from __future__ import annotations

from fastapi import APIRouter

from app.api_schemas.meta import CsvAliasesOut, DemandEntry, MetaOut
from app.csvio.parse import HEADER_ALIASES
from app.scheduling import DEFAULT_DEMAND

router = APIRouter(prefix="/api", tags=["meta"])


def _header_aliases() -> dict[str, list[str]]:
    """Canonical column -> its aliases, derived from the parser so the two never drift."""
    out: dict[str, list[str]] = {}
    for alias, canonical in HEADER_ALIASES.items():
        out.setdefault(canonical, []).append(alias)
    return out


_HEADER_ALIASES = _header_aliases()
_ROLE_ALIASES = {
    "GENERAL_GUARD": ["General Guard", "general-guard", "Guard", "GG"],
    "SCREENER": ["Screener", "SCR"],
    "SUPERVISOR": ["Supervisor", "SUP"],
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
