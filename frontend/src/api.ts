import type {
  User,
  RepoSummary,
  RepoFilesResponse,
  Citation,
  FixResult,
  ValidationResult,
  ExplainResult,
  TranscribeResponse,
  ApplyFixRequest,
  ApplyFixResponse,
  PipelineStatusResponse,
  ErrorReport,
  ErrorReportsResponse,
  GenerateErrorFixResponse,
  ApplyErrorFixResponse,
  DocSectionItem,
  DocValidationSummary,
  MasterDocsResponse,
  CommitDocsResponse,
  AutomationLogResponse,
  ApiKeyStatusResponse,
  SaveApiKeysPayload,
  TestConnectionPayload,
  TestConnectionResponse,
  CiWorkflowPreviewResponse,
  CiOverviewResponse,
  CiRunItem,
  CiJobItem,
  CiDiagnosisResult,
  NvidiaModelsResponse,
  MasterAiRegistryResponse,
  ModelForTaskResponse,
  ApinexQuotaResponse,
  TerminalSessionItem,
  GitStatusResponse,
  GitCommitRequest,
  GitCommitResponse,
  GitHistoryResponse,
} from "./types";

const configuredApiUrl = (
  (import.meta.env.VITE_API_URL as string | undefined) ??
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  ""
).trim();

export const API_BASE = configuredApiUrl || (import.meta.env.PROD ? "https://codebrain-backend.onrender.com" : "http://localhost:8000");

let onUnauthorizedCallback: (() => void) | null = null;

export function setOnUnauthorizedCallback(cb: () => void) {
  onUnauthorizedCallback = cb;
}

/**
 * Universal authenticated fetch helper that attaches credentials (cookies)
 * and globally catches 401 Unauthorized responses.
 */
export async function apiFetch(input: string | URL | Request, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const token = typeof window !== "undefined" ? localStorage.getItem("codebrain_token") : null;
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const options: RequestInit = {
    ...init,
    headers,
    credentials: init.credentials ?? "include",
  };
  let res: Response;
  try {
    res = await fetch(input, options);
  } catch (err: unknown) {
    const rawMsg = err instanceof Error ? err.message : String(err);
    if (rawMsg.includes("Failed to fetch") || rawMsg.includes("NetworkError") || rawMsg.includes("Load failed")) {
      throw new Error(
        "Unable to connect to the CodeBrain backend. The server may be waking up from idle or network connectivity was interrupted. Please retry in a few seconds."
      );
    }
    throw err;
  }
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("codebrain_token");
    }
    if (onUnauthorizedCallback) {
      onUnauthorizedCallback();
    }
  }
  return res;
}

// ── Auth & Identity ──────────────────────────────────────────────────────────

export async function getCurrentUser(): Promise<User | null> {
  const res = await apiFetch(`${API_BASE}/me`);
  if (res.status === 401) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch current user: ${res.statusText}`);
  }
  return res.json();
}

export async function logout(): Promise<void> {
  if (typeof window !== "undefined") {
    localStorage.removeItem("codebrain_token");
  }
  await apiFetch(`${API_BASE}/logout`, { method: "POST" });
}

export async function fetchGitHubUserRepos(): Promise<{ connected: boolean; repos: any[]; total: number; username: string | null }> {
  const res = await apiFetch(`${API_BASE}/auth/github/repos`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch GitHub repositories");
  }
  return res.json();
}

export async function disconnectGitHub(): Promise<{ status: string; message: string }> {
  const res = await apiFetch(`${API_BASE}/auth/github/disconnect`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to disconnect GitHub");
  }
  return res.json();
}

export async function devLogin(username = "dev_user"): Promise<User> {
  const res = await apiFetch(`${API_BASE}/auth/dev-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      github_id: `dev_${username.toLowerCase()}`,
      github_username: username,
      github_avatar_url: `https://github.com/${username}.png`,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Dev login failed");
  }
  const data = await res.json();
  if (data.token && typeof window !== "undefined") {
    localStorage.setItem("codebrain_token", data.token);
  }
  return data.user;
}

export async function registerUser(email: string, username: string, password: string): Promise<User> {
  const res = await apiFetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Registration failed");
  }
  const data = await res.json();
  if (data.token && typeof window !== "undefined") {
    localStorage.setItem("codebrain_token", data.token);
  }
  return data.user;
}

export async function passwordLogin(identifier: string, password: string): Promise<User> {
  const res = await apiFetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Login failed");
  }
  const data = await res.json();
  if (data.token && typeof window !== "undefined") {
    localStorage.setItem("codebrain_token", data.token);
  }
  return data.user;
}

// ── Repos ────────────────────────────────────────────────────────────────────

export async function fetchRepos(): Promise<RepoSummary[]> {
  const res = await apiFetch(`${API_BASE}/repos/`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadRepo(file: File): Promise<RepoSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`${API_BASE}/repos/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export async function connectGithubRepo(
  url: string,
  accessToken?: string
): Promise<RepoSummary> {
  const res = await apiFetch(`${API_BASE}/repos/github`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, access_token: accessToken || undefined }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Clone failed");
  }
  return res.json();
}

export async function fetchRepoFiles(repoId: string): Promise<RepoFilesResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/files`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchCiPreview(repoId: string): Promise<CiWorkflowPreviewResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci-preview`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch CI preview");
  }
  return res.json();
}

export async function fetchCiOverview(repoId: string): Promise<CiOverviewResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/overview`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch CI/CD overview");
  }
  return res.json();
}

export async function analyzeCi(repoId: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/analyze`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to re-analyze CI repository");
  }
  return res.json();
}

export async function generateCiWorkflow(repoId: string): Promise<CiWorkflowPreviewResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/generate`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to generate CI workflow proposal");
  }
  return res.json();
}

export async function installCiViaPr(repoId: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/install-pr`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to propose CI workflow PR");
  }
  return res.json();
}

export async function installCiDirect(
  repoId: string,
  payload?: { workflow_content?: string; commit_message?: string }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/install-direct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to commit CI workflow directly");
  }
  return res.json();
}

export async function verifyCiInstallation(repoId: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/verify-installation`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to verify remote CI installation");
  }
  return res.json();
}

export async function fetchCiRuns(repoId: string, limit: number = 15): Promise<{ repo_id: string; runs: CiRunItem[] }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/runs?limit=${limit}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch GitHub Actions runs");
  }
  return res.json();
}

export async function fetchCiRunDetails(repoId: string, runId: string): Promise<{ repo_id: string; run_id: string; jobs: CiJobItem[]; status?: string; conclusion?: string | null }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/runs/${runId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch workflow run details");
  }
  return res.json();
}

export async function dispatchCiWorkflow(
  repoId: string,
  payload?: { workflow_id_or_filename?: string; ref?: string }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/dispatch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to dispatch workflow");
  }
  return res.json();
}

export async function triggerDeployment(
  repoId: string,
  payload?: { environment?: string; skip_ci_check?: boolean }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/deployment/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to trigger deployment");
  }
  return res.json();
}

export async function diagnoseCiFailure(repoId: string, runId: string): Promise<CiDiagnosisResult> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/diagnose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to diagnose CI failure");
  }
  return res.json();
}

export async function applyCiFix(
  repoId: string,
  payload: { run_id: string; patch: string; commit_message?: string }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/apply-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to apply CI fix");
  }
  return res.json();
}

export async function updateCiSettings(
  repoId: string,
  settings: { auto_fix_enabled?: boolean; auto_commit_enabled?: boolean; max_retry_budget?: number }
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/ci/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to update CI settings");
  }
  return res.json();
}

export async function fetchFileContent(
  repoId: string,
  filePath: string
): Promise<{ repo_id: string; path: string; content: string; language: string; size: number }> {
  const params = new URLSearchParams({ path: filePath });
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/file-content?${params.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to load file content");
  }
  return res.json();
}

export async function deleteRepo(repoId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Delete failed");
  }
}

// ── API Key Settings ─────────────────────────────────────────────────────────

export async function fetchApiKeyStatus(): Promise<ApiKeyStatusResponse> {
  const res = await apiFetch(`${API_BASE}/auth/keys`);
  if (!res.ok) throw new Error("Failed to fetch API key status");
  return res.json();
}

export async function saveApiKeys(keys: SaveApiKeysPayload): Promise<ApiKeyStatusResponse> {
  const res = await apiFetch(`${API_BASE}/auth/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(keys),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to save API keys");
  }
  return res.json();
}

export async function testProviderConnection(payload: TestConnectionPayload): Promise<TestConnectionResponse> {
  const res = await apiFetch(`${API_BASE}/auth/keys/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Connection test failed");
  }
  return res.json();
}

export async function deleteApiKey(provider: string): Promise<{ status: string; message: string }> {
  const res = await apiFetch(`${API_BASE}/auth/keys/${provider}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to remove API key");
  }
  return res.json();
}

export async function fetchNvidiaModels(): Promise<NvidiaModelsResponse> {
  const res = await apiFetch(`${API_BASE}/ai/models/nvidia`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch NVIDIA models");
  }
  return res.json();
}

export async function fetchAiRegistry(): Promise<MasterAiRegistryResponse> {
  const res = await apiFetch(`${API_BASE}/ai/models`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch AI registry");
  }
  return res.json();
}

export async function fetchApinexQuota(): Promise<ApinexQuotaResponse> {
  const res = await apiFetch(`${API_BASE}/ai/apinex/quota`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch APInex quota");
  }
  return res.json();
}

export function notifyQuotaUpdated() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("apinex-quota-updated"));
  }
}

export async function fetchModelForTask(
  task: string,
  contextSize: number = 0,
  requiresVision: boolean = false,
  requiresTools: boolean = false,
  complexity: string = "normal"
): Promise<ModelForTaskResponse> {
  const params = new URLSearchParams({
    task,
    context_size: String(contextSize),
    requires_vision: String(requiresVision),
    requires_tools: String(requiresTools),
    complexity,
  });
  const res = await apiFetch(`${API_BASE}/ai/model-for-task?${params.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to resolve model for task");
  }
  return res.json();
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export async function fetchPipelineStatus(repoId: string): Promise<PipelineStatusResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/pipeline-status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function retriggerPipeline(repoId: string): Promise<{ status: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/pipeline/run`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Pipeline retrigger failed");
  }
  return res.json();
}

export async function triggerEmbed(repoId: string): Promise<{ status: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/embed`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Embed failed");
  }
  return res.json();
}

export async function fetchEmbedStatus(
  repoId: string
): Promise<{ status: string; stats?: unknown; error?: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/embed/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function searchRepo(
  repoId: string,
  query: string,
  topK = 8
): Promise<{ repo_id: string; query: string; results: any[] }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Search failed");
  }
  return res.json();
}

// ── RAG streaming ask ────────────────────────────────────────────────────────

export interface AskStreamCallbacks {
  onCitations: (citations: Citation[]) => void;
  onErrorReports?: (reports: ErrorReport[]) => void;
  onStatus?: (status: string | null) => void;
  onToken: (token: string) => void;
  onDone: () => void;
  onError: (err: string) => void;
  onStop?: () => void;
}

/**
 * Streams the /ask response. Parses leading [STATUS] and [CONTEXT] metadata lines,
 * fires onStatus() for real-time analysis progress, fires onCitations() and onErrorReports() once,
 * then fires onToken() for every subsequent chunk.
 * Supports optional imageFile attachment for vision diagnosis, plus AbortSignal for immediate cancellation.
 */
export async function streamAsk(
  repoId: string,
  query: string,
  topK: number,
  callbacks: AskStreamCallbacks,
  imageFile?: File | Blob,
  provider?: string,
  model?: string,
  abortSignal?: AbortSignal
): Promise<void> {
  if (abortSignal?.aborted) {
    callbacks.onStop?.();
    return;
  }

  let fetchOptions: RequestInit;

  if (imageFile) {
    const formData = new FormData();
    formData.append("query", query);
    formData.append("top_k", String(topK));
    formData.append("image", imageFile);
    if (provider) formData.append("provider", provider);
    if (model) formData.append("model", model);
    fetchOptions = {
      method: "POST",
      body: formData,
      signal: abortSignal,
    };
  } else {
    fetchOptions = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        top_k: topK,
        ...(provider ? { provider } : {}),
        ...(model ? { model } : {}),
      }),
      signal: abortSignal,
    };
  }

  let res: Response;
  try {
    res = await apiFetch(`${API_BASE}/repos/${repoId}/ask`, fetchOptions);
  } catch (err: any) {
    if (abortSignal?.aborted || err?.name === "AbortError") {
      callbacks.onStop?.();
      return;
    }
    callbacks.onError(err?.message || "Failed to connect to AI server");
    return;
  }

  if (abortSignal?.aborted) {
    callbacks.onStop?.();
    return;
  }

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText);
    callbacks.onError(text);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let citationsParsed = false;

  try {
    while (true) {
      if (abortSignal?.aborted) {
        try { await reader.cancel(); } catch {}
        callbacks.onStop?.();
        return;
      }

      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      if (!chunk) continue;

      buffer += chunk;

      // 1. Process all available [STATUS] lines: data: [STATUS] <message>\n\n
      while (buffer.startsWith("data: [STATUS]")) {
        const doubleNewlineIdx = buffer.indexOf("\n\n");
        if (doubleNewlineIdx === -1) break; // Wait for complete \n\n delimiter
        const statusLine = buffer.slice(0, doubleNewlineIdx).trim();
        buffer = buffer.slice(doubleNewlineIdx + 2);
        const statusMsg = statusLine.slice("data: [STATUS]".length).trim();
        if (statusMsg && callbacks.onStatus) {
          callbacks.onStatus(statusMsg);
        }
      }

      // 2. Process [CONTEXT] metadata line: data: [CONTEXT] <json>\n\n
      if (!citationsParsed && buffer.startsWith("data: [CONTEXT]")) {
        const doubleNewlineIdx = buffer.indexOf("\n\n");
        if (doubleNewlineIdx !== -1) {
          const contextLine = buffer.slice(0, doubleNewlineIdx).trim();
          buffer = buffer.slice(doubleNewlineIdx + 2);
          try {
            const jsonStr = contextLine.slice("data: [CONTEXT]".length).trim();
            const meta = JSON.parse(jsonStr) as { citations?: Citation[]; error_reports?: ErrorReport[] };
            if (meta.citations) callbacks.onCitations(meta.citations);
            if (meta.error_reports && callbacks.onErrorReports) {
              callbacks.onErrorReports(meta.error_reports);
            }
          } catch {
            // Malformed metadata — skip
          }
          citationsParsed = true;
        } else {
          // Still waiting for complete \n\n delimiter
          continue;
        }
      }

      // 3. Partial prefix check: wait if buffer is an incomplete prefix of an SSE line
      if (!citationsParsed && ("data: [CONTEXT]".startsWith(buffer) || "data: [STATUS]".startsWith(buffer))) {
        continue;
      }

      // 4. Stream tokens: clear analysis status and emit tokens
      if (buffer) {
        citationsParsed = true;
        if (callbacks.onStatus) {
          callbacks.onStatus(null);
        }
        callbacks.onToken(buffer);
        buffer = "";
      }
    }

    if (buffer) {
      if (callbacks.onStatus) callbacks.onStatus(null);
      callbacks.onToken(buffer);
      buffer = "";
    }
  } catch (err: any) {
    if (abortSignal?.aborted || err?.name === "AbortError") {
      try { await reader.cancel(); } catch {}
      callbacks.onStop?.();
      return;
    }
    callbacks.onError(err?.message || "Streaming interrupted");
    return;
  } finally {
    try {
      reader.releaseLock();
    } catch {}
    if (callbacks.onStatus) callbacks.onStatus(null);
    if (!abortSignal?.aborted) {
      callbacks.onDone();
      notifyQuotaUpdated();
    }
  }
}

// ── Codefix ───────────────────────────────────────────────────────────────────

export async function explainSymbol(symbolId: number): Promise<ExplainResult> {
  const res = await apiFetch(`${API_BASE}/symbols/${symbolId}/explain`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Explain failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export async function generateFix(
  symbolId: number,
  issueDescription: string
): Promise<FixResult> {
  const res = await apiFetch(`${API_BASE}/symbols/${symbolId}/fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_description: issueDescription }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Fix generation failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export async function validatePatch(
  repoId: string,
  filePath: string,
  diff?: string,
  patchedContent?: string,
  testCommand?: string,
): Promise<ValidationResult> {
  const cleanDiff = diff?.trim() || undefined;
  const cleanContent = patchedContent?.trim() || undefined;

  if (!cleanDiff && !cleanContent) {
    return {
      repo_id: repoId,
      file_path: filePath,
      passed: false,
      test_command: "(none)",
      exit_code: -1,
      output: "",
      error: "Cannot run tests: No code diff was generated for this issue.",
      failure_type: "INVALID_PATCH",
    };
  }

  const res = await apiFetch(`${API_BASE}/repos/${repoId}/validate-patch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_path: filePath,
      diff: cleanDiff,
      patched_content: cleanContent,
      test_command: testCommand || undefined,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Validation failed");
  }
  return res.json();
}

// ── Multi-Terminal Sessions ──────────────────────────────────────────────────

export async function fetchTerminalSessions(repoId: string): Promise<TerminalSessionItem[]> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals`);
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to fetch terminal sessions"));
  return res.json();
}

export async function createTerminalSession(
  repoId: string,
  title?: string,
  subpath?: string
): Promise<TerminalSessionItem> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, subpath }),
  });
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to create terminal session"));
  return res.json();
}

export async function fetchTerminalSession(
  repoId: string,
  sessionId: string,
  since: number = 0
): Promise<TerminalSessionItem> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals/${sessionId}?since=${since}`);
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to fetch terminal"));
  return res.json();
}

export async function executeTerminalCommand(
  repoId: string,
  sessionId: string,
  command: string
): Promise<{ status: string; session_id: string; command: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals/${sessionId}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to execute terminal command");
  }
  return res.json();
}

export async function sendTerminalInput(
  repoId: string,
  sessionId: string,
  text: string
): Promise<{ sent: boolean }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals/${sessionId}/input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to send terminal input"));
  return res.json();
}

export async function stopTerminalProcess(
  repoId: string,
  sessionId: string
): Promise<{ status: string; session_id: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals/${sessionId}/stop`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to stop terminal"));
  return res.json();
}

export async function closeTerminalSession(
  repoId: string,
  sessionId: string
): Promise<{ status: string; session_id: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/terminals/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to close terminal session"));
  return res.json();
}

// ── Voice ─────────────────────────────────────────────────────────────────────

/**
 * Send a recorded audio Blob to the backend /voice/transcribe endpoint.
 * Returns the transcribed text plus intent classification metadata.
 */
export async function transcribeAudio(audioBlob: Blob, filename = "audio.webm"): Promise<TranscribeResponse> {
  const form = new FormData();
  form.append("audio", audioBlob, filename);
  const res = await apiFetch(`${API_BASE}/voice/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Transcription failed");
  }
  return res.json();
}

// ── GitOps — apply fix as branch + PR ─────────────────────────────────────────

export async function applyFix(repoId: string, request: ApplyFixRequest): Promise<ApplyFixResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/apply-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Apply fix failed");
  }
  return res.json();
}

// ── GitOps Source Control & Commits ──────────────────────────────────────────

export async function fetchGitStatus(repoId: string): Promise<GitStatusResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/git-status`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch git status");
  }
  return res.json();
}

export async function fetchGitDiff(repoId: string, filePath: string): Promise<{ path: string; diff: string }> {
  const params = new URLSearchParams({ path: filePath });
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/git-diff?${params.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch git diff");
  }
  return res.json();
}

export async function createGitCommit(repoId: string, payload: GitCommitRequest): Promise<GitCommitResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/git-commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Git commit failed");
  }
  return res.json();
}

export async function fetchGitHistory(repoId: string): Promise<GitHistoryResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/git-history`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch git history");
  }
  return res.json();
}

// ── DocGen ───────────────────────────────────────────────────────────────────

export interface ReadmeResponse {
  repo_id: string;
  has_readme: boolean;
  readme: string;
  source_fingerprint?: string | null;
  current_fingerprint?: string | null;
  is_stale?: boolean;
  generator_model?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export async function fetchReadme(repoId: string): Promise<ReadmeResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/readme`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch README");
  }
  return res.json();
}

export async function generateReadme(
  repoId: string,
  force: boolean = false
): Promise<{ repo_id: string; readme: string; is_fresh?: boolean; source_fingerprint?: string }> {
  const url = force ? `${API_BASE}/repos/${repoId}/docs/readme?force=true` : `${API_BASE}/repos/${repoId}/docs/readme`;
  const res = await apiFetch(url, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "README generation failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export interface DocGenProgressResponse {
  status: string;
  percentage: number;
  current_section: string;
  section_number: number;
  completed: number;
  total: number;
}

export async function fetchDocGenProgress(repoId: string): Promise<DocGenProgressResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/progress`);
  if (!res.ok) throw new Error(await res.text().catch(() => "Failed to fetch doc progress"));
  return res.json();
}

export async function generateMasterDocs(repoId: string, force: boolean = false): Promise<MasterDocsResponse> {
  const qs = force ? "?force=true" : "";
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/master${qs}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Master documentation generation failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export async function fetchDocSections(repoId: string): Promise<{
  repo_id: string;
  has_docs: boolean;
  is_complete?: boolean;
  master_content: string;
  readme_content?: string;
  sections: DocSectionItem[];
  validation_summary?: DocValidationSummary;
}> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/sections`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function triggerDocExport(repoId: string): Promise<{ repo_id: string; status: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/export`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Doc export failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export async function fetchDocExportStatus(repoId: string): Promise<{
  repo_id: string;
  status: string;
  result?: { total_symbols: number; documented_symbols: number; doc_files: { path: string; size: number }[]; errors: string[] };
  error?: string;
}> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/export/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function getDocDownloadUrl(repoId: string): string {
  return `${API_BASE}/repos/${repoId}/docs/download/zip`;
}

export function getFormatDownloadUrl(repoId: string, format: "pdf" | "md" | "zip", allowDraft: boolean = false): string {
  const qs = allowDraft ? "?allow_draft=true" : "";
  return `${API_BASE}/repos/${repoId}/docs/download/${format}${qs}`;
}

export async function commitDocsToRepo(repoId: string): Promise<CommitDocsResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/docs/commit-to-repo`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to commit documentation to repository");
  }
  return res.json();
}

// ── Error Reports (Issues tab) ────────────────────────────────────────────────

export async function fetchErrorReports(
  repoId: string,
  severity?: string,
  fixStatus?: string,
): Promise<ErrorReportsResponse> {
  const params = new URLSearchParams();
  if (severity) params.set("severity", severity);
  if (fixStatus) params.set("fix_status", fixStatus);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/errors${qs}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateErrorFix(
  repoId: string,
  errorId: string,
): Promise<GenerateErrorFixResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/errors/${errorId}/generate-fix`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Generate fix failed");
  }
  const data = await res.json();
  notifyQuotaUpdated();
  return data;
}

export async function applyErrorFix(
  repoId: string,
  errorId: string,
): Promise<ApplyErrorFixResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/errors/${errorId}/apply-fix`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Apply fix failed");
  }
  return res.json();
}

export async function rejectErrorFix(
  repoId: string,
  errorId: string,
): Promise<{ error_id: string; fix_status: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/errors/${errorId}/reject`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Reject failed");
  }
  return res.json();
}

export async function regenerateErrorFix(
  repoId: string,
  errorId: string,
): Promise<{ error_id: string; status: string }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/errors/${errorId}/regenerate`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Regenerate failed");
  }
  return res.json();
}

// ── Automation Log ───────────────────────────────────────────────────────────

export async function fetchAutomationLog(repoId: string): Promise<AutomationLogResponse> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/automation-log`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch automation log");
  }
  return res.json();
}

// ── Conversations (7-day scoped Copilot sessions) ───────────────────────────

export async function fetchConversations(repoId: string): Promise<{ conversations: any[] }> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/conversations`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createConversation(
  repoId: string,
  title = "New Conversation",
  modelProvider?: string,
  modelName?: string,
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, model_provider: modelProvider, model_name: modelName }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchConversation(repoId: string, convId: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/conversations/${convId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function addConversationMessage(
  repoId: string,
  convId: string,
  role: string,
  content: string,
  citations?: any[],
  errorReports?: any[],
): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/conversations/${convId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, content, citations, error_reports: errorReports }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteConversation(repoId: string, convId: string): Promise<any> {
  const res = await apiFetch(`${API_BASE}/repos/${repoId}/conversations/${convId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
