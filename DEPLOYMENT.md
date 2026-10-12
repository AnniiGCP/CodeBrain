# CodeBrain — Production Deployment Guide
## Vercel + Render + Supabase + GitHub Actions

**Release Target:** Public Production / Beta Deployment  
**Architecture:** Decoupled React SPA (Vercel) + FastAPI Backend (Render) + PostgreSQL Database & Object Storage (Supabase) + CI/CD (GitHub Actions)  
**Last Updated:** October 2026  

---

## 1. Verified Production Architecture

CodeBrain is decoupled into specialized serverless and cloud platform components to ensure zero-cost scalability, isolation, and rapid deployment.

```mermaid
flowchart TD
    User[Public User]
    Browser[CodeBrain Frontend]
    Vercel[Vercel Platform]
    Render[Render FastAPI Backend]
    SupabaseDB[Supabase PostgreSQL]
    Storage[Supabase Storage]
    AI[Configured AI Providers]
    GitHub[GitHub Repository]
    Actions[GitHub Actions]

    User --> Browser
    Browser --> Vercel
    Browser --> Render
    Render --> SupabaseDB
    Render --> Storage
    Render --> AI
    GitHub --> Actions
    Actions --> Vercel
    Actions --> Render
```

### Platform Responsibility Matrix

| Component | Platform | Responsibility | Durability / Tier |
| :--- | :--- | :--- | :--- |
| **Frontend** | **Vercel** | Static hosting for React 19 / Vite SPA, asset caching, edge CDN, SPA routing. | Vercel Free / Hobby tier |
| **Backend** | **Render** | FastAPI Python 3.11 ASGI service, AST parsing, RAG coordination, AI model routing. | Render Free / Starter Web Service |
| **Database** | **Supabase** | Managed PostgreSQL 15+, persistent relational metadata, sessions, error reports. | Supabase Free tier (500MB DB) |
| **Object Storage**| **Supabase Storage** | Private bucket for exported documentation artifacts (PDF/HTML/ZIP packages). | Supabase Free tier (1GB storage) |
| **CI/CD** | **GitHub Actions**| Automated testing (244 tests), security auditing, linting, and deploy hooks. | 2,000 free runner mins/month |
| **Source Control**| **GitHub** | Repository management, GitOps branches (`ai-fix/*`), and automated PRs. | Public / Private repository |
| **AI Providers** | **Direct APIs** | Upstream inference (NVIDIA NIM, Groq, APInex, Anthropic). | Pay-as-you-go / Free tier |

---

## 2. Service Setup Requirements

### 2.1 Supabase Setup (Database & Storage)

1. **Create Supabase Project:**
   - Sign in at [https://supabase.com](https://supabase.com) and create a new project (e.g. `codebrain-prod`).
   - Choose a geographic region close to your Render deployment (e.g. US East - N. Virginia).
   - Set a strong database password and save it securely.

2. **Initialize Database Schema:**
   - In the Supabase Dashboard, open the **SQL Editor**.
   - Open and copy the contents of [`supabase/migrations/20261012_initial_schema.sql`](file:///b:/College/7%20SEM/BCG786%20Major%20Project%20Phase%20II/ai/supabase/migrations/20261012_initial_schema.sql).
   - Paste the SQL script and click **Run**.
   - Verify that tables are created: `users`, `repos`, `repo_files`, `symbols`, `error_reports`, `automation_logs`, `conversations`, `conversation_messages`, `apinex_daily_usage`, `repo_readmes`, `repo_ci_configs`, `repo_ci_runs`.

3. **Get PostgreSQL Connection String:**
   - Go to **Project Settings** -> **Database**.
   - Under **Connection string**, select **URI**.
   - Choose **Transaction Pooler** (Port 6543, recommended for Render/serverless):
     ```
     postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
     ```
   - Replace `[YOUR-PASSWORD]` with your actual database password.

4. **(Optional) Configure Supabase Storage Bucket:**
   - Go to **Storage** -> **Create a new bucket**.
   - Name: `codebrain-artifacts`.
   - Access: **Private** (or Public depending on whether you want signed download links).
   - Retrieve your Project URL (`https://[PROJECT-REF].supabase.co`) and `service_role` secret key from **Project Settings** -> **API**.

---

### 2.2 Render Backend Setup

1. **Deploy via Render Blueprint (Recommended):**
   - Sign in to [https://render.com](https://render.com).
   - Click **New +** -> **Blueprint**.
   - Connect your GitHub repository (`AnniiGCP/MAJOR-PROJECT`).
   - Render will detect [`render.yaml`](file:///b:/College/7%20SEM/BCG786%20Major%20Project%20Phase%20II/ai/render.yaml) automatically and prompt you for the required environment variables.
   - Enter your `DATABASE_URL` (from Supabase), `FRONTEND_URL` (from Vercel), and your AI provider API keys.
   - Click **Apply**.

2. **Manual Web Service Configuration (Alternative):**
   - Click **New +** -> **Web Service**.
   - Select your repository.
   - Configure settings:
     - **Name:** `codebrain-backend`
     - **Root Directory:** `backend`
     - **Runtime:** `Python 3`
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
     - **Health Check Path:** `/health`
     - **Plan:** `Free`

3. **Obtain Render Deploy Hook & Backend URL:**
   - In Render Dashboard under your Web Service, go to **Settings**.
   - Copy the **Deploy Hook** URL (`https://api.render.com/deploy/srv-...`).
   - Copy the service URL (`https://codebrain-backend.onrender.com`).

---

### 2.3 Vercel Frontend Setup

1. **Import Project to Vercel:**
   - Sign in to [https://vercel.com](https://vercel.com).
   - Click **Add New...** -> **Project**.
   - Import your GitHub repository (`AnniiGCP/MAJOR-PROJECT`).

2. **Configure Build Settings:**
   - **Framework Preset:** `Vite`
   - **Root Directory:** `./` (or `frontend`) — both [`vercel.json`](file:///b:/College/7%20SEM/BCG786%20Major%20Project%20Phase%20II/ai/vercel.json) and [`frontend/vercel.json`](file:///b:/College/7%20SEM/BCG786%20Major%20Project%20Phase%20II/ai/frontend/vercel.json) are pre-configured with SPA rewrites.
   - **Build Command:** `cd frontend && npm run build` (if Root is `./`) or `npm run build` (if Root is `frontend`).
   - **Output Directory:** `frontend/dist` (or `dist`).

3. **Configure Environment Variables:**
   - `VITE_API_URL`: Your Render backend URL (e.g. `https://codebrain-backend.onrender.com`).
   - `VITE_API_BASE_URL`: `https://codebrain-backend.onrender.com`.

4. **Deploy:**
   - Click **Deploy**. Vercel will build and assign your domain (e.g. `https://codebrain-app.vercel.app`).
   - Copy your assigned production Vercel URL and update `FRONTEND_URL` and `CORS_ORIGINS` in your Render backend settings.

---

## 3. Required Environment Variables

### 3.1 Vercel Frontend Environment Variables
Set these in the **Vercel Dashboard** under **Project Settings -> Environment Variables**:

| Variable Name | Required | Secret? | Value / Description |
| :--- | :---: | :---: | :--- |
| `VITE_API_URL` | **Yes** | No | Full URL of the Render backend: `https://codebrain-backend.onrender.com`. |
| `VITE_API_BASE_URL` | Optional | No | Alias for `VITE_API_URL` to ensure client compatibility. |

> **Security Rule:** Never place AI provider keys (Groq, NVIDIA, Anthropic), GitHub secrets, or database passwords in Vercel environment variables.

---

### 3.2 Render Backend Environment Variables
Set these in the **Render Dashboard** under **Environment** (or via `render.yaml`):

| Variable Name | Required | Secret? | Recommended Production Value / Purpose |
| :--- | :---: | :---: | :--- |
| `ENVIRONMENT` | **Yes** | No | `production` (enforces secure cookies, disables dev login, enables HSTS). |
| `DATABASE_URL` | **Yes** | **Yes** | Supabase pooled connection string (`postgresql://postgres.[ref]:[pw]@...pooler.supabase.com:6543/postgres?sslmode=require`). |
| `SESSION_SECRET` | **Yes** | **Yes** | Cryptographically random 64-byte hex string for signing session cookies. |
| `ENCRYPTION_KEY` | **Yes** | **Yes** | Fernet key for encrypting user tokens at rest: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `FRONTEND_URL` | **Yes** | No | Your Vercel frontend URL: `https://codebrain-app.vercel.app`. |
| `CORS_ORIGINS` | **Yes** | No | Comma-separated allowed origins: `https://codebrain-app.vercel.app`. |
| `SECURE_COOKIES` | **Yes** | No | `true` (enforces HTTPS cookie transmission). |
| `ALLOW_DEV_LOGIN` | **Yes** | No | `false` (hard disables the `/auth/dev-login` developer route). |
| `TRUSTED_PROXIES` | **Yes** | No | `10.0.0.0/8,172.16.0.0/12,127.0.0.1` (CIDRs for Render reverse proxies). |
| `NVIDIA_NIM_API_KEY` | Optional | **Yes** | Upstream API key for NVIDIA NIM LLMs. |
| `GROQ_API_KEY` | Optional | **Yes** | Upstream API key for Groq Cloud LLMs and Whisper. |
| `APINEX_API_KEY` | Optional | **Yes** | Upstream API key for APInex GPT-6 Luna. |
| `ANTHROPIC_API_KEY` | Optional | **Yes** | Upstream API key for Claude 3.5 Sonnet. |
| `GITHUB_OAUTH_CLIENT_ID` | Optional | No | GitHub OAuth App Client ID (for GitHub login). |
| `GITHUB_OAUTH_CLIENT_SECRET` | Optional | **Yes** | GitHub OAuth App Client Secret. |
| `GITHUB_OAUTH_REDIRECT_URI` | Optional | No | `https://codebrain-backend.onrender.com/auth/github/callback`. |
| `SUPABASE_URL` | Optional | No | `https://[PROJECT-REF].supabase.co` (for Supabase Storage). |
| `SUPABASE_SERVICE_ROLE_KEY` | Optional | **Yes** | Supabase Service Role key (for storage upload permissions). |
| `SUPABASE_STORAGE_BUCKET` | Optional | No | `codebrain-artifacts`. |

---

### 3.3 GitHub Actions Secrets
Set these in your **GitHub Repository Settings -> Secrets and variables -> Actions**:

| Secret Name | Required for | Value / Description |
| :--- | :--- | :--- |
| `RENDER_DEPLOY_HOOK_URL` | Automated backend deployment | The Deploy Hook URL from Render Web Service Settings. |
| `RENDER_BACKEND_URL` | Post-deploy smoke check | `https://codebrain-backend.onrender.com` |
| `VERCEL_TOKEN` | Automated Vercel CLI deployment | Personal access token created at `https://vercel.com/account/tokens`. |
| `VERCEL_ORG_ID` | Automated Vercel CLI deployment | Vercel Organization / Team ID (found in Project Settings). |
| `VERCEL_PROJECT_ID` | Automated Vercel CLI deployment | Vercel Project ID (found in Project Settings). |

---

## 4. Deployment and Migration Sequence

```
Step 1: Run Supabase SQL Migration
        └── Execute supabase/migrations/20261012_initial_schema.sql in Supabase SQL Editor.

Step 2: Deploy Backend to Render
        └── Deploy codebrain-backend with Supabase DATABASE_URL and SESSION_SECRET.
        └── Backend automatically runs idempotent init_db() and verifies connectivity.

Step 3: Deploy Frontend to Vercel
        └── Deploy frontend with VITE_API_URL set to Render backend.

Step 4: Update CORS & OAuth Callbacks
        └── In Render: update FRONTEND_URL & CORS_ORIGINS with actual Vercel domain.
        └── In GitHub Developer Settings: update OAuth callback URL with Render domain.

Step 5: Verify via Smoke Test
        └── Probe /health on Render backend.
        └── Open Vercel frontend, create test account, and index a repository.
```

---

## 5. Verification & Live Smoke Testing

### Backend Health Probe
```bash
curl -f https://codebrain-backend.onrender.com/health
```
**Expected Response:**
```json
{
  "status": "ok",
  "version": "0.8.1",
  "database": "connected",
  "runtime": { "status": "ok", "provider": "subprocess" },
  "checks": { "liveness": "pass", "readiness": "pass" }
}
```

### Frontend Route Verification
1. **Public Landing Page:** Visit `https://codebrain-app.vercel.app/` — verify GoodsGo-style expanding header and hero showcase.
2. **Direct Route Refresh:** Visit `https://codebrain-app.vercel.app/login` and refresh — verify SPA rewrite prevents 404.
3. **Registration & Auth:** Register an account or log in — verify secure session cookie is issued.
4. **Repository Ingestion:** Ingest a public repository via ZIP upload or GitHub URL — verify file tree and symbols populate.
5. **Grounded Q&A:** Ask a question in Copilot chat — verify streaming tokens and citation badges.
6. **Master DocGen:** Navigate to `/docs` and trigger generation — verify 16 sections render with Mermaid diagrams.

---

## 6. Free-Tier Limitations & Operational Guidance

| Resource | Free Tier Constraint | Operational Impact | Recommended Mitigation |
| :--- | :--- | :--- | :--- |
| **Render Spin-Down (Cold Starts)** | Free web services spin down after 15 minutes of inactivity. First request takes 30–50s. | Initial user request after idle delay may feel slow. | Keep-alive ping via UptimeRobot / Cron, or upgrade to Render Starter ($7/mo). |
| **Render Local Filesystem** | Files written to local disk are ephemeral across deploys / restarts. | Cloned repos and FAISS indices rebuild on restart if disk is reset. | Repositories re-index automatically on demand; use Supabase Storage for PDFs/docs. |
| **Supabase DB Limits** | 500MB database limit and 2 active projects. | Sufficient for tens of thousands of code symbols and chat records. | Clean up old indexed repositories via the Delete Repo API. |
| **Supabase Connection Pooling** | Max 60 concurrent connections on free tier. | Direct connections (`port 5432`) may exhaust pool under high traffic. | **Always use Transaction Pooler (`port 6543`)** as documented in `DATABASE_URL`. |
| **Vercel Edge Functions** | 100GB-hours edge bandwidth. | Ample for static Vite React SPA bundles. | Production assets use Vite hashing and long-lived cache headers. |

---

## 7. Rollback & Recovery Guidance

- **Frontend Rollback (Vercel):**
  1. Open Vercel Dashboard -> **Deployments**.
  2. Locate the previous stable deployment.
  3. Click **...** -> **Instant Rollback**.
- **Backend Rollback (Render):**
  1. Open Render Dashboard -> **Deploys**.
  2. Select the previous successful commit deploy.
  3. Click **Rollback to this deploy**.
- **Database Safety:**
  - Migrations in [`20261012_initial_schema.sql`](file:///b:/College/7%20SEM/BCG786%20Major%20Project%20Phase%20II/ai/supabase/migrations/20261012_initial_schema.sql) are non-destructive and use `ADD COLUMN IF NOT EXISTS`.
  - To create a point-in-time backup: Go to Supabase -> **Database** -> **Backups**.
