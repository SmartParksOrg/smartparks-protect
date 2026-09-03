"""Alembic environment.

Migrations run synchronously through psycopg (decision D30 and the reuse audit): the async URL
from settings is rewritten to the sync driver. Models are imported so autogenerate sees every
table; the geoalchemy2 helpers stop it from emitting duplicate spatial indexes.
"""

from logging.config import fileConfig
from typing import Any

from geoalchemy2.alembic_helpers import include_object as geoalchemy_include_object
from geoalchemy2.alembic_helpers import render_item, writer
from sqlalchemy import engine_from_config, pool

from alembic import context
from shared.config import get_settings
from shared.models import HYPERTABLES, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_TIMESCALE_INDEXES = {f"{table}_{column}_idx" for table, column in HYPERTABLES.items()}


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Skip the time index TimescaleDB creates on every hypertable, then apply the geoalchemy2
    filter for spatial indexes."""
    if type_ == "index" and reflected and name in _TIMESCALE_INDEXES:
        return False
    return bool(geoalchemy_include_object(obj, name, type_, reflected, compare_to))


def sync_database_url() -> str:
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    context.configure(
        url=sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_item=render_item,
        process_revision_directives=writer,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = sync_database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_item=render_item,
            process_revision_directives=writer,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
