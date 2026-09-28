"""Proves the one error shape (§6): {"error": {"code","message","details"}}."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import NotFoundError, register_exception_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise NotFoundError("worker not found", details={"worker_id": "123"})

    return app


def test_error_shape_and_status():
    client = TestClient(_make_app())
    resp = client.get("/boom")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "worker not found"
    assert body["error"]["details"] == {"worker_id": "123"}


def test_error_code_families_have_expected_status():
    from app import errors as e

    assert e.VersionConflictError("x").status_code == 409
    assert e.StalePreviewError("x").status_code == 409
    assert e.AlreadyConfirmedError("x").status_code == 409
    assert e.WorkerInUseError("x").status_code == 409
    assert e.ApprovedEditNotAcknowledgedError("x").status_code == 409
    assert e.FileTooLargeError("x").status_code == 413
    assert e.TooManyRowsError("x").status_code == 413
    assert e.UnsupportedMediaTypeError("x").status_code == 415
    assert e.HardViolationsError("x").status_code == 422
    assert e.LockedShiftError("x").status_code == 422
    assert e.GenerationInProgressError("x").status_code == 429
    assert e.EngineError("x").status_code == 500
