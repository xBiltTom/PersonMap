#!/usr/bin/env python3
"""Create/reset the dedicated PersonMap Lite database and migrate it to head."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


DATABASE_NAME = "personmap_lite"
REQUIRED_TABLES = {
    "analysis_notes",
    "awareness_surveys",
    "correlation_groups",
    "targets",
    "investigations",
    "entities",
    "relationships",
    "tool_executions",
    "entity_observations",
    "investigation_sessions",
    "investigation_trace_events",
    "review_decisions",
    "alembic_version",
}
EXPECTED_TYPES = {
    ("targets", "id"): "UUID",
    ("targets", "extra_data"): "JSONB",
    ("investigations", "id"): "UUID",
    ("investigations", "metrics"): "JSONB",
    ("entities", "id"): "UUID",
    ("entities", "metadata_info"): "JSONB",
    ("relationships", "id"): "UUID",
    ("relationships", "evidence"): "JSONB",
    ("tool_executions", "id"): "UUID",
    ("tool_executions", "input_summary"): "JSONB",
    ("entity_observations", "id"): "UUID",
    ("entity_observations", "evidence_urls"): "JSONB",
    ("review_decisions", "id"): "UUID",
    ("review_decisions", "investigation_id"): "UUID",
    ("review_decisions", "entity_id"): "UUID",
    ("review_decisions", "history"): "JSONB",
}
CASCADE_FOREIGN_KEYS = {
    ("investigations", "target_id", "targets", "id"),
    ("entities", "investigation_id", "investigations", "id"),
    ("relationships", "source_entity_id", "entities", "id"),
    ("relationships", "target_entity_id", "entities", "id"),
    ("tool_executions", "investigation_id", "investigations", "id"),
    ("entity_observations", "investigation_id", "investigations", "id"),
    ("entity_observations", "entity_id", "entities", "id"),
    ("entity_observations", "tool_execution_id", "tool_executions", "id"),
    ("review_decisions", "investigation_id", "investigations", "id"),
    ("review_decisions", "entity_id", "entities", "id"),
}
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _configuration() -> tuple[str, object]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("Falta DATABASE_URL; apunta explícitamente a la base personmap_lite.")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or url.drivername != "postgresql+asyncpg":
        raise SystemExit("DATABASE_URL debe usar PostgreSQL con el driver postgresql+asyncpg.")
    if url.database != DATABASE_NAME:
        raise SystemExit(
            f"Operación cancelada: DATABASE_URL apunta a {url.database!r}; "
            f"este script solo puede preparar {DATABASE_NAME!r}."
        )
    declared_environment = os.getenv("PERSONMAP_ENV")
    if declared_environment and declared_environment.casefold() != "lite":
        raise SystemExit("PERSONMAP_ENV está definido y no es 'lite'; no se tocará ninguna base.")
    return database_url, url


async def _ensure_database(url, *, reset: bool) -> None:
    maintenance_url = url.set(database="postgres")
    engine = create_async_engine(maintenance_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            exists = bool((await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": DATABASE_NAME}
            )).scalar_one_or_none())

            if reset and exists:
                await connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ), {"name": DATABASE_NAME})
                # The target database name was checked against a fixed allowlist above.
                await connection.exec_driver_sql(f'DROP DATABASE "{DATABASE_NAME}"')
                exists = False

            if not exists:
                # The target database name was checked against a fixed allowlist above.
                await connection.exec_driver_sql(f'CREATE DATABASE "{DATABASE_NAME}"')
                print(f"{'Recreada' if reset else 'Creada'} la base {DATABASE_NAME}.")
            else:
                print(f"La base {DATABASE_NAME} ya existe; se conservarán sus datos.")
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


def _verify_review_table(connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    missing = REQUIRED_TABLES - tables
    if missing:
        raise RuntimeError(f"Faltan tablas requeridas: {', '.join(sorted(missing))}")

    for (table_name, column_name), expected_type in EXPECTED_TYPES.items():
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        if columns[column_name]["type"].__class__.__name__ != expected_type:
            raise RuntimeError(f"{table_name}.{column_name} no es {expected_type} PostgreSQL.")

    unique_pairs = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("review_decisions")
    }
    if ("investigation_id", "entity_id") not in unique_pairs:
        raise RuntimeError("Falta UNIQUE(investigation_id, entity_id) en review_decisions.")

    actual_cascade_fks = set()
    for table_name in REQUIRED_TABLES - {"alembic_version"}:
        for fk in inspector.get_foreign_keys(table_name):
            if len(fk["constrained_columns"]) == len(fk["referred_columns"]) == 1:
                if fk.get("options", {}).get("ondelete", "").upper() == "CASCADE":
                    actual_cascade_fks.add((table_name, fk["constrained_columns"][0],
                        fk["referred_table"], fk["referred_columns"][0]))
    missing_cascades = CASCADE_FOREIGN_KEYS - actual_cascade_fks
    if missing_cascades:
        raise RuntimeError(f"Faltan claves foráneas ON DELETE CASCADE: {sorted(missing_cascades)}")

    checks = {constraint["name"]: constraint["sqltext"]
              for constraint in inspector.get_check_constraints("review_decisions")}
    check = checks.get("ck_review_decisions_valid_decision", "").replace('"', "").casefold()
    if not all(value in check for value in ("confirmed", "rejected", "uncertain")):
        raise RuntimeError("Falta el CHECK ck_review_decisions_valid_decision.")

    indexes = {index["name"] for index in inspector.get_indexes("review_decisions")}
    expected_indexes = {"ix_review_decisions_investigation_id", "ix_review_decisions_entity_id"}
    if not expected_indexes <= indexes:
        raise RuntimeError("Faltan índices de búsqueda de review_decisions.")

    print("Tablas del esquema verificadas: " + ", ".join(sorted(REQUIRED_TABLES)))
    print("Tipos UUID/JSONB, UNIQUE, índices y FKs CASCADE verificados.")
    print("CHECK ck_review_decisions_valid_decision verificado.")


async def _verify_database(database_url: str, config: Config) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            current = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            expected_heads = ScriptDirectory.from_config(config).get_heads()
            if len(expected_heads) != 1:
                raise RuntimeError(f"Se esperaba un único Alembic head, se encontraron: {expected_heads}")
            if current != expected_heads:
                raise RuntimeError(f"La base quedó en {current}; el head esperado es {expected_heads}.")
            print(f"Alembic head verificado: {expected_heads[0]}.")
            await connection.run_sync(_verify_review_table)
    finally:
        await engine.dispose()


async def bootstrap(*, reset: bool) -> None:
    database_url, url = _configuration()
    await _ensure_database(url, reset=reset)

    # migrations/env.py uses the same environment setting as the application.
    # Set it before Alembic imports the app settings, and pin the environment label.
    os.environ["DATABASE_URL"] = database_url
    os.environ["PERSONMAP_ENV"] = "lite"
    sys.path.insert(0, str(BACKEND_ROOT))
    config = _alembic_config()
    # migrations/env.py uses asyncio.run(), so invoke the synchronous Alembic
    # command on a worker thread instead of nesting it in this async loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    await _verify_database(database_url, config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help=f"borrar y recrear {DATABASE_NAME}; requiere DATABASE_URL con ese nombre exacto",
    )
    args = parser.parse_args()
    asyncio.run(bootstrap(reset=args.reset))


if __name__ == "__main__":
    main()
