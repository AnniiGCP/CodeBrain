# CodeBrain — Manual Actions Required Checklist

This checklist documents the exact actions required to finalize the production deployment and update downstream repository workflows.

---

## Action 1: Deploy Verified Fixes to Production (Git Push)

- **Where to perform:** Git terminal in repository root (`AnniiGCP/CodeBrain`).
- **Steps:**
  1. Review the modified files:
     ```bash
     git status
     ```
  2. Stage and commit the verified remediation changes:
     ```bash
     git add backend/ frontend/ docs/
     git commit -m "fix(prod): workspace path recovery, mermaid diagram repair, doc version parity, and ci/cd health reporting"
     ```
  3. Push to your GitHub repository:
     ```bash
     git push origin main
     ```
- **Why it is required:** CodeBrain's frontend hosting (Vercel) and backend hosting (Render) automatically deploy new revisions triggered by GitHub pushes on the default branch.
- **Expected result:**
  - Vercel automatically deploys the frontend bundle to `https://codebrain-dev.vercel.app`.
  - Render automatically rebuilds the FastAPI container for `https://codebrain-backend.onrender.com`.
- **How to verify completion:**
  - Visit `https://codebrain-dev.vercel.app/dashboard?file=.github%2Fcopilot-instructions.md` and confirm the file loads immediately in the editor.
  - Visit `https://codebrain-dev.vercel.app/docs` and confirm the flowchart renders without syntax fallbacks.
  - Visit `https://codebrain-dev.vercel.app/cicd` and confirm pipeline configuration and execution health appear as distinct, accurate badges.

---

## Action 2: Update the CI/CD Pipeline on `AnniiGCP/QuizGenAI`

- **Where to perform:** GitHub repository `https://github.com/AnniiGCP/QuizGenAI` or via CodeBrain's CI/CD tab.
- **Steps:**
  1. Open CodeBrain at `https://codebrain-dev.vercel.app/cicd`.
  2. Select `QuizGenAI (github)` from the repository dropdown.
  3. Click **Generate AI Proposal** to generate the updated pipeline containing `PYTHONPATH: .:${{ github.workspace }}` and honest test reporting (no failing `npm test` step).
  4. Click **Install via Pull Request** (or **Direct Commit to Branch** if you have direct commit access).
  5. If installed via PR, open `https://github.com/AnniiGCP/QuizGenAI/pulls`, review the diff, and click **Merge pull request**.
- **Why it is required:** The previous workflow in QuizGenAI had an invalid `npm test` command for a frontend without test scripts, and missing root package imports in the backend job.
- **Expected result:** The GitHub Actions workflow run on `QuizGenAI` passes all quality gates without syntax or import errors.
- **How to verify completion:**
  - Open `https://github.com/AnniiGCP/QuizGenAI/actions` and verify that the latest run shows green passing checks for both the backend quality gate and frontend build.

---

## Action 3: Database & Secret Verification

- **Database Migrations:** **NONE REQUIRED.** All database models and queries remain 100% backward-compatible with existing Supabase PostgreSQL tables.
- **Secrets & API Keys:** **NO ACTION NEEDED.** All existing environment variables (`SESSION_SECRET`, `SUPABASE_*`, `APINEX_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`) remain securely configured on Render and Vercel. No keys were modified, leaked, or exposed.
