FROM python:3.12-slim AS base

WORKDIR /app

# psycopg[binary] and ortools ship wheels, so no compiler toolchain is needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# §2 startup: alembic upgrade head -> seed -> uvicorn (one worker), done in the
# app lifespan (app/main.py), so the container's entrypoint just runs uvicorn.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
