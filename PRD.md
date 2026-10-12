# CodeBrain — Product Requirements Document (PRD)

**Document Version:** 1.0.0  
**Status:** Approved / Active Baseline  
**Target Release:** v1.0 Production Readiness  
**Last Updated:** October 2026  

---

## 1. Product Overview

### 1.1 Product Name
**CodeBrain** — AI-Powered Codebase Intelligence, Automated Documentation, Issue Detection, Code-Fixing & CI/CD Platform.

### 1.2 One-Line Product Description
CodeBrain is an intelligent, developer-first web application that ingests source code repositories, performs deep syntactic and semantic analysis, detects software flaws, validates AI-generated code fixes in isolated sandboxes, generates publication-ready technical documentation, and orchestrates CI/CD GitOps pipelines.

### 1.3 Product Vision
To eliminate developer onboarding friction, eradicate documentation rot, and automate mundane code diagnosis and release workflows through deterministic repository analysis combined with grounded, zero-hallucination artificial intelligence.

### 1.4 Core Value Proposition
- **Rapid Codebase Onboarding:** Ingest repositories via ZIP upload or GitHub OAuth clone in seconds, extracting symbols, relationships, and call paths without manual configuration.
- **Grounded AI Assistance (Zero-Hallucination):** RAG Q&A powered by Abstract Syntax Tree (AST) symbol extraction and local vector embeddings (`all-MiniLM-L6-v2`) with verifiable file and line citations.
- **Deterministic 16-Section Documentation:** Produces comprehensive, standardized architectural documentation exportable to Markdown, HTML, JSON, and PDF.
- **Closed-Loop Bug Remediation:** Discovers static analysis issues, generates unified diff patches, validates them in an execution sandbox, and creates automated GitHub Pull Requests (`ai-fix/*`).
- **Autonomous CI/CD Healing:** Detects failed GitHub Actions workflows, extracts error logs, diagnoses root causes with AI, and opens corrective PRs with bounded retry budgets.

### 1.5 Current Product Scope
CodeBrain currently operates as a full-stack web application featuring a FastAPI Python 3.11 backend, a React 19 / TypeScript / Vite / TailwindCSS v4 frontend, SQLite / PostgreSQL persistence, FAISS vector search, and a centralized multi-provider AI model router (supporting NVIDIA NIM, Groq, Anthropic, APInex, and custom OpenAI/Anthropic-compatible endpoints).

---

## 2. Problem Statement

Modern software engineering teams face four major friction points throughout the software delivery lifecycle:

1. **High Cognitive Burden in Unfamiliar Codebases:** Developers spend up to 40% of their working hours trying to understand legacy, inherited, or multi-repo architectures. Existing search tools rely on naive string matching that lacks semantic and syntactic context.
2. **Persistent Documentation Rot:** Software documentation quickly becomes obsolete because manual documentation maintenance is decoupled from code commits and CI/CD pipelines.
3. **High Remediation Cycles for Common Issues:** Identifying syntax flaws, security anti-patterns, resource leaks, and unhandled edge cases requires repetitive review cycles. Fixes often introduce regressions when untested before pull request creation.
4. **Disjointed CI/CD Failure Triage:** When continuous integration builds fail on remote Git providers, developers must context-switch to remote consoles, download raw log files, manually correlate stack traces to local code, and draft fix commits.

---

## 3. Goals and Outcomes

### 3.1 Primary Goals
- **Grounded Understanding:** Provide conversational answers with exact source code citations (file path, line ranges, symbol signatures) derived from AST indexation.
- **Standardized Documentation:** Generate 16-section technical documentation packages covering system architecture, schemas, API specifications, and dependency trees.
- **Automated Remediation:** Detect issues, generate unified diffs, validate patches in isolated execution runtimes, and deliver automated GitHub Pull Requests.
- **CI/CD Failure Recovery:** Monitor GitHub Actions workflows, categorize failure modes, diagnose root causes, and propose verified code fixes.

### 3.2 Capability State

| Capability | Current State (Verified) | Future Objective |
| :--- | :--- | :--- |
| **Repository Ingestion** | Local ZIP upload & GitHub OAuth HTTPS cloning with SSRF & Zip Slip protections. | Azure DevOps, GitLab, and Bitbucket provider integrations. |
| **AST Symbol Parsing** | Tree-sitter extraction across Python, JavaScript, TypeScript, Go, Java, Rust, C/C++. | Support for Ruby, PHP, Swift, Kotlin, and Scala ASTs. |
| **Vector Search** | Sentence-Transformers (`all-MiniLM-L6-v2`) + FAISS FlatIP index. | Multi-node HNSW / Milvus / pgvector clustering for multi-million SLOC repos. |
| **Model Routing** | Centralized router: NVIDIA NIM, Groq, Anthropic, APInex Luna, custom endpoints. | Local quantized on-device LLM inference via WebGPU / ONNX Runtime. |
| **Issue Detection** | Multi-rule AST scanner for common anti-patterns, resource leaks, and syntax errors. | Deep taint analysis and symbolic execution engines. |
| **Sandbox Execution** | Subprocess, Docker, Remote daemon, and Null execution providers. | Ephemeral Firecracker microVM sandboxes for untrusted code execution. |
| **Documentation Generation** | Master 16-section docgen with Mermaid diagrams, exported to Markdown, HTML, JSON, PDF. | Interactive API playground embedding and automated Confluence/Notion sync. |
| **Desktop Client** | Web SPA running in modern desktop and mobile browsers. | Standalone Electron / Tauri desktop IDE shell (Roadmap Phase 8). |

---

## 4. Target Users

1. **Software Engineers & Onboarding Developers:** Engineers joining unfamiliar projects who need to rapidly understand architecture, trace symbols, and ask architectural questions.
2. **Tech Leads & Software Architects:** Engineering leaders needing consistent, up-to-date system documentation, schema diagrams, and dependency maps across projects.
3. **Repository Maintainers & DevOps Engineers:** Maintainers looking to automate CI/CD pipeline diagnosis, triaging test failures, and generating auto-fix PRs with minimal human intervention.
4. **Security & Quality Assurance Engineers:** Teams needing automated scans of uploaded archives or cloned repositories for insecure functions, leaked secrets, and unhandled exceptions.

---

## 5. Core Features

### 5.1 Repository Management & Ingestion
- **Purpose:** Intake and organize source code repositories securely.
- **User Benefit:** Instantly index an entire repository without installing local language toolchains.
- **Status:** **COMPLETE**
- **User Actions:** Click "Connect Repository", choose "GitHub" or "Upload ZIP", enter HTTPS clone URL or drag-and-drop a `.zip` archive.
- **Dependencies & Safeguards:** Clamped extraction limits (10,000 files, 50MB single file, 200MB total), Unix symlink rejection, SSRF protection blocking private CIDRs and AWS metadata (`169.254.169.254`).

### 5.2 Tree-sitter AST Parsing & Symbol Extraction
- **Purpose:** Parse raw code files into language-specific ASTs to extract functions, classes, methods, and signatures.
- **User Benefit:** Grounding LLMs in precise symbol structures rather than unstructured text chunks.
- **Status:** **COMPLETE**
- **User Actions:** Runs automatically during repository ingestion pipeline.
- **Dependencies:** `tree-sitter`, `tree-sitter-languages`.

### 5.3 Vector Indexing & RAG Q&A (Copilot Chat)
- **Purpose:** Allow natural language queries over the repository with real-time token streaming and citation cards.
- **User Benefit:** Find how code works, locate implementation logic, and understand cross-file flows with verified source references.
- **Status:** **COMPLETE**
- **User Actions:** Type questions in the Chat panel, click citations to jump to line numbers in Monaco Editor, toggle voice input for speech-to-text queries.
- **Dependencies:** FAISS FlatIP index, Sentence Transformers, Centralized AI Model Router.

### 5.4 Automated Error Detection & Issue Scanner
- **Purpose:** Scan repository ASTs and source files for anti-patterns, unhandled exceptions, unused variables, and resource leaks.
- **User Benefit:** Proactively discover software defects before they manifest in production.
- **Status:** **COMPLETE**
- **User Actions:** View issues in the Problems tab of BottomPanel or PrimarySidebar Issues view, inspect severity (error, warning, info), rule IDs, and stack traces.
- **Dependencies:** `backend/errordetection/scanner.py`.

### 5.5 AI Code-Fix Pipeline & Patch Sandbox
- **Purpose:** Generate unified diff fixes for detected issues and validate them before committing.
- **User Benefit:** Confidence that AI-suggested bug fixes do not introduce syntax errors or broken tests.
- **Status:** **COMPLETE**
- **User Actions:** Click "Generate Fix", view unified side-by-side diff in `DiffViewer`, execute validation in sandbox, approve and apply fix to local files.
- **Dependencies:** `backend/codefix/fixer.py`, `backend/codefix/sandbox.py`, `backend/execution/provider.py`.

### 5.6 Master 16-Section Documentation Generator
- **Purpose:** Generate exhaustive, structured architectural documentation and plain-language READMEs.
- **User Benefit:** Eliminates manual documentation authoring and generates audit-ready architecture documents.
- **Status:** **COMPLETE**
- **User Actions:** Navigate to `/docs`, click "Generate Full Documentation", export to Markdown, HTML, JSON, or PDF, view embedded Mermaid architectural diagrams.
- **Dependencies:** `backend/docgen/master_doc_gen.py`, `ReportLab`, `Mermaid.js`.

### 5.7 GitOps PR Automation & GitHub Actions CI/CD Healing
- **Purpose:** Automate Git operations (`ai-fix/*` branches, remote pushes, PR creation) and diagnose failing CI runs.
- **User Benefit:** End-to-end autonomous healing loop from remote CI failure to merged fix.
- **Status:** **COMPLETE**
- **User Actions:** Configure CI/CD under `/cicd`, trigger auto-fix on failed GitHub Actions workflow runs, view automated PR links.
- **Dependencies:** GitHub REST/GraphQL API, `backend/gitops/pr_client.py`, `backend/automation/ci_diagnosis.py`.

### 5.8 Interactive Multi-Terminal & Shell Execution
- **Purpose:** Provide an in-browser VS Code-style interactive terminal for running build, test, and lint commands.
- **User Benefit:** Execute shell commands directly within the repository context without leaving the web workspace.
- **Status:** **COMPLETE**
- **User Actions:** Open BottomPanel Terminal tab, launch multiple named terminal sessions, execute shell commands, kill sessions.
- **Dependencies:** WebSocket streaming, `backend/terminals/manager.py`.

### 5.9 Model Selection & Bring-Your-Own-Key (BYOK)
- **Purpose:** Allow users to choose their preferred LLM provider or supply their own API keys.
- **User Benefit:** Freedom of model choice (speed vs reasoning), cost optimization, and enterprise key privacy.
- **Status:** **COMPLETE**
- **User Actions:** Open Settings modal or ModelSelector dropdown in Chat, select provider (NVIDIA, Groq, Anthropic, Custom), enter API keys (encrypted via Fernet at rest).
- **Dependencies:** `backend/ai/registry.py`, `backend/auth.py`.

---

## 6. User Flows

### 6.1 Authentication & Onboarding Flow
1. User arrives at `/` (Homepage).
2. User clicks "Sign In" or "Get Started" in the Floating Header.
3. User logs in via GitHub OAuth or Email/Password credentials.
4. Backend establishes a signed, HTTP-only, secure session cookie (`session_token`).
5. User is redirected to `/dashboard`.

### 6.2 Repository Ingestion Flow
1. On `/dashboard`, user clicks "Connect Repository" button.
2. In `ConnectRepoModal`, user selects:
   - **GitHub Tab:** Enters `https://github.com/owner/repo.git` and optional branch.
   - **Upload Tab:** Drags and drops a `.zip` archive.
3. Backend creates a `Repo` database record (`pipeline_status: CLONING` or `PENDING`).
4. Pipeline sequentially runs:
   - Archive extraction / Git clone.
   - Tree-sitter AST symbol parsing (`PARSING`).
   - Sentence-Transformer vector embedding (`EMBEDDING`).
   - Static error scanning (`DETECTING_ERRORS`).
   - Background README generation.
5. Workspace activates with loaded file tree, editor, issues, and chat ready.

### 6.3 Grounded Q&A & Code Exploration Flow
1. User opens Chat panel on right sidebar.
2. User enters a query (e.g., "Where is authentication handled and how are tokens signed?").
3. Backend classifies query intent (`QueryIntent.REPO_QUERY`).
4. System queries FAISS vector store for semantic symbol matches.
5. Prompt builder constructs an untrusted code context block with redacting filters.
6. Centralized model router streams answer tokens to frontend.
7. Frontend renders clean Markdown with clickable citation badges.
8. Clicking a citation opens the target file at the exact line range in Monaco Editor.

### 6.4 Issue Detection & AI Code-Fix Flow
1. User navigates to Problems tab or selects an issue in the sidebar.
2. User inspects issue details (file, line, severity, rule ID, diagnostic message).
3. User clicks "Generate Fix".
4. AI generates explanation and unified diff patch.
5. Sandbox execution provider validates the patch in an isolated runner (syntax check + test suite).
6. User reviews the side-by-side visual diff in `DiffViewer`.
7. User clicks "Apply Fix" to write changes to disk or "Open Pull Request" to trigger GitOps branch push.

### 6.5 Documentation Generation & Export Flow
1. User navigates to `/docs`.
2. User clicks "Generate Documentation".
3. Master docgen orchestrator generates all 16 standardized sections:
   - Executive Summary, Tech Stack, Repo Structure, Architecture, Modules, Symbol Catalog, APIs, DB Schema, Relationships, Dependencies, Configuration, Testing, Security, CI/CD, Deployment, Developer Guide.
4. Mermaid diagrams are rendered dynamically in-browser.
5. User selects export format: Markdown (`.md`), PDF (`.pdf`), HTML (`.html`), or JSON (`.json`).

### 6.6 CI/CD Failure Diagnosis & Healing Flow
1. User navigates to `/cicd`.
2. System displays connected repository GitHub Actions runs.
3. For failed runs, user clicks "Diagnose Failure".
4. System downloads remote workflow run logs, categorizes failure (syntax, test, dependency), and runs AI diagnosis.
5. AI proposes a corrective patch.
6. User triggers automated GitOps flow: CodeBrain creates an `ai-fix/*` branch, commits the fix, pushes to remote GitHub, and opens a Pull Request with diagnostic summary.

---

## 7. Functional Requirements

### Ingestion & Parsing
- **FR-01:** System MUST accept repository input via authenticated GitHub HTTPS clone URL or `.zip` file upload.
- **FR-02:** Repository URL parser MUST reject non-HTTPS URLs, private IP addresses (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.1`), and cloud metadata (`169.254.169.254`).
- **FR-03:** ZIP upload handler MUST enforce a maximum 10,000 files limit, 50MB single-file limit, 200MB total extraction size limit, and reject Unix symlinks and directory traversal paths.
- **FR-04:** Parser MUST extract functions, classes, methods, and line numbers using Tree-sitter for all supported programming languages.

### Vector Store & Search
- **FR-05:** System MUST compute 384-dimensional dense embeddings for extracted symbols using `all-MiniLM-L6-v2`.
- **FR-06:** System MUST maintain isolated FAISS FlatIP vector indices per repository under `backend/storage/indices/{repo_id}.faiss`.
- **FR-07:** Top-k semantic search queries MUST return symbol metadata, file paths, line ranges, and source code excerpts.

### AI Copilot & Prompt Policy
- **FR-08:** AI queries MUST stream tokens in real-time to the frontend over HTTP chunked transfer.
- **FR-09:** Context builder MUST wrap retrieved code in untrusted prompt fences and automatically redact sensitive credentials, API keys, and private tokens before dispatching to LLMs.
- **FR-10:** System MUST classify user queries into distinct intents (`greeting`, `general_prog`, `project_overview`, `repo_query`, `error_diagnosis`, `code_explanation`, `code_fix`, `analysis`).

### Issue Detection & Remediation
- **FR-11:** Static analyzer MUST generate structured error reports containing `rule_id`, `file_path`, `line`, `severity`, and `message`.
- **FR-12:** Fixer MUST produce valid unified diff patches adhering to standard patch formatting.
- **FR-13:** Patch validator MUST test candidate diffs in an isolated execution provider prior to applying changes to source files.

### Documentation & Export
- **FR-14:** Documentation generator MUST output complete 16-section technical documentation compliant with the schema defined in `backend/docgen/schema.py`.
- **FR-15:** System MUST generate valid Mermaid architecture and entity-relationship diagrams.
- **FR-16:** System MUST export documentation to Markdown, styled HTML, structured JSON, and multi-page PDF formats.

### GitOps & CI/CD
- **FR-17:** System MUST support creating branches prefixed with `ai-fix/` on connected GitHub repositories.
- **FR-18:** System MUST commit patches using authenticated GitHub tokens and open Pull Requests via the GitHub REST API.
- **FR-19:** System MUST fetch and categorize remote GitHub Actions workflow runs and logs.

### Terminal & Shell
- **FR-20:** System MUST provide multi-session interactive pseudoterminals over WebSockets with ANSI color support.

---

## 8. Non-Functional Requirements

### 8.1 Security & Privacy
- **NFR-01:** All session cookies MUST enforce `HttpOnly`, `SameSite=Lax`, and `Secure` (in production).
- **NFR-02:** User API keys (NVIDIA, Groq, Anthropic, GitHub) MUST be encrypted at rest using Fernet symmetric encryption.
- **NFR-03:** Authentication endpoints MUST enforce sliding-window rate limiting and exponential backoff on repeated login failures, returning HTTP 429 with `Retry-After`.
- **NFR-04:** Browser security headers MUST be sent on all responses: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy`.
- **NFR-05:** Untrusted uploaded code MUST NEVER be executed on the bare API server host; execution MUST route through container or isolated worker abstractions.

### 8.2 Reliability & Availability
- **NFR-06:** Ingestion and docgen pipelines MUST fail gracefully with persistent error logging in database records (`pipeline_status: FAILED`, `pipeline_error: <msg>`).
- **NFR-07:** API router MUST support upstream provider fallback (e.g., APInex -> NVIDIA -> Groq) when an upstream LLM times out or hits rate limits.

### 8.3 Performance
- **NFR-08:** FAISS vector search queries over repositories with up to 50,000 symbols MUST return top-k results in under 150 milliseconds.
- **NFR-09:** Frontend streaming rendering MUST use requestAnimationFrame (RAF) token batching to prevent UI jank during high-velocity LLM token delivery.
- **NFR-10:** Frontend production bundle size MUST remain optimized, with code-splitting for heavy libraries (`monaco-editor`, `mermaid`, `pdfjs-dist`).

### 8.4 Accessibility & UI Standards
- **NFR-11:** All interactive elements MUST provide accessible focus rings and keyboard navigability.
- **NFR-12:** Color contrast for primary text on dark surfaces MUST achieve a minimum 4.5:1 ratio (WCAG AA).
- **NFR-13:** UI MUST respect `prefers-reduced-motion` media queries.

---

## 9. UX and Platform Requirements

### Supported Environments
- **Browsers:** Modern Chromium-based browsers (Chrome, Edge, Brave 110+), Firefox (115+), Safari (17+).
- **Display Resolutions:** Desktop (1920x1080, 1440x900, 1280x800), Laptop, and Responsive Tablet viewport down to 768px width.
- **Color Aesthetics:** Strict developer IDE dark theme:
  - Application page / hero background: `#161718`
  - Workspace unified panel background: `#0c0d0e`
  - Restrained CodeBrain purple accents: `#8b5cf6` / `#9f75ff`
  - Borders: `#1e1f23` / `rgba(255, 255, 255, 0.06)`

---

## 10. Success Metrics

### Operational Metrics (Currently Measured)
- Automated test suite pass rate: **100%** (244/244 backend tests, 20/20 frontend tests).
- Ingestion pipeline success rate across standard ZIP archives and public GitHub repos.
- Vector query response latency (sub-200ms).

### Target Product Metrics (Proposed)
- **Time to First Architecture Comprehension:** Reduction in developer onboarding time from days to under 15 minutes.
- **Auto-Fix Acceptance Rate:** Over 75% of AI-generated unified diff patches applied without manual adjustments.
- **Documentation Completeness:** 100% of analyzed repositories successfully generate all 16 standardized sections without manual intervention.
- **CI/CD Failure Recovery Time:** Automated diagnosis and PR generation completed within 90 seconds of remote build failure.

---

## 11. Out of Scope

The following capabilities are intentionally deferred from the current release:
1. **Desktop Shell Packaging:** Standalone Electron or Tauri desktop application (documented on roadmap as Phase 8).
2. **Multi-Tenant SaaS Billing:** Metered stripe subscriptions, team seat management, or usage quotas.
3. **Automated Merging Without Human Approval:** CodeBrain creates branches and PRs; it does not force-merge pull requests into production default branches without human review.
4. **Live Collaborative Multi-Cursor Editing:** Real-time Google Docs-style simultaneous editing in Monaco editor.
5. **Non-Git Version Control Systems:** SVN, Mercurial, or Perforce integrations.

---

## 12. Assumptions, Risks, and Dependencies

### Technical Assumptions
- Cloned repositories can be parsed into UTF-8 text files; binary assets are excluded from embedding and AST indexation.
- The host system has network egress to reach external LLM provider endpoints (NVIDIA, Groq, Anthropic).

### Risks & Mitigations
- **LLM Provider Outages & Rate Limits:** Mitigated by centralized fallback router across multiple providers and persistent token quota tracking (`ApinexDailyUsage`).
- **Memory Consumption on Massive Repositories:** Mitigated by file size filters, file count caps (10,000 files), and FAISS FlatIP index serialization to disk.
- **Untrusted Code Execution:** Mitigated by `BaseExecutionProvider` abstraction enforcing isolated Docker containers or disabled execution (`null` provider) in production environments.
