# API INVENTORY

This document contains a complete inventory of the REST API endpoints identified in the AI-Driven Code Analysis system.

## Authentication Endpoints

### 1. Development Login
- **Method:** POST
- **Path:** `/auth/dev-login`
- **Purpose:** Mock login for development and testing.
- **Request:** JSON body with `github_id`, `github_username`, `github_avatar_url`.
- **Response:** JSON with `user` object.
- **Implementation:** `backend/routers/auth.py`
- **Dependencies:** Database (SQLite)
- **Status:** Functional (mocked)
- **Test status:** UNVERIFIED

## Repository Management Endpoints

### 2. List Repositories
- **Method:** GET
- **Path:** `/repos/`
- **Purpose:** List all repositories owned by the current authenticated user.
- **Request:** None (uses auth cookie).
- **Response:** Array of `RepoSummary` objects.
- **Implementation:** `backend/routers/repos.py`
- **Dependencies:** Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 3. Upload Repository
- **Method:** POST
- **Path:** `/repos/upload`
- **Purpose:** Accept a zip archive and extract it as a new repository for the current user.
- **Request:** `multipart/form-data` with a `file` field (.zip).
- **Response:** `RepoSummary` object.
- **Implementation:** `backend/routers/repos.py`
- **Dependencies:** Database, `zipfile` module
- **Status:** Functional
- **Test status:** UNVERIFIED

### 4. Connect GitHub Repository
- **Method:** POST
- **Path:** `/repos/github`
- **Purpose:** Clone a GitHub repository and ingest its files for the current user.
- **Request:** JSON body with `url` and optional `access_token`.
- **Response:** `RepoSummary` object.
- **Implementation:** `backend/routers/repos.py`
- **Dependencies:** `GitPython`, Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 5. Fetch Repository Files
- **Method:** GET
- **Path:** `/repos/{repo_id}/files`
- **Purpose:** Return the file tree for a repository.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON file tree (`RepoFilesResponse`).
- **Implementation:** `backend/routers/repos.py`
- **Dependencies:** Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 6. Delete Repository
- **Method:** DELETE
- **Path:** `/repos/{repo_id}`
- **Purpose:** Delete a repository, its files, symbols, and disk storage.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON `{ status: "deleted", repo_id: ... }`
- **Implementation:** `backend/routers/repos.py`
- **Dependencies:** Database, File System
- **Status:** Functional
- **Test status:** UNVERIFIED

## Pipeline and Vector Search Endpoints

### 7. Fetch Pipeline Status
- **Method:** GET
- **Path:** `/repos/{repo_id}/pipeline-status`
- **Purpose:** Check the status of background ingestion tasks.
- **Request:** Path parameter `repo_id`.
- **Response:** `PipelineStatusResponse` JSON.
- **Implementation:** `backend/routers/pipeline.py`
- **Dependencies:** Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 8. Retrigger Pipeline
- **Method:** POST
- **Path:** `/repos/{repo_id}/pipeline/run`
- **Purpose:** Force re-run the pipeline on a repository.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON `{ status: string }`.
- **Implementation:** `backend/routers/pipeline.py`
- **Dependencies:** Database, BackgroundTasks
- **Status:** Functional
- **Test status:** UNVERIFIED

### 9. Trigger Embedding
- **Method:** POST
- **Path:** `/repos/{repo_id}/embed`
- **Purpose:** Build/incrementally update the FAISS index for a repo.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON `{ status: string }`.
- **Implementation:** `backend/routers/embeddings.py`
- **Dependencies:** FAISS, Sentence-Transformers, Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 10. Fetch Embed Status
- **Method:** GET
- **Path:** `/repos/{repo_id}/embed/status`
- **Purpose:** Get status of ongoing embedding process.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON `{ status: string, stats: ..., error: ... }`.
- **Implementation:** `backend/routers/embeddings.py`
- **Dependencies:** In-memory status tracking map
- **Status:** Functional
- **Test status:** UNVERIFIED

### 11. Search Repository (Vector Search)
- **Method:** POST
- **Path:** `/repos/{repo_id}/search`
- **Purpose:** Semantic search over a repo's embedded symbols.
- **Request:** JSON body with `query` and `top_k`.
- **Response:** Array of search results.
- **Implementation:** `backend/vectorstore/index.py` & `backend/routers/ask.py`
- **Dependencies:** FAISS, Sentence-Transformers, Database
- **Status:** Functional (uses FAISS IndexFlatIP Brute Force)
- **Test status:** UNVERIFIED

## RAG & Chat Endpoints

### 12. RAG Streaming Ask
- **Method:** POST
- **Path:** `/repos/{repo_id}/ask`
- **Purpose:** Full RAG pipeline (retrieve -> prompt -> stream).
- **Request:** JSON with `query`, `top_k` OR `multipart/form-data` with `query`, `top_k`, and `image` file.
- **Response:** SSE-style streaming response containing metadata and LLM tokens.
- **Implementation:** `backend/rag/answer.py` & `backend/routers/ask.py`
- **Dependencies:** Groq API, FAISS, Database
- **Status:** Functional
- **Test status:** UNVERIFIED

## Code Fix and Error Reporting Endpoints

### 13. Explain Symbol
- **Method:** POST
- **Path:** `/symbols/{symbol_id}/explain`
- **Purpose:** Get AI explanation of a specific code symbol.
- **Request:** Path parameter `symbol_id`.
- **Response:** `ExplainResult` JSON.
- **Implementation:** `backend/routers/codefix.py`
- **Dependencies:** Database, Groq API
- **Status:** Functional
- **Test status:** UNVERIFIED

### 14. Generate Fix
- **Method:** POST
- **Path:** `/symbols/{symbol_id}/fix`
- **Purpose:** Generate a fix for a symbol based on issue description.
- **Request:** JSON with `issue_description`.
- **Response:** `FixResult` JSON.
- **Implementation:** `backend/routers/codefix.py`
- **Dependencies:** Database, Groq API
- **Status:** Functional
- **Test status:** UNVERIFIED

### 15. Validate Patch
- **Method:** POST
- **Path:** `/repos/{repo_id}/validate-patch`
- **Purpose:** Validate a proposed patch before applying it.
- **Request:** JSON with `file_path` and `diff`.
- **Response:** `ValidationResult` JSON.
- **Implementation:** `backend/routers/codefix.py`
- **Dependencies:** File system, GitPython
- **Status:** Functional
- **Test status:** UNVERIFIED

### 16. Fetch Error Reports
- **Method:** GET
- **Path:** `/repos/{repo_id}/errors`
- **Purpose:** List detected issues/errors for a repository.
- **Request:** Query params `severity` and `fix_status`.
- **Response:** `ErrorReportsResponse` JSON.
- **Implementation:** `backend/routers/errors.py`
- **Dependencies:** Database
- **Status:** Functional
- **Test status:** UNVERIFIED

### 17. Generate Error Fix
- **Method:** POST
- **Path:** `/repos/{repo_id}/errors/{error_id}/generate-fix`
- **Purpose:** AI generation of a fix for a specific detected error.
- **Request:** Path parameters `repo_id`, `error_id`.
- **Response:** `GenerateErrorFixResponse` JSON.
- **Implementation:** `backend/routers/errors.py`
- **Dependencies:** Database, Groq API
- **Status:** Functional
- **Test status:** UNVERIFIED

### 18. Apply Error Fix (GitOps)
- **Method:** POST
- **Path:** `/repos/{repo_id}/errors/{error_id}/apply-fix`
- **Purpose:** Commit a generated fix to the repository (or PR).
- **Request:** Path parameters `repo_id`, `error_id`.
- **Response:** `ApplyErrorFixResponse` JSON.
- **Implementation:** `backend/routers/errors.py` & `backend/routers/gitops.py`
- **Dependencies:** Database, GitPython
- **Status:** Functional
- **Test status:** UNVERIFIED

### 19. Reject Error Fix
- **Method:** POST
- **Path:** `/repos/{repo_id}/errors/{error_id}/reject`
- **Purpose:** Reject a proposed AI fix for an error.
- **Request:** Path parameters `repo_id`, `error_id`.
- **Response:** JSON `{ error_id: string, fix_status: string }`.
- **Implementation:** `backend/routers/errors.py`
- **Dependencies:** Database
- **Status:** Functional
- **Test status:** UNVERIFIED

## Voice Endpoints

### 20. Transcribe Audio
- **Method:** POST
- **Path:** `/voice/transcribe`
- **Purpose:** Transcribe audio Blob into text and classify intent.
- **Request:** `multipart/form-data` with `audio` Blob.
- **Response:** `TranscribeResponse` JSON.
- **Implementation:** `backend/voice/router.py`
- **Dependencies:** Groq API (Whisper)
- **Status:** Functional
- **Test status:** UNVERIFIED

## Documentation Generation Endpoints

### 21. Generate Master Docs
- **Method:** POST
- **Path:** `/repos/{repo_id}/docs/master`
- **Purpose:** Triggers full documentation suite generation (16 sections, Mermaid graphs, etc.).
- **Request:** Path parameter `repo_id`.
- **Response:** `MasterDocsResponse` JSON.
- **Implementation:** `backend/docgen/master_doc_gen.py` & `backend/routers/docs.py`
- **Dependencies:** Database, Groq API
- **Status:** Functional
- **Test status:** UNVERIFIED

### 22. Fetch Doc Sections
- **Method:** GET
- **Path:** `/repos/{repo_id}/docs/sections`
- **Purpose:** Retrieve the status and content of generated documentation sections.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON containing `has_docs`, `master_content`, `sections`, `validation_summary`.
- **Implementation:** `backend/routers/docs.py`
- **Dependencies:** File system
- **Status:** Functional
- **Test status:** UNVERIFIED

### 23. Trigger Doc Export
- **Method:** POST
- **Path:** `/repos/{repo_id}/docs/export`
- **Purpose:** Generate markdown and pdf exports of documentation.
- **Request:** Path parameter `repo_id`.
- **Response:** JSON `{ repo_id: string, status: string }`.
- **Implementation:** `backend/routers/docs.py`
- **Dependencies:** PDF rendering logic, File system
- **Status:** Functional
- **Test status:** UNVERIFIED

### 24. Download Documentation
- **Method:** GET
- **Path:** `/repos/{repo_id}/docs/download/{format}`
- **Purpose:** Download generated documentation (ZIP, PDF, MD).
- **Request:** Path parameters `repo_id`, `format` (pdf|md|zip).
- **Response:** File stream.
- **Implementation:** `backend/routers/docs.py`
- **Dependencies:** File system
- **Status:** Functional
- **Test status:** UNVERIFIED

### 25. Commit Docs To Repo
- **Method:** POST
- **Path:** `/repos/{repo_id}/docs/commit-to-repo`
- **Purpose:** Commit generated docs into a `/docs` folder within the connected repository via PR.
- **Request:** Path parameter `repo_id`.
- **Response:** `CommitDocsResponse` JSON.
- **Implementation:** `backend/routers/docs.py`
- **Dependencies:** GitPython, GitHub API
- **Status:** Functional
- **Test status:** UNVERIFIED
