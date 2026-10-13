# CodeBrain — Manual Actions Required Checklist

**Date:** October 2026  
**Audience:** Repository Owner / Production Administrator  

---

## 1. Status Overview

All core application bugs, database connection drops, deadlocks, documentation persistence mechanisms, and code-fix workflows have been fixed, tested, and verified directly in code.

The following checklist details optional configuration optimizations and external dashboard steps that require user involvement or secrets.

---

## 2. Action Checklist

### Action 1: Verify GitHub OAuth Token Scopes
- **Dashboard / Tool:** [GitHub Developer Settings — OAuth Apps](https://github.com/settings/developers)
- **Why It Is Needed:** For automated branch creation and Pull Requests on private or user-owned repositories, GitHub OAuth requires the `repo` scope.
- **Expected Outcome:** Users who log in via GitHub will automatically have push permissions to open PRs directly on their own repositories rather than falling back to `APPLIED_LOCAL`.
- **How to Verify:** Import a repository owned by your authenticated GitHub account, generate a fix, and click "Apply Fix". It will push branch `ai-fix/...` and open a Pull Request.

### Action 2: Supabase Connection String Configuration
- **Dashboard / Tool:** [Supabase Project Dashboard](https://supabase.com/dashboard) -> Settings -> Database -> Connection string
- **Configuration:** Ensure the environment variable `DATABASE_URL` on Render uses the **Transaction Pooler** (`port 6543`, `aws-0-*.pooler.supabase.com`) with `sslmode=require`.
- **Why It Is Needed:** Standard direct connection (`port 5432`) has a strict connection limit on Supabase Free Tier (maximum 15 connections), whereas the pooler (`port 6543`) supports high concurrency. CodeBrain has already enabled `NullPool`, `pool_pre_ping=True`, and TCP keepalives to prevent disconnects.
- **How to Verify:** Visit `https://codebrain-backend.onrender.com/health` and verify `"database": "connected"`.

### Action 3: Production Environment Variables on Render
- **Dashboard / Tool:** [Render Dashboard](https://dashboard.render.com) -> `codebrain-backend` -> Environment
- **Variables to Confirm:**
  1. `APINEX_API_KEY`: Required for APINex GPT-6 Luna quota allocation.
  2. `NVIDIA_API_KEY`: Required for primary NVIDIA NIM fallback (`deepseek-v4.1-flash`, `glm-5-3`).
  3. `GROQ_API_KEY`: Required for secondary Groq fallback.
  4. `SESSION_SECRET`: A 32+ character random secret string for HMAC session cookie signing.
  5. `GITHUB_TOKEN`: Fallback PAT for public GitHub API queries.
- **Why It Is Needed:** Ensures AI requests always execute with high-quality models and fallback to NVIDIA/Groq without disruption.
- **How to Verify:** Check `GET /ai/health` or `/ai/models` on the deployed backend to verify provider availability.

---

## 3. Alternative Hosting Assessment (Amazon EC2 vs Render)

*As requested in the user prompt, below is the zero-cost-first assessment and step-by-step plan for potentially moving the backend to Amazon EC2.*

### Comparison
| Dimension | Render (Current) | Amazon EC2 (`t4g.small` / `t3.medium`) |
| :--- | :--- | :--- |
| **Memory Limit** | 512 MB (Free Tier) | 1 GB (`t4g.micro` / Free Tier) or 2 GB (`t4g.small`) |
| **Idle Behavior** | Spins down after 15 minutes of inactivity | Always-on 24/7 (zero cold starts) |
| **Disk Storage** | Ephemeral (resets on container restart) | Persistent EBS volume (30GB Free Tier) |
| **Docker Execution**| Unavailable (null sandbox provider) | Supported (real isolated Docker sandbox) |
| **Cost** | Free | Free Tier (750 hours/month for 12 months on `t2.micro` or `t3.micro`) |

### Recommended Migration Steps (When Approved):
1. **Launch EC2 Instance:** Ubuntu 24.04 LTS on AWS Free Tier (`t3.micro` or `t4g.small` in `ap-south-1`).
2. **Install Runtime Dependencies:**
   ```bash
   sudo apt update && sudo apt install -y python3.11 python3.11-venv git docker.io
   sudo usermod -aG docker ubuntu
   ```
3. **Clone & Configure:**
   ```bash
   git clone https://github.com/AnniiGCP/CodeBrain.git /opt/codebrain
   cd /opt/codebrain/backend
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Setup Systemd Service:** Create `/etc/systemd/system/codebrain.service` running `uvicorn main:app --host 0.0.0.0 --port 8000`.
5. **Setup Nginx & SSL (Certbot):** Reverse proxy port 80/443 to `127.0.0.1:8000` with free Let's Encrypt TLS certificate.
6. **Update Vercel:** Point `VITE_API_URL` to the new EC2 domain.
