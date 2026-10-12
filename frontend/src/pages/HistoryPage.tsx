import { useState, useEffect, type FC } from "react";
import { useNavigate } from "react-router-dom";
import { History, FolderGit2, Calendar, FileCode, CheckCircle2, AlertCircle, Clock, Trash2, ArrowUpRight, Plus, RefreshCw, GitCommit } from "lucide-react";
import { fetchRepos, deleteRepo } from "../api";
import type { RepoSummary, User } from "../types";
import Navigation from "../components/Navigation";
import ConnectRepoModal from "../components/ConnectRepoModal";

interface HistoryPageProps {
  user: User;
  onLogout: () => void;
}

export const HistoryPage: FC<HistoryPageProps> = ({ user, onLogout }) => {
  const navigate = useNavigate();
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadRepos = async () => {
    setLoading(true);
    try {
      const list = await fetchRepos();
      setRepos(list);
    } catch (err) {
      console.error("Failed to load repo history:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRepos();
  }, []);

  const handleDelete = async (repo: RepoSummary) => {
    if (!confirm(`Are you sure you want to remove '${repo.name}' and all its indexed data?`)) return;
    setDeletingId(repo.repo_id);
    try {
      await deleteRepo(repo.repo_id);
      setRepos((prev) => prev.filter((r) => r.repo_id !== repo.repo_id));
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-[#161718] text-[#cccccc] font-sans overflow-hidden">
      <Navigation user={user} onLogout={onLogout} />

      <main className="flex-1 overflow-y-auto max-w-6xl mx-auto w-full p-8 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between pb-6 border-b border-[#2a2b2e] shrink-0 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <History size={26} className="text-purple-400" />
              <span>Repository & Project History</span>
            </h1>
            <p className="text-xs text-[#a1a1aa] mt-1">
              All codebases ingested, indexed in FAISS, and analyzed by CodeBrain AI.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={loadRepos}
              className="p-2 bg-[#202124] hover:bg-[#26272a] text-[#a1a1aa] hover:text-white rounded-xl transition-colors border border-[#2a2b2e] cursor-pointer"
              title="Refresh history"
            >
              <RefreshCw size={16} className={loading ? "animate-spin text-purple-400" : ""} />
            </button>
            <button
              onClick={() => setShowConnectModal(true)}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-purple-900/30 flex items-center gap-2 transition-all cursor-pointer"
            >
              <Plus size={16} />
              <span>Ingest New Repo</span>
            </button>
          </div>
        </div>

        {/* List of Repos */}
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-3">
            <RefreshCw className="animate-spin text-purple-400" size={32} />
            <p className="text-sm text-[#a1a1aa]">Loading project history...</p>
          </div>
        ) : repos.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-12 bg-[#18191b] border border-[#2a2b2e] rounded-2xl">
            <FolderGit2 size={54} className="text-[#52525b] mb-4" />
            <h3 className="text-lg font-bold text-white mb-1">No repositories indexed yet</h3>
            <p className="text-xs text-[#a1a1aa] max-w-sm mb-6">
              Connect a GitHub repository or upload a zip archive to begin analyzing code, fixing bugs, and generating master docs.
            </p>
            <button
              onClick={() => setShowConnectModal(true)}
              className="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-xs font-medium transition-all shadow-md flex items-center gap-2 cursor-pointer"
            >
              <Plus size={16} />
              <span>Connect Repository</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {repos.map((repo) => {
              const statusColor =
                repo.pipeline_status === "DONE"
                  ? "text-emerald-400 bg-emerald-950/80 border-emerald-800"
                  : repo.pipeline_status === "FAILED"
                  ? "text-red-400 bg-red-950/80 border-red-800"
                  : "text-purple-400 bg-purple-950/80 border-purple-800";

              return (
                <div
                  key={repo.repo_id}
                  className="bg-[#18191b] border border-[#2a2b2e] hover:border-purple-500/50 rounded-2xl p-5 transition-all shadow-sm flex flex-col justify-between group"
                >
                  <div>
                    {/* Title + Status */}
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="p-2 bg-[#161718] rounded-xl border border-[#2a2b2e] text-purple-400 group-hover:text-white transition-colors">
                          <FolderGit2 size={18} />
                        </div>
                        <div className="min-w-0">
                          <h3 className="text-sm font-bold text-white truncate group-hover:text-purple-400 transition-colors">
                            {repo.name}
                          </h3>
                          <span className="text-[11px] text-[#71717a] uppercase tracking-wider font-mono">
                            {repo.source_type}
                          </span>
                        </div>
                      </div>

                      <span
                        className={`text-[11px] px-2.5 py-1 rounded-full border font-mono font-medium flex items-center gap-1 ${statusColor}`}
                      >
                        {repo.pipeline_status === "DONE" ? (
                          <CheckCircle2 size={12} />
                        ) : repo.pipeline_status === "FAILED" ? (
                          <AlertCircle size={12} />
                        ) : (
                          <Clock size={12} className="animate-spin" />
                        )}
                        <span>{repo.pipeline_status || "PENDING"}</span>
                      </span>
                    </div>

                    {/* Meta info & Last Activity */}
                    <div className="space-y-2.5 my-4">
                      <div className="grid grid-cols-2 gap-2 text-xs text-[#a1a1aa] bg-[#161718] p-3 rounded-xl border border-[#2a2b2e]">
                        <div className="flex items-center gap-1.5">
                          <FileCode size={14} className="text-[#71717a]" />
                          <span>{repo.file_count ?? 0} files indexed</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Calendar size={14} className="text-[#71717a]" />
                          <span>
                            {repo.created_at ? new Date(repo.created_at).toLocaleDateString() : "Recently"}
                          </span>
                        </div>
                      </div>

                      {/* Last Worked On / Activity summary */}
                      <div className="bg-[#161718] p-3 rounded-xl border border-[#2a2b2e] text-xs space-y-1.5">
                        <div className="flex items-center justify-between text-[#a1a1aa]">
                          <span className="font-semibold text-[#f3f4f6] flex items-center gap-1">
                            <Clock size={12} className="text-purple-400" />
                            <span>Last Activity</span>
                          </span>
                          <span className="text-[11px] font-mono text-[#71717a]">
                            {repo.last_activity_at ? new Date(repo.last_activity_at).toLocaleDateString() : "Initial index"}
                          </span>
                        </div>
                        <p className="text-[#a1a1aa] text-[11px] truncate">
                          {repo.last_activity_summary || "Repository indexed and ready in workspace"}
                        </p>
                      </div>

                      {/* Git Commit status */}
                      {repo.last_commit_sha && (
                        <div className="bg-[#161718] px-3 py-2 rounded-xl border border-[#2a2b2e] text-[11px] flex items-center justify-between">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <GitCommit size={13} className="text-purple-400 shrink-0" />
                            <span className="font-mono text-purple-300 shrink-0">{repo.last_commit_sha}</span>
                            <span className="text-[#a1a1aa] truncate">({repo.last_commit_message || "commit"})</span>
                          </div>
                          <span className="font-mono text-[#71717a] shrink-0 ml-2">[{repo.last_commit_branch || "main"}]</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="pt-3 border-t border-[#2a2b2e] flex items-center justify-between gap-2">
                    <button
                      onClick={() => handleDelete(repo)}
                      disabled={deletingId === repo.repo_id}
                      className="p-2 text-[#71717a] hover:text-red-400 hover:bg-[#202124] rounded-lg transition-colors text-xs flex items-center gap-1 cursor-pointer"
                      title="Delete repository and remove from index"
                    >
                      <Trash2 size={14} />
                      <span className="text-[11px]">Delete</span>
                    </button>

                    <button
                      onClick={() => navigate(`/dashboard?repoId=${repo.repo_id}`)}
                      className="px-4 py-2 bg-[#202124] hover:bg-purple-600 hover:text-white text-[#f3f4f6] rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5 border border-[#2a2b2e] cursor-pointer"
                    >
                      <span>Resume Workspace</span>
                      <ArrowUpRight size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {showConnectModal && (
        <ConnectRepoModal
          onClose={() => setShowConnectModal(false)}
          onRepoAdded={() => {
            setShowConnectModal(false);
            loadRepos();
          }}
        />
      )}
    </div>
  );
};

export default HistoryPage;
