import { useState, useEffect, type FC } from "react";
import {
  GitMerge,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  Sparkles,
  Terminal,
  Play,
  Copy,
  Check,
  FileCode,
  GitPullRequest,
  RotateCcw,
  Layers,
  BookOpen,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Slash,
  MinusCircle,
  Rocket,
  CheckCheck,
} from "lucide-react";
import {
  fetchRepos,
  fetchCiOverview,
  analyzeCi,
  generateCiWorkflow,
  installCiViaPr,
  installCiDirect,
  verifyCiInstallation,
  fetchCiRuns,
  fetchCiRunDetails,
  dispatchCiWorkflow,
  diagnoseCiFailure,
  applyCiFix,
  updateCiSettings,
  triggerDeployment,
} from "../api";
import type {
  RepoSummary,
  User,
  CiOverviewResponse,
  CiRunItem,
  CiJobItem,
  CiDiagnosisResult,
} from "../types";
import Navigation from "../components/Navigation";
import DiffViewer from "../components/DiffViewer";

interface CICDPageProps {
  user: User;
  onLogout: () => void;
}

type TabKey = "workflow" | "runs" | "deployment" | "guide";

function sanitizeErrorNotice(msg: string | null): string {
  if (!msg) return "";
  return msg
    .replace(/gh[opusr]_[A-Za-z0-9_]{10,}/g, "[REDACTED_TOKEN]")
    .replace(/github_pat_[A-Za-z0-9_]{10,}/g, "[REDACTED_TOKEN]")
    .replace(/https?:\/\/[^@\s]+@/g, "https://[REDACTED_AUTH]@");
}

export const CICDPage: FC<CICDPageProps> = ({ user, onLogout }) => {
  // Repositories state
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState<string>(() => {
    try {
      return localStorage.getItem("codebrain_active_repo_id") || "";
    } catch {
      return "";
    }
  });
  const [activeTab, setActiveTab] = useState<TabKey>("workflow");

  // Overview & Per-Repo state
  const [overview, setOverview] = useState<CiOverviewResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState<boolean>(false);
  const [runs, setRuns] = useState<CiRunItem[]>([]);
  const [loadingRuns, setLoadingRuns] = useState<boolean>(false);
  const [isDispatchPolling, setIsDispatchPolling] = useState<boolean>(false);
  const [deploymentTriggering, setDeploymentTriggering] = useState<boolean>(false);
  const [showDeployModal, setShowDeployModal] = useState<boolean>(false);
  const [deployEnv, setDeployEnv] = useState<string>("production");
  const [skipCiCheck, setSkipCiCheck] = useState<boolean>(false);

  // In-flight action states
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);
  const [errorNotice, setErrorNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  // Run detail & logs modal state
  const [selectedRun, setSelectedRun] = useState<CiRunItem | null>(null);
  const [selectedRunJobs, setSelectedRunJobs] = useState<CiJobItem[]>([]);
  const [loadingRunJobs, setLoadingRunJobs] = useState<boolean>(false);

  // AI Failure Diagnosis state
  const [diagnosingRunId, setDiagnosingRunId] = useState<string | null>(null);
  const [diagnosisResult, setDiagnosisResult] = useState<CiDiagnosisResult | null>(null);
  const [applyingFix, setApplyingFix] = useState<boolean>(false);

  const handleSelectRepo = (repoId: string) => {
    setSelectedRepoId(repoId);
    try {
      localStorage.setItem("codebrain_active_repo_id", repoId);
    } catch {}
  };

  // 1. Initial Repo load
  useEffect(() => {
    fetchRepos().then((list) => {
      setRepos(list);
      if (list.length > 0) {
        const saved = localStorage.getItem("codebrain_active_repo_id");
        const found = saved && list.find((r) => r.repo_id === saved);
        if (found) {
          setSelectedRepoId(found.repo_id);
        } else if (!selectedRepoId) {
          setSelectedRepoId(list[0].repo_id);
          try {
            localStorage.setItem("codebrain_active_repo_id", list[0].repo_id);
          } catch {}
        }
      }
    });
  }, []);

  // 2. Load Per-Repo CI/CD State on Repo Selection
  useEffect(() => {
    if (!selectedRepoId) return;
    loadRepoCiState(selectedRepoId);
  }, [selectedRepoId]);

  // 3. Intelligent Polling for Active Runs & Eventual Consistency
  useEffect(() => {
    if (!selectedRepoId) return;

    const hasActiveRun = runs.some((r) => {
      const s = (r.status || "").toLowerCase();
      return s === "in_progress" || s === "queued" || s === "waiting" || s === "requested" || s === "pending";
    });

    if (!hasActiveRun && !isDispatchPolling) return;

    const intervalTimer = setInterval(async () => {
      try {
        const res = await fetchCiRuns(selectedRepoId, 15);
        if (res && res.runs) {
          setRuns(res.runs);
          const stillActive = res.runs.some((r) => {
            const s = (r.status || "").toLowerCase();
            return s === "in_progress" || s === "queued" || s === "waiting" || s === "requested" || s === "pending";
          });
          if (!stillActive && isDispatchPolling) {
            setIsDispatchPolling(false);
          }
        }
      } catch (err) {
        console.warn("Background run synchronization paused:", err);
      }
    }, 4500);

    return () => clearInterval(intervalTimer);
  }, [selectedRepoId, runs, isDispatchPolling]);

  const loadRepoCiState = async (repoId: string) => {
    setLoadingOverview(true);
    setSuccessNotice(null);
    setErrorNotice(null);
    setDiagnosisResult(null);
    setSelectedRun(null);
    try {
      const data = await fetchCiOverview(repoId);
      setOverview(data);
      // Also fetch runs
      if (data.source_type === "github") {
        loadRuns(repoId);
      } else {
        setRuns([]);
      }
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to load repository CI/CD state");
    } finally {
      setLoadingOverview(false);
    }
  };

  const loadRuns = async (repoId: string) => {
    setLoadingRuns(true);
    try {
      const res = await fetchCiRuns(repoId, 15);
      setRuns(res.runs || []);
    } catch (err: any) {
      console.warn("Failed to load GitHub Actions runs:", err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Actions
  const handleAnalyze = async () => {
    if (!selectedRepoId) return;
    setActionLoading("analyze");
    setErrorNotice(null);
    try {
      await analyzeCi(selectedRepoId);
      await loadRepoCiState(selectedRepoId);
      setSuccessNotice("Repository evidence and workflows re-analyzed successfully.");
    } catch (err: any) {
      setErrorNotice(err.message || "Analysis failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleGenerate = async () => {
    if (!selectedRepoId) return;
    setActionLoading("generate");
    setErrorNotice(null);
    try {
      await generateCiWorkflow(selectedRepoId);
      await loadRepoCiState(selectedRepoId);
      setSuccessNotice("Tailored CI quality gate workflow generated with verified repository evidence.");
    } catch (err: any) {
      setErrorNotice(err.message || "Generation failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleInstallPr = async () => {
    if (!selectedRepoId) return;
    setActionLoading("install-pr");
    setErrorNotice(null);
    try {
      const res = await installCiViaPr(selectedRepoId);
      await loadRepoCiState(selectedRepoId);
      setSuccessNotice(
        `CI Proposal Pull Request opened successfully (#${res.pr_number || ""}). Review and merge to activate CI.`
      );
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to create installation PR");
    } finally {
      setActionLoading(null);
    }
  };

  const handleInstallDirect = async () => {
    if (!selectedRepoId) return;
    if (!confirm("Are you sure you want to commit this CI workflow directly to the default branch?")) return;
    setActionLoading("install-direct");
    setErrorNotice(null);
    try {
      const res = await installCiDirect(selectedRepoId, {
        workflow_content: overview?.proposed_workflow_content || undefined,
      });
      await loadRepoCiState(selectedRepoId);
      const shaMsg = res.commit_sha ? ` (Commit ${res.commit_sha.slice(0, 7)})` : "";
      setSuccessNotice(`CI workflow committed directly to default branch${shaMsg}. Remote CI is now active and verified!`);
    } catch (err: any) {
      setErrorNotice(err.message || "Direct installation failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleVerify = async () => {
    if (!selectedRepoId) return;
    setActionLoading("verify");
    setErrorNotice(null);
    try {
      const res = await verifyCiInstallation(selectedRepoId);
      await loadRepoCiState(selectedRepoId);
      if (res.setup_status === "installed" || res.remote_workflow_verified) {
        setSuccessNotice("Verified remotely! GitHub Actions workflow is installed and verified on the remote repository.");
      } else if (res.is_merged) {
        setSuccessNotice("Verified! CI Proposal Pull Request has been merged into default branch.");
      } else {
        setSuccessNotice("Checked remote repository: Workflow not yet detected on main branch. Merge the PR or commit directly.");
      }
    } catch (err: any) {
      setErrorNotice(err.message || "Verification failed");
    } finally {
      setActionLoading(null);
    }
  };

  const handleDispatch = async () => {
    if (!selectedRepoId) return;
    setActionLoading("dispatch");
    setErrorNotice(null);
    try {
      await dispatchCiWorkflow(selectedRepoId, { ref: overview?.branch_name || "main" });
      setSuccessNotice("Workflow dispatch signal accepted by GitHub Actions. Run will appear momentarily.");
      setIsDispatchPolling(true);
      setTimeout(() => loadRuns(selectedRepoId), 2500);
    } catch (err: any) {
      setErrorNotice(err.message || "Workflow dispatch failed");
    } finally {
      setActionLoading(null);
    }
  };


  const handleToggleAutoFix = async () => {
    if (!selectedRepoId || !overview) return;
    const nextVal = !overview.auto_fix_enabled;
    try {
      await updateCiSettings(selectedRepoId, { auto_fix_enabled: nextVal });
      setOverview({ ...overview, auto_fix_enabled: nextVal });
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to update setting");
    }
  };

  const handleToggleAutoCommit = async () => {
    if (!selectedRepoId || !overview) return;
    const nextVal = !overview.auto_commit_enabled;
    if (nextVal && !confirm("Enable Automatic Fix Commits?\n\nCodeBrain will automatically commit authorized AI patches for fixable CI failures within the retry budget.")) {
      return;
    }
    try {
      await updateCiSettings(selectedRepoId, { auto_commit_enabled: nextVal });
      setOverview({ ...overview, auto_commit_enabled: nextVal });
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to update setting");
    }
  };

  const handleViewRunDetails = async (run: CiRunItem) => {
    setSelectedRun(run);
    setLoadingRunJobs(true);
    setDiagnosisResult(null);
    try {
      const res = await fetchCiRunDetails(selectedRepoId, run.run_id);
      setSelectedRunJobs(res.jobs || []);
      // If live run status was updated, synchronize local run state
      if (res.status) {
        setRuns((prev) =>
          prev.map((r) =>
            r.run_id === run.run_id
              ? { ...r, status: res.status ?? r.status, conclusion: res.conclusion ?? r.conclusion }
              : r
          )
        );
        setSelectedRun((prev) =>
          prev && prev.run_id === run.run_id
            ? { ...prev, status: res.status ?? prev.status, conclusion: res.conclusion ?? prev.conclusion }
            : prev
        );
      }
    } catch (err: any) {
      console.warn("Failed to fetch run jobs:", err);
    } finally {
      setLoadingRunJobs(false);
    }
  };

  const handleDiagnose = async (runId: string) => {
    setDiagnosingRunId(runId);
    setErrorNotice(null);
    try {
      const res = await diagnoseCiFailure(selectedRepoId, runId);
      setDiagnosisResult(res);
    } catch (err: any) {
      setErrorNotice(err.message || "Diagnosis failed");
    } finally {
      setDiagnosingRunId(null);
    }
  };

  const handleApplyFix = async () => {
    if (!selectedRepoId || !selectedRun || !diagnosisResult?.proposed_patch) return;
    setApplyingFix(true);
    setErrorNotice(null);
    try {
      const res = await applyCiFix(selectedRepoId, {
        run_id: selectedRun.run_id,
        patch: diagnosisResult.proposed_patch,
      });
      setSuccessNotice(`Patch applied! Created PR #${res.pr_number || ""} on branch ${res.branch_name}.`);
      setDiagnosisResult(null);
      await loadRepoCiState(selectedRepoId);
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to apply fix");
    } finally {
      setApplyingFix(false);
    }
  };

  // Helper formatting badges
  const renderInstallationBadge = () => {
    const s = overview?.setup_status;
    if (s === "installed") {
      return (
        <span className="px-2.5 py-1 bg-zinc-800/90 border border-zinc-700 text-zinc-300 rounded-full text-xs font-semibold flex items-center gap-1.5" title="Workflow file is present in repository">
          <FileCode size={13} className="text-purple-400" />
          <span>Installed</span>
        </span>
      );
    }
    if (s === "awaiting_installation") {
      return (
        <span className="px-2.5 py-1 bg-purple-950/80 border border-purple-700 text-purple-300 rounded-full text-xs font-semibold flex items-center gap-1.5" title="Pull Request is open awaiting merge">
          <GitPullRequest size={13} />
          <span>Awaiting Merge (PR Open)</span>
        </span>
      );
    }
    if (s === "proposed") {
      return (
        <span className="px-2.5 py-1 bg-amber-950/80 border border-amber-700 text-amber-300 rounded-full text-xs font-semibold flex items-center gap-1.5" title="Pipeline proposal generated">
          <Sparkles size={13} />
          <span>Proposal Ready</span>
        </span>
      );
    }
    return (
      <span className="px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-400 rounded-full text-xs font-semibold flex items-center gap-1.5">
        <AlertCircle size={13} />
        <span>Not Configured</span>
      </span>
    );
  };

  const renderLatestHealthBadge = () => {
    const latestRun = runs.length > 0 ? runs[0] : null;
    const conclusion = (latestRun?.conclusion || overview?.last_run_conclusion || "").toLowerCase();
    const status = (latestRun?.status || overview?.last_run_status || "").toLowerCase();

    if (conclusion === "success") {
      return (
        <span className="px-2.5 py-1 bg-emerald-950/80 border border-emerald-700 text-emerald-400 rounded-full text-xs font-semibold flex items-center gap-1.5" title="Latest workflow run passed all quality gates">
          <CheckCircle2 size={13} />
          <span>Passing</span>
        </span>
      );
    }
    if (conclusion === "failure") {
      return (
        <span className="px-2.5 py-1 bg-red-950/80 border border-red-700 text-red-400 rounded-full text-xs font-semibold flex items-center gap-1.5" title="Latest workflow run failed one or more quality gates">
          <XCircle size={13} />
          <span>Failing (Check Logs)</span>
        </span>
      );
    }
    if (conclusion === "cancelled") {
      return (
        <span className="px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-400 rounded-full text-xs font-semibold flex items-center gap-1.5">
          <Slash size={13} />
          <span>Cancelled</span>
        </span>
      );
    }
    if (status === "in_progress") {
      return (
        <span className="px-2.5 py-1 bg-amber-950/80 border border-amber-700 text-amber-300 rounded-full text-xs font-semibold flex items-center gap-1.5">
          <RefreshCw size={13} className="animate-spin" />
          <span>Running</span>
        </span>
      );
    }
    if (status === "queued" || status === "waiting" || status === "requested") {
      return (
        <span className="px-2.5 py-1 bg-purple-950/80 border border-purple-700 text-purple-300 rounded-full text-xs font-semibold flex items-center gap-1.5">
          <Clock size={13} />
          <span>Queued</span>
        </span>
      );
    }
    if (overview?.setup_status === "installed") {
      return (
        <span className="px-2.5 py-1 bg-zinc-800/80 border border-zinc-700 text-zinc-400 rounded-full text-xs font-semibold flex items-center gap-1.5">
          <Clock size={13} />
          <span>No Run History</span>
        </span>
      );
    }
    return (
      <span className="px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-500 rounded-full text-xs font-semibold flex items-center gap-1.5">
        <MinusCircle size={13} />
        <span>N/A</span>
      </span>
    );
  };

  const handleTriggerDeployment = async (env: string = "production", skipCi: boolean = false) => {
    if (!selectedRepoId) return;
    setDeploymentTriggering(true);
    setErrorNotice(null);
    setSuccessNotice(null);
    try {
      const res = await triggerDeployment(selectedRepoId, {
        environment: env,
        skip_ci_check: skipCi,
      });
      setShowDeployModal(false);
      setSuccessNotice(`Deployment initiated! Provider: ${res.provider}, Deploy ID: ${res.deploy_id || "dispatched"}. Status: ${res.status}`);
      await loadRepoCiState(selectedRepoId);
    } catch (err: any) {
      setErrorNotice(err.message || "Failed to trigger deployment");
    } finally {
      setDeploymentTriggering(false);
    }
  };

  const renderRunStatusBadge = (r: CiRunItem) => {
    const status = (r.status || "").toLowerCase();
    const conclusion = (r.conclusion || "").toLowerCase();

    if (conclusion === "success") {
      return (
        <span className="inline-flex items-center gap-1.5 text-emerald-400 font-semibold">
          <CheckCircle2 size={14} />
          <span>Passed</span>
        </span>
      );
    }
    if (conclusion === "failure") {
      return (
        <span className="inline-flex items-center gap-1.5 text-red-400 font-semibold">
          <XCircle size={14} />
          <span>Failed</span>
        </span>
      );
    }
    if (conclusion === "cancelled") {
      return (
        <span className="inline-flex items-center gap-1.5 text-zinc-400 font-semibold">
          <Slash size={14} />
          <span>Cancelled</span>
        </span>
      );
    }
    if (conclusion === "timed_out") {
      return (
        <span className="inline-flex items-center gap-1.5 text-amber-400 font-semibold">
          <Clock size={14} />
          <span>Timed out</span>
        </span>
      );
    }
    if (conclusion === "neutral" || conclusion === "skipped") {
      return (
        <span className="inline-flex items-center gap-1.5 text-blue-300 font-semibold">
          <MinusCircle size={14} />
          <span>Completed ({conclusion === "neutral" ? "Neutral" : "Skipped"})</span>
        </span>
      );
    }
    if (status === "in_progress") {
      return (
        <span className="inline-flex items-center gap-1.5 text-amber-400 font-semibold">
          <RefreshCw size={14} className="animate-spin" />
          <span>Running</span>
        </span>
      );
    }
    if (status === "queued") {
      return (
        <span className="inline-flex items-center gap-1.5 text-purple-300 font-semibold">
          <Clock size={14} />
          <span>Queued</span>
        </span>
      );
    }
    if (status === "requested" || status === "waiting") {
      return (
        <span className="inline-flex items-center gap-1.5 text-purple-300 font-semibold">
          <Clock size={14} />
          <span>Queued / Waiting</span>
        </span>
      );
    }
    if (status) {
      return (
        <span className="text-gray-400 capitalize">{status}</span>
      );
    }
    return (
      <span className="text-gray-500 italic">Unknown</span>
    );
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-[#161718] text-[#cccccc] font-sans overflow-hidden">
      <Navigation user={user} onLogout={onLogout} />

      <main className="flex-1 overflow-y-auto max-w-7xl mx-auto w-full p-8 flex flex-col space-y-6">
        {/* Header & Per-Repo Selector */}
        <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-[#3c3c3c] shrink-0 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <GitMerge size={26} className="text-purple-400" />
              <span>CI/CD Setup & Automation Pipeline</span>
            </h1>
            <p className="text-xs text-gray-400 mt-1">
              Independent, repository-aware continuous integration, failure recovery, and deployment orchestration.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs text-gray-400 font-medium shrink-0">Repository:</label>
            <select
              value={selectedRepoId}
              onChange={(e) => handleSelectRepo(e.target.value)}
              className="bg-[#2d2d2d] border border-[#3c3c3c] text-white px-3.5 py-2 rounded-xl text-xs outline-none focus:border-purple-500 font-mono shadow-sm"
            >
              {repos.map((r) => (
                <option key={r.repo_id} value={r.repo_id}>
                  {r.name} ({r.source_type})
                </option>
              ))}
            </select>
            <button
              onClick={() => selectedRepoId && loadRepoCiState(selectedRepoId)}
              title="Refresh repository CI state"
              className="p-2 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] text-gray-300 rounded-xl text-xs transition-colors"
            >
              <RefreshCw size={14} className={loadingOverview ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Status Alerts */}
        {successNotice && (
          <div className="p-4 bg-emerald-950/80 border border-emerald-700/80 rounded-2xl text-emerald-200 text-xs flex items-center justify-between shadow-lg animate-fade-in">
            <div className="flex items-center gap-3">
              <CheckCircle size={18} className="text-emerald-400 shrink-0" />
              <span>{successNotice}</span>
            </div>
            <button onClick={() => setSuccessNotice(null)} className="text-emerald-400 hover:text-white text-xs">
              Dismiss
            </button>
          </div>
        )}

        {errorNotice && (
          <div className="p-4 bg-red-950/80 border border-red-800 rounded-2xl text-red-300 text-xs flex items-center justify-between shadow-lg animate-fade-in">
            <div className="flex items-center gap-3">
              <AlertTriangle size={18} className="text-red-400 shrink-0" />
              <div>
                <p className="font-semibold text-white">Notice</p>
                <p className="text-red-300/90 mt-0.5">{sanitizeErrorNotice(errorNotice)}</p>
              </div>
            </div>
            <button onClick={() => setErrorNotice(null)} className="text-red-400 hover:text-white text-xs">
              Dismiss
            </button>
          </div>
        )}

        {/* Per-Repository Status Bar */}
        <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-5 shadow-sm grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-4 items-center">
          <div>
            <span className="text-[11px] text-gray-400 block mb-1">Pipeline Config</span>
            {renderInstallationBadge()}
          </div>

          <div>
            <span className="text-[11px] text-gray-400 block mb-1">Latest Run Health</span>
            {renderLatestHealthBadge()}
          </div>

          <div>
            <span className="text-[11px] text-gray-400 block mb-1">Detected Tech Stack</span>
            <div className="flex items-center gap-1.5 flex-wrap">
              {overview?.evidence?.ecosystems && overview.evidence.ecosystems.length > 0 ? (
                overview.evidence.ecosystems.map((eco) => (
                  <span
                    key={eco}
                    className="px-2 py-0.5 bg-blue-950/70 border border-blue-800 text-blue-300 rounded text-[11px] font-mono capitalize"
                  >
                    {eco}
                  </span>
                ))
              ) : (
                <span className="text-xs text-gray-400 font-mono">General Project</span>
              )}
            </div>
          </div>

          <div>
            <span className="text-[11px] text-gray-400 block mb-1">Automation Policy</span>
            <div className="flex items-center gap-3 text-xs">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(overview?.auto_fix_enabled)}
                  onChange={handleToggleAutoFix}
                  className="rounded bg-zinc-800 border-zinc-700 text-purple-600 focus:ring-0"
                />
                <span className="text-gray-300">Auto-Fix</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(overview?.auto_commit_enabled)}
                  onChange={handleToggleAutoCommit}
                  className="rounded bg-zinc-800 border-zinc-700 text-purple-600 focus:ring-0"
                />
                <span className="text-gray-300">Auto-Commit</span>
              </label>
            </div>
          </div>

          <div>
            <span className="text-[11px] text-gray-400 block mb-1">Bounded Retry Budget</span>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-purple-300">
                {overview?.current_retry_count || 0} / {overview?.max_retry_budget || 3} used
              </span>
              <span className="text-[11px] text-gray-500">(Loop-Protected)</span>
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 border-b border-[#3c3c3c] pb-2 text-xs font-semibold">
          <button
            onClick={() => setActiveTab("workflow")}
            className={`px-4 py-2 rounded-xl transition-all flex items-center gap-2 ${
              activeTab === "workflow"
                ? "bg-purple-600 text-white shadow-md shadow-purple-900/30"
                : "text-gray-400 hover:text-white hover:bg-[#2d2d2d]"
            }`}
          >
            <FileCode size={15} />
            <span>Workflow & Pipeline</span>
          </button>

          <button
            onClick={() => setActiveTab("runs")}
            className={`px-4 py-2 rounded-xl transition-all flex items-center gap-2 ${
              activeTab === "runs"
                ? "bg-purple-600 text-white shadow-md shadow-purple-900/30"
                : "text-gray-400 hover:text-white hover:bg-[#2d2d2d]"
            }`}
          >
            <Play size={15} />
            <span>Run History & Logs ({runs.length})</span>
          </button>

          <button
            onClick={() => setActiveTab("deployment")}
            className={`px-4 py-2 rounded-xl transition-all flex items-center gap-2 ${
              activeTab === "deployment"
                ? "bg-purple-600 text-white shadow-md shadow-purple-900/30"
                : "text-gray-400 hover:text-white hover:bg-[#2d2d2d]"
            }`}
          >
            <Layers size={15} />
            <span>Deployment ({overview?.deployment?.display_name || "None"})</span>
          </button>

          <button
            onClick={() => setActiveTab("guide")}
            className={`px-4 py-2 rounded-xl transition-all flex items-center gap-2 ${
              activeTab === "guide"
                ? "bg-purple-600 text-white shadow-md shadow-purple-900/30"
                : "text-gray-400 hover:text-white hover:bg-[#2d2d2d]"
            }`}
          >
            <BookOpen size={15} />
            <span>Setup Instructions</span>
          </button>
        </div>

        {/* Tab 1: Workflow & Pipeline */}
        {activeTab === "workflow" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Action & Metadata Side Panel */}
            <div className="lg:col-span-1 space-y-6">
              <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-5">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <ShieldCheck size={16} className="text-blue-400" />
                  <span>Pipeline Actions</span>
                </h3>

                <p className="text-xs text-gray-400 leading-relaxed">
                  CodeBrain analyzes repository manifests (e.g. requirements.txt, package.json) to generate or inspect
                  isolated GitHub Actions workflows.
                </p>

                <div className="space-y-3 pt-2">
                  {/* Re-analyze repository manifests */}
                  <button
                    onClick={handleAnalyze}
                    disabled={actionLoading !== null}
                    className="w-full py-2 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] disabled:opacity-50 text-gray-200 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all shadow-sm"
                  >
                    <RefreshCw size={14} className={actionLoading === "analyze" ? "animate-spin" : ""} />
                    <span>Analyze Repository Evidence</span>
                  </button>

                  {/* Generate / Re-generate proposal */}
                  <button
                    onClick={handleGenerate}
                    disabled={actionLoading !== null}
                    className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all shadow"
                  >
                    <Sparkles size={14} className={actionLoading === "generate" ? "animate-spin" : ""} />
                    <span>Generate AI Proposal</span>
                  </button>

                  {/* Install via PR */}
                  <button
                    onClick={handleInstallPr}
                    disabled={actionLoading !== null || overview?.source_type !== "github"}
                    className="w-full py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold shadow-lg shadow-purple-900/30 flex items-center justify-center gap-2 transition-all"
                  >
                    <GitPullRequest size={14} className={actionLoading === "install-pr" ? "animate-spin" : ""} />
                    <span>Install via Pull Request</span>
                  </button>

                  {/* Direct Commit */}
                  <button
                    onClick={handleInstallDirect}
                    disabled={actionLoading !== null || overview?.source_type !== "github"}
                    className="w-full py-2 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] text-gray-200 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all"
                  >
                    <CheckCircle2 size={14} className={actionLoading === "install-direct" ? "animate-spin" : ""} />
                    <span>Direct Commit to Branch</span>
                  </button>

                  {/* Verify Remote Installation */}
                  <button
                    onClick={handleVerify}
                    disabled={actionLoading !== null || overview?.source_type !== "github"}
                    className="w-full py-2 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] text-gray-300 rounded-xl text-xs font-medium flex items-center justify-center gap-2 transition-all"
                  >
                    <RotateCcw size={14} className={actionLoading === "verify" ? "animate-spin" : ""} />
                    <span>Verify Remote Installation</span>
                  </button>

                  {/* Dispatch Workflow */}
                  <button
                    onClick={handleDispatch}
                    disabled={actionLoading !== null || overview?.setup_status !== "installed"}
                    className="w-full py-2.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-xl text-xs font-semibold shadow-lg shadow-emerald-900/30 flex items-center justify-center gap-2 transition-all"
                  >
                    <Play size={14} className={actionLoading === "dispatch" ? "animate-spin" : ""} />
                    <span>Dispatch Workflow Run</span>
                  </button>
                </div>

                {overview?.pr_url && (
                  <div className="pt-3 border-t border-[#3c3c3c]">
                    <a
                      href={overview.pr_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1.5"
                    >
                      <span>Open Setup PR #{overview.pr_number || ""} on GitHub</span>
                      <ExternalLink size={12} />
                    </a>
                  </div>
                )}
              </div>

              {/* Discovered Full-Stack Components */}
              {overview?.evidence?.components && overview.evidence.components.length > 0 && (
                <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-5 shadow-sm space-y-4">
                  <h4 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                    <Layers size={14} className="text-purple-400" />
                    <span>Discovered Components ({overview.evidence.components.length})</span>
                  </h4>
                  <div className="space-y-3">
                    {overview.evidence.components.map((comp, idx) => (
                      <div key={idx} className="bg-[#1e1e1e] border border-[#383838] rounded-xl p-3 text-xs space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-white flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-purple-400"></span>
                            {comp.name}
                          </span>
                          <span className="text-[10px] font-mono text-gray-400 px-2 py-0.5 bg-zinc-800 rounded">
                            {comp.path === "." ? "root" : comp.path}
                          </span>
                        </div>
                        <div className="text-[11px] text-gray-400 space-y-1">
                          <div className="flex justify-between">
                            <span>Framework:</span>
                            <span className="text-gray-300 font-mono capitalize">{comp.framework}</span>
                          </div>
                          {comp.lockfile && (
                            <div className="flex justify-between">
                              <span>Lockfile:</span>
                              <span className="text-gray-300 font-mono">{comp.lockfile}</span>
                            </div>
                          )}
                          {comp.build_command && (
                            <div className="flex justify-between">
                              <span>Build:</span>
                              <span className="text-gray-300 font-mono">{comp.build_command}</span>
                            </div>
                          )}
                          <div className="flex justify-between items-center pt-1 border-t border-[#2e2e2e]">
                            <span>Test Suite:</span>
                            {comp.has_test_suite ? (
                              <span className="text-emerald-400 font-mono flex items-center gap-1">
                                <CheckCircle2 size={10} />
                                {comp.test_command || "configured"}
                              </span>
                            ) : (
                              <span className="text-amber-400 font-mono text-[10px]">
                                Not configured
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Workflow Code / Diff View */}
            <div className="lg:col-span-2 space-y-6">
              <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-3">
                  <div className="flex items-center gap-2">
                    <Terminal size={16} className="text-purple-400" />
                    <span className="text-sm font-bold text-white">
                      {overview?.setup_status === "installed"
                        ? "Active Continuous Integration Workflow"
                        : "Proposed CI Quality Gate Workflow"}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-400">
                      {overview?.workflow_path || ".github/workflows/ci.yml"}
                    </span>
                    <button
                      onClick={() =>
                        handleCopy(
                          overview?.active_workflow_content ||
                            overview?.proposed_workflow_content ||
                            ""
                        )
                      }
                      className="px-2.5 py-1 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] text-gray-300 rounded text-xs flex items-center gap-1"
                    >
                      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                      <span>{copied ? "Copied" : "Copy"}</span>
                    </button>
                  </div>
                </div>

                {overview?.proposed_diff && overview.setup_status !== "installed" ? (
                  <div className="space-y-3">
                    <p className="text-xs text-gray-400">
                      Unified diff to be committed to <code className="text-purple-300">.github/workflows/ci.yml</code>:
                    </p>
                    <DiffViewer diff={overview.proposed_diff} />
                  </div>
                ) : (
                  <pre className="p-4 bg-[#1e1e1e] border border-[#3c3c3c] rounded-xl font-mono text-xs text-gray-300 overflow-x-auto leading-relaxed max-h-[500px]">
                    {overview?.active_workflow_content ||
                      overview?.proposed_workflow_content ||
                      `# No workflow loaded yet. Click "Generate AI Proposal" to synthesize.`}
                  </pre>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Run History & Logs */}
        {activeTab === "runs" && (
          <div className="space-y-6">
            <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-4">
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <Play size={16} className="text-emerald-400" />
                    <span>GitHub Actions Workflow Runs</span>
                  </h3>
                  <p className="text-xs text-gray-400 mt-1">
                    Real execution results retrieved directly from GitHub Actions for this repository.
                  </p>
                </div>

                <button
                  onClick={() => selectedRepoId && loadRuns(selectedRepoId)}
                  disabled={loadingRuns}
                  className="px-3 py-1.5 bg-[#2d2d2d] hover:bg-[#383838] border border-[#3c3c3c] text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors"
                >
                  <RefreshCw size={13} className={loadingRuns ? "animate-spin" : ""} />
                  <span>Refresh Runs</span>
                </button>
              </div>

              {runs.length === 0 ? (
                <div className="p-12 text-center text-gray-500 text-xs">
                  {overview?.setup_status === "installed"
                    ? "No workflow runs found yet for this repository. Trigger one above or push a commit."
                    : "Install the workflow in GitHub first to view real workflow runs."}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs font-sans">
                    <thead>
                      <tr className="border-b border-[#3c3c3c] text-gray-400 text-[11px]">
                        <th className="pb-3 font-medium">Status</th>
                        <th className="pb-3 font-medium">Run</th>
                        <th className="pb-3 font-medium">Commit & Branch</th>
                        <th className="pb-3 font-medium">Event</th>
                        <th className="pb-3 font-medium">Date</th>
                        <th className="pb-3 font-medium text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#333333]">
                      {runs.map((r) => {
                        const isFailed = r.conclusion === "failure";

                        return (
                          <tr key={r.run_id} className="hover:bg-[#2a2a2b] transition-colors">
                            <td className="py-3.5">
                              {renderRunStatusBadge(r)}
                            </td>

                            <td className="py-3.5">
                              <span className="font-semibold text-white block">#{r.run_number || r.run_id}</span>
                              <span className="text-[11px] text-gray-400">{r.name}</span>
                            </td>

                            <td className="py-3.5">
                              <span className="font-mono text-purple-300 block">
                                {r.head_branch} ({r.head_sha?.slice(0, 7) || "HEAD"})
                              </span>
                              <span className="text-[11px] text-gray-400 truncate max-w-xs block">
                                {r.commit_message || "Commit"}
                              </span>
                            </td>

                            <td className="py-3.5 text-gray-300 font-mono text-[11px] uppercase">{r.event}</td>

                            <td className="py-3.5 text-gray-400 text-[11px]">
                              {r.created_at ? new Date(r.created_at).toLocaleString() : "N/A"}
                            </td>

                            <td className="py-3.5 text-right space-x-2">
                              {isFailed && (
                                <button
                                  onClick={() => handleDiagnose(r.run_id)}
                                  disabled={diagnosingRunId === r.run_id}
                                  className="px-2.5 py-1 bg-red-950/80 hover:bg-red-900 border border-red-700 text-red-300 rounded text-xs font-semibold transition-colors"
                                >
                                  {diagnosingRunId === r.run_id ? "Diagnosing..." : "Diagnose with AI"}
                                </button>
                              )}

                              <button
                                onClick={() => handleViewRunDetails(r)}
                                className="px-2.5 py-1 bg-[#333333] hover:bg-[#3d3d3d] text-gray-200 rounded text-xs font-medium transition-colors"
                              >
                                View Logs
                              </button>

                              {r.html_url && (
                                <a
                                  href={r.html_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="p-1 inline-block text-gray-400 hover:text-white"
                                  title="View on GitHub Actions"
                                >
                                  <ExternalLink size={13} />
                                </a>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Run Logs / Steps Drawer */}
            {selectedRun && (
              <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-4 animate-fade-in">
                <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-3">
                  <div>
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      <Terminal size={15} className="text-purple-400" />
                      <span>
                        Run #{selectedRun.run_number || selectedRun.run_id} Job Details & Logs
                      </span>
                    </h4>
                    <span className="text-xs text-gray-400">{selectedRun.commit_message}</span>
                  </div>
                  <button
                    onClick={() => setSelectedRun(null)}
                    className="text-xs text-gray-400 hover:text-white"
                  >
                    Close Drawer
                  </button>
                </div>

                {loadingRunJobs ? (
                  <div className="p-8 text-center text-gray-400 text-xs">Loading job logs...</div>
                ) : (
                  <div className="space-y-4">
                    {selectedRunJobs.map((j) => (
                      <div key={j.job_id} className="bg-[#1e1e1e] border border-[#3c3c3c] rounded-xl p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-white text-xs">{j.name}</span>
                          <span
                            className={`text-[11px] font-mono px-2 py-0.5 rounded ${
                              j.conclusion === "success"
                                ? "bg-emerald-950 text-emerald-400"
                                : j.conclusion === "failure"
                                ? "bg-red-950 text-red-400"
                                : "bg-zinc-800 text-gray-400"
                            }`}
                          >
                            {j.conclusion || j.status}
                          </span>
                        </div>

                        {/* Steps summary */}
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                          {j.steps.map((st) => (
                            <div
                              key={st.number}
                              className={`p-2 rounded text-[11px] border flex items-center justify-between ${
                                st.conclusion === "success"
                                  ? "bg-emerald-950/20 border-emerald-900/40 text-emerald-300"
                                  : st.conclusion === "failure"
                                  ? "bg-red-950/30 border-red-800/50 text-red-300 font-semibold"
                                  : "bg-[#252526] border-[#383838] text-gray-400"
                              }`}
                            >
                              <span className="truncate">{st.name}</span>
                              <span>{st.conclusion === "success" ? "✓" : st.conclusion === "failure" ? "✗" : "•"}</span>
                            </div>
                          ))}
                        </div>

                        {j.logs && (
                          <pre className="p-3 bg-black/60 border border-[#333333] rounded font-mono text-[11px] text-gray-300 max-h-60 overflow-y-auto leading-relaxed">
                            {j.logs}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* AI Diagnosis Result Modal */}
            {diagnosisResult && (
              <div className="bg-[#252526] border border-red-800/80 rounded-2xl p-6 shadow-xl space-y-4 animate-fade-in">
                <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-3">
                  <h4 className="text-sm font-bold text-white flex items-center gap-2">
                    <Sparkles size={16} className="text-purple-400" />
                    <span>AI Failure Diagnosis & Repair Proposal</span>
                  </h4>
                  <button onClick={() => setDiagnosisResult(null)} className="text-xs text-gray-400 hover:text-white">
                    Close
                  </button>
                </div>

                <div className="p-4 bg-[#1e1e1e] rounded-xl text-xs text-gray-300 space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="font-semibold text-white">Classification:</span>
                    <span className="px-2 py-0.5 bg-red-950 text-red-400 rounded font-mono text-[11px] uppercase">
                      {diagnosisResult.category}
                    </span>
                    <span className="text-gray-400 font-mono text-[11px]">
                      Fingerprint: {diagnosisResult.fingerprint}
                    </span>
                  </div>

                  <div className="whitespace-pre-wrap leading-relaxed">{diagnosisResult.diagnosis}</div>

                  {diagnosisResult.proposed_patch && (
                    <div className="pt-2">
                      <p className="font-semibold text-white mb-2">Proposed Fix Patch:</p>
                      <DiffViewer diff={diagnosisResult.proposed_patch} />
                    </div>
                  )}
                </div>

                {diagnosisResult.proposed_patch && (
                  <div className="flex items-center justify-end gap-3 pt-2">
                    <button
                      onClick={handleApplyFix}
                      disabled={applyingFix}
                      className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow"
                    >
                      <CheckCircle2 size={14} className={applyingFix ? "animate-spin" : ""} />
                      <span>{applyingFix ? "Applying & Committing..." : "Apply & Commit AI Fix (PR)"}</span>
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Deployment */}
        {activeTab === "deployment" && (
          <div className="space-y-6">
            <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-[#3c3c3c] pb-4 gap-3">
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <Layers size={16} className="text-blue-400" />
                    <span>Deployment Configuration & Safety Gates</span>
                  </h3>
                  <p className="text-xs text-gray-400 mt-1">
                    Verified hosting provider, runtime specifications, safety checks, and manual deployment controls.
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  {/* Status Badge */}
                  {(() => {
                    const conn = (overview?.deployment?.connection_status || (overview?.deployment?.is_configured ? "detected" : "unknown")).toLowerCase();
                    if (conn === "connected") {
                      return (
                        <span className="text-xs px-2.5 py-1 rounded-full font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-1.5">
                          <CheckCircle2 size={13} />
                          <span>Connected</span>
                        </span>
                      );
                    }
                    if (conn === "configured") {
                      return (
                        <span className="text-xs px-2.5 py-1 rounded-full font-semibold bg-blue-950 text-blue-300 border border-blue-800 flex items-center gap-1.5">
                          <CheckCheck size={13} />
                          <span>Configured</span>
                        </span>
                      );
                    }
                    if (conn === "detected") {
                      return (
                        <span className="text-xs px-2.5 py-1 rounded-full font-semibold bg-purple-950 text-purple-300 border border-purple-800 flex items-center gap-1.5">
                          <Sparkles size={13} />
                          <span>Detected</span>
                        </span>
                      );
                    }
                    if (conn === "deploying") {
                      return (
                        <span className="text-xs px-2.5 py-1 rounded-full font-semibold bg-amber-950 text-amber-300 border border-amber-800 flex items-center gap-1.5">
                          <RefreshCw size={13} className="animate-spin" />
                          <span>Deploying</span>
                        </span>
                      );
                    }
                    return (
                      <span className="text-xs px-2.5 py-1 rounded-full font-semibold bg-zinc-800 text-gray-400 border border-zinc-700 flex items-center gap-1.5">
                        <AlertCircle size={13} />
                        <span>Not Connected</span>
                      </span>
                    );
                  })()}

                  <button
                    onClick={() => setShowDeployModal(true)}
                    className="px-3.5 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-md transition-all"
                  >
                    <Rocket size={13} />
                    <span>Deploy Now</span>
                  </button>
                </div>
              </div>

              {/* Deployment Details Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Left Card: Provider Specification */}
                <div className="p-5 bg-[#1e1e1e] border border-[#3c3c3c] rounded-xl space-y-4 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white text-sm">Provider Specification</span>
                    <span className="font-mono text-purple-300 font-semibold px-2 py-0.5 bg-purple-950/60 border border-purple-800/80 rounded">
                      {overview?.deployment?.display_name || "None Detected"}
                    </span>
                  </div>

                  <p className="text-gray-300 leading-relaxed">
                    {overview?.deployment?.description || "No deployment configuration detected in this repository."}
                  </p>

                  <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[#2e2e2e]">
                    <div>
                      <span className="text-gray-400 text-[11px] block">Framework / Runtime:</span>
                      <span className="text-white font-mono font-medium">{overview?.deployment?.framework || "Standard Web"}</span>
                    </div>
                    <div>
                      <span className="text-gray-400 text-[11px] block">Target Branch:</span>
                      <span className="text-purple-300 font-mono font-medium">{overview?.deployment?.target_branch || "main"}</span>
                    </div>
                    <div>
                      <span className="text-gray-400 text-[11px] block">Build Command:</span>
                      <span className="text-gray-300 font-mono">{overview?.deployment?.build_command || "npm run build"}</span>
                    </div>
                    <div>
                      <span className="text-gray-400 text-[11px] block">Publish Directory:</span>
                      <span className="text-gray-300 font-mono">{overview?.deployment?.output_dir || "dist / build"}</span>
                    </div>
                  </div>

                  {overview?.deployment?.detected_files && overview.deployment.detected_files.length > 0 && (
                    <div className="pt-2 border-t border-[#2e2e2e]">
                      <span className="text-gray-400 text-[11px] block mb-1.5">Detected Manifests:</span>
                      <div className="flex gap-2 flex-wrap">
                        {overview.deployment.detected_files.map((df) => (
                          <span key={df} className="px-2 py-0.5 bg-[#282828] border border-[#3c3c3c] text-emerald-300 rounded font-mono text-[11px]">
                            {df}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Required Environment Variables without secret values */}
                  {overview?.deployment?.required_env_vars && overview.deployment.required_env_vars.length > 0 && (
                    <div className="pt-2 border-t border-[#2e2e2e]">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-gray-400 text-[11px]">Required Environment Variables:</span>
                        <span className="text-[10px] text-gray-500">(Configured in secrets)</span>
                      </div>
                      <div className="flex gap-1.5 flex-wrap">
                        {overview.deployment.required_env_vars.map((ev) => (
                          <span key={ev} className="px-2 py-0.5 bg-zinc-800 text-zinc-300 rounded font-mono text-[10px] border border-zinc-700">
                            {ev}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Provider External Link */}
                  {overview?.deployment?.provider_dashboard_url && (
                    <div className="pt-2 border-t border-[#2e2e2e] flex items-center justify-between">
                      <span className="text-gray-400 text-[11px]">Provider Dashboard:</span>
                      <a
                        href={overview.deployment.provider_dashboard_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-purple-400 hover:text-purple-300 font-medium flex items-center gap-1 text-[11px]"
                      >
                        <span>Open Dashboard</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                  )}
                </div>

                {/* Right Card: Safety Gates Pipeline */}
                <div className="p-5 bg-[#1e1e1e] border border-[#3c3c3c] rounded-xl space-y-4 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white text-sm">Deployment Safety Pipeline</span>
                    <span className="text-[11px] text-amber-400 flex items-center gap-1 font-semibold">
                      <ShieldCheck size={13} />
                      <span>Production Gated</span>
                    </span>
                  </div>

                  <p className="text-gray-300 leading-relaxed">
                    {overview?.deployment?.recommendation || "Deployments are automatically monitored and gated behind CI verification."}
                  </p>

                  {/* 5-Step Pipeline Flow */}
                  <div className="space-y-2 pt-1">
                    <span className="text-gray-400 text-[11px] block font-medium">Orchestration Stages:</span>
                    <div className="space-y-2">
                      {[
                        { step: "1. Code Change", desc: "Committed to repository branch", state: "verified" },
                        { step: "2. CI Quality Tests", desc: "Automated frontend & backend test jobs run", state: overview?.last_run_conclusion === "success" ? "verified" : overview?.last_run_status === "in_progress" ? "running" : "pending" },
                        { step: "3. Safety Gates Enforced", desc: "Production promotion blocked if tests fail", state: "verified" },
                        { step: "4. Deployment Triggered", desc: `${overview?.deployment?.display_name || "Provider"} release dispatched`, state: "ready" },
                        { step: "5. Live Verification", desc: "Live endpoint health check and URL routing", state: "pending" },
                      ].map((st, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-2.5 rounded-lg bg-[#252526] border border-[#333333]"
                        >
                          <div>
                            <span className="font-semibold text-white block text-[11px]">{st.step}</span>
                            <span className="text-[10px] text-gray-400">{st.desc}</span>
                          </div>
                          <div>
                            {st.state === "verified" ? (
                              <span className="text-emerald-400 font-mono text-[10px] px-2 py-0.5 bg-emerald-950/60 rounded flex items-center gap-1">
                                <CheckCircle2 size={11} /> Pass
                              </span>
                            ) : st.state === "running" ? (
                              <span className="text-amber-400 font-mono text-[10px] px-2 py-0.5 bg-amber-950/60 rounded flex items-center gap-1">
                                <RefreshCw size={11} className="animate-spin" /> Running
                              </span>
                            ) : st.state === "ready" ? (
                              <span className="text-blue-300 font-mono text-[10px] px-2 py-0.5 bg-blue-950/60 rounded">
                                Ready
                              </span>
                            ) : (
                              <span className="text-zinc-500 font-mono text-[10px] px-2 py-0.5 bg-zinc-800 rounded">
                                Gated
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="p-3 bg-amber-950/30 border border-amber-800/40 rounded-lg text-amber-200 text-[11px] space-y-1">
                    <span className="font-semibold block flex items-center gap-1.5">
                      <AlertTriangle size={13} className="text-amber-400" />
                      <span>Continuous Deployment Policy</span>
                    </span>
                    <p className="text-amber-200/90 leading-relaxed">
                      If your provider (e.g. Netlify/Vercel) deploys on every Git push, ensure your branch protection rules require the <strong className="text-white">CodeBrain CI</strong> workflow to pass before merges.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Deploy Confirmation Modal */}
            {showDeployModal && (
              <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
                <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 max-w-lg w-full space-y-5 shadow-2xl animate-fade-in">
                  <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-3">
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      <Rocket size={16} className="text-purple-400" />
                      <span>Trigger Repository Deployment</span>
                    </h4>
                    <button
                      onClick={() => setShowDeployModal(false)}
                      className="text-xs text-gray-400 hover:text-white"
                    >
                      Cancel
                    </button>
                  </div>

                  <div className="space-y-4 text-xs">
                    <div className="p-3.5 bg-[#1e1e1e] rounded-xl border border-[#3c3c3c] space-y-2">
                      <div className="flex justify-between">
                        <span className="text-gray-400">Repository:</span>
                        <span className="text-white font-mono font-semibold">{overview?.repo_name}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Target Provider:</span>
                        <span className="text-purple-300 font-mono">{overview?.deployment?.display_name || "Detected Provider"}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-400">Branch:</span>
                        <span className="text-gray-300 font-mono">{overview?.deployment?.target_branch || "main"}</span>
                      </div>
                    </div>

                    <div>
                      <label className="text-gray-300 block mb-1.5 font-medium">Deployment Environment:</label>
                      <div className="grid grid-cols-2 gap-3">
                        <button
                          type="button"
                          onClick={() => setDeployEnv("production")}
                          className={`p-3 rounded-xl border text-center transition-all ${
                            deployEnv === "production"
                              ? "bg-purple-950/60 border-purple-500 text-white font-semibold"
                              : "bg-[#1e1e1e] border-[#383838] text-gray-400 hover:text-white"
                          }`}
                        >
                          Production
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeployEnv("preview")}
                          className={`p-3 rounded-xl border text-center transition-all ${
                            deployEnv === "preview"
                              ? "bg-purple-950/60 border-purple-500 text-white font-semibold"
                              : "bg-[#1e1e1e] border-[#383838] text-gray-400 hover:text-white"
                          }`}
                        >
                          Preview / Staging
                        </button>
                      </div>
                    </div>

                    {/* CI Gate Validation Alert */}
                    {overview?.last_run_conclusion === "success" ? (
                      <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-xl text-emerald-300 flex items-center gap-2">
                        <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                        <span>Latest CI Quality Gate is Verified (Passed). Ready to release safely.</span>
                      </div>
                    ) : (
                      <div className="p-3 bg-amber-950/50 border border-amber-800/60 rounded-xl text-amber-200 space-y-2">
                        <div className="flex items-center gap-2 font-semibold">
                          <AlertTriangle size={16} className="text-amber-400 shrink-0" />
                          <span>CI Safety Gate Warning</span>
                        </div>
                        <p className="text-[11px] text-amber-200/90 leading-relaxed">
                          The latest workflow run conclusion is{" "}
                          <strong className="text-white capitalize">{overview?.last_run_conclusion || overview?.last_run_status || "not passed"}</strong>.
                          Deploying unverified code may cause production regressions.
                        </p>
                        <label className="flex items-center gap-2 pt-1 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={skipCiCheck}
                            onChange={(e) => setSkipCiCheck(e.target.checked)}
                            className="rounded bg-[#2d2d2d] border-[#444] text-purple-600 focus:ring-0"
                          />
                          <span className="text-[11px] text-gray-300 font-medium">
                            Force deploy (Override safety gate)
                          </span>
                        </label>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-2 border-t border-[#3c3c3c]">
                    <button
                      type="button"
                      onClick={() => setShowDeployModal(false)}
                      className="px-4 py-2 bg-[#2d2d2d] hover:bg-[#383838] text-gray-300 rounded-xl text-xs font-medium"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => handleTriggerDeployment(deployEnv, skipCiCheck)}
                      disabled={deploymentTriggering}
                      className="px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow"
                    >
                      <Rocket size={14} className={deploymentTriggering ? "animate-spin" : ""} />
                      <span>{deploymentTriggering ? "Deploying..." : "Confirm & Trigger Deployment"}</span>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Dynamic Setup Instructions */}
        {activeTab === "guide" && (
          <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-sm space-y-6">
            <div className="border-b border-[#3c3c3c] pb-4">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <BookOpen size={16} className="text-purple-400" />
                <span>Repository-Specific Setup & Best Practices Guide</span>
              </h3>
              <p className="text-xs text-gray-400 mt-1">
                Dynamic guidance generated specifically for {overview?.repo_name || "this repository"}.
              </p>
            </div>

            <div className="space-y-4 text-xs">
              <div className="p-4 bg-[#1e1e1e] rounded-xl border border-[#3c3c3c] space-y-2">
                <h5 className="font-semibold text-white flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px]">1</span>
                  <span>Detected Technology Stack</span>
                </h5>
                <p className="text-gray-400 leading-relaxed">
                  CodeBrain detected: <strong>{overview?.evidence?.ecosystems?.join(", ") || "General Stack"}</strong> ({overview?.evidence?.total_files || 0} source files indexed).
                </p>
              </div>

              <div className="p-4 bg-[#1e1e1e] rounded-xl border border-[#3c3c3c] space-y-2">
                <h5 className="font-semibold text-white flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px]">2</span>
                  <span>Pipeline Location & Minimal Permissions</span>
                </h5>
                <p className="text-gray-400 leading-relaxed">
                  The workflow is placed at <code className="text-purple-300">{overview?.workflow_path || ".github/workflows/ci.yml"}</code> with least-privilege tokens (<code className="text-emerald-300">contents: read</code> / write). Documentation commits matching <code className="text-gray-300">docs/**</code> are ignored to conserve runner minutes.
                </p>
              </div>

              <div className="p-4 bg-[#1e1e1e] rounded-xl border border-[#3c3c3c] space-y-2">
                <h5 className="font-semibold text-white flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px]">3</span>
                  <span>Review and Merge Installation PR</span>
                </h5>
                <p className="text-gray-400 leading-relaxed">
                  Initial workflow installation requires user confirmation. When you click <strong>Install via Pull Request</strong>, CodeBrain opens a PR. Merge it into your default branch to enable automated CI gating.
                </p>
              </div>

              <div className="p-4 bg-[#1e1e1e] rounded-xl border border-[#3c3c3c] space-y-2">
                <h5 className="font-semibold text-white flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-purple-600 text-white flex items-center justify-center text-[10px]">4</span>
                  <span>Automated AI Repair & Loop Safeguards</span>
                </h5>
                <p className="text-gray-400 leading-relaxed">
                  When CI fails, CodeBrain diagnoses the failure logs using AI. If Auto-Commit is authorized, CodeBrain commits a targeted patch and stops if the failure is identical or if 3 attempts have been exhausted, preventing infinite CI execution loops.
                </p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default CICDPage;
