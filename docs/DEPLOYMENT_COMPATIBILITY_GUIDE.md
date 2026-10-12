# CodeBrain — Hosting-Platform-Independent Architecture & Deployment Compatibility Guide

## 1. Architectural Philosophy & Deployment Boundaries

CodeBrain is designed with strict boundaries separating the web application presentation, the API coordinator, and untrusted repository code execution. The application does not depend on any single cloud hosting provider, private infrastructure, or the developer's workstation.

```
┌────────────────────────────────────────────────────────┐
│                      FRONTEND                          │
│   Vercel / Cloudflare Pages / Netlify / S3 + CDN       │
│   - React 18 + Vite + TypeScript SPA                   │
│   - Monaco Editor, 16-Section DocGen UI, Chat          │
│   - VS Code-Style Bottom Panel (Problems/Output/Term)  │
└──────────────────────────┬─────────────────────────────┘
                           │ Authenticated REST & WebSockets
                           ▼
┌────────────────────────────────────────────────────────┐
│                BACKEND API COORDINATOR                 │
│      Any Container / VM / PaaS Host                    │
│   - FastAPI (Python 3.11)                              │
│   - Authentication & Workspace Authorization           │
│   - AI Provider Routing (APInex -> NVIDIA -> Groq)     │
│   - Multi-Terminal Manager & Session Registries        │
│   - Audit Logging & Rate Limiting                      │
└──────────────────────────┬─────────────────────────────┘
                           │ ExecutionProvider Abstraction
                           ▼
┌────────────────────────────────────────────────────────┐
│               CODE EXECUTION RUNTIME                   │
│   - DockerExecutionProvider (Isolated Container)       │
│   - RemoteExecutionProvider (Worker Daemon over HTTP)  │
│   - SubprocessExecutionProvider (Local Dev Only)       │
│   - NullExecutionProvider (Safe Closed-Gate in Prod)   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Execution Runtime Abstraction

The execution runtime is decoupled from the web framework through the `BaseExecutionProvider` abstraction (`backend/execution/provider.py`). Application routers (`/terminals`, `/validate-patch`, `/errors`) interact exclusively with this abstraction:

| Provider | Strategy | Intended Environment | Security Boundary |
| :--- | :--- | :--- | :--- |
| **`docker`** | Unprivileged container per command / session | Self-hosted VMs, VPS, Kubernetes, dedicated servers | Container cgroups, `--network none`, `--memory 512m`, `--cpus 1.0`, mounted workspace only |
| **`remote`** | HTTP/WebSocket RPC to an isolated worker service | PaaS backends without Docker socket access | Worker host enforces container/microVM isolation |
| **`subprocess`** | Host child process with scrubbed environment | Local developer machines (`ENVIRONMENT=development`) | Environment allowlist (`PATH`, `CI`, `PYTHONPATH`), blocked outside workspace root |
| **`null`** | Closed-gate fail-safe | Production instances where no runtime is configured | Untrusted code is **never** executed directly on host |

---

## 3. Candidate Hosting Platform Compatibility Matrix

This matrix evaluates candidate platforms against CodeBrain's functional and security requirements:
- **WebSocket Streaming:** Required for interactive multi-terminal input/output.
- **Persistent Processes:** Required for running long-running dev servers (`npm run dev`, `uvicorn`).
- **Execution Timeout:** Test suites may run up to 60 seconds; dev servers run continuously.
- **Docker / Isolated Containers:** Required for safe multi-tenant repository sandboxing.
- **Storage Durability:** Cloned repos, AST indexes, and SQLite/PostgreSQL persistence.

| Platform | WebSocket Support | Max Request Duration | Persistent Shells / Processes | Container / Docker Support | Storage Options | Best Suited Tier / Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Render** | Full support (Web Services) | 100 minutes (HTTP/WS) | Supported on Web Services (stops on Free tier spin-down) | Native Dockerfile deployment; DinD requires custom setup or remote worker | Persistent Disks available ($0.25/GB/mo) | **Compatible for Backend API Coordinator.** Execution worker best paired as a Private Service or Remote Worker. |
| **Fly.io** | Native support | Configurable (long-lived) | Supported via Fly Machines (lightweight microVMs) | First-class microVM containers; custom kernel & DinD possible | Persistent Volumes (`flyctl volumes`) | **Highly Compatible.** Can host both Backend API and isolated execution workers with hardware virtualization. |
| **Railway** | Full support | Configurable | Supported while container is running | Dockerfile & Docker Compose support | Persistent Volumes available | **Compatible.** Good turnkey option for small-to-medium deployments. |
| **AWS (App Runner + ECS)** | App Runner (HTTP only) / ECS (ALB supports WS) | App Runner (120s limit) / ECS (unlimited) | ECS Fargate supports persistent tasks; App Runner does not support long-running workers | ECS Fargate / EC2 has full container isolation | Amazon EFS or EBS volumes | **Production Grade for Enterprise.** Backend on ECS Fargate behind ALB; workers in isolated Fargate tasks. |
| **GCP (Cloud Run + GKE)** | Supported via HTTP/2 & WebSockets | Cloud Run: up to 60 mins | Cloud Run scales to zero (kills background processes on idle) | Cloud Run supports containers; GKE supports full DinD / Kata containers | Cloud Storage FUSE / Persistent Disks | **Compatible with GKE or Cloud Run (with min-instances=1).** |
| **DigitalOcean (Droplets / App Platform)** | Droplets: unlimited; App Platform: supported | Droplets: unlimited; App Platform: long-lived | Full root Linux VM on Droplet | Docker natively supported on Droplet | Block Storage volumes | **Turnkey Self-Hosted.** A single $12-$24/mo Droplet can run the entire `docker-compose.yml` stack with Docker-in-Docker isolation. |
| **Vercel Functions** | Limited (Serverless Edge) | 10s (Hobby) / 60s (Pro) | **Unsupported** (Serverless functions terminate immediately upon response) | **Unsupported** (No Docker daemon, read-only ephemeral `/tmp`) | Ephemeral (512MB `/tmp`) | **Frontend Only.** Vercel is ideal for hosting the static React/Vite SPA, but **cannot** host CodeBrain's persistent interactive shells or Docker sandboxes. |

---

## 4. Local Development vs. Production Execution

### Local Development Mode
- **Configuration:** `ENVIRONMENT=development`, `EXECUTION_PROVIDER=subprocess`, `ISOLATED_RUNTIME_REQUIRED=false`.
- **Behavior:**
  - Sandboxes run using the local interpreter within temporary directories.
  - Interactive terminals run local PowerShell (Windows) or Bash (macOS/Linux) processes.
  - Environment variables are scrubbed by `_build_safe_env()`, stripping backend keys.
  - No Docker daemon is required.

### Production Execution Mode
- **Configuration:** `ENVIRONMENT=production`, `PUBLIC_DEPLOYMENT=true`, `EXECUTION_PROVIDER=docker` (or `EXECUTION_PROVIDER=remote`), `ISOLATED_RUNTIME_REQUIRED=true`.
- **Behavior:**
  - Untrusted repository code and test suites run in isolated containers with zero host filesystem access.
  - Container resources are capped (`--memory 512m`, `--cpus 1.0`, `--network none`).
  - If the execution provider is unreachable, the system fails closed with `RUNTIME_UNAVAILABLE`. Under no circumstances will it fall back to unrestricted host execution.

---

## 5. Provider-Neutral Deployment Workflow

Because the architecture is decoupled, deploying CodeBrain to **any** hosting provider follows this simple 3-step process:

### Step 1: Deploy Frontend SPA
1. Connect repository to any static/SPA hosting provider (e.g. Vercel, Cloudflare Pages, Netlify, AWS Amplify).
2. Set Build Command: `npm run build` (in `frontend/`).
3. Set Output Directory: `dist`.
4. Configure Environment Variable:
   - `VITE_API_URL`: Public HTTPS URL of the Backend API Coordinator.

### Step 2: Deploy Backend API Coordinator
1. Build container from `backend/Dockerfile`.
2. Configure mandatory environment variables:
   - `DATABASE_URL`: Connection string (SQLite file on persistent volume or PostgreSQL URL).
   - `REDIS_URL`: Redis cache endpoint.
   - `SESSION_SECRET`: Random 32+ character string.
   - `ENCRYPTION_KEY`: Base64-encoded 32-byte Fernet key.
   - `FRONTEND_URL`: URL of the deployed frontend SPA.
   - `CORS_ORIGINS`: Comma-separated list of allowed origins.
   - `AI_PRIMARY_PROVIDER`: `apinex` (with `APINEX_API_KEY`).
3. Configure execution runtime mode:
   - If hosting on a VM/VPS with Docker: set `EXECUTION_PROVIDER=docker`.
   - If hosting on a container PaaS with external worker: set `EXECUTION_PROVIDER=remote` and configure `EXECUTION_WORKER_URL`.
   - If hosting without execution capability: set `EXECUTION_PROVIDER=null` (enables documentation, chat, AST explorer, and code navigation while gracefully disabling command execution).

### Step 3: Verify Deployment
1. Query `GET /health` on the backend API:
   ```json
   {
     "status": "ok",
     "version": "0.8.1",
     "runtime": {
       "provider": "docker",
       "status": "ready",
       "isolated": true
     }
   }
   ```
2. Open the frontend in your browser and confirm login, repository upload, documentation generation, and terminal sessions.

---

## 6. Provider-Specific Checklist (To Be Completed After Hosting Decision)

When a specific hosting provider is selected by the operator, only the following configuration details need to be filled in (zero application code modifications required):

1. **Domain & DNS:**
   - Map custom domains (e.g. `app.codebrain.ai` for frontend, `api.codebrain.ai` for backend).
2. **CORS & SSL:**
   - Add backend domain to `FRONTEND_URL` and `CORS_ORIGINS`.
3. **Database Provisioning:**
   - If SQLite: attach a persistent volume to `/app/storage` and `/app/app.db`.
   - If Managed PostgreSQL: set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.
4. **Execution Worker Wiring (If PaaS Chosen):**
   - If backend cannot run Docker directly, deploy the worker container and set `EXECUTION_WORKER_URL=https://worker.internal` and `EXECUTION_WORKER_TOKEN=<secret>`.
5. **OAuth Redirect:**
   - Update `GITHUB_OAUTH_REDIRECT_URI` in GitHub Developer Settings to match production backend URL.
