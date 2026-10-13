# CodeBrain — Manual Actions Required Checklist

**Document:** `docs/MANUAL_ACTIONS_REQUIRED.md`  
**Purpose:** Precise, step-by-step checklist of manual administrative actions required to verify and maintain the live production deployment of CodeBrain.

---

## 1. Mandatory Deployment Actions

### Step 1: Render Build & Deploy Cycle Verification
- **Platform:** Render Dashboard (`https://dashboard.render.com`)
- **Service:** `codebrain-backend` (Web Service)
- **Setting / Page:** **Events** / **Logs**
- **Action:**
  1. Open the `codebrain-backend` service page.
  2. Confirm that the latest commit (`fix(database): ensure PostgreSQL schema migrations execute on startup by isolating SQLite PRAGMA calls`) has triggered a build and is showing **Deploy Live**.
  3. Inspect the startup log and confirm the following line appears without error:
     ```
     [INFO] Application startup complete. Uvicorn running on http://0.0.0.0:10000
     ```
  4. Ensure no `ProgrammingError` or `UnboundLocalError` appears in the logs during table migrations.
- **Verification:** Open `https://codebrain-backend.onrender.com/health` in your browser. It must return HTTP 200 with:
  ```json
  {"status":"ok","version":"0.8.1","database":"connected","checks":{"liveness":"pass","readiness":"pass"}}
  ```
- **Next Step:** Proceed to Step 2.

---

### Step 2: Supabase Column Verification (Optional Inspection)
- **Platform:** Supabase Dashboard (`https://supabase.com/dashboard`)
- **Project:** CodeBrain Production Project
- **Setting / Page:** **Table Editor** -> `users` and `repos`
- **Action:**
  1. Select the `users` table.
  2. Verify that the columns `user_email` (text/varchar) and `password_hash` (text/varchar) are present.
  3. Select the `repos` table.
  4. Verify that `last_activity_summary` (text) and `last_activity_at` (timestamptz) are present.
- **Verification:** If the columns are present, startup migrations have completed successfully. If not, open the **SQL Editor** tab and execute:
  ```sql
  ALTER TABLE users ADD COLUMN IF NOT EXISTS user_email VARCHAR UNIQUE;
  ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR;
  ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_activity_summary TEXT;
  ALTER TABLE repos ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP WITH TIME ZONE;
  ```
- **Next Step:** Proceed to Step 3.

---

### Step 3: Vercel Frontend Deployment Verification
- **Platform:** Vercel Dashboard (`https://vercel.com/dashboard`)
- **Project:** `codebrain` / `codebrain-dev`
- **Setting / Page:** **Deployments**
- **Action:**
  1. Verify the production deployment linked to branch `main` is marked **Ready**.
  2. In **Settings** -> **Environment Variables**, ensure:
     - `VITE_API_URL` is set to `https://codebrain-backend.onrender.com`
     - (No trailing slash).
- **Verification:** Visit `https://codebrain-dev.vercel.app`. Open DevTools Console. Confirm no CORS or 404 errors appear on page load.
- **Next Step:** Proceed to Section 2 (Verification Testing).

---

## 2. Verification Testing in Browser

### Step 4: Repository Ingestion Smoke Test
- **Platform:** CodeBrain Web App (`https://codebrain-dev.vercel.app`)
- **Action:**
  1. Log into your account or register a new user.
  2. Click **+ Add Repository**.
  3. Enter `https://github.com/AnniiGCP/QuizGenAI`.
  4. Click **Clone Repository**.
- **Expected Behavior:**
  - The modal closes immediately (within <500ms) with a toast: *"Repository clone started in background"*.
  - The bottom status bar shows: *"Cloning repository from GitHub…"*, followed by *"Discovering and indexing files…"*, *"Extracting code symbols…"*, and *"Analysing structure…"*.
  - The File Tree populates automatically with QuizGenAI source files.
  - The Problems panel shows the 4 detected issues (`PY007` in `test_auth_flow.py`, `GEN001` in `app.py` and `qwen_llm.py`).

---

## 3. Optional Performance Improvements

### Step 5: Render Free Tier Inactivity Prevention (Optional)
- **Platform:** Uptime Monitoring Service (e.g., UptimeRobot / Cron-Job.org)
- **Setting:** HTTP Monitor
- **Action:**
  1. Create a free HTTP monitor targeting: `https://codebrain-backend.onrender.com/health`
  2. Set interval to **every 10 minutes**.
- **Benefit:** Prevents Render free-tier services from sleeping after 15 minutes of inactivity, completely eliminating the 45–60 second cold start delay.
