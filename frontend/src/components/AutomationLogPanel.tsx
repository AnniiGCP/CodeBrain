import { useState, useEffect, useCallback, useRef } from "react";
import type { RepoSummary, AutomationLogResponse, AutomationLogEntry, AutomationStage } from "../types";
import { fetchAutomationLog } from "../api";

interface AutomationLogPanelProps {
  repo: RepoSummary;
}

const STAGE_CONFIG: Record<
  AutomationStage | string,
  { label: string; icon: string; color: string; badgeBg: string }
> = {
  DETECTED: {
    label: "Issue Detected",
    icon: "🔍",
    color: "text-amber-400 border-amber-500/30",
    badgeBg: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  },
  FIX_GENERATED: {
    label: "Fix Generated",
    icon: "⚡",
    color: "text-blue-400 border-blue-500/30",
    badgeBg: "bg-blue-500/10 text-blue-300 border-blue-500/30",
  },
  SANDBOX_PASSED: {
    label: "Sandbox Passed",
    icon: "✅",
    color: "text-emerald-400 border-emerald-500/30",
    badgeBg: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  },
  SANDBOX_FAILED: {
    label: "Sandbox Failed",
    icon: "❌",
    color: "text-rose-400 border-rose-500/30",
    badgeBg: "bg-rose-500/10 text-rose-300 border-rose-500/30",
  },
  BRANCH_PUSHED: {
    label: "Branch Pushed",
    icon: "🌿",
    color: "text-cyan-400 border-cyan-500/30",
    badgeBg: "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
  },
  PR_OPENED: {
    label: "PR Opened (Auto-Merge)",
    icon: "🚀",
    color: "text-indigo-400 border-indigo-500/30",
    badgeBg: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  },
  PIPELINE_PASSED: {
    label: "CI Pipeline Passed",
    icon: "✨",
    color: "text-teal-400 border-teal-500/30",
    badgeBg: "bg-teal-500/10 text-teal-300 border-teal-500/30",
  },
  PIPELINE_FAILED: {
    label: "CI Pipeline Failed",
    icon: "⚠️",
    color: "text-red-400 border-red-500/30",
    badgeBg: "bg-red-500/10 text-red-300 border-red-500/30",
  },
  MERGED: {
    label: "Merged to Main",
    icon: "🔀",
    color: "text-purple-400 border-purple-500/30",
    badgeBg: "bg-purple-500/10 text-purple-300 border-purple-500/30",
  },
  SKIPPED: {
    label: "Skipped",
    icon: "⏭️",
    color: "text-gray-400 border-gray-500/30",
    badgeBg: "bg-gray-500/10 text-gray-400 border-gray-500/30",
  },
};

export default function AutomationLogPanel({ repo }: AutomationLogPanelProps) {
  const [data, setData] = useState<AutomationLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStage, setFilterStage] = useState<string>("ALL");
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadLogs = useCallback(
    async (showLoading = false) => {
      if (showLoading) setLoading(true);
      try {
        const res = await fetchAutomationLog(repo.repo_id);
        setData(res);
        setError(null);
      } catch (err: any) {
        setError(err.message || "Failed to load automation logs");
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [repo.repo_id]
  );

  useEffect(() => {
    loadLogs(true);
  }, [loadLogs]);

  useEffect(() => {
    if (!autoRefresh) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      return;
    }
    pollTimerRef.current = setInterval(() => {
      loadLogs(false);
    }, 3000);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [autoRefresh, loadLogs]);

  const summary = data?.summary;
  const logs = data?.logs || [];

  const filteredLogs = logs.filter((l) => {
    if (filterStage === "ALL") return true;
    if (filterStage === "ERRORS") return l.outcome === "FAILED";
    if (filterStage === "PRS") return ["PR_OPENED", "PIPELINE_PASSED", "MERGED"].includes(l.stage);
    return l.stage === filterStage;
  });

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-950 text-gray-100 overflow-hidden font-sans">
      {/* ── Top Bar ── */}
      <div className="px-6 py-4 border-b border-gray-800/80 bg-gray-900/60 backdrop-blur-md flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">🤖</span>
            <h1 className="text-base font-bold text-white tracking-wide">Automated Fix &amp; CI Pipeline Log</h1>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30">
              Zero-Touch CI Gate
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            Real-time audit log of auto-generated fixes, sandboxed test runs, GitHub branches, and CI-gated auto-merges.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer bg-gray-800/80 border border-gray-700/80 px-3 py-1.5 rounded-lg hover:bg-gray-800 transition-colors">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-600 text-blue-500 focus:ring-0 focus:ring-offset-0"
            />
            <span>Live Polling</span>
            {autoRefresh && <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />}
          </label>

          <button
            onClick={() => loadLogs(true)}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-200 transition-colors flex items-center gap-1.5"
          >
            <span>🔄</span> Refresh
          </button>
        </div>
      </div>

      {/* ── Metrics Cards ── */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-6 border-b border-gray-800/60 bg-gray-900/30 shrink-0">
          <div className="bg-gray-900/80 border border-gray-800 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Issues Scanned</p>
            <p className="text-xl font-bold text-white mt-1">{summary.total_issues}</p>
            <p className="text-[11px] text-gray-500 mt-0.5">{summary.auto_fix_attempted} attempted</p>
          </div>

          <div className="bg-gray-900/80 border border-emerald-900/40 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">Sandbox Passed</p>
            <p className="text-xl font-bold text-emerald-300 mt-1">{summary.sandbox_passed}</p>
            <p className="text-[11px] text-emerald-500/80 mt-0.5">Isolated test suites ✓</p>
          </div>

          <div className="bg-gray-900/80 border border-rose-900/40 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-rose-400 uppercase tracking-wider">Sandbox Failed</p>
            <p className="text-xl font-bold text-rose-300 mt-1">{summary.sandbox_failed}</p>
            <p className="text-[11px] text-rose-500/80 mt-0.5">0 commits created</p>
          </div>

          <div className="bg-gray-900/80 border border-indigo-900/40 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-indigo-400 uppercase tracking-wider">PRs Opened</p>
            <p className="text-xl font-bold text-indigo-300 mt-1">{summary.prs_opened}</p>
            <p className="text-[11px] text-indigo-400/80 mt-0.5">Auto-complete on</p>
          </div>

          <div className="bg-gray-900/80 border border-teal-900/40 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-teal-400 uppercase tracking-wider">Auto-Merged</p>
            <p className="text-xl font-bold text-teal-300 mt-1">{summary.merged}</p>
            <p className="text-[11px] text-teal-400/80 mt-0.5">CI gate passed ✓</p>
          </div>

          <div className="bg-gray-900/80 border border-red-900/40 rounded-xl p-3">
            <p className="text-[11px] font-semibold text-red-400 uppercase tracking-wider">CI Failed</p>
            <p className="text-xl font-bold text-red-400 mt-1">{summary.pipeline_failed}</p>
            <p className="text-[11px] text-red-500/80 mt-0.5">Auto-merge blocked</p>
          </div>
        </div>
      )}

      {/* ── Filters & Controls ── */}
      <div className="px-6 py-2.5 bg-gray-900/40 border-b border-gray-800/60 flex items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-1.5 overflow-x-auto py-1">
          <span className="text-xs font-semibold text-gray-400 mr-1">Filter:</span>
          {(
            [
              ["ALL", "All Events"],
              ["PRS", "PRs & Merges"],
              ["SANDBOX_PASSED", "Sandbox Passed"],
              ["SANDBOX_FAILED", "Sandbox Failed"],
              ["ERRORS", "Failures Only"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilterStage(key)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                filterStage === key
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-gray-800/80 text-gray-300 hover:bg-gray-700 hover:text-white border border-gray-700/60"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-500 shrink-0">
          Showing {filteredLogs.length} of {logs.length} entries
        </span>
      </div>

      {/* ── Timeline Log Content ── */}
      <div className="flex-1 overflow-y-auto p-6 space-y-3">
        {loading && logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-12 h-12 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-2xl animate-spin">
              ⚙️
            </div>
            <p className="text-sm font-semibold text-gray-300 mt-4">Loading automation pipeline events…</p>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-950/40 border border-red-800/60 rounded-xl text-red-300 text-sm">
            ❌ {error}
          </div>
        ) : filteredLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 rounded-2xl bg-gray-800/80 border border-gray-700/80 flex items-center justify-center text-3xl mb-3">
              📋
            </div>
            <p className="text-sm font-semibold text-gray-300">No automation log entries yet</p>
            <p className="text-xs text-gray-500 mt-1 max-w-sm">
              The automated fix pipeline runs automatically after error detection. Once code issues are scanned,
              fixes will be generated, sandbox-validated, and pushed to PRs.
            </p>
          </div>
        ) : (
          <div className="relative pl-6 space-y-4 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-gray-800">
            {filteredLogs.map((log: AutomationLogEntry) => {
              const cfg = STAGE_CONFIG[log.stage] || {
                label: log.stage,
                icon: "📌",
                color: "text-gray-400 border-gray-600",
                badgeBg: "bg-gray-800 text-gray-300 border-gray-700",
              };
              const isExpanded = expandedLogId === log.id;
              const hasDetails = Boolean(log.details);
              const prMatch = log.details && (log.details.startsWith("http://") || log.details.startsWith("https://"));

              return (
                <div
                  key={log.id}
                  className="relative group bg-gray-900/70 hover:bg-gray-900 border border-gray-800 hover:border-gray-700/80 rounded-xl p-4 transition-all shadow-sm"
                >
                  {/* Timeline dot */}
                  <div
                    className={`absolute -left-6 top-4 w-5 h-5 rounded-full bg-gray-950 border flex items-center justify-center text-[10px] ${cfg.color}`}
                  >
                    {cfg.icon}
                  </div>

                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`px-2 py-0.5 text-[11px] font-semibold rounded-md border ${cfg.badgeBg}`}>
                          {cfg.icon} {cfg.label}
                        </span>

                        <span
                          className={`px-2 py-0.5 text-[10px] font-bold rounded-md uppercase tracking-wider ${
                            log.outcome === "SUCCESS"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              : log.outcome === "FAILED"
                              ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                              : "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                          }`}
                        >
                          {log.outcome}
                        </span>

                        {log.created_at && (
                          <span className="text-[11px] text-gray-500">
                            {new Date(log.created_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })}
                          </span>
                        )}
                      </div>

                      <p className="text-sm font-medium text-gray-100 mt-2 leading-relaxed break-words">
                        {log.message}
                      </p>
                    </div>

                    {/* PR Link button if this event has a PR url */}
                    {prMatch && (
                      <a
                        href={log.details!}
                        target="_blank"
                        rel="noreferrer"
                        className="shrink-0 px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 hover:text-indigo-200 border border-indigo-500/30 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5"
                      >
                        <span>Inspect PR</span>
                        <span>↗</span>
                      </a>
                    )}
                  </div>

                  {/* Expandable details (diffs, test outputs, etc.) */}
                  {hasDetails && !prMatch && (
                    <div className="mt-3">
                      <button
                        onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                        className="text-xs text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1 transition-colors"
                      >
                        <span>{isExpanded ? "▾ Hide Details" : "▸ View Sandbox Output / Diff"}</span>
                      </button>

                      {isExpanded && (
                        <div className="mt-2 p-3 bg-gray-950 border border-gray-800 rounded-lg overflow-x-auto max-h-60 text-xs font-mono text-gray-300 whitespace-pre-wrap leading-normal">
                          {log.details}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
