# CodeBrain — Manual Actions Required Checklist

**File:** `docs/MANUAL_ACTIONS_REQUIRED.md`  
**Date:** October 17, 2026  
**Auditor / Engineering Lead:** CodeBrain Core Systems & Reliability Engineering  
**Release Recommendation:** `PARTIALLY READY` (Local test suites pass 100%; manual cloud deployment and GitHub credentials required for live remote operations).

---

## 1. Summary of Required User Actions

The following 3 manual actions genuinely require user authorization and credentials:

1. **GitHub Personal Access Token (PAT) Configuration for Remote Pushes**
2. **Pushing Verified Local Changes to `origin/main` for Production Deployment**
3. **Validating APINex GPT-6 Luna Environment Variables on Render**

---

## 2. Action Details & Step-by-Step Instructions

### Action 1: GitHub PAT Setup (Resolves Git Push Exit Code 128)
- **Why Required:** Password authentication for Git operations was removed by GitHub. In local development or dev-login modes, Git pushes to branches like `ai-fix/f1bfa8e1-gen001-app` or `codebrain/setup-ci-workflow` on `https://github.com/AnniiGCP/QuizGenAI.git` require an authorized GitHub Personal Access Token or OAuth session.
- **Exact Steps:**
  1. Go to your GitHub account: **Settings** -> **Developer settings** -> **Personal access tokens** -> **Tokens (classic)**.
  2. Click **Generate new token (classic)** with note: `CodeBrain Remote Ops`.
  3. Select scopes:
     - `repo` (Full control of private repositories)
     - `workflow` (Update GitHub Action workflows)
  4. Generate and copy the token (`ghp_...`).
  5. In CodeBrain:
     - In the bottom status bar or User Settings modal, paste the token into the **GitHub Token** field.
     - Alternatively, export it in your environment:
       ```bash
       $env:GITHUB_TOKEN="ghp_your_token_here"
       ```
  6. Re-run **Apply Fix to Repo** or **Install via Pull Request**. Git push will authenticate via HTTPS Bearer token cleanly.

---

### Action 2: Trigger Cloud Deployments (Render & Vercel)
- **Why Required:** Antigravity operates under strict safety rules and will not push to `origin/main` on remote production without explicit authorization.
- **Exact Steps:**
  1. In the CodeBrain repository root (`ai/`), review changes:
     ```bash
     git status
     ```
  2. Stage and commit the verified production recovery changes:
     ```bash
     git add backend/ frontend/ docs/
     git commit -m "fix(production): patch safety, dynamic problem reconciliation, CI/CD PYTHONPATH, and git push auth error handling"
     ```
  3. Push to GitHub:
     ```bash
     git push origin main
     ```
  4. **Verify Render Backend Deployment:**
     - Open [Render Dashboard](https://dashboard.render.com).
     - Select service `codebrain-backend`.
     - Confirm the deploy completes with `Application startup complete.`
     - Test live health check: `https://codebrain-backend.onrender.com/health` -> HTTP 200.
  5. **Verify Vercel Frontend Deployment:**
     - Open [Vercel Dashboard](https://vercel.com/dashboard).
     - Select `codebrain-dev`.
     - Confirm the latest deployment is **Ready**.

---

### Action 3: Verify APINex GPT-6 Luna API Key in Production
- **Why Required:** The centralized AI orchestration layer routes all code fixing, documentation, and chat requests to APINex GPT-6 Luna first.
- **Exact Steps:**
  1. In Render Dashboard -> `codebrain-backend` -> **Environment**:
  2. Confirm `APINEX_API_KEY` is configured with your valid APINex key.
  3. Confirm `APINEX_BASE_URL` is set to `https://api.apinex.io/v1` (or your configured APINex endpoint).
  4. Confirm fallback keys (`NVIDIA_API_KEY` and `GROQ_API_KEY`) are present for multi-tier bounded failover.

---

## 3. Verification Checklist After Deployment

Once the 3 actions above are executed, perform these live checks in `https://codebrain-dev.vercel.app`:

- [ ] Open QuizGenAI workspace.
- [ ] Verify Problems panel loads 4 issues initially.
- [ ] Click **Fix** on `PY007` in `test_auth_flow.py`.
- [ ] Review diff; confirm it only replaces passwords with `TEST_PASSWORD` (no deleted test functions, no conversational `"I'll inspect..."` text).
- [ ] Click **Apply Fix to Repo**.
- [ ] Confirm `PY007` **disappears** from the Problems panel, leaving only 3 issues.
- [ ] Confirm terminal displays clean branch creation and remote push confirmation.
- [ ] Open CI/CD tab; inspect proposed `ci.yml`. Confirm `PYTHONPATH: .` is present in backend test step.
- [ ] Click **Install via Pull Request**; confirm PR URL is returned.
