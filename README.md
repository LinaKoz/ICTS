# ICTS Europe Rostering System

**Status: work in progress.** This is the T0 skeleton (compose, Dockerfiles,
shared backend/frontend contracts). The full README — architecture, schema,
setup, CSV format, scheduling design and benchmarks, assumptions,
trade-offs and limitations — is written in T9 (see `docs/plans/application.md`).

## Quick start (once later tasks land)

```
cp .env.example .env   # optional; edit to override demo passwords
docker compose up
```

Frontend: http://localhost:8080  Backend health: http://localhost:8080/api/health

## Repo layout

See `docs/plans/application.md` §2 for the full architecture.
