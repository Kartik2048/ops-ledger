"""FastAPI Application Entrypoint.
Initializes database schema, seeds realistic data, orchestrates background outbox worker,
and mounts API routers.
Stage P5: Production Deployment & Free-Tier Resource Hardening.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import AsyncSessionLocal, Base, engine
from app.routes import outbox, users_teams, work_items
from app.seed import seed_database
from app.worker import run_outbox_worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    1. Ensures all relational tables and composite indexes exist.
    2. Idempotently seeds initial teams, users, and 35 realistic work items.
    3. Launches asynchronous background Transactional Outbox worker loop (event-driven).
    4. Gracefully stops background worker on shutdown.
    """
    # 1. Initialize relational schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Idempotently seed operational data
    async with AsyncSessionLocal() as session:
        await seed_database(session)

    # 3. Start background outbox worker task (event-driven with 60s fallback timeout)
    worker_task = asyncio.create_task(run_outbox_worker_loop(fallback_timeout=60.0))

    try:
        yield
    finally:
        # 4. Graceful shutdown
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await engine.dispose()


app = FastAPI(
    title="Newtonite Operations Platform API",
    version="1.0.0",
    description="High-Integrity Operations Engine with OCC, Idempotency, and Transactional Outbox",
    lifespan=lifespan,
)

# Environment-driven CORS configuration
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
if cors_origins_raw.strip() == "*":
    cors_origins = ["*"]
else:
    cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers under both /api and /api/v1 for uniform frontend routing
app.include_router(users_teams.router, prefix="/api")
app.include_router(work_items.router, prefix="/api")
app.include_router(outbox.router, prefix="/api")

# Backward-compatible /api/v1 alias mounts
app.include_router(users_teams.router, prefix="/api/v1")
app.include_router(work_items.router, prefix="/api/v1")
app.include_router(outbox.router, prefix="/api/v1")


@app.get("/api/health")
@app.get("/api/v1/health")
@app.get("/health")
async def health_check():
    """Health and readiness probe executing a lightweight SELECT 1 database ping.

    Used by Koyeb health checks and external cron jobs to prevent cold start idle sleep.
    """
    db_status = "connected"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {str(exc)}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "service": "newtonite-operations-engine",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
