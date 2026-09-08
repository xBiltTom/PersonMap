from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Lleva el esquema al último revision de Alembic.

    Sustituye al antiguo `Base.metadata.create_all`, que solo sabía crear tablas
    nuevas: nunca alteraba las existentes, así que añadir una columna rompía en
    silencio cualquier instalación ya desplegada. Las migraciones son ahora la
    única fuente de verdad del esquema.

    Es idempotente: en una base vacía aplica todo el historial; en una ya
    migrada no hace nada.
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Alembic es síncrono y abre su propia conexión; se ejecuta fuera del bucle
    # de eventos para no bloquearlo durante el arranque.
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
