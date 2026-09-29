"""§8 T6 Limits: 1 MB exact, +1 byte 413, counting stream, Content-Length before
reading, 5,000/5,001 rows, invalid UTF-8, multipart 415."""
from __future__ import annotations

import asyncio

import pytest

from app.csvio.limits import read_csv_body, read_limited
from app.csvio.parse import MAX_BYTES
from app.errors import BadRequestError, FileTooLargeError, UnsupportedMediaTypeError
from tests.conftest import requires_db
from tests.csvio.conftest import count, post_csv
from tests.csvio.helpers import csv_text, valid_id

HEADER = b"national_id,full_name,role\n"


def padded(size: int) -> bytes:
    """A valid CSV of exactly `size` bytes (padding is blank lines)."""
    body = HEADER + f"{valid_id(1)},A,guard\n".encode()
    assert len(body) <= size
    return body + b"\n" * (size - len(body))


class CountingStream:
    """Async chunk source that records how many bytes were pulled from it."""

    def __init__(self, total: int, chunk: int = 65_536):
        self.total, self.chunk, self.pulled, self.chunks = total, chunk, 0, 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.pulled >= self.total:
            raise StopAsyncIteration
        n = min(self.chunk, self.total - self.pulled)
        self.pulled += n
        self.chunks += 1
        return b"x" * n


class FakeRequest:
    def __init__(self, headers, stream):
        self.headers, self._stream, self.streamed = headers, stream, False

    def stream(self):
        self.streamed = True
        return self._stream


def test_exactly_the_limit_is_accepted_and_plus_one_is_not():
    assert len(asyncio.run(read_limited(CountingStream(MAX_BYTES)))) == MAX_BYTES
    with pytest.raises(FileTooLargeError) as e:
        asyncio.run(read_limited(CountingStream(MAX_BYTES + 1)))
    assert e.value.status_code == 413 and e.value.code == "FILE_TOO_LARGE"


def test_stream_is_aborted_at_once_not_read_to_the_end():
    stream = CountingStream(total=50 * MAX_BYTES, chunk=65_536)
    with pytest.raises(FileTooLargeError):
        asyncio.run(read_limited(stream))
    assert stream.pulled <= MAX_BYTES + 65_536  # the limit plus at most one chunk


def test_oversized_content_length_rejected_before_reading():
    req = FakeRequest({"content-type": "text/csv", "content-length": str(MAX_BYTES + 1)}, CountingStream(10))
    with pytest.raises(FileTooLargeError):
        asyncio.run(read_csv_body(req))
    assert req.streamed is False and req._stream.pulled == 0


def test_content_length_at_limit_passes_and_garbage_is_400():
    ok = FakeRequest({"content-type": "text/csv; charset=utf-8", "content-length": str(MAX_BYTES)}, CountingStream(5))
    assert len(asyncio.run(read_csv_body(ok))) == 5
    with pytest.raises(BadRequestError):
        asyncio.run(read_csv_body(FakeRequest({"content-type": "text/csv", "content-length": "abc"}, CountingStream(1))))


@pytest.mark.parametrize("ctype", ["multipart/form-data; boundary=x", "application/json", "text/plain", "application/octet-stream", None])
def test_other_content_types_are_415_before_reading(ctype):
    headers = {"content-type": ctype} if ctype else {}
    req = FakeRequest(headers, CountingStream(10))
    with pytest.raises(UnsupportedMediaTypeError) as e:
        asyncio.run(read_csv_body(req))
    assert e.value.status_code == 415 and req.streamed is False


@requires_db
def test_api_exactly_1mb_ok_and_plus_one_413(planner, db):
    client, _ = planner
    ok = post_csv(client, padded(MAX_BYTES))
    assert ok.status_code == 201, ok.text
    assert ok.json()["counts"]["new"] == 1
    over = post_csv(client, padded(MAX_BYTES + 1))
    assert over.status_code == 413 and over.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert count(db, "csv_imports") == 1


@requires_db
def test_api_chunked_body_without_content_length_is_limited_while_streaming(planner, db):
    client, _ = planner

    def gen():
        for _ in range(20):
            yield b"a" * 100_000  # 2 MB total, no Content-Length

    resp = client.post("/api/imports", content=gen(), headers={"content-type": "text/csv"})
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert count(db, "csv_imports") == 0


@requires_db
def test_api_rows_5000_ok_5001_413_and_nothing_stored(planner, db):
    client, _ = planner

    def make(n):
        return HEADER + b"".join(f"{valid_id(i)},N{i},guard\n".encode() for i in range(n))

    resp = post_csv(client, make(5000))
    assert resp.status_code == 201 and resp.json()["counts"]["new"] == 5000
    stored = count(db, "csv_imports")
    over = post_csv(client, make(5001))
    assert over.status_code == 413 and over.json()["error"]["code"] == "TOO_MANY_ROWS"
    assert count(db, "csv_imports") == stored and count(db, "workers") == 0


@requires_db
def test_api_invalid_utf8_is_400(planner, db):
    client, _ = planner
    resp = post_csv(client, HEADER + valid_id(1).encode() + b",\xff\xfe,guard\n")
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "INVALID_ENCODING"
    assert count(db, "csv_imports") == 0


@requires_db
def test_api_multipart_is_415(planner, db):
    client, _ = planner
    resp = client.post("/api/imports", files={"file": ("w.csv", csv_text(["national_id", "full_name", "role"], []), "text/csv")})
    assert resp.status_code == 415 and resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert client.post("/api/imports", json={"a": 1}).status_code == 415


@requires_db
def test_api_header_errors_are_400(planner):
    client, _ = planner
    r = post_csv(client, b"national_id,status\n1,Active\n")
    assert r.status_code == 400 and r.json()["error"]["code"] == "MISSING_COLUMNS"
    assert r.json()["error"]["details"]["missing"] == ["full_name", "role"]
    r = post_csv(client, b"national_id,ID,full_name,role\n")
    assert r.status_code == 400 and r.json()["error"]["code"] == "DUPLICATE_COLUMN"


@requires_db
def test_api_requires_login(db):
    from fastapi.testclient import TestClient

    from tests.csvio.conftest import make_app

    with TestClient(make_app()) as anon:
        assert post_csv(anon, HEADER).status_code == 401
        assert anon.get("/api/exports/workers.csv").status_code == 401
        assert anon.get("/api/imports/1").status_code == 401
