# CodeBrain Deployment Baseline & Reproduction Audit

**Audit Date:** October 15, 2026  
**Target Deployment:** `https://codebrain-dev.vercel.app` (Frontend: Vercel)  
**Backend API:** `https://codebrain-backend.onrender.com` (Backend: Render, Database: Supabase PostgreSQL)  
**Primary Test Repositories:**
- `https://github.com/AnniiGCP/QuizGenAI`
- `https://github.com/kangan289/dev`

---

## 1. Reproduction of Confirmed Production Failures

### Failure A — Workspace File Cannot Be Opened (`.github/copilot-instructions.md`)
- **Observed Behavior:**
  - Navigating to `https://codebrain-dev.vercel.app/dashboard?file=.github%2Fcopilot-instructions.md` displays the file in the left Explorer tree under `QuizGenAI -> .github -> copilot-instructions.md`.
  - When selected, the Monaco editor fails to load the content and displays:
    ```
    // Error loading '.github/copilot-instructions.md':
    // File '.github/copilot-instructions.md' not found in repository.
    ```
- **Confirmed Root Causes:**
  1. **Ephemeral Filesystem on Render:** Render container instances sleep and recycle ephemeral storage. When the backend container restarts, local directories under `backend/storage/{repo_id}` are wiped. While repository metadata and `RepoFile` rows persist in Supabase PostgreSQL, the local files on disk no longer exist.
  2. **Symbol-Only Database Fallback:** In `backend/routers/repos.py` (`get_file_content`), when the disk file is absent, the backend queries `Symbol` joined with `RepoFile`. Non-code files (Markdown documents, configuration files, dotfiles) contain 0 AST symbols, causing the backend to throw HTTP 404 (`File '.github/copilot-instructions.md' not found in repository.`).
  3. **Double URL Decoding & Canonical Path Resolution:** FastAPI query parameters are automatically URL-decoded. Calling `urllib.parse.unquote(path)` again can cause double-decoding issues. In addition, leading `./` or repository name prefixes caused path mismatches against disk checkouts.
  4. **Lack of On-Demand Repository Restoration:** If a repository workspace on disk is missing after a container restart, the backend lacked automated on-demand cloning/fetching from GitHub.

---

### Failure B — Documentation Diagram Rendering Fails (`Syntax Fallback`)
- **Observed Behavior:**
  - Navigating to `https://codebrain-dev.vercel.app/docs` under Section 1.6 (*Problem & Solution Flow Architecture*) displays an amber syntax warning panel instead of a visual SVG flowchart:
    ```
    Architecture Blueprint [Syntax Fallback]
    Visual SVG rendering could not parse this diagram syntax. Displaying usable structural blueprint:
    flowchart TD
      ps_problem["Operational Challenge<br/>Domain Inefficiencies"]
      ps_limit["System Limitations<br/>Manual / Unscaled Workflow"]
      ps_solution["QuizGenAI Solution<br/>Static Web Application (HTML/CSS/JS)"]
      ps_engine["Core Engine & Modules<br/>0 Verified Symbols"]
      ps_outcome["Delivered Outcome<br/>Automated & Robust Output"]
      ps_problem -->|Exposes| ps_limit
      ps_limit -->|Resolved by| ps_solution
      ps_solution -->|Orchestrates| ps_engine
      ps_engine -->|Delivers| ps_outcome
    ```
- **Confirmed Root Causes:**
  1. **Mermaid v11 Syntax Rules & Sublabel Ingestion:** In `backend/docgen/diagram_engine.py`, sublabels were concatenated with `<br/>` into node labels containing unescaped special characters (e.g. parentheses `(HTML/CSS/JS)` in `ps_solution`).
  2. **Asymmetric Sanitization in Frontend:** In `frontend/src/components/MermaidDiagram.tsx`, regex label quoting and normalization was guarded behind `if (isChat)`. For documentation and editor views, `isChat` was false or undefined, bypassing normalization and triggering Mermaid syntax parse exceptions.
  3. **Export & Quality Gaps:** Generated documentation lacked deep AST symbol grounding (0 verified symbols displayed) and had version discrepancy between PDF and Markdown exports.

---

### Failure C — CI/CD Conflates Installation with Health Status
- **Observed Behavior:**
  - GitHub Actions runs for QuizGenAI show:
    - Backend API Quality Gate: **Failing** (after 28s)
    - Frontend UI Quality Gate: **Failing** (after 14s)
    - Deployment Quality Gate: **Skipped**
  - In contrast, CodeBrain's CI/CD dashboard at `https://codebrain-dev.vercel.app/cicd` displays a green badge:
    `CI Status: [✓ Installed & Active]`
- **Confirmed Root Causes:**
  1. **Conflated Status Badge:** In `frontend/src/pages/CICDPage.tsx`, `renderStatusBadge()` checked only `overview?.setup_status === "installed"`, rendering a green `Installed & Active` badge regardless of whether the latest GitHub Actions workflow run passed, failed, or was cancelled.
  2. **Missing Real-Time Quality Gate Breakdown:** The interface did not present distinct indicators for **Installation State** vs. **Execution Health**.

---

### Failure D — Generated GitHub Actions Pipeline Failures
- **Observed Behavior:**
  - GitHub Actions workflow run `38464655689` failed on both quality gates:
    - Frontend UI Quality Gate failed during `Run frontend test suite` (`npm test`).
    - Backend API Quality Gate failed during `Run backend tests` (`pytest`).
- **Confirmed Root Causes:**
  1. **Missing `test` Script in Frontend:** `frontend/package.json` only defines `dev`, `build`, `lint`, and `preview`. There is no `test` script. Running `npm test` fails with `Missing script: "test"`.
  2. **Python Import Path Mismatch:** In QuizGenAI, `db/` is in the repository root, while `main.py` is in `backend/app/main.py` and executes `import db.models`. When running `pytest` with `working-directory: backend`, Python does not have repository root in its module search path (`PYTHONPATH`), causing import errors.
  3. **Cache Dependency Path:** The generated workflow specified `cache-dependency-path: requirements.txt` at the root, whereas `requirements.txt` is located at `backend/requirements.txt`.
  4. **Fallback Heuristics:** In `ci_setup.py`, when disk checks were unavailable, the fallback logic unconditionally inserted `npm test` and `pytest` without verifying whether those scripts actually existed in repository manifests.

---

## 2. Baseline Measurements & Reproduction Matrix

| Component | Tested Path / Operation | Baseline Status | Error / Root Cause |
|---|---|---|---|
| **Workspace Explorer** | Open `.github/copilot-instructions.md` | **FAIL** (HTTP 404) | Render ephemeral disk wiped; DB fallback has no symbols for Markdown |
| **Workspace Explorer** | Open `backend/app.py` | **PARTIAL** | Concatenated symbol fallback used when disk checkout is absent |
| **Docs Generator** | Section 1.6 Flowchart Diagram | **FAIL** (Syntax Fallback) | Node labels with `(HTML/CSS/JS)` and `<br/>` fail Mermaid v11 parse without normalization |
| **CI/CD Dashboard** | Overview status for QuizGenAI | **FAIL** (False Healthy) | Displays "Installed & Active" while latest run is failing |
| **CI/CD Generator** | Generated `.github/workflows/ci.yml` | **FAIL** (Jobs Break) | `npm test` generated without script in `package.json`; Python `PYTHONPATH` omitted |
| **Document Export** | Markdown & PDF Version Parity | **PARTIAL** | Markdown `v1.6` vs PDF `v2.0` version mismatch; diagrams missing from PDF |
