import { useState, useRef, useEffect } from "react";
import type { RepoSummary, GitHubRepoItem } from "../types";
import { uploadRepo, connectGithubRepo, fetchGitHubUserRepos, API_BASE } from "../api";
import { Upload, Lock, Globe, Search, RefreshCw, ExternalLink, ArrowRight } from "lucide-react";

const Github = ({ size = 16, className = "" }: { size?: number; className?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);

interface Props {
  onRepoAdded: (repo: RepoSummary) => void;
  onClose: () => void;
}

export default function ConnectRepoModal({ onRepoAdded, onClose }: Props) {
  const [tab, setTab] = useState<"upload" | "github">("upload");
  const [githubUrl, setGithubUrl] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // GitHub user repo state
  const [ghLoading, setGhLoading] = useState(false);
  const [ghConnected, setGhConnected] = useState<boolean | null>(null);
  const [userRepos, setUserRepos] = useState<GitHubRepoItem[]>([]);
  const [repoFilter, setRepoFilter] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepoItem | null>(null);

  // Load GitHub repos when switching to github tab
  useEffect(() => {
    if (tab === "github" && ghConnected === null) {
      loadUserRepos();
    }
  }, [tab]);

  const loadUserRepos = async () => {
    setGhLoading(true);
    setError(null);
    try {
      const data = await fetchGitHubUserRepos();
      setGhConnected(data.connected);
      setUserRepos(data.repos || []);
    } catch (e: unknown) {
      setGhConnected(false);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGhLoading(false);
    }
  };

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Please select a .zip file.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const repo = await uploadRepo(file);
      onRepoAdded(repo);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleGithubClone = async (urlToClone?: string) => {
    const targetUrl = urlToClone || githubUrl.trim();
    if (!targetUrl) {
      setError("Please enter or select a GitHub repository URL.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const repo = await connectGithubRepo(targetUrl, accessToken || undefined);
      onRepoAdded(repo);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const filteredRepos = userRepos.filter((r) =>
    r.full_name.toLowerCase().includes(repoFilter.toLowerCase()) ||
    (r.description && r.description.toLowerCase().includes(repoFilter.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-[#1e1e1e] border border-[#3c3c3c] rounded-2xl shadow-2xl w-full max-w-xl overflow-hidden flex flex-col max-h-[88vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#2d2d2d] bg-[#252526]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
              {tab === "upload" ? <Upload size={18} /> : <Github size={18} />}
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Import Codebase</h2>
              <p className="text-xs text-gray-400">Add a project for semantic analysis &amp; documentation</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors text-2xl leading-none p-1 rounded-md hover:bg-[#333333]"
          >
            &times;
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#2d2d2d] bg-[#1a1a1a]">
          <button
            onClick={() => { setTab("upload"); setError(null); }}
            className={`flex-1 py-3 text-xs font-semibold uppercase tracking-wider transition-colors flex items-center justify-center gap-2 ${
              tab === "upload"
                ? "text-blue-400 border-b-2 border-blue-500 bg-[#1e1e1e]"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <Upload size={14} /> ZIP Archive
          </button>
          <button
            onClick={() => { setTab("github"); setError(null); }}
            className={`flex-1 py-3 text-xs font-semibold uppercase tracking-wider transition-colors flex items-center justify-center gap-2 ${
              tab === "github"
                ? "text-purple-400 border-b-2 border-purple-500 bg-[#1e1e1e]"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <Github size={14} /> GitHub Repositories
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-4 flex-1">
          {tab === "upload" ? (
            <div className="space-y-4">
              <p className="text-xs text-gray-400 leading-relaxed">
                Upload a <span className="font-mono text-gray-200 bg-[#2d2d2d] px-1.5 py-0.5 rounded">.zip</span> archive containing your source code.
                CodeBrain recursively indexes AST symbols, functions, and architecture.
              </p>
              <label className="flex flex-col items-center justify-center w-full h-36 border-2 border-dashed border-[#3c3c3c] rounded-xl cursor-pointer hover:border-blue-500 hover:bg-blue-950/10 transition-all bg-[#252526]/50 group">
                <Upload className="w-8 h-8 text-gray-500 group-hover:text-blue-400 mb-2 transition-colors" />
                <span className="text-xs text-gray-300 font-medium group-hover:text-white">
                  Click to browse or drop ZIP file
                </span>
                <span className="text-[11px] text-gray-500 mt-1">Accepts standard ZIP files up to 50MB</span>
                <input ref={fileRef} type="file" accept=".zip" className="hidden" />
              </label>
              <button
                id="upload-repo-btn"
                onClick={handleUpload}
                disabled={loading}
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:opacity-50 text-white rounded-lg font-medium transition-all text-xs flex items-center justify-center gap-2 shadow-md cursor-pointer"
              >
                {loading ? (
                  <>
                    <RefreshCw size={14} className="animate-spin" /> Ingesting &amp; Parsing AST...
                  </>
                ) : (
                  <>
                    Upload &amp; Analyze Codebase <ArrowRight size={14} />
                  </>
                )}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* GitHub OAuth Connection Status Banner */}
              {ghConnected === false && (
                <div className="p-4 rounded-xl bg-purple-950/20 border border-purple-800/40 flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-xs font-semibold text-purple-200 flex items-center gap-1.5">
                      <Github size={14} /> Connect your GitHub Account
                    </h4>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      Authorize CodeBrain to list your public and private repositories automatically.
                    </p>
                  </div>
                  <a
                    href={`${API_BASE}/auth/github/login`}
                    className="px-3.5 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-xs font-medium transition-colors shrink-0 flex items-center gap-1.5 shadow"
                  >
                    Connect <ExternalLink size={12} />
                  </a>
                </div>
              )}

              {/* Connected Repositories Selector */}
              {ghConnected && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-medium text-gray-300 flex items-center gap-1.5">
                      <span>Your GitHub Repositories</span>
                      <span className="text-[10px] bg-purple-900/50 text-purple-300 px-1.5 py-0.5 rounded-full font-mono">
                        {userRepos.length}
                      </span>
                    </label>
                    <button
                      onClick={loadUserRepos}
                      disabled={ghLoading}
                      className="text-[11px] text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                    >
                      <RefreshCw size={11} className={ghLoading ? "animate-spin" : ""} /> Refresh
                    </button>
                  </div>

                  {/* Filter Search */}
                  <div className="relative">
                    <Search size={13} className="absolute left-2.5 top-2.5 text-gray-500" />
                    <input
                      type="text"
                      value={repoFilter}
                      onChange={(e) => setRepoFilter(e.target.value)}
                      placeholder="Search repositories..."
                      className="w-full bg-[#252526] border border-[#3c3c3c] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
                    />
                  </div>

                  {/* Repo List View */}
                  <div className="max-h-48 overflow-y-auto border border-[#2d2d2d] rounded-lg divide-y divide-[#2d2d2d] bg-[#1a1a1a]">
                    {ghLoading ? (
                      <div className="p-4 text-center text-xs text-gray-400 flex items-center justify-center gap-2">
                        <RefreshCw size={13} className="animate-spin text-purple-400" /> Loading your GitHub repositories...
                      </div>
                    ) : filteredRepos.length === 0 ? (
                      <div className="p-4 text-center text-xs text-gray-500">
                        {repoFilter ? "No repositories matching filter." : "No repositories found."}
                      </div>
                    ) : (
                      filteredRepos.map((r) => (
                        <div
                          key={r.id}
                          onClick={() => {
                            setSelectedRepo(r);
                            setGithubUrl(r.html_url);
                          }}
                          className={`p-2.5 hover:bg-[#252526] cursor-pointer flex items-center justify-between transition-colors ${
                            selectedRepo?.id === r.id ? "bg-purple-950/30 border-l-2 border-purple-500" : ""
                          }`}
                        >
                          <div className="min-w-0 pr-2">
                            <div className="flex items-center gap-1.5">
                              {r.private ? (
                                <Lock size={12} className="text-amber-400 shrink-0" />
                              ) : (
                                <Globe size={12} className="text-blue-400 shrink-0" />
                              )}
                              <span className="text-xs font-medium text-white truncate">{r.full_name}</span>
                            </div>
                            {r.description && (
                              <p className="text-[11px] text-gray-400 truncate mt-0.5">{r.description}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {r.language && (
                              <span className="text-[10px] text-gray-400 font-mono bg-[#2d2d2d] px-1.5 py-0.5 rounded">
                                {r.language}
                              </span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleGithubClone(r.html_url);
                              }}
                              disabled={loading}
                              className="px-2 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded text-[10px] font-medium transition-colors"
                            >
                              Import
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* Manual URL Input Option */}
              <div className="space-y-2 pt-2 border-t border-[#2d2d2d]">
                <label className="text-xs font-medium text-gray-300 block">
                  Or Clone Any GitHub URL
                </label>
                <input
                  id="github-url-input"
                  type="url"
                  value={githubUrl}
                  onChange={(e) => {
                    setGithubUrl(e.target.value);
                    setSelectedRepo(null);
                  }}
                  placeholder="https://github.com/owner/repository"
                  className="w-full bg-[#252526] border border-[#3c3c3c] rounded-lg px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 transition-colors"
                />
                <input
                  id="github-token-input"
                  type="password"
                  value={accessToken}
                  onChange={(e) => setAccessToken(e.target.value)}
                  placeholder="Personal Access Token (optional if already connected)"
                  className="w-full bg-[#252526] border border-[#3c3c3c] rounded-lg px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 transition-colors"
                />
                <button
                  id="clone-repo-btn"
                  onClick={() => handleGithubClone()}
                  disabled={loading || !githubUrl.trim()}
                  className="w-full py-2.5 bg-purple-600 hover:bg-purple-500 active:bg-purple-700 disabled:opacity-50 text-white rounded-lg font-medium transition-all text-xs flex items-center justify-center gap-2 shadow-md cursor-pointer"
                >
                  {loading ? (
                    <>
                      <RefreshCw size={14} className="animate-spin" /> Cloning &amp; Parsing Repository...
                    </>
                  ) : (
                    <>
                      Clone &amp; Ingest Repository <ArrowRight size={14} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-950/40 border border-red-800 rounded-lg p-3 leading-relaxed">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
