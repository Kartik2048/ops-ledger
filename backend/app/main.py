"""FastAPI Application Entrypoint.
Initializes database schema, seeds realistic data, orchestrates background outbox worker,
and mounts API routers.
Stage P2: Async Outbox Worker, Seed Engine & API Wiring.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import AsyncSessionLocal, Base, engine
from app.routes import outbox, users_teams, work_items
from app.seed import seed_database
from app.worker import run_outbox_worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    1. Ensures all relational tables and composite indexes exist.
    2. Idempotently seeds initial teams, users, and 35 realistic work items.
    3. Launches asynchronous background Transactional Outbox worker loop.
    4. Gracefully stops background worker on shutdown.
    """
    # 1. Initialize relational schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Idempotently seed operational data
    async with AsyncSessionLocal() as session:
        await seed_database(session)

    # 3. Start background outbox worker task
    worker_task = asyncio.create_task(run_outbox_worker_loop(interval_seconds=3.0))

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

# CORS Middleware for React Vite client (port 5173 / localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
async def health_check():
    """Health and readiness probe."""
    return {
        "status": "healthy",
        "service": "newtonite-operations-engine",
        "version": "1.0.0",
    }
