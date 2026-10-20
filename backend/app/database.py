"""Database Engine & Session Configuration.
Configured for high-concurrency SQLite (WAL Mode) with seamless Supabase PostgreSQL support.
Stage P5: Production Deployment & Free-Tier Resource Hardening.
"""

import os
from collections.abc import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# 1. Read and normalize DATABASE_URL
raw_db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./newtonite.db")

# Normalize Supabase / Heroku / generic postgres URIs for SQLAlchemy asyncpg
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+"):
    DATABASE_URL = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = raw_db_url

is_sqlite = DATABASE_URL.startswith("sqlite")

# 2. Create asynchronous engine with environment-tuned pooling
if is_sqlite:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
    )

    # Apply SQLite WAL and concurrency PRAGMAs on every connection
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
else:
    # Supabase PostgreSQL / Supavisor Connection Pooler configuration (ports 5432 & 6543)
    # statement_cache_size=0 prevents DuplicatePreparedStatementError under connection poolers
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"statement_cache_size": 0},
    )

# 3. Session factory for asynchronous database sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency helper providing an isolated asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
