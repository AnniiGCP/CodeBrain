<div align="center">

# CodeBrain AI

### AI-Powered Codebase Understanding, Static Analysis & Documentation Engine with CI/CD Diagnostic Integration

[![Live Demo](https://img.shields.io/badge/Live%20Application-codebrain--dev.vercel.app-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://codebrain-dev.vercel.app/)
[![React 19](https://img.shields.io/badge/React-19.2-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Tree-sitter](https://img.shields.io/badge/Tree--sitter-AST%20Parser-green?style=for-the-badge)](https://tree-sitter.github.io/)
[![FAISS](https://img.shields.io/badge/FAISS-Vector%20Index-blue?style=for-the-badge)](https://github.com/facebookresearch/faiss)
[![Tests](https://img.shields.io/badge/Tests-248%20Passed-success?style=for-the-badge&logo=pytest)](backend/tests/)
[![Docker](https://img.shields.io/badge/Docker-Sandboxed%20Execution-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

**A high-performance software intelligence platform enabling instant repository ingestion, deep AST symbol analysis, RAG-grounded natural language Q&A, automated 16-section enterprise documentation generation, sandboxed patch validation, and autonomous CI/CD failure remediation.**

[Explore Live Demo](https://codebrain-dev.vercel.app/) • [System Architecture](#system-architecture) • [Features](#key-capabilities) • [Setup & Run](#developer-setup--onboarding) • [Testing](#verification--test-suite)

</div>

---

<div align="center">
  <img src="./assets/readme-preview.png" alt="CodeBrain AI — Project Preview" width="100%" />
</div>

---

## 1. System Overview

Navigating large, complex software repositories requires developers to manually parse call hierarchies, correlate dispersed documentation, diagnose obscure CI/CD build failures, and trace architectural boundaries.

**CodeBrain** coordinates syntactic static analysis, dense local vector search, and multi-provider LLM orchestration to transform any raw repository into an interactive, self-documenting workspace.

```mermaid
flowchart TD
    subgraph ClientLayer["Frontend Client (React 19 + TypeScript + Vite)"]
        UI["Workspace SPA Dashboard"]
        Monaco["Monaco Code Editor"]
        ChatUI["Streaming Copilot Chat"]
        DocUI["16-Section Doc Viewer"]
        TermUI["Interactive WebSockets Terminal"]
    end

    subgraph GatewayLayer["API & Security Gateway (FastAPI)"]
        MainApp["FastAPI Coordinator (main.py)"]
        SecHeaders["Security Headers Middleware (CSP, HSTS)"]
        RateLimiter["Sliding-Window Rate Limiter"]
        AuthService["Auth & Session Manager (Fernet + PBKDF2)"]
    end

    subgraph Subsystems["Application Subsystems (APIRouters)"]
        RepoRouter["/repos (Clone, Upload, AST)"]
        AskRouter["/repos/{id}/ask (RAG Q&A)"]
        DocsRouter["/docs (16-Section Master Gen)"]
        ErrorsRouter["/errors & /codefix (Fix & Sandbox)"]
        CiRouter["/cicd & /gitops (PRs & Action Logs)"]
        TermRouter["/terminals (PTY & WebSockets)"]
    end

    subgraph EngineLayer["Core Analysis & AI Engines"]
        TreeSitter["Tree-sitter AST Parser"]
        VectorEngine["Sentence-Transformers all-MiniLM-L6-v2"]
        FAISS[("FAISS FlatIP Vector Index")]
        AIRouter["Centralized Multi-Provider Model Router"]
        SandboxRunner["Isolated Sandbox Execution Runtime"]
    end

    subgraph ProviderLayer["External AI Providers & Services"]
        NVIDIA["NVIDIA NIM (GLM 5.3, Nemotron)"]
        Groq["Groq (Llama 3.3 70B, Whisper)"]
        Anthropic["Anthropic (Claude 3.5 Sonnet)"]
        APInex["APInex (GPT-6 Luna)"]
        GitHub["GitHub REST & GraphQL API"]
    end

    subgraph StorageLayer["Data & Index Persistence"]
        DB[("Relational DB: SQLite / PostgreSQL")]
        FileStore[("Local Storage / storage/repos")]
    end

    UI --> SecHeaders --> MainApp
    MainApp --> RateLimiter --> AuthService
    AuthService --> Subsystems

    RepoRouter --> TreeSitter --> VectorEngine --> FAISS
    RepoRouter --> FileStore
    AskRouter --> FAISS
    AskRouter --> AIRouter
    ErrorsRouter --> SandboxRunner
    CiRouter --> GitHub
    DocsRouter --> AIRouter

    AIRouter --> NVIDIA
    AIRouter --> Groq
    AIRouter --> Anthropic
    AIRouter --> APInex

    Subsystems --> DB
```

---

## 2. Key Capabilities

### 🔍 Concrete AST Parsing & Static Code Analysis
- Ingests repositories via Git URL cloning or multi-file ZIP archive uploads.
- Language-aware symbol extraction using **Tree-sitter** across Python, TypeScript, JavaScript, Go, and Java.
- Maps imports, exports, class hierarchies, and call graphs without invoking untrusted code.

### 🧠 Semantic Vector RAG Q&A
- Local chunking and dense vector embedding using `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
- In-memory similarity retrieval using **FAISS FlatIP**, returning cited code snippets and exact file boundaries.
- Multi-provider model routing across **NVIDIA NIM**, **Groq**, **Anthropic**, and **APInex** with automatic fallback.

### 📚 Automated 16-Section Master Technical Documentation
- Generates exhaustive, structured documentation including:
  1. System Architecture
  2. Data Flow & Sequence Workflows
  3. API Specification Tables
  4. Database Entity Relationships
  5. Security & Threat Modeling
  6. Configuration & Environment Reference
  7. Performance & Optimization Profiles
  8. Deployment & CI/CD Pipelines
- Multi-format export: Markdown, styled HTML, and enterprise PDF via **ReportLab**.

### 🛡️ Sandboxed Patch Validation & Issue Remediation
- Automated AST issue detection and AI patch generation.
- Validates patches inside containerized execution sandboxes (`DockerExecutionProvider` with `--network none`, cgroups CPU and memory caps) before suggesting pull requests.

### 🔄 CI/CD Diagnostic Engine
- Connects to GitHub Actions to ingest failed workflow run logs.
- Categorizes failure root causes (syntax, dependency mismatch, failing assertions, timeout) and generates remediation diffs.

### 💻 Interactive Pseudoterminal (PTY)
- WebSockets streaming terminal (`xterm.js` / custom PTY bridge) enabling real-time terminal execution against workspace environments.

---

## 3. Technology Stack

| Domain | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Frontend Framework** | React | `^19.2.8` | Modern declarative UI layer |
| **Language (Frontend)**| TypeScript | `~6.0.2` | Type-safe development |
| **Bundler & Tooling** | Vite | `^8.2.0` | High-velocity build pipeline and HMR |
| **Styling** | Tailwind CSS | `^4.3.3` | Utility-first visual design system |
| **Code Editor** | Monaco Editor | `^4.7.0` | In-browser VS Code editing experience |
| **Diagram Engine** | Mermaid.js | `^11.16.1` | Dynamic SVG architecture rendering |
| **Backend Framework**| FastAPI | Latest | Asynchronous REST coordinator |
| **AST Engine** | Tree-sitter | Latest | Syntax analysis and symbol extraction |
| **Vector Embeddings** | Sentence-Transformers | Latest | Local dense 384-dim semantic embeddings |
| **Vector Index** | FAISS (`faiss-cpu`) | Latest | High-speed dense similarity search |
| **ORM & Database** | SQLAlchemy / SQLite / Postgres | Latest | Relational persistence for sessions and issues |
| **Security & Crypto** | Cryptography (Fernet) | Latest | User token encryption at rest |
| **Test Suite** | Pytest | Latest | 248 unit, integration, and security tests |

---

## 4. Ingestion & Analysis Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant Client as "Web Client (React 19)"
    participant API as FastAPI Gateway
    participant AST as Tree-sitter Parser
    participant Embed as Sentence-Transformers
    participant FAISS as FAISS Index
    participant LLM as Multi-Provider Model Router

    Dev->>Client: Ingest Repository (Git / ZIP)
    Client->>API: POST /repos/ingest
    API->>AST: Parse file syntax & extract symbols
    AST-->>API: AST Symbol Graph (Classes, Functions, Imports)
    API->>Embed: Compute 384-dim dense vector embeddings
    Embed->>FAISS: Index document chunks
    API-->>Client: Ingestion Complete (AST Ready)
    
    Dev->>Client: Query: "How does authentication work?"
    Client->>API: POST /repos/{id}/ask
    API->>FAISS: Nearest-neighbor similarity search
    FAISS-->>API: Top-k Relevant Code Snippets
    API->>LLM: Grounded Prompt + Code Context
    LLM-->>Client: Streaming Response with File Citations
```

---

## 5. Security & Defense-in-Depth

1. **Token Encryption at Rest:** Third-party credentials (GitHub, NVIDIA, Groq, Anthropic) are symmetrically encrypted using **Fernet** (`ENCRYPTION_KEY`).
2. **SSRF Protection:** Strict HTTPS validation and IP host resolution verifying requests do not target loopback (`127.0.0.1`), private RFC1918 subnets, link-local addresses, or cloud metadata endpoints (`169.254.169.254`).
3. **Archive Security:** ZIP extraction enforces Zip Slip prevention (`../`), maximum nesting depth limits, single-file size caps (50MB), total size caps (200MB), and drops Unix symlinks.
4. **Sandboxed Execution:** Untrusted code execution is constrained through `BaseExecutionProvider` with Docker cgroup memory limits (`512MB`), CPU quotas (`1.0`), and zero network access (`--network none`).
5. **Security Headers:** Injected on every response: Content Security Policy (CSP), HSTS, `X-Content-Type-Options: nosniff`, and `X-Frame-Options: DENY`.

---

## 6. Developer Setup & Onboarding

### Prerequisites
- Node.js `20+` and npm `10+`
- Python `3.11+`
- Git `2.40+`
- (Optional) Docker for containerized patch validation

### 1. Clone Repository
```bash
git clone https://github.com/AnniiGCP/CodeBrain.git
cd CodeBrain
```

### 2. Configure Backend
```bash
cd backend
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

### 3. Configure Frontend
```bash
cd ../frontend
npm install
```

### 4. Start Development Servers

**Terminal 1 — Backend (Port 8000):**
```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```
*Interactive Swagger documentation available at: `http://localhost:8000/docs`*

**Terminal 2 — Frontend (Port 5173):**
```bash
cd frontend
npm run dev
```

---

## 7. Verification & Test Suite

The codebase includes an extensive automated testing harness with **248 passing tests**:

```bash
# Run complete backend pytest suite
cd backend
python -m pytest

# Run dedicated security regression test suite
python -m pytest tests/test_production_security_suite.py

# Run frontend test suite
cd ../frontend
npm test -- --run

# Validate production frontend build
npm run build
```
