#!/usr/bin/env python3
"""Writes backend/openapi.json from the FastAPI app, with no server running.

Usage: python scripts/export_openapi.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import export_openapi  # noqa: E402

if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"
    export_openapi(str(out))
    print(f"wrote {out}")
