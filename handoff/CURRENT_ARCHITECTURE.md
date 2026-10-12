# CURRENT ARCHITECTURE

This document describes the actual architecture of the AI-Driven Code Analysis system based on the current implementation found in the codebase.

## High-Level Data Flow

```mermaid
flowchart TD
    User([User / Browser])
    
    subgraph Frontend [Frontend (React + Vite)]
        UI[UI Components]
        APIClient[API Client]
    end
    
    subgraph Backend [Backend (FastAPI)]
        Router[API Routers]
        Pipeline[Ingestion Pipeline]
        DocGen[Documentation Generator]
        RAG[RAG & Ask Engine]
        GitOps[GitOps & CI Automation]
        ErrorDetect[Error Detection]
    end
    
    subgraph Data [Data Persistence]
        SQLite[(SQLite App DB)]
        FAISS[(FAISS Vector DB)]
        Disk[(Local Storage Repo Archive)]
    end
    
    subgraph AI [AI Models / APIs]
        Groq[Groq API - LLM Generation]
        ST[Sentence Transformers - Local Embedding]
        Whisper[Groq Whisper - Audio Transcribe]
    end

    User -->|Interacts| UI
    UI -->|REST / SSE| APIClient
    APIClient <-->|HTTP Requests| Router
    
    Router --> Pipeline
    Pipeline -->|Extracts Files| Disk
    Pipeline -->|Parses Code| SQLite
    Pipeline -->|Embeds Chunks| ST
    ST -->|Vectors| FAISS
    
    Router --> DocGen
    DocGen -->|Queries Knowledge Graph| SQLite
    DocGen -->|Generates Markdown| Groq
    DocGen -->|Saves PDF/ZIP| Disk
    
    Router --> RAG
    RAG -->|Similarity Search| FAISS
    RAG -->|Context + Prompt| Groq
    
    Router --> GitOps
    GitOps -->|Creates PRs / Branches| Disk
    
    Router --> ErrorDetect
    ErrorDetect -->|Suggests Fixes| Groq
```

## Component Breakdown

### 1. Frontend (React 19, TypeScript)
- Serves as the UI dashboard.
- Uses `react-router-dom` for navigation (HomePage, DashboardPage, DocumentationPage).
- Interacts with backend using the `api.ts` module with standard `fetch` API.
- Implements real-time RAG answers via Server-Sent Events (SSE).

### 2. Backend (FastAPI, Python 3.11)
- The central orchestrator handling all logic.
- Structured into domain-specific routers:
  - `/repos`: Repo ingestion (Zip/GitHub)
  - `/docs`: Automated documentation suite
  - `/ask`: Retrieval-Augmented Generation
  - `/errors`: Code issue detection & automated fixes
  - `/voice`: Voice input transcription
  - `/gitops`: Commit/PR generation

### 3. AI & Vector Layers
- **Embedding:** Uses local `sentence-transformers` for embedding code symbols.
- **Vector Search:** Uses `faiss-cpu` (specifically `IndexIDMap(IndexFlatIP)`) for fast Brute Force exact inner-product semantic search. Advanced algorithms like HNSW and KD-Tree are NOT yet implemented.
- **Generation:** Cloud-based generation using `Groq` and `NVIDIA NIM` APIs. Strict system prompts heavily restrict hallucinations.

### 4. Storage & Persistence
- **Relational Data:** `SQLite` (`app.db`) through `SQLAlchemy`. Stores `Repo`, `RepoFile`, `Symbol`, `ErrorReport` metadata.
- **Vector Data:** `FAISS` indexes stored locally in the `storage/{repo_id}/faiss.index` folder.
- **File Data:** Extracted zip contents and cloned repos live in `storage/{repo_id}/`.

## Identified Architectural Limitations
- SQLite may become a bottleneck for concurrent large-scale repository scans.
- Using FAISS FlatIP (Brute Force) scales linearly $O(N)$ with the number of code symbols. As repositories grow, this will cause latency issues without HNSW.
- The pipeline architecture executes synchronously within the FastAPI background tasks rather than utilizing a dedicated distributed task queue (e.g. Celery).
