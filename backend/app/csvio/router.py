"""CSV API (§6 "CSV"): `POST /api/imports` (raw `text/csv`), `GET /api/imports/{id}`,
`POST /api/imports/{id}/confirm`, `GET /api/exports/workers.csv`. PLANNER and
MANAGER may use all of it (P12)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_schemas.common import error_responses
from app.api_schemas.csv import ImportConfirmOut, ImportConfirmRequest, ImportPreviewOut
from app.auth.models import User
from app.auth.session import require_role
from app.changes.service import month_start
from app.csvio.export import export_workers
from app.csvio.limits import read_csv_body
from app.csvio.parse import parse_csv
from app.csvio.service import (
    StaleImportError,
    confirm_import,
    create_preview,
    fresh_preview,
    get_import,
    preview_from_record,
)
from app.db import get_session
from app.errors import StalePreviewError
from app.rosters.problem_builder import MONTH_PATTERN, parse_month
from app.timeutil import now_israel

router = APIRouter(tags=["csv"])

_ANY_PLANNER = Depends(require_role("PLANNER", "MANAGER"))

_CSV_BODY = {
    "requestBody": {
        "required": True,
        "description": "The raw CSV file (UTF-8, optional BOM), at most 1,048,576 bytes and 5,000 data rows.",
        "content": {"text/csv": {"schema": {"type": "string"}}},
    }
}


@router.post(
    "/api/imports",
    response_model=ImportPreviewOut,
    status_code=201,
    openapi_extra=_CSV_BODY,
    responses=error_responses(400, 401, 403, 413, 415),
)
async def create_import(
    request: Request,
    user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ImportPreviewOut:
    """Parses and classifies the file and stores a PENDING import. Invalid rows
    are reported, not fatal. Nothing is applied until `confirm`."""
    data = await read_csv_body(request)
    now = now_israel()
    default_month = month_start(now)  # frozen for this import (D11)
    parsed = parse_csv(data, default_month)
    preview = await create_preview(session, parsed.rows, parsed.unknown_columns, user.id, now, default_month)
    await session.commit()
    return preview


@router.get("/api/imports/{import_id}", response_model=ImportPreviewOut, responses=error_responses(401, 403, 404, 422))
async def read_import(
    import_id: int,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ImportPreviewOut:
    return preview_from_record(await get_import(session, import_id))


@router.post(
    "/api/imports/{import_id}/confirm",
    response_model=ImportConfirmOut,
    responses=error_responses(401, 403, 404, 409, 422),
)
async def confirm(
    import_id: int,
    body: ImportConfirmRequest,
    user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> ImportConfirmOut:
    """One transaction. A second confirm is 409 `ALREADY_CONFIRMED` (details:
    the stored result); a moved base is 409 `STALE_PREVIEW` (details: a fresh
    preview, stored as a new import) and nothing is applied."""
    now = now_israel()
    actor_id = user.id  # read before a rollback expires the ORM object
    try:
        out = await confirm_import(session, import_id, dict(body.decisions), actor_id, now)
    except StaleImportError as stale:
        await session.rollback()
        fresh = await fresh_preview(session, import_id, actor_id, now)
        await session.commit()
        raise StalePreviewError(
            stale.message, details={"reasons": stale.details, "preview": fresh.model_dump(mode="json")}
        ) from None
    except BaseException:
        await session.rollback()
        raise
    await session.commit()
    return out


@router.get(
    "/api/exports/workers.csv",
    response_class=Response,
    responses={
        200: {
            "description": "UTF-8 CSV with BOM. Headers X-Worker-Count and X-No-Contract-Count give the totals.",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        },
        **error_responses(401, 403, 422),
    },
)
async def export_csv(
    month: Annotated[str | None, Query(pattern=MONTH_PATTERN, description="YYYY-MM; default: the current Israel month")] = None,
    _user: User = _ANY_PLANNER,
    session: AsyncSession = Depends(get_session),
) -> Response:
    target = parse_month(month) if month else month_start(now_israel())
    result = await export_workers(session, target)
    return Response(
        content=result.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="workers-{target:%Y-%m}.csv"',
            "X-Worker-Count": str(result.worker_count),
            "X-No-Contract-Count": str(result.no_contract_count),
            "Access-Control-Expose-Headers": "X-Worker-Count, X-No-Contract-Count, Content-Disposition",
        },
    )
