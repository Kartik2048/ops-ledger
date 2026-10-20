# Production Deployment Runbook: Free-Tier Hardened Architecture

> **Target Topology:** Cloudflare Pages (Frontend) + Render Free Web Service (FastAPI Backend, Python 3.11 / Docker) + Supabase (Managed PostgreSQL)  
> **Cost:** $0.00 / month (100% Free Tier Compliant)  
> **Zero Drift:** Local zero-config SQLite (`sqlite+aiosqlite`) and `pytest` remain 100% functional.

---

## Architecture Overview

```
                                      +-----------------------------------------+
                                      |            CLOUDFLARE PAGES             |
                                      |  React 18 + Vite SPA (Global Edge CDN)  |
                                      |  Build: dist/  |  Route: _redirects     |
                                      +-----------------------------------------+
                                                           |
                                                HTTPS API Requests
                                          (VITE_API_BASE_URL /api)
                                                           v
+-------------------------------+     +-----------------------------------------+
|   CLOUDFLARE CRON WORKER      |     |             RENDER FREE TIER            |
|   deploy/cloudflare-keepalive | --> |   FastAPI App (Free 512MB RAM Web Svc)  |
|   Pings /api/health every 12m |     |   Native Python 3.11.9 / Dockerfile     |
|   Prevents 15m spin-down      |     |   Event-Driven Outbox Loop (asyncio)    |
+-------------------------------+     +-----------------------------------------+
                                                           |
                                             AsyncPG IPv4 Connection Pooler
                                             (Port 5432 / 6543, pool_size=5,
                                              connect_args statement_cache_size=0)
                                                           v
                                      +-----------------------------------------+
                                      |           SUPABASE POSTGRESQL           |
                                      |   Managed Relational Storage            |
                                      |   Tables, OCC Indexes, ACID Audit Logs  |
                                      +-----------------------------------------+
```

---

## Step 1: Provision Supabase (PostgreSQL Database)

1. Sign up or log in at [supabase.com](https://supabase.com).
2. Click **New Project**:
   - **Name:** `newtonite-operations`
   - **Database Password:** Set a strong password (save this securely).
   - **Region:** Select the region closest to your Render service (e.g., `us-east-1` / Oregon or Frankfurt).
3. Retrieve the **IPv4 Connection Pooler String**:
   - Navigate to **Project Settings** (gear icon) -> **Database**.
   - Under **Connection Parameters**, locate **Connection String** and switch to **URI**.
   - Under **Connection Pooling**, choose **Mode: Session** and port **5432** (or Transaction mode on port **6543**).
   - The connection string will look like:
     ```
     postgres://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres
     ```
   *(Note: The Newtonite backend in `backend/app/database.py` automatically normalizes `postgres://` into `postgresql+asyncpg://`, sets `connect_args={"statement_cache_size": 0}` to prevent `DuplicatePreparedStatementError` across Supavisor pooler connections, and tunes pool size to `pool_size=5`, `max_overflow=5` for Render's 512MB RAM constraint).*

---

## Step 2: Deploy Backend to Render (FastAPI Engine)

You can deploy the backend using either **Render Blueprints (Automated)**, the **Render Dashboard**, or **Docker Fallback**.

### Option A: Render Blueprint via `render.yaml` (Recommended 1-Click Setup)
1. Push your repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com), click **New** -> **Blueprint**.
3. Connect your repository. Render will automatically detect [render.yaml](file:///c:/Users/karti/Documents/Newtonite%20Assessment%20Task/render.yaml) and configure:
   - **Runtime:** `Python 3.11.9` (via `backend/.python-version`)
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - **Health Check Path:** `/api/health`
4. When prompted, fill in the secret environment variable:
   - `DATABASE_URL`: Your Supabase pooler connection string from Step 1.
5. Click **Apply**.

---

### Option B: Manual Render Dashboard Setup
1. In the [Render Dashboard](https://dashboard.render.com), click **New** -> **Web Service**.
2. Connect your GitHub repository.
3. Configure the service settings:
   - **Name:** `newtonite-backend`
   - **Region:** Closest to your Supabase region (e.g., `Oregon (US West)` or `Frankfurt (EU Central)`).
   - **Branch:** `main`
   - **Root Directory:** `backend`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - **Instance Type:** **Free** (512 MB RAM, 0.1 vCPU).
4. Under **Advanced** -> **Environment Variables**, add:

   | Key | Value | Notes |
   | :--- | :--- | :--- |
   | `PYTHON_VERSION` | `3.11.9` | Enforces Python 3.11 pre-built binary wheels |
   | `DATABASE_URL` | `postgres://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres` | Your Supabase Session Pooler URI |
   | `CORS_ORIGINS` | `*` *(or your Cloudflare Pages domain)* | Permitted CORS origins |

5. Under **Advanced** -> **Health Check Path**, enter:
   ```
   /api/health
   ```
6. Click **Create Web Service**.
   - On startup, the backend's `lifespan` automatically executes `Base.metadata.create_all` and runs the idempotent seed routine to generate all initial tables, roles, and 35 operational work items.
7. Verify Deployment:
   - Once deployed, copy your Render URL (e.g., `https://<your-app>.onrender.com`).
   - Test health check in your terminal:
     ```bash
     curl https://<your-app>.onrender.com/api/health
     ```
   - Expected response:
     ```json
     {
       "status": "ok",
       "database": "connected",
       "service": "newtonite-operations-engine",
       "version": "1.0.0",
       "timestamp": "2026-10-21T01:25:00.000000+00:00"
     }
     ```

---

### Option C: Docker Fallback (Deploy via Dockerfile)
If you prefer containerized deployment or are deploying to Railway/Fly.io:
1. When creating the Web Service, choose **Environment: Docker**.
2. Render detects [backend/Dockerfile](file:///c:/Users/karti/Documents/Newtonite%20Assessment%20Task/backend/Dockerfile), builds the Python 3.11-slim container, and binds Uvicorn to `$PORT`.

---

## Step 3: Deploy Frontend to Cloudflare Pages (React + Vite)

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com).
2. Go to **Workers & Pages** -> **Create application** -> **Pages** -> **Connect to Git**.
3. Select your repository:
   - **Framework preset:** `Vite`
   - **Root directory:** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
4. Add **Environment Variable**:

   | Key | Value | Notes |
   | :--- | :--- | :--- |
   | `VITE_API_BASE_URL` | `https://<your-app>.onrender.com/api` | Your live Render backend API URL |

5. Click **Save and Deploy**:
   - Cloudflare will build the production bundle and copy `public/_redirects` (`/* /index.html 200`) into `dist/_redirects`, ensuring SPA direct-URL routing works without 404 errors.
   - Your frontend will be live at `https://<project-name>.pages.dev`.

---

## Step 4: 12-Minute Keep-Alive Automation (Prevent Render Sleep & Supabase Pause)

### The Free-Tier Constraints
- **Render Free Tier:** Free Web Services spin down after **15 minutes** of zero incoming traffic. Cold start wakeup takes ~20–30 seconds.
- **Supabase Free Tier:** Projects without active database queries are paused after **7 days** of inactivity.

### Solution: 12-Minute Keep-Alive Ping
We provide two zero-cost solutions to keep both services perpetually warm:

#### Option A: Deploy Cloudflare Worker Cron (Included in Repo)
A pre-configured Cloudflare Worker is provided in `deploy/cloudflare-keepalive-worker/`:
```bash
cd deploy/cloudflare-keepalive-worker

# 1. Edit wrangler.toml with your Render public URL:
# BACKEND_HEALTH_URL = "https://<your-app>.onrender.com/api/health"

# 2. Deploy with Cloudflare Wrangler:
npx wrangler deploy
```
*Schedule:* Executes every 12 minutes (`*/12 * * * *`), sending a lightweight `GET /api/health` request that pings Supabase via `SELECT 1`. This satisfies both the Render 15-minute spin-down threshold and the Supabase 7-day query activity window.

#### Option B: External Webhook Monitor (cron-job.org / UptimeRobot)
1. Go to [cron-job.org](https://cron-job.org) or [uptimerobot.com](https://uptimerobot.com) (both 100% free).
2. Create a new monitor/job:
   - **URL:** `https://<your-app>.onrender.com/api/health`
   - **Interval:** Every 10 or 12 minutes
   - **Method:** `GET`

---

## Step 5: Cold-Start UX & Heartbeat Features

Even if an instance experiences a cold start:
1. **Intelligent Cold-Start Banner:** If the backend does not respond within 1.5 seconds on initial page load, `App.tsx` displays a non-intrusive status banner (*"Connecting to cloud backend instance..."*) with an animated loader, automatically dismissing once the health probe succeeds.
2. **Active-Tab Heartbeat:** As long as an operator keeps the Newtonite dashboard open in an active browser tab, `App.tsx` automatically emits a background ping to `${API_BASE_URL}/health` every 5 minutes (`300,000` ms) to keep the Render container awake during shifts.
3. **Event-Driven Outbox:** Mutations immediately wake the background outbox worker via `asyncio.Event` without polling, conserving 100% of Render's 0.1 vCPU and memory headroom during idle periods.

---

## Local Verification Commands

Before deploying to the cloud, you can test both environments locally:

```bash
# 1. Verify Backend Tests (16 tests covering OCC, RBAC, Idempotency, DLQ)
cd backend
.\.venv\Scripts\pytest -v

# 2. Verify Multi-User Concurrency Simulator
python simulate_conditions.py

# 3. Test Health Ping Locally
python -c "import httpx; print(httpx.get('http://127.0.0.1:8000/api/health').json())"

# 4. Verify Frontend TypeScript Compilation & Vite Production Bundle
cd ../frontend
npm run build
```
