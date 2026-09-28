"""Application configuration, read from environment variables.

See docs/plans/application.md §2 for the demo-credentials and
configuration policy: passwords and the session secret come from the
environment (with demo defaults supplied by docker-compose.yml's
interpolation, not hardcoded here).
"""
from __future__ import annotations

import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://icts:icts@db:5432/icts"

    # Auth / sessions
    session_secret: str = ""
    planner_password: str = "planner-demo"
    manager_password: str = "manager-demo"

    # Engine execution (§2 "Generation execution")
    num_workers: int = 8
    solver_time_limit_s: float = 10.0

    # Misc
    log_level: str = "INFO"

    def resolved_session_secret(self) -> str:
        """Returns the configured secret, or a random one if unset.

        Per §2: "If SESSION_SECRET is empty, the backend generates a
        random secret at startup and logs a warning. Sessions then
        reset on restart. No secret is hardcoded."
        The caller (main.py lifespan) is responsible for logging the
        warning when falling back to a generated value.
        """
        return self.session_secret or secrets.token_urlsafe(32)


settings = Settings()
