"""`GET /api/meta` (§6): shifts, roles, demand, and the documented CSV
header/value aliases."""
from __future__ import annotations

from pydantic import BaseModel

from app.api_schemas.common import Role, Shift


class DemandEntry(BaseModel):
    shift: Shift
    role: Role
    headcount: int


class CsvAliasesOut(BaseModel):
    """P14 documented header and value aliases."""

    header_aliases: dict[str, list[str]]
    role_aliases: dict[str, list[str]]
    status_aliases: dict[str, list[str]]


class MetaOut(BaseModel):
    shifts: list[Shift]
    roles: list[Role]
    demand: list[DemandEntry]
    csv_aliases: CsvAliasesOut
