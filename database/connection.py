"""
database/connection.py
SQLite connection setup with WAL mode and connection pooling.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event, text

from config.settings import settings


def _get_database_path() -> Path:
    path = settings.database_path_resolved
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _enable_wal_mode(dbapi_connection, connection_record):
    """Enable WAL mode and other performance pragmas on every new connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


def create_engine():
    db_path = _get_database_path()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=settings.is_development,
        pool_pre_ping=True,
    )

    # Register WAL pragma hook
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        _enable_wal_mode(dbapi_connection, connection_record)

    return engine


# Global engine and session factory
engine = create_engine()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency — yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def db_session():
    """Context manager for use outside FastAPI (e.g., background tasks)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables and run incremental column additions if they don't exist."""
    from database.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Incremental column migrations for SQLite
        columns_to_add = [
            ("review_required", "BOOLEAN DEFAULT 1"),
            ("review_completed", "BOOLEAN DEFAULT 0"),
            ("submission_confirmed_by_user", "BOOLEAN DEFAULT 0"),
            ("resume_compiler_error", "TEXT"),
        ]
        for col_name, col_type in columns_to_add:
            try:
                await conn.execute(text(f"ALTER TABLE applications ADD COLUMN {col_name} {col_type}"))
            except Exception:
                pass  # Column already exists
