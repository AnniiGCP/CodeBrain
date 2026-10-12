/**
 * IssuesPanel.tsx
 * ─────────────────
 * Grid panel rendering ErrorSuggestionCards for a repository.
 * Polls every 5 s while any card is PENDING/GENERATING.
 */

import { useState, useEffect, useCallback } from "react";
import type { RepoSummary, ErrorReport, FixStatus } from "../types";
import { fetchErrorReports } from "../api";
import ErrorSuggestionCard from "./ErrorSuggestionCard";

interface Props {
  repo: RepoSummary;
}

type SevFilter    = "all" | "error" | "warning" | "info";
type StatusFilter = "all" | "PENDING" | "READY_TO_APPLY" | "APPLIED" | "FAILED" | "REJECTED";

export default function IssuesPanel({ repo }: Props) {
  const [reports, setReports]         = useState<ErrorReport[]>([]);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState<string | null>(null);
  const [sevFilter, setSevFilter]     = useState<SevFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await fetchErrorReports(repo.repo_id);
      setReports(data.errors);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [repo.repo_id]);

  // Initial load
  useEffect(() => { load(); }, [load]);

  const handleStatusChange = useCallback((id: string, newStatus: FixStatus) => {
    setReports(prev => prev.map(r => r.id === id ? { ...r, fix_status: newStatus } : r));
  }, []);

  // ── Filters ──────────────────────────────────────────────────────────────────
  const filtered = reports.filter(r => {
    if (sevFilter !== "all" && r.severity !== sevFilter) return false;
    if (statusFilter !== "all") {
      if (statusFilter === "APPLIED") {
        if (r.fix_status !== "APPLIED" && r.fix_status !== "APPLIED_LOCAL" && r.fix_status !== "OPEN") return false;
      } else if (statusFilter === "FAILED") {
        if (r.fix_status !== "FAILED" && r.fix_status !== "SANDBOX_FAILED") return false;
      } else if (statusFilter === "READY_TO_APPLY") {
        if (r.fix_status !== "READY" && r.fix_status !== "READY_TO_APPLY") return false;
      } else if (statusFilter === "PENDING") {
        if (r.fix_status !== "PENDING" && r.fix_status !== "GENERATING") return false;
      } else if (r.fix_status !== statusFilter) {
        return false;
      }
    }
    return true;
  });

  // ── Stats ─────────────────────────────────────────────────────────────────────
  const errCount  = reports.filter(r => r.severity === "error").length;
  const warnCount = reports.filter(r => r.severity === "warning").length;
  const infoCount = reports.filter(r => r.severity === "info").length;
  const fixedCount    = reports.filter(r => r.fix_status === "APPLIED" || r.fix_status === "APPLIED_LOCAL" || r.fix_status === "OPEN").length;
  const pendingCount  = reports.filter(r => r.fix_status === "PENDING" || r.fix_status === "GENERATING").length;
  const readyCount    = reports.filter(r => r.fix_status === "READY" || r.fix_status === "READY_TO_APPLY").length;
  const failedCount   = reports.filter(r => r.fix_status === "FAILED" || r.fix_status === "SANDBOX_FAILED").length;

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8">
        <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-gray-400 text-sm animate-pulse">Loading issues…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <div className="text-4xl">⚠️</div>
        <p className="text-red-300 text-sm max-w-sm">{error}</p>
        <button
          onClick={() => load()}
          className="px-4 py-2 bg-red-700 hover:bg-red-600 rounded-xl text-sm transition-colors"
        >
          ↻ Retry
        </button>
      </div>
    );
  }

  if (reports.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <div className="w-16 h-16 rounded-2xl bg-emerald-900/20 border border-emerald-700/40 flex items-center justify-center text-3xl">
          ✅
        </div>
        <div>
          <p className="text-white font-semibold">No issues detected</p>
          <p className="text-gray-400 text-sm mt-1">The scanner found no code issues in this repository.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* ── Summary banner ── */}
      <div className="px-5 py-3 border-b border-gray-800 bg-gray-900/40 shrink-0">
        <div className="flex flex-wrap items-center gap-4">
          {/* Issue counts */}
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-400 font-medium">{reports.length} issues detected</span>
            {errCount > 0  && <span className="text-red-400">🔴 {errCount} error{errCount !== 1 ? "s" : ""}</span>}
            {warnCount > 0 && <span className="text-amber-400">🟡 {warnCount} warning{warnCount !== 1 ? "s" : ""}</span>}
            {infoCount > 0 && <span className="text-blue-400">🔵 {infoCount} info</span>}
          </div>

          <div className="h-4 border-r border-gray-700 hidden sm:block" />

          {/* Fix status counts */}
          <div className="flex items-center gap-3 text-xs text-gray-500">
            {pendingCount > 0 && <span className="text-amber-400">⏳ {pendingCount} pending</span>}
            {readyCount > 0   && <span className="text-blue-300">⚡ {readyCount} ready to apply</span>}
            {fixedCount > 0   && <span className="text-emerald-400">✅ {fixedCount} fixed</span>}
            {failedCount > 0  && <span className="text-red-400">❌ {failedCount} failed</span>}
          </div>

          {/* Refresh button */}
          <button
            onClick={() => load(true)}
            className="ml-auto text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1 transition-colors"
          >
            ↻ Refresh
          </button>
        </div>

        {/* ── Filters ── */}
        <div className="flex flex-wrap gap-2 mt-3">
          {/* Severity filter */}
          <div className="flex items-center gap-1">
            {(["all", "error", "warning", "info"] as SevFilter[]).map(sev => (
              <button
                key={sev}
                onClick={() => setSevFilter(sev)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  sevFilter === sev
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800/60 text-gray-400 hover:text-white hover:bg-gray-700/60"
                }`}
              >
                {sev === "all" ? "All Severity" : sev.charAt(0).toUpperCase() + sev.slice(1)}
              </button>
            ))}
          </div>

          <div className="h-5 border-r border-gray-700 self-center hidden sm:block" />

          {/* Status filter */}
          <div className="flex items-center gap-1">
            {([
              ["all", "All Status"],
              ["PENDING", "⏳ Pending"],
              ["READY_TO_APPLY", "⚡ Ready"],
              ["APPLIED", "✅ Fixed"],
              ["FAILED", "❌ Failed"],
            ] as [StatusFilter, string][]).map(([st, label]) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  statusFilter === st
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800/60 text-gray-400 hover:text-white hover:bg-gray-700/60"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Card grid ── */}
      <div className="flex-1 overflow-y-auto p-5">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
            <div className="text-3xl opacity-40">🔍</div>
            <p className="text-gray-500 text-sm">No issues match the current filters.</p>
            <button
              onClick={() => { setSevFilter("all"); setStatusFilter("all"); }}
              className="text-xs text-blue-400 hover:text-blue-300 underline"
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 items-start">
            {filtered.map(report => (
              <ErrorSuggestionCard
                key={report.id}
                report={report}
                repoId={repo.repo_id}
                onStatusChange={handleStatusChange}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
