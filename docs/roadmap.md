# CodeBrain — Product Roadmap

> **Current version:** 0.7.0  
> **Status:** Active development — Phases 1–7 complete.

---

## Completed Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Repo ingestion (zip upload + GitHub clone) | ✅ Done |
| 2 | Code parsing + symbol extraction (Tree-sitter) | ✅ Done |
| 3 | Vector embeddings + FAISS index | ✅ Done |
| 4 | RAG streaming Q&A (Groq LLaMA 3 70B) | ✅ Done |
| 5 | AI documentation generation (docstrings + export) | ✅ Done |
| 6 | AI code-fix: explain / generate diff / sandbox validation | ✅ Done |
| 7 | Voice interface (Groq Whisper + Web Speech API TTS) | ✅ Done |
| **7.5** | **Git/CI-CD integration (branch, commit, PR, pipeline)** | ✅ **Done** |

---

## Phase 8 — Electron AI IDE Shell (Planned)

### Vision

Wrap the existing React frontend + FastAPI backend into a **cross-platform desktop application** using [Electron](https://www.electronjs.org/), transforming CodeBrain from a web app into a standalone **AI-powered IDE shell** that runs entirely offline (air-gapped) or with selectable cloud backends.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Electron Main Process               │
│                                                     │
│  ┌──────────────┐   IPC Bridge   ┌───────────────┐  │
│  │  FastAPI     │◄──────────────►│  Renderer     │  │
│  │  Backend     │  (child_process │  (React SPA)  │  │
│  │  (uvicorn)   │   or socket)    │               │  │
│  └──────────────┘                └───────────────┘  │
│                                                     │
│  Native APIs: fs, shell, clipboard, tray, auto-     │
│  updater, system-level keyboard shortcuts           │
└─────────────────────────────────────────────────────┘
```

The Electron **main process** launches the FastAPI backend as a child process (`uvicorn main:app`) on a random ephemeral port, then serves the Vite-built React frontend in a `BrowserWindow` pointed at `http://localhost:<port>`.

### Implementation Plan

#### 8.1 — Electron Shell Bootstrap

- Scaffold with `electron-vite` (replaces CRA/Vite standalone):
  ```bash
  npx create-electron-vite@latest codebrain-desktop
  ```
- Move existing `frontend/` source into `src/renderer/`.
- Wire `src/main/index.ts` to:
  1. Spawn `python -m uvicorn main:app --port 0` as a child process.
  2. Parse the port from stdout.
  3. Create `BrowserWindow` loading `http://localhost:<port>`.
  4. Pass port via `VITE_API_URL` env var at build time or via IPC.

#### 8.2 — Python Bundling

Use **PyInstaller** to bundle the FastAPI backend into a single executable so users don't need Python installed:

```bash
pyinstaller backend/main.py \
  --name codebrain-api \
  --add-data "backend/storage:storage" \
  --hidden-import sentence_transformers \
  --hidden-import faiss
```

The Electron main process spawns `codebrain-api[.exe]` from `resources/`.

#### 8.3 — Native IDE Features

| Feature | Implementation |
|---------|---------------|
| **File open dialog** | `dialog.showOpenDialog()` → send path to backend via IPC |
| **Directory watcher** | `chokidar` in main process → trigger re-indexing via REST |
| **Global shortcut** | `globalShortcut.register('Alt+Space')` → toggle voice mic |
| **System tray** | `Tray` icon with quick-access menu (Open Repo, Voice, Quit) |
| **Native menu bar** | Replace browser tab with native menu (File, View, Help) |
| **Auto-updater** | `electron-updater` + GitHub Releases or Cloud Storage |
| **Clipboard integration** | One-click "Copy fix diff" to system clipboard |

#### 8.4 — Offline / Air-Gapped Mode

- Bundle a quantised local LLM (e.g. **Ollama llama3:8b** or **LM Studio**) as an optional sidecar.
- Add `LOCAL_LLM_URL` env toggle that switches the Groq API client to a local OpenAI-compatible endpoint.
- Ship FAISS index and embeddings model (`all-MiniLM-L6-v2`) locally — no cloud dependency.

#### 8.5 — Distribution

| Target | Method |
|--------|--------|
| **Windows** | NSIS installer via `electron-builder` |
| **macOS** | `.dmg` + notarisation via Apple Developer account |
| **Linux** | `.AppImage` + `.deb` packages |
| **Auto-update** | `electron-updater` polling GitHub Releases |

CI/CD for the desktop app extends `.github/workflows/ci.yml` with a new `build-desktop` job:
```yaml
jobs:
  build-desktop:
    needs: test
    if: github.ref == 'refs/heads/main'
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - run: npm run electron:build
```

### Timeline Estimate

| Milestone | Effort |
|-----------|--------|
| 8.1 Electron shell + backend spawn | 2–3 days |
| 8.2 PyInstaller bundle | 1–2 days |
| 8.3 Native IDE features (tray, shortcuts, dialogs) | 3–4 days |
| 8.4 Offline/local LLM mode | 3–5 days |
| 8.5 Distribution + auto-update | 2–3 days |
| **Total** | **~2 weeks** |

---

## Phase 9 — Future Ideas (Backlog)

| Idea | Notes |
|------|-------|
| **Multi-repo workspace** | Side-by-side comparison across repos |
| **Git blame integration** | Annotate chat citations with git blame |
| **PR review assistant** | Auto-summarise incoming PRs via webhook |
| **IDE plugin (VS Code extension)** | Sidecar mode connecting to running CodeBrain backend |
| **Team collaboration** | Shared sessions, comment threads on code explanations |
| **Custom embedding models** | Swap `all-MiniLM-L6-v2` for domain-specific fine-tunes |
| **Incremental indexing** | Watch `git diff` and re-embed only changed symbols |

---

*Last updated: Phase 7.5 — Git/CI-CD integration complete.*
