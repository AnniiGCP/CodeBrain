import type { FC } from "react";
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  FolderPlus,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Trash2,
  GitPullRequest,
  AlertCircle,
  AlertTriangle,
  Search as SearchIcon,
  Wand2,
  BookOpen,
  FileText,
  GitBranch,
  GitCommit,
  ShieldAlert,
  History as HistoryIcon,
} from "lucide-react";
import type {
  RepoSummary,
  FileNode,
  ErrorReport,
  GitStatusResponse,
  GitStatusFile,
  GitCommitItem,
} from "../types";
import { searchRepo, fetchGitStatus, fetchGitDiff, createGitCommit, fetchGitHistory } from "../api";
import FileTree from "./FileTree";

interface PrimarySidebarProps {
  activeTab: "explorer" | "search" | "git" | "issues" | "docs" | null;
  repos: RepoSummary[];
  activeRepo: RepoSummary | null;
  onSelectRepo: (repo: RepoSummary) => void;
  onDeleteRepo: (repo: RepoSummary) => void;
  onOpenConnectModal: () => void;
  onRetryPipeline: () => void;
  fileTree: FileNode[];
  onSelectFile: (path: string, line?: number) => void;
  errors: ErrorReport[];
  onTriggerFix: (error: ErrorReport) => void;
  docSections: any[];
  masterContent?: string;
  onSelectDocSection: (section: any) => void;
  onOpenPR: () => void;
  onSelectDiff?: (diff: string, title: string) => void;
}

const PrimarySidebar: FC<PrimarySidebarProps> = ({
  activeTab,
  repos,
  activeRepo,
  onSelectRepo,
  onDeleteRepo,
  onOpenConnectModal,
  onRetryPipeline,
  fileTree,
  onSelectFile,
  errors,
  onTriggerFix,
  docSections,
  masterContent,
  onSelectDocSection,
  onOpenPR,
  onSelectDiff,
}) => {
  if (!activeTab) return null;

  // Search view state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  const handleSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeRepo || !searchQuery.trim()) return;
    setSearching(true);
    setSearchError("");
    try {
      const res = await searchRepo(activeRepo.repo_id, searchQuery.trim(), 12);
      setSearchResults(res.results || []);
    } catch (err: any) {
      setSearchError(err.message || "Search failed.");
    } finally {
      setSearching(false);
    }
  };

  // ── Source Control View state ──────────────────────────────────────────────
  const [gitStatus, setGitStatus] = useState<GitStatusResponse | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [selectedGitFiles, setSelectedGitFiles] = useState<Set<string>>(new Set());
  const [commitMessage, setCommitMessage] = useState("");
  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);
  const [commitSuccess, setCommitSuccess] = useState<string | null>(null);
  const [gitHistory, setGitHistory] = useState<GitCommitItem[]>([]);
  const [gitSubTab, setGitSubTab] = useState<"changes" | "history">("changes");

  const refreshGitState = useCallback(async () => {
    if (!activeRepo) return;
    setGitLoading(true);
    setCommitError(null);
    try {
      const [statusRes, historyRes] = await Promise.all([
        fetchGitStatus(activeRepo.repo_id),
        fetchGitHistory(activeRepo.repo_id).catch(() => ({ repo_id: activeRepo.repo_id, commits: [] })),
      ]);
      setGitStatus(statusRes);
      setGitHistory(historyRes.commits || []);
      // Automatically select all changed files by default
      setSelectedGitFiles(new Set(statusRes.files.map((f) => f.path)));
    } catch (err: any) {
      setCommitError(err.message || "Failed to load git status");
    } finally {
      setGitLoading(false);
    }
  }, [activeRepo]);

  useEffect(() => {
    if (activeTab === "git" && activeRepo) {
      refreshGitState();
    }
  }, [activeTab, activeRepo, refreshGitState]);

  const handleToggleFile = (filePath: string) => {
    setSelectedGitFiles((prev) => {
      const next = new Set(prev);
      if (next.has(filePath)) next.delete(filePath);
      else next.add(filePath);
      return next;
    });
  };

  const handleToggleAllFiles = () => {
    if (!gitStatus) return;
    if (selectedGitFiles.size === gitStatus.files.length) {
      setSelectedGitFiles(new Set());
    } else {
      setSelectedGitFiles(new Set(gitStatus.files.map((f) => f.path)));
    }
  };

  const handleFileDiffClick = async (file: GitStatusFile) => {
    if (!activeRepo) return;
    try {
      const res = await fetchGitDiff(activeRepo.repo_id, file.path);
      onSelectDiff?.(res.diff, file.path);
    } catch (err: any) {
      onSelectDiff?.(`// Error loading diff: ${err.message}`, file.path);
    }
  };

  const hasSensitiveFileSelected = useMemo(() => {
    const sensitive = [".env", "id_rsa", "id_ed25519", ".pem", ".key"];
    return Array.from(selectedGitFiles).some((p) =>
      sensitive.some((s) => p.toLowerCase().includes(s))
    );
  }, [selectedGitFiles]);

  const handleCommitSubmit = async () => {
    if (!activeRepo) return;
    if (!commitMessage.trim()) {
      setCommitError("Commit message cannot be empty.");
      return;
    }
    if (selectedGitFiles.size === 0) {
      setCommitError("Select at least one file to commit.");
      return;
    }
    if (hasSensitiveFileSelected) {
      setCommitError("Security warning: Cannot commit sensitive or secret files (.env, keys). Deselect them before committing.");
      return;
    }
    setCommitting(true);
    setCommitError(null);
    setCommitSuccess(null);
    try {
      const res = await createGitCommit(activeRepo.repo_id, {
        files: Array.from(selectedGitFiles),
        message: commitMessage.trim(),
      });
      setCommitSuccess(`Committed [${res.commit_sha}]: "${res.message}"`);
      setCommitMessage("");
      await refreshGitState();
    } catch (err: any) {
      setCommitError(err.message || "Commit failed.");
    } finally {
      setCommitting(false);
    }
  };

  // Group errors by file
  const errorsByFile: Record<string, ErrorReport[]> = {};
  for (const err of errors) {
    const file = err.file_path || "General";
    if (!errorsByFile[file]) errorsByFile[file] = [];
    errorsByFile[file].push(err);
  }

  // Expanded files in problems tree
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});
  const toggleFileExpand = (file: string) => {
    setExpandedFiles((prev) => ({ ...prev, [file]: !prev[file] }));
  };

  // File tree wrapper
  const rootNode: FileNode = {
    name: activeRepo?.name || "root",
    type: "directory",
    children: fileTree,
  };

  return (
    <div className="h-full w-full bg-[#0c0d0e] text-[#cccccc] flex flex-col select-none overflow-hidden border-r border-[#1e1f22]">
      {/* ── 1. EXPLORER SIDEBAR ─────────────────────────────────────────── */}
      {activeTab === "explorer" && (
        <div className="flex flex-col h-full bg-[#0c0d0e]">
          {/* Header */}
          <div className="px-4 py-2.5 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-[#858585] border-b border-[#1e1f22] bg-[#0c0d0e]">
            <span>Explorer</span>
            <button
              onClick={onOpenConnectModal}
              title="Connect New Repository"
              className="p-1 hover:text-white hover:bg-[#18191d] rounded transition-colors text-[#cccccc]"
            >
              <FolderPlus size={16} />
            </button>
          </div>

          {/* Connected Repositories Selector */}
          <div className="p-3 border-b border-[#1e1f22] bg-[#0c0d0e]">
            <div className="text-[11px] font-semibold text-[#858585] uppercase mb-1.5 flex items-center justify-between">
              <span>Repository</span>
              <span className="text-[10px] lowercase text-purple-400">{repos.length} loaded</span>
            </div>
            {repos.length === 0 ? (
              <button
                onClick={onOpenConnectModal}
                className="w-full py-1.5 px-2.5 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded font-medium flex items-center justify-center gap-1.5 transition-colors"
              >
                <FolderPlus size={14} /> Connect Repo
              </button>
            ) : (
              <div className="flex flex-col gap-1.5">
                <select
                  value={activeRepo?.repo_id || ""}
                  onChange={(e) => {
                    const r = repos.find((repo) => repo.repo_id === e.target.value);
                    if (r) onSelectRepo(r);
                  }}
                  className="w-full bg-[#0c0d0e] text-white text-xs px-2.5 py-1.5 rounded border border-[#1e1f22] focus:outline-none focus:border-purple-500"
                >
                  {repos.map((r) => (
                    <option key={r.repo_id} value={r.repo_id}>
                      {r.source_type === "github" ? "🐙" : "📦"} {r.name}
                    </option>
                  ))}
                </select>

                {/* Active Repo Actions & Pipeline State */}
                {activeRepo && (
                  <div className="flex items-center justify-between text-[11px] text-[#858585] px-0.5">
                    <span className="flex items-center gap-1">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          activeRepo.pipeline_status === "DONE"
                            ? "bg-green-500"
                            : activeRepo.pipeline_status === "FAILED"
                            ? "bg-red-500"
                            : "bg-yellow-500 animate-pulse"
                        }`}
                      />
                      {activeRepo.pipeline_status || "PENDING"}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={onRetryPipeline}
                        title="Re-run pipeline"
                        className="hover:text-white"
                      >
                        <RefreshCw size={12} />
                      </button>
                      <button
                        onClick={() => onDeleteRepo(activeRepo)}
                        title="Delete repository"
                        className="hover:text-red-400"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* File Tree */}
          <div className="flex-1 overflow-y-auto p-2">
            <div className="text-[11px] font-semibold text-[#858585] uppercase px-2 py-1 mb-1">
              Files ({fileTree.length})
            </div>
            {fileTree.length > 0 ? (
              <FileTree tree={rootNode} onSelectFile={(path) => onSelectFile(path)} />
            ) : (
              <div className="p-4 text-center text-xs text-[#858585]">
                {activeRepo ? "No files indexed yet." : "Connect a repository to explore files."}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 2. SEARCH SIDEBAR ─────────────────────────────────────────── */}
      {activeTab === "search" && (
        <div className="flex flex-col h-full bg-[#0c0d0e]">
          <div className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-[#858585] border-b border-[#1e1f22] bg-[#0c0d0e]">
            Semantic Code Search
          </div>
          <div className="p-3 border-b border-[#1e1f22] bg-[#0c0d0e]">
            <form onSubmit={handleSearchSubmit} className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search symbols or functions…"
                className="w-full bg-[#0c0d0e] text-white text-xs pl-8 pr-3 py-1.5 rounded border border-[#1e1f22] focus:outline-none focus:border-purple-500"
              />
              <SearchIcon size={14} className="absolute left-2.5 top-2 text-[#858585]" />
            </form>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {searching && (
              <div className="p-4 text-center text-xs text-[#858585] animate-pulse">
                Searching vector index…
              </div>
            )}
            {searchError && (
              <div className="p-3 text-xs text-red-400 bg-red-950/30 rounded border border-red-900/50">
                {searchError}
              </div>
            )}
            {!searching && searchResults.length > 0 && (
              <div className="space-y-1">
                <div className="text-[11px] text-[#858585] uppercase px-2 py-1">
                  {searchResults.length} Results Found
                </div>
                {searchResults.map((r, idx) => (
                  <div
                    key={idx}
                    onClick={() => onSelectFile(r.file_path, r.start_line || 1)}
                    className="p-2 hover:bg-[#18191d] rounded cursor-pointer border border-transparent hover:border-[#1e1f22] transition-colors"
                  >
                    <div className="flex items-center justify-between text-xs font-medium text-white mb-0.5">
                      <span className="truncate">{r.name || r.symbol_type}</span>
                      <span className="text-[10px] text-purple-400 font-mono">
                        {Math.round((r.score || 0) * 100)}% match
                      </span>
                    </div>
                    <p className="text-[11px] text-[#858585] truncate font-mono">
                      {r.file_path}:{r.start_line || 1}
                    </p>
                    {r.source_code && (
                      <pre className="text-[10px] text-gray-400 bg-[#0c0d0e] p-1.5 rounded mt-1.5 overflow-x-hidden line-clamp-2 font-mono border border-[#1e1f22]">
                        {r.source_code.trim()}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!searching && searchResults.length === 0 && !searchError && (
              <div className="p-4 text-center text-xs text-[#858585]">
                {activeRepo ? "Enter a query to search embedded symbols." : "Connect a repo first."}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 3. SOURCE CONTROL SIDEBAR ───────────────────────────────────── */}
      {activeTab === "git" && (
        <div className="flex flex-col h-full bg-[#0c0d0e] text-[#cccccc]">
          {/* Header */}
          <div className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-[#858585] border-b border-[#1e1f22] bg-[#0c0d0e] flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-white">
              <GitBranch size={13} className="text-purple-400" />
              <span>Source Control</span>
            </span>
            <div className="flex items-center gap-1">
              {onOpenPR && (
                <button
                  onClick={onOpenPR}
                  title="Open Pull Request"
                  className="p-1 hover:text-white hover:bg-[#18191d] rounded transition-colors text-[#cccccc]"
                >
                  <GitPullRequest size={13} />
                </button>
              )}
              <button
                onClick={refreshGitState}
                title="Refresh Status"
                className="p-1 hover:text-white hover:bg-[#18191d] rounded transition-colors text-[#cccccc]"
              >
                <RefreshCw size={13} className={gitLoading ? "animate-spin text-purple-400" : ""} />
              </button>
            </div>
          </div>

          {/* Repo & Branch info */}
          <div className="p-3 border-b border-[#1e1f22] bg-[#0c0d0e]">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-white font-medium truncate">
                {activeRepo ? activeRepo.name : "No repository active"}
              </span>
              <span className="text-[10px] bg-[#0c0d0e] border border-[#1e1f22] px-1.5 py-0.5 rounded text-purple-400 font-mono">
                {gitStatus?.branch || "main"}
              </span>
            </div>

            {/* Sub-tabs: Changes vs History */}
            <div className="flex items-center gap-1 mt-2 border-b border-[#1e1f22] pb-1 text-xs">
              <button
                onClick={() => setGitSubTab("changes")}
                className={`px-2 py-1 rounded transition-colors flex items-center gap-1 font-medium ${
                  gitSubTab === "changes"
                    ? "bg-[#141518] text-white border border-[#1e1f22]"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                <span>Changes</span>
                <span className="text-[10px] bg-[#0c0d0e] border border-[#1e1f22] px-1.5 rounded-full font-mono">
                  {gitStatus?.files.length ?? 0}
                </span>
              </button>
              <button
                onClick={() => setGitSubTab("history")}
                className={`px-2 py-1 rounded transition-colors flex items-center gap-1 font-medium ${
                  gitSubTab === "history"
                    ? "bg-[#141518] text-white border border-[#1e1f22]"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                <HistoryIcon size={12} />
                <span>History</span>
                <span className="text-[10px] bg-[#0c0d0e] border border-[#1e1f22] px-1.5 rounded-full font-mono">
                  {gitHistory.length}
                </span>
              </button>
            </div>
          </div>

          {/* Content Body */}
          {gitSubTab === "changes" ? (
            <div className="flex-1 flex flex-col overflow-hidden bg-[#0c0d0e]">
              {/* Commit input box */}
              <div className="p-3 border-b border-[#1e1f22] flex flex-col gap-2 bg-[#0c0d0e]">
                <textarea
                  value={commitMessage}
                  onChange={(e) => setCommitMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                      e.preventDefault();
                      handleCommitSubmit();
                    }
                  }}
                  placeholder="Commit message (Ctrl+Enter to commit)"
                  rows={2}
                  className="w-full bg-[#0c0d0e] text-white text-xs p-2 rounded border border-[#1e1f22] focus:outline-none focus:border-purple-500 resize-none font-sans"
                />

                {hasSensitiveFileSelected && (
                  <div className="p-1.5 bg-red-950/60 border border-red-800 rounded text-[11px] text-red-300 flex items-center gap-1">
                    <ShieldAlert size={13} className="shrink-0 text-red-400" />
                    <span>Secret file selected! Exclude .env and keys.</span>
                  </div>
                )}

                {commitError && (
                  <div className="p-1.5 bg-red-950/60 border border-red-800 rounded text-[11px] text-red-300">
                    {commitError}
                  </div>
                )}

                {commitSuccess && (
                  <div className="p-1.5 bg-green-950/60 border border-green-800 rounded text-[11px] text-green-300">
                    {commitSuccess}
                  </div>
                )}

                <button
                  onClick={handleCommitSubmit}
                  disabled={committing || !activeRepo || !commitMessage.trim() || selectedGitFiles.size === 0 || hasSensitiveFileSelected}
                  className="w-full py-1.5 px-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors shadow-sm"
                >
                  <GitCommit size={14} className={committing ? "animate-spin" : ""} />
                  <span>{committing ? "Committing..." : `Commit Changes (${selectedGitFiles.size})`}</span>
                </button>
              </div>

              {/* Changed files list */}
              <div className="flex-1 overflow-y-auto p-2 bg-[#0c0d0e]">
                <div className="px-2 py-1 flex items-center justify-between text-[11px] font-semibold text-[#858585] uppercase">
                  <span>Files ({gitStatus?.files.length ?? 0})</span>
                  {gitStatus && gitStatus.files.length > 0 && (
                    <button
                      onClick={handleToggleAllFiles}
                      className="text-[10px] text-purple-400 hover:underline normal-case font-normal"
                    >
                      {selectedGitFiles.size === gitStatus.files.length ? "Deselect All" : "Select All"}
                    </button>
                  )}
                </div>

                {!gitStatus || gitStatus.files.length === 0 ? (
                  <div className="p-6 text-center text-xs text-[#858585]">
                    {activeRepo ? "No working tree changes. Repository clean." : "Connect a repository first."}
                  </div>
                ) : (
                  <div className="space-y-0.5 mt-1">
                    {gitStatus.files.map((file) => {
                      const isSelected = selectedGitFiles.has(file.path);
                      const statusColor =
                        file.status === "M"
                          ? "text-yellow-400"
                          : file.status === "A" || file.status === "?"
                          ? "text-green-400"
                          : file.status === "D"
                          ? "text-red-400"
                          : "text-purple-400";

                      return (
                        <div
                          key={file.path}
                          className="flex items-center gap-2 p-1.5 rounded hover:bg-[#18191d] text-xs transition-colors group cursor-pointer border border-transparent hover:border-[#1e1f22]"
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleFile(file.path)}
                            className="rounded bg-[#0c0d0e] border-[#1e1f22] text-purple-600 focus:ring-0 cursor-pointer"
                          />
                          <div
                            onClick={() => handleFileDiffClick(file)}
                            className="flex-1 min-w-0 flex items-center justify-between gap-1"
                            title={`Click to view diff: ${file.path}`}
                          >
                            <span className="truncate font-mono text-[11px] text-gray-200 group-hover:text-white">
                              {file.path}
                            </span>
                            <span className={`text-[10px] font-mono font-bold shrink-0 ${statusColor}`}>
                              {file.status === "?" ? "U" : file.status}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* History Sub-tab */
            <div className="flex-1 overflow-y-auto p-2 bg-[#0c0d0e]">
              <div className="px-2 py-1 text-[11px] font-semibold text-[#858585] uppercase">
                Commit History ({gitHistory.length})
              </div>
              {gitHistory.length === 0 ? (
                <div className="p-6 text-center text-xs text-[#858585]">
                  No commit history available.
                </div>
              ) : (
                <div className="space-y-2 mt-2">
                  {gitHistory.map((c) => (
                    <div
                      key={c.full_sha}
                      className="p-2 rounded bg-[#0c0d0e] border border-[#1e1f22] text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="font-mono text-purple-400 font-semibold">
                          {c.sha}
                        </span>
                        <span className="text-[10px] text-[#858585]">
                          {new Date(c.date).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="text-white text-xs font-medium leading-tight">
                        {c.message}
                      </p>
                      <p className="text-[10px] text-gray-400 font-mono">
                        by {c.author}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── 4. ISSUES / PROBLEMS TREE ───────────────────────────────────── */}
      {activeTab === "issues" && (
        <div className="flex flex-col h-full bg-[#0c0d0e]">
          <div className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-[#858585] border-b border-[#1e1f22] bg-[#0c0d0e] flex items-center justify-between">
            <span>Problems</span>
            <span className="text-[11px] text-orange-400">{errors.length} Issues</span>
          </div>

          <div className="flex-1 overflow-y-auto p-2 bg-[#0c0d0e]">
            {Object.keys(errorsByFile).length === 0 ? (
              <div className="p-6 text-center text-xs text-[#858585]">
                {activeRepo ? "No problems detected in codebase ✓" : "Connect a repository to scan issues."}
              </div>
            ) : (
              <div className="space-y-1">
                {Object.entries(errorsByFile).map(([filePath, fileErrors]) => {
                  const isExpanded = expandedFiles[filePath] ?? true;
                  return (
                    <div key={filePath} className="border-b border-[#1e1f22]/60 pb-1">
                      {/* File Header */}
                      <button
                        onClick={() => toggleFileExpand(filePath)}
                        className="w-full flex items-center gap-1.5 py-1 px-1.5 hover:bg-[#18191d] rounded text-left text-xs font-medium text-[#cccccc]"
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <span className="truncate flex-1 font-mono text-[11px]">{filePath}</span>
                        <span className="bg-[#0c0d0e] border border-[#1e1f22] text-[10px] text-gray-300 font-bold px-1.5 py-0.2 rounded-full">
                          {fileErrors.length}
                        </span>
                      </button>

                      {/* File Errors List */}
                      {isExpanded && (
                        <div className="pl-4 pr-1 py-1 space-y-1.5">
                          {fileErrors.map((err) => (
                            <div
                              key={err.id}
                              className="p-2 rounded bg-[#0c0d0e] hover:bg-[#18191d] border border-[#1e1f22] text-xs transition-colors"
                            >
                              <div className="flex items-start gap-1.5 justify-between">
                                <div
                                  onClick={() => onSelectFile(err.file_path, err.line || 1)}
                                  className="cursor-pointer flex-1"
                                >
                                  <div className="flex items-center gap-1 text-[11px] font-semibold text-white">
                                    {err.severity === "error" ? (
                                      <AlertCircle size={12} className="text-red-400 shrink-0" />
                                    ) : (
                                      <AlertTriangle size={12} className="text-yellow-400 shrink-0" />
                                    )}
                                    <span>Line {err.line || "?"}</span>
                                    <span className="text-[#858585] font-mono text-[10px]">
                                      [{err.rule_id}]
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-gray-300 mt-1 leading-snug">
                                    {err.message}
                                  </p>
                                </div>
                                <button
                                  onClick={() => onTriggerFix(err)}
                                  title="Generate & Review Fix"
                                  className="px-2 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded text-[11px] font-medium shrink-0 flex items-center gap-1 transition-colors"
                                >
                                  <Wand2 size={12} /> Fix it
                                </button>
                              </div>
                              {err.explanation && (
                                <p className="text-[10px] text-gray-400 mt-1.5 border-t border-[#1e1f22] pt-1 leading-tight line-clamp-2">
                                  💡 {err.explanation}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 5. DOCUMENTATION TREE ───────────────────────────────────────── */}
      {activeTab === "docs" && (
        <div className="flex flex-col h-full bg-[#0c0d0e]">
          <div className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-[#858585] border-b border-[#1e1f22] bg-[#0c0d0e]">
            Documentation Suite
          </div>

          <div className="flex-1 overflow-y-auto p-2 bg-[#0c0d0e]">
            {docSections.length === 0 ? (
              <div className="p-6 text-center text-xs text-[#858585]">
                {activeRepo
                  ? "No doc sections generated yet. Trigger from Command Palette or Docs panel."
                  : "Connect a repository first."}
              </div>
            ) : (
              <div className="space-y-1">
                {/* Canonical Master Document entry */}
                <button
                  onClick={() =>
                    onSelectDocSection({
                      section_number: 0,
                      title: "Master Technical Documentation",
                      filename: "FULL_PROJECT_DOCUMENTATION.md",
                      content:
                        masterContent ||
                        docSections.map((s) => s.content).join("\n\n---\n\n"),
                      status: "fully_generated",
                    })
                  }
                  className="w-full p-2 mb-2 bg-[#0c0d0e] hover:bg-[#18191d] rounded flex items-center justify-between text-left text-xs transition-colors border border-purple-800/50"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText size={14} className="text-purple-400 shrink-0" />
                    <span className="truncate text-purple-200 font-semibold">
                      Master Document (Full Suite)
                    </span>
                  </div>
                  <span className="text-[9px] bg-purple-900/80 text-purple-200 px-1.5 py-0.5 rounded font-mono font-bold">
                    16 SECTIONS
                  </span>
                </button>
                <div className="h-px bg-[#1e1f22] my-1.5" />

                {docSections.map((sec) => (
                  <button
                    key={sec.section_number}
                    onClick={() => onSelectDocSection(sec)}
                    className="w-full p-2 hover:bg-[#18191d] rounded flex items-center justify-between text-left text-xs transition-colors border border-transparent hover:border-[#1e1f22]"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <BookOpen size={14} className="text-purple-400 shrink-0" />
                      <span className="truncate text-[#cccccc] font-medium">
                        {sec.section_number}. {sec.title}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {sec.has_diagram && (
                        <span className="text-[9px] bg-purple-900/60 text-purple-300 px-1 rounded font-bold">
                          Diagram
                        </span>
                      )}
                      <span
                        className={`w-2 h-2 rounded-full ${
                          sec.status === "fully_generated"
                            ? "bg-green-500"
                            : sec.status === "fallback"
                            ? "bg-yellow-500"
                            : "bg-red-500"
                        }`}
                        title={sec.status}
                      />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default PrimarySidebar;
