# IMPLEMENTATION ROADMAP

This document outlines the remaining work for the **AI-Driven Code Analysis, Error Detection, and Documentation System**, organized in dependency-aware order starting from the *actual current state*.

## Phase 1: Vector Search Expansion (P0 - Critical)

Currently, the vector search relies entirely on `FAISS IndexFlatIP` (Brute Force). For the system to scale to large codebases as originally intended, we must implement sub-linear approximate nearest neighbor algorithms.

### 1.1 Implement KD-Tree Support
- **Objective:** Provide logarithmic search for low-dimensional spaces or as a baseline alternative.
- **Prerequisites:** Existing `faiss-cpu` dependency and `IndexIDMap` structure in `vectorstore/index.py`.
- **Tasks:**
  - Add KD-Tree builder option in `_make_new_index()`.
  - Add configuration variable to choose algorithm.
- **Affected Files:** `backend/vectorstore/index.py`
- **Tests Required:** Index creation, Insertion, Top-K Recall vs Brute Force.

### 1.2 Implement HNSW (Hierarchical Navigable Small World)
- **Objective:** Implement the primary scalable vector search algorithm.
- **Prerequisites:** FAISS HNSW module available in the current environment.
- **Tasks:**
  - Add `IndexHNSWFlat` logic in `_make_new_index()`.
  - Expose HNSW hyperparameters: `M`, `efConstruction`, `efSearch`.
  - Implement incremental update handling since HNSW `remove_ids` is historically tricky in FAISS (may require index rebuilding or soft deletion).
- **Affected Files:** `backend/vectorstore/index.py`
- **Tests Required:** HNSW graph build, accuracy testing on large repos.

## Phase 2: Error Detection & Auto-Fix Finalization (P1 - Important)

The error detection exists, but it currently relies primarily on API endpoints with minimal local semantic analysis verification.

### 2.1 Static Analysis Integration
- **Objective:** Connect actual parser rules to the `ErrorReport` generation rather than solely LLM inferences.
- **Prerequisites:** `tree-sitter` already extracts AST symbols.
- **Tasks:**
  - Enhance `errordetection/scanner.py` to flag obvious AST anomalies (e.g., syntax errors, missing variables) before sending to Groq.
- **Affected Files:** `backend/errordetection/scanner.py`, `backend/code_parser.py`

### 2.2 Complete GitOps Fix Application
- **Objective:** Ensure the generated fixes can actually push to GitHub.
- **Prerequisites:** `routers/gitops.py` structure exists.
- **Tasks:**
  - Implement Git push with GitHub PAT.
  - Implement GitHub API call to open Pull Requests.
- **Affected Files:** `backend/routers/gitops.py`

## Phase 3: Benchmarking and Visualization (P2 - Enhancement)

### 3.1 PCA Visualization UI
- **Objective:** Allow users to visualize code vectors in 2D/3D to understand the semantic layout of their repository.
- **Prerequisites:** Python `scikit-learn` for PCA, Frontend charting library (e.g., Plotly or D3).
- **Tasks:**
  - Add `backend/analysis/pca.py` to reduce dimensions of symbol vectors.
  - Create `GET /repos/{repo_id}/visualization` API endpoint.
  - Build `Frontend -> VisualizationPage.tsx` using `react-plotly.js` or similar.
- **Affected Files:** `backend/routers/analysis.py`, `frontend/src/pages/VisualizationPage.tsx`

### 3.2 Algorithm Benchmarking Suite
- **Objective:** Quantify performance differences between Brute Force, KD-Tree, and HNSW.
- **Prerequisites:** Phase 1 complete.
- **Tasks:**
  - Create a benchmarking script `scripts/benchmark_vectors.py`.
  - Measure Index Build Time, Search Time, and Recall %.
- **Affected Files:** `backend/scripts/benchmark.py`

## Phase 4: Automated Testing Suite (P0 - Critical)

Currently, testing relies entirely on manual verification.

### 4.1 Pytest Setup
- **Objective:** Ensure the system does not regress.
- **Prerequisites:** None.
- **Tasks:**
  - Add `pytest`, `pytest-asyncio`, `httpx` to `requirements.txt`.
  - Implement unit tests for `code_parser.py`.
  - Implement integration tests for FastAPI routers.
- **Affected Files:** `backend/requirements.txt`, `backend/tests/*`

### 4.2 CI/CD Integration
- **Objective:** Run tests on PRs.
- **Prerequisites:** Phase 4.1 complete.
- **Tasks:**
  - Create `.github/workflows/backend-test.yml` and `frontend-test.yml`.
- **Affected Files:** `.github/workflows/*`

## Completion Criteria
1. User can switch vector search algorithms dynamically in UI.
2. HNSW provides sub-50ms search times on 10k+ symbol repositories.
3. Automated fixes successfully result in GitHub Pull Requests.
4. Test coverage exceeds 70% for backend core logic.
