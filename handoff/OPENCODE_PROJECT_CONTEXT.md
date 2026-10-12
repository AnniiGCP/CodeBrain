# OPENCODE_PROJECT_CONTEXT.md

## Project Identity
**Project Name:** AI-Driven Code Analysis, Error Detection, and Documentation System
**Version:** 0.8.0

## Project Objective
The project aims to provide an end-to-end AI-powered assistant that ingests software repositories (via GitHub cloning or ZIP upload), parses the source code using AST (Tree-sitter), embeds code chunks into a Vector Database, and provides advanced RAG (Retrieval-Augmented Generation) capabilities for semantic search, automated bug detection with GitOps-enabled fixes, and comprehensive technical documentation generation.

## Current Implementation Summary
The project has successfully implemented the core ingestion pipeline, the `Tree-sitter` parser, a local embedding pipeline using `Sentence-Transformers`, and a brute-force vector search using `FAISS IndexFlatIP`. The RAG pipeline utilizing the `Groq` API successfully streams context-grounded responses to a React/Vite frontend dashboard. The automated documentation suite successfully generates complex architecture and API markdown documentation (with Mermaid graphs). 

However, advanced scalable vector search algorithms (HNSW, KD-Tree) are completely absent. True automated CI/CD pipeline integration and comprehensive unit tests are missing.

## Technology Stack
**Backend:**
- Python 3.11
- FastAPI / Uvicorn
- SQLAlchemy + SQLite
- FAISS (faiss-cpu)
- Sentence-Transformers
- Tree-sitter
- GitPython
- Groq / NVIDIA NIM Cloud LLMs

**Frontend:**
- React 19 + TypeScript
- Vite
- TailwindCSS v4
- Monaco Editor
- React Router DOM
- Mermaid.js

## Current Architecture
The actual architecture uses a FastAPI backend orchestrating `sqlite` for metadata and local disk `/storage` for raw files and FAISS indices. The frontend is a React application querying the backend via standard REST and SSE (Server-Sent Events) for streaming RAG completions. See `CURRENT_ARCHITECTURE.md` for a complete visual breakdown.

## Module-by-Module Status

### MODULE 1 — Project Setup
- **Status:** PARTIAL
- **Evidence:** `docker-compose.yml`, `requirements.txt`, and `package.json` exist.
- **Problems:** Tests lack dependencies; environment vars need manual injection.

### MODULE 2 — GitHub Repository Input
- **Status:** COMPLETE
- **Evidence:** `backend/routers/repos.py` implements `/repos/upload` and `/repos/github` with `GitPython`.

### MODULE 3 — Repository Scanner
- **Status:** COMPLETE
- **Evidence:** `backend/file_walker.py` successfully traverses and identifies files and languages.

### MODULE 4 — Source Code Parsing
- **Status:** COMPLETE
- **Evidence:** `backend/code_parser.py` implements real AST parsing via `tree-sitter`.

### MODULE 5 — Error Detection
- **Status:** PARTIAL
- **Evidence:** `backend/errordetection/scanner.py` and `backend/routers/errors.py` exist, but rely heavily on AI generation without strict deterministic static analysis rules.

### MODULE 6 — AI Code Analysis
- **Status:** PARTIAL
- **Evidence:** Prompts exist in RAG logic, but LLM analysis is cloud-dependent (Groq/NVIDIA) and non-deterministic.

### MODULE 7 — Embeddings
- **Status:** COMPLETE
- **Evidence:** `backend/vectorstore/embedder.py` uses local `sentence-transformers`.

### MODULE 8 — Vector Database
- **Status:** COMPLETE
- **Evidence:** `backend/vectorstore/index.py` implements a FAISS index on disk.

### MODULE 9 — Vector Search Algorithms
- **Brute Force (FlatIP):** COMPLETE (Implemented in `vectorstore/index.py`).
- **HNSW:** NOT IMPLEMENTED (No code exists).
- **KD-Tree:** NOT IMPLEMENTED (No code exists).

### MODULE 10 — Distance Metrics
- **Cosine Similarity / Inner Product:** COMPLETE (Used implicitly via L2 normalization + FAISS FlatIP).
- **Euclidean / Manhattan:** NOT IMPLEMENTED.

### MODULE 11 — Document Processing
- **Status:** NOT IMPLEMENTED
- **Evidence:** The system only parses source code (`tree-sitter`); there is no PDF/Docx text extraction module.

### MODULE 12 — RAG
- **Status:** PARTIAL
- **Evidence:** Pipeline exists in `backend/rag/answer.py`, streaming tokens to UI. Verification of high recall is lacking.

### MODULE 13 — Documentation Generation
- **Status:** COMPLETE (PRESERVE)
- **Evidence:** `backend/docgen/master_doc_gen.py` successfully generates a 16-section technical documentation suite, including Mermaid.js diagram validation. It works well and should be preserved.

### MODULE 14 — REST API
- **Status:** PARTIAL
- **Evidence:** Dozens of endpoints exist, but test coverage is unverified. See `API_INVENTORY.md`.

### MODULE 15 — Frontend
- **Status:** PARTIAL
- **Evidence:** Pages (`DashboardPage.tsx`, `DocumentationPage.tsx`) exist and connect to backend `api.ts`, but layout/UI refinement might be needed.

### MODULE 16 — PCA / Visualization
- **Status:** NOT IMPLEMENTED
- **Evidence:** No PCA or graphing logic was found.

### MODULE 17 — Benchmarking
- **Status:** NOT IMPLEMENTED
- **Evidence:** No benchmark scripts found.

### MODULE 18 — CI/CD
- **Status:** PARTIAL
- **Evidence:** A module `automation/ci_setup.py` exists to propose CI workflows to GitHub, but the app itself lacks CI/CD tests.

### MODULE 19 — Testing
- **Status:** IMPLEMENTED BUT UNVERIFIED
- **Evidence:** `.pytest_cache` exists, but `pytest` is missing from `requirements.txt`. Tests cannot currently be run out-of-the-box.

### MODULE 20 — Persistence
- **Status:** COMPLETE
- **Evidence:** Uses `SQLite` and FAISS index disk serialization.

### MODULE 21 — Security
- **Status:** STUB
- **Evidence:** `auth.py` contains a dev-login stub. Real OAuth is missing. Path traversal protections exist on ZIP uploads.

## Feature Status Matrix

| Feature                  | Status          | Evidence | Files | Tested |
| ------------------------ | --------------- | -------- | ----- | ------ |
| GitHub cloning           | COMPLETE        | `repos.py` uses `GitPython` | `backend/routers/repos.py` | NO |
| Repository scanning      | COMPLETE        | `file_walker.py` | `backend/file_walker.py` | NO |
| Documentation generation | COMPLETE        | `master_doc_gen.py` | `backend/docgen/*` | NO |
| Embeddings               | COMPLETE        | Local `sentence-transformers` | `backend/vectorstore/embedder.py` | NO |
| FAISS Brute Force        | COMPLETE        | `IndexFlatIP` used | `backend/vectorstore/index.py` | NO |
| HNSW                     | NOT IMPLEMENTED | Grep search yielded 0 results | N/A | NO |
| KD-Tree                  | NOT IMPLEMENTED | Grep search yielded 0 results | N/A | NO |
| RAG                      | PARTIAL         | `answer.py` streams SSE | `backend/rag/answer.py` | NO |
| CI/CD Auto-Setup         | PARTIAL         | `ci_setup.py` proposes PRs | `backend/automation/ci_setup.py` | NO |
| Automated Testing        | IMPLEMENTED BUT UNVERIFIED | `test_docgen.py` | `backend/test_docgen.py` | NO |

## Do Not Change / Preserve List
**PRESERVE** `backend/docgen/master_doc_gen.py` and its related dependencies. This documentation generator is a sophisticated pipeline that safely handles hallucinations, validates Mermaid diagrams, and writes complete Markdown.
**PRESERVE** `backend/rag/answer.py` SSE streaming logic.

## Files Requiring Attention
- `backend/vectorstore/index.py`: Requires major upgrades to support HNSW and KD-Tree.
- `backend/requirements.txt`: Requires `pytest` and related testing libraries.
- `frontend/src/api.ts`: Ensure endpoints map exactly to the FastAPI backend.

## Environment Setup
1. `docker-compose up` runs Redis, FastAPI, and Vite.
2. Required environment variables: `GROQ_API_KEY`, `NVIDIA_NIM_API_KEY`.
3. Backend starts on port `8000`.
4. Frontend starts on port `5173`.

## Current Git State
UNVERIFIED. Assuming standard local development.

## Known Limitations
- Vector search is brute-force only; large repositories will degrade performance.
- Reliance on external Cloud APIs (Groq) creates rate-limiting bottlenecks.
- Mock authentication prevents multi-user production deployment.

## Recommended Development Order
See `IMPLEMENTATION_ROADMAP.md` for a comprehensive step-by-step breakdown.
1. Implement HNSW in FAISS.
2. Setup Pytest framework.
3. Enhance Error Detection.
4. Add PCA Visualizations.
