# CodeBrain — Localhost vs. Production Baseline Assessment

**Date:** October 2026  
**Repositories Tested:**
1. Primary Ingestion, Detection & Fixes: `https://github.com/AnniiGCP/QuizGenAI`
2. CI/CD Pipeline & Workflows: `https://github.com/kangan289/dev`

---

## 1. Environment Topology & Architectural Baselines

| Component | Localhost (`http://127.0.0.1:8000`) | Production (`https://codebrain-backend.onrender.com`) |
| :--- | :--- | :--- |
| **Frontend Host** | Vite Dev Server (`http://localhost:5173`) | Vercel (`https://codebrain-dev.vercel.app`) |
| **Backend Host** | Uvicorn / Python 3.11 (Host Subprocess) | Render Free Tier (512MB RAM, Ephemeral Container) |
| **Database** | Supabase PostgreSQL (`aws-0-ap-south-1.pooler.supabase.com`) | Supabase PostgreSQL (Shared PgBouncer pooler :6543) |
| **Disk Storage** | Persistent Windows local disk (`backend/storage/`) | Ephemeral Container Storage (`/opt/render/.../storage`) |
| **AI Primary** | APINex GPT-6 Luna (`free/gpt-6-luna`) | APINex GPT-6 Luna (`free/gpt-6-luna`) |
| **AI Fallback 1**| NVIDIA NIM (`deepseek-v4.1-flash`) | NVIDIA NIM (`deepseek-v4.1-flash`) |
| **AI Fallback 2**| Groq (`openai/gpt-oss-20b`) | Groq (`openai/gpt-oss-20b`) |

---

## 2. Ingestion & Cloning Performance

### A. QuizGenAI (`AnniiGCP/QuizGenAI`)
- **Total Files Discovered:** 118 files
- **Total Code Symbols Extracted:** 1,332 symbols
- **Embedding Model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors)
- **Vector Store:** FAISS FlatIP index
- **Localhost Duration:** ~45 seconds total (Clone: ~4s, Discover & Parse: ~6s, Embed & Index: ~30s, Analyze & Detect: ~5s).
- **Previous Production Symptom:** Stuck in `CLONING` state for > 10 minutes with "No files indexed yet".
- **Identified Root Causes:**
  1. `ImportError: cannot import name 'sanitize_sensitive_text' from 'docgen.secret_redactor'` at line 438 of `routers/repos.py` crashed the background clone worker immediately upon launch.
  2. Memory spikes from PyTorch previously exceeded Render's 512MB RAM limit, triggering Linux OOM SIGKILL (code 137).
  3. Ephemeral container restarts aborted running background tasks while leaving `pipeline_status = 'CLONING'` in the database.
- **Post-Remediation Behavior:**
  - Import corrected to `gitops.git_ops.sanitize_sensitive_text`.
  - Stale detection automatically recovers interrupted tasks.
  - Progressive file tree discovery populates the UI as files are discovered.

---

## 3. Issue Detection & Error Verification

### A. QuizGenAI Findings Baseline
The static AST analysis engine detected exactly 4 genuine code findings:
1. `PY007` — `backend/tests/test_auth_flow.py` (Line 14): Hard-coded password detected in source code.
2. `PY007` — `backend/tests/test_auth_flow.py` (Line 81): Hard-coded password detected in source code.
3. `GEN001` — `chatbot/app.py` (Line 8): Potential hardcoded secret or API key credential detected.
4. `GEN001` — `llm_service/tests/qwen_llm.py` (Line 11): Potential hardcoded secret or API key credential detected.

All 4 findings are persisted in `error_reports` table with precise line numbers, severities, and remediation diffs.

---

## 4. Code-Fix Application Lifecycle

- **Finding:** `GEN001` in `chatbot/app.py` (API Key credential exposure).
- **Patch Generation:** Model proposed unified diff extracting secret to `os.environ.get("NVAPI_KEY")`.
- **Apply Workflow:**
  - For repositories where user has write push credentials, creates `ai-fix/<id>-<slug>` branch, pushes to origin, and opens PR.
  - When upstream git push fails (403 Forbidden / unauthenticated / read-only public clone), CodeBrain automatically applies the patch directly to the local workspace file and marks `fix_status = "APPLIED_LOCAL"`.
  - Rejection cleanly transitions finding status to `REJECTED` without altering source files.

---

## 5. 16-Section Technical Documentation & Persistence

- **Canonical 16 Sections:**
  1. Project Overview
  2. Technology Stack
  3. Repository Structure
  4. System Architecture
  5. Modules and Components
  6. Classes and Functions
  7. APIs and Interfaces
  8. Database and Data Model
  9. Database Relationships
  10. Dependencies
  11. Configuration and Environment
  12. Testing
  13. Security
  14. CI/CD Pipeline
  15. Deployment Architecture
  16. Setup and Developer Guide
- **Previous Production Symptom:** Documentation disappeared after refreshing the page or restarting Render.
- **Root Cause:** Documentation was stored exclusively on the ephemeral container disk (`/storage/<repo_id>/docs`).
- **Remediation:** Added `RepoDoc` PostgreSQL model (`repo_docs` table in Supabase) to permanently store the full master document, all 16 sections, diagrams, and manifest. Opening the project fetches from database immediately without regeneration.

---

## 6. CI/CD Pipeline (`kangan289/dev`)

- **Workflow File:** `.github/workflows/ci.yml`
- **Detection Status:** Installed (`detected_ci: True`, `detected_ci_files: [".github/workflows/ci.yml"]`)
- **Remote Polling:** Handles 401/403 rate limits gracefully without 500 exceptions, displaying local workflow definitions accurately.
