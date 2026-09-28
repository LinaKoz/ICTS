"""Placeholder Alembic environment; the real one (with the metadata
target and async engine wiring) is added in T2 (§8)."""
from alembic import context

config = context.config


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # TODO(T2): wire up app.db's engine and the ORM metadata.
    pass


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
