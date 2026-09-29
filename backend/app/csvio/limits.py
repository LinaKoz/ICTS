"""Raw request-body reading with the P14 byte limit, enforced while reading.

`POST /imports` accepts only `text/csv`. A `Content-Length` over the limit
is rejected before the body is touched; otherwise the stream is consumed
chunk by chunk with a running byte count and aborted as soon as it exceeds
the limit, so at most one chunk past the limit is ever read.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from app.csvio.parse import MAX_BYTES
from app.errors import BadRequestError, FileTooLargeError, UnsupportedMediaTypeError


class RequestLike(Protocol):
    headers: Mapping[str, str]

    def stream(self) -> AsyncIterator[bytes]: ...


def check_content_type(content_type: str | None) -> None:
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media != "text/csv":
        raise UnsupportedMediaTypeError(
            f"POST /imports takes a raw text/csv body (got {media or 'no content type'})"
        )


def check_content_length(value: str | None, limit: int = MAX_BYTES) -> None:
    if value is None:
        return
    try:
        length = int(value)
    except ValueError:
        raise BadRequestError("invalid Content-Length header") from None
    if length < 0:
        raise BadRequestError("invalid Content-Length header")
    if length > limit:
        raise FileTooLargeError(f"the file is larger than the {limit}-byte limit", details={"limit_bytes": limit})


async def read_limited(stream: AsyncIterator[bytes], limit: int = MAX_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > limit:
            raise FileTooLargeError(f"the file is larger than the {limit}-byte limit", details={"limit_bytes": limit})
        chunks.append(chunk)
    return b"".join(chunks)


async def read_csv_body(request: RequestLike, limit: int = MAX_BYTES) -> bytes:
    check_content_type(request.headers.get("content-type"))
    check_content_length(request.headers.get("content-length"), limit)
    return await read_limited(request.stream(), limit)
