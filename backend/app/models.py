"""Imports every `app/*/models.py` for side effects, so all tables are
registered on `Base.metadata` (and the ORM's relationship graph is
complete) before Alembic, `create_all`, or a flush needs the full
picture. Import this module (not the individual `*/models.py` files)
wherever that matters: `alembic/env.py`, `app/main.py`, tests.
"""
from __future__ import annotations

from app.auth import models as auth_models  # noqa: F401
from app.contracts import models as contracts_models  # noqa: F401
from app.csvio import models as csvio_models  # noqa: F401
from app.rosters import models as rosters_models  # noqa: F401
from app.workers import models as workers_models  # noqa: F401
