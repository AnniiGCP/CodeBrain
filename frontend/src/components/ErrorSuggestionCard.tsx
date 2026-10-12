/**
 * ErrorSuggestionCard.tsx
 * ─────────────────────────
 * Sticky-note card for a single ErrorReport.
 * States:
 *   PENDING               → Initial detected state, "Fix it" active
 *   READY_TO_APPLY        → Propose & sandbox passed, ready to apply
 *   APPLIED / APPLIED_LOCAL / OPEN → Green success card + PR info / DiffViewer
 *   FAILED / SANDBOX_FAILED        → Red failure card + sandbox details & retry
 *   REJECTED              → Muted dismissed card
 *
 * Flow:
 *   Single click on "Fix it" sequentially calls:
 *     1. POST /generate-fix (generates diff + runs sandbox test validation)
 *     2. POST /apply-fix (if sandbox passed -> disk patch for zip or branch + PR + auto-merge for git)
 *   If sandbox fails, flow halts before apply, card turns red, and failure details are displayed.
 */

import { useState, useCallback } from "react";
import type { ErrorReport, FixStatus } from "../types";
import { generateErrorFix, applyErrorFix, rejectErrorFix, regenerateErrorFix } from "../api";
import DiffViewer from "./DiffViewer";

interface Props {
  report: ErrorReport;
  repoId: string;
  /** Called after fix_status changes so the parent can refresh its list */
  onStatusChange?: (id: string, newStatus: ErrorReport["fix_status"]) => void;
}

// ── Severity colours ──────────────────────────────────────────────────────────
const SEV_BORDER: Record<string, string> = {
  error:   "border-l-red-500",
  warning: "border-l-amber-400",
  info:    "border-l-blue-400",
};
const SEV_BADGE: Record<string, string> = {
  error:   "bg-red-900/50 text-red-300 ring-1 ring-red-700/50",
  warning: "bg-amber-900/40 text-amber-300 ring-1 ring-amber-600/40",
  info:    "bg-blue-900/40 text-blue-300 ring-1 ring-blue-600/40",
};
const SEV_LABEL: Record<string, string> = {
  error:   "Error",
  warning: "Warning",
  info:    "Info",
};

// ── Status overlay colours (card background) ──────────────────────────────────
const STATUS_BG: Record<string, string> = {
  APPLIED:        "bg-gradient-to-br from-emerald-950/80 to-green-900/40 border-emerald-700/60",
  APPLIED_LOCAL:  "bg-gradient-to-br from-emerald-950/80 to-green-900/40 border-emerald-700/60",
  FIX_APPLIED:    "bg-gradient-to-br from-emerald-950/80 to-green-900/40 border-emerald-700/60",
  OPEN:           "bg-gradient-to-br from-indigo-950/80 to-teal-900/30 border-teal-700/60",
  FAILED:         "bg-gradient-to-br from-red-950/80 to-rose-900/30 border-red-700/60",
  PATCH_GENERATION_FAILED: "bg-gradient-to-br from-red-950/80 to-rose-900/30 border-red-700/60",
  PATCH_APPLICATION_FAILED: "bg-gradient-to-br from-red-950/80 to-rose-900/30 border-red-700/60",
  SANDBOX_FAILED: "bg-gradient-to-br from-red-950/80 to-rose-900/30 border-red-700/60",
  ENVIRONMENT_FAILED: "bg-gradient-to-br from-amber-950/80 to-yellow-900/30 border-amber-700/60",
  REJECTED:       "bg-gray-900/60 border-gray-700/40 opacity-60",
  PENDING:        "bg-gray-900/70 border-gray-700/50",
  GENERATING:     "bg-gray-900/70 border-gray-700/50",
  READY:          "bg-gray-900/70 border-gray-700/50",
  READY_TO_APPLY: "bg-gray-900/70 border-blue-700/50",
  PATCH_GENERATED: "bg-gray-900/70 border-blue-700/50",
};

// ── File name helper ──────────────────────────────────────────────────────────
function basename(path: string) {
  return path.split("/").pop() ?? path;
}

export default function ErrorSuggestionCard({ report: initialReport, repoId, onStatusChange }: Props) {
  const [report, setReport]         = useState<ErrorReport>(initialReport);
  const [loading, setLoading]       = useState(false);
  const [loadingMsg, setLoadingMsg] = useState<string>("Processing…");
  const [diffOpen, setDiffOpen]     = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  // Sync when parent refreshes the prop
  const currentReport = report;

  // Single-click combined Fix Action: generate-fix -> static format check -> apply-fix
  const handleFixIt = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setApplyError(null);

    try {
      // Step 1: Generate fix (format & safety validated statically)
      setLoadingMsg("Generating fix…");
      const genRes = await generateErrorFix(repoId, currentReport.id);

      if (!genRes.passed || genRes.fix_status === "FAILED" || genRes.fix_status === "PATCH_GENERATION_FAILED" || !genRes.suggested_fix) {
        const failMsg = genRes.error || genRes.output || "Failed to generate fix.";
        const failedReport: ErrorReport = {
          ...currentReport,
          fix_status: "FAILED",
          fix_error: failMsg,
          explanation: genRes.explanation || currentReport.explanation,
          suggested_fix: genRes.suggested_fix || currentReport.suggested_fix,
          fix_model: genRes.model_used || currentReport.fix_model,
          fix_provider: genRes.provider_used || currentReport.fix_provider,
          fix_attribution: genRes.fix_attribution || currentReport.fix_attribution,
          fix_attempts: genRes.attempts || currentReport.fix_attempts,
          provider_used: genRes.provider_used || currentReport.provider_used,
          model_used: genRes.model_used || currentReport.model_used,
          fallback_used: genRes.fallback_used,
          patch_status: "PATCH_GENERATION_FAILED",
          validation_status: "NOT_RUN",
          validation_skipped: true,
        };
        setReport(failedReport);
        setApplyError(failMsg);
        setDetailOpen(true);
        onStatusChange?.(currentReport.id, "FAILED");
        return;
      }

      // Step 2: Apply fix directly to disk or git PR
      setLoadingMsg("Applying fix…");
      const applyRes = await applyErrorFix(repoId, currentReport.id);

      const appliedReport: ErrorReport = {
        ...currentReport,
        fix_status: applyRes.fix_status,
        patch_status: "FIX_APPLIED",
        validation_status: "NOT_RUN",
        validation_skipped: true,
        validation_notice: applyRes.validation_notice || "Execution-based validation was skipped. Review the diff and run tests manually before relying on this change.",
        pr_status: applyRes.pr_status || currentReport.pr_status,
        branch_name: applyRes.branch_name || currentReport.branch_name,
        pr_url: applyRes.pr_url || currentReport.pr_url,
        pr_id: applyRes.pr_id || currentReport.pr_id,
        explanation: genRes.explanation || currentReport.explanation,
        suggested_fix: genRes.suggested_fix || currentReport.suggested_fix,
        fix_model: genRes.model_used || currentReport.fix_model,
        fix_provider: genRes.provider_used || currentReport.fix_provider,
        fix_attribution: genRes.fix_attribution || currentReport.fix_attribution,
        fix_attempts: genRes.attempts || currentReport.fix_attempts,
        provider_used: genRes.provider_used || currentReport.provider_used,
        model_used: genRes.model_used || currentReport.model_used,
        fallback_used: genRes.fallback_used,
        fix_error: null,
      };

      setReport(appliedReport);
      onStatusChange?.(currentReport.id, applyRes.fix_status);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setApplyError(msg);
      setDetailOpen(true);
      const errReport = { ...currentReport, fix_status: "FAILED" as FixStatus, fix_error: msg };
      setReport(errReport);
      onStatusChange?.(currentReport.id, "FAILED");
    } finally {
      setLoading(false);
    }
  }, [currentReport, loading, repoId, onStatusChange]);

  const handleReject = useCallback(async () => {
    try {
      await rejectErrorFix(repoId, currentReport.id);
      const updated = { ...currentReport, fix_status: "REJECTED" as const };
      setReport(updated);
      onStatusChange?.(currentReport.id, "REJECTED");
    } catch {
      // silently ignore
    }
  }, [currentReport, repoId, onStatusChange]);

  const handleRegenerate = useCallback(async () => {
    try {
      await regenerateErrorFix(repoId, currentReport.id);
      const updated = { ...currentReport, fix_status: "PENDING" as const, suggested_fix: null, explanation: null, fix_error: null };
      setReport(updated);
      setApplyError(null);
      onStatusChange?.(currentReport.id, "PENDING");
    } catch {
      // silently ignore
    }
  }, [currentReport, repoId, onStatusChange]);

  const isApplied    = currentReport.fix_status === "APPLIED" || currentReport.fix_status === "APPLIED_LOCAL" || currentReport.fix_status === "FIX_APPLIED" || currentReport.fix_status === "OPEN";
  const isFailed     = currentReport.fix_status === "FAILED" || currentReport.fix_status === "PATCH_GENERATION_FAILED" || currentReport.fix_status === "PATCH_APPLICATION_FAILED" || currentReport.fix_status === "SANDBOX_FAILED" || currentReport.fix_status === "ENVIRONMENT_FAILED";
  const isRejected   = currentReport.fix_status === "REJECTED";
  const isPending    = currentReport.fix_status === "PENDING";
  const isReady      = currentReport.fix_status === "READY" || currentReport.fix_status === "READY_TO_APPLY" || currentReport.fix_status === "PATCH_GENERATED";

  const cardBg = STATUS_BG[currentReport.fix_status] ?? STATUS_BG.PENDING;

  return (
    <div
      className={`
        relative rounded-2xl border-l-4 border p-4 flex flex-col gap-3 shadow-lg
        transition-all duration-500 backdrop-blur-sm
        ${SEV_BORDER[currentReport.severity] ?? "border-l-gray-500"}
        ${cardBg}
      `}
      style={{ minHeight: "160px" }}
    >
      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 rounded-2xl bg-gray-950/70 backdrop-blur-sm flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-2 p-4 text-center">
            <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-blue-300 font-medium">{loadingMsg}</span>
          </div>
        </div>
      )}

      {/* ── Header row ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          {/* Severity badge */}
          <span className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${SEV_BADGE[currentReport.severity]}`}>
            {SEV_LABEL[currentReport.severity]}
          </span>
          {/* Rule ID */}
          <span className="text-[10px] font-mono text-gray-500 bg-gray-800/60 px-1.5 py-0.5 rounded">
            {currentReport.rule_id}
          </span>
        </div>

        {/* Status indicator */}
        <div className="shrink-0">
          {(currentReport.fix_status === "APPLIED" || currentReport.fix_status === "APPLIED_LOCAL" || currentReport.fix_status === "FIX_APPLIED") && (
            <span className="flex items-center gap-1 text-xs font-semibold text-emerald-400 bg-emerald-900/40 px-2 py-0.5 rounded-full ring-1 ring-emerald-600/40">
              ✅ Fix Applied
            </span>
          )}
          {currentReport.fix_status === "OPEN" && (
            <span className="flex items-center gap-1 text-xs font-semibold text-teal-300 bg-teal-900/40 px-2 py-0.5 rounded-full ring-1 ring-teal-600/40">
              🚀 PR Opened
            </span>
          )}
          {currentReport.fix_status === "ENVIRONMENT_FAILED" && (
            <span className="flex items-center gap-1 text-xs font-semibold text-amber-300 bg-amber-900/40 px-2 py-0.5 rounded-full ring-1 ring-amber-600/40" title={currentReport.failure_type || "Environment issue"}>
              ⚠️ Environment Issue
            </span>
          )}
          {currentReport.fix_status === "SANDBOX_FAILED" && (
            <span className="flex items-center gap-1 text-xs font-semibold text-red-300 bg-red-900/40 px-2 py-0.5 rounded-full ring-1 ring-red-600/40">
              ❌ Sandbox Failed
            </span>
          )}
          {currentReport.fix_status === "FAILED" && (
            <span className="flex items-center gap-1 text-xs font-semibold text-red-300 bg-red-900/40 px-2 py-0.5 rounded-full ring-1 ring-red-600/40">
              ❌ Failed
            </span>
          )}
          {isRejected && (
            <span className="text-xs text-gray-500 italic">Dismissed</span>
          )}
          {isPending && (
            <span className="flex items-center gap-1 text-xs text-amber-400/90 font-medium">
              ⏳ Pending Action
            </span>
          )}
          {isReady && (
            <span className="text-xs text-blue-300 font-medium">✓ Ready</span>
          )}
        </div>
      </div>

      {/* ── File path + line ── */}
      <div className="flex items-center gap-2 text-xs text-gray-400 min-w-0">
        <span className="text-gray-600">📄</span>
        <span className="font-mono truncate" title={currentReport.file_path}>
          {basename(currentReport.file_path)}
        </span>
        {currentReport.line != null && (
          <span className="shrink-0 text-gray-600">:{currentReport.line}</span>
        )}
        {currentReport.symbol_name && (
          <span className="shrink-0 text-gray-600 truncate">
            in <span className="text-gray-300 font-mono">{currentReport.symbol_name}</span>
          </span>
        )}
      </div>

      {/* ── Error message ── */}
      <p className="text-sm text-white/90 leading-relaxed">
        {currentReport.message}
      </p>

      {/* ── AI Explanation ── */}
      {currentReport.explanation && (
        <p className="text-xs text-gray-400 leading-relaxed border-t border-white/5 pt-2">
          {currentReport.explanation}
        </p>
      )}

      {/* ── Applied: diff viewer ── */}
      {isApplied && currentReport.suggested_fix && (
        <div className="border-t border-emerald-700/30 pt-2 space-y-2">
          <button
            onClick={() => setDiffOpen(v => !v)}
            className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center gap-1 transition-colors"
          >
            <span className={`transition-transform ${diffOpen ? "rotate-90" : ""}`}>▶</span>
            {diffOpen ? "Collapse diff" : "View applied diff"}
          </button>
          {diffOpen && (
            <div className="mt-2">
              <DiffViewer diff={currentReport.suggested_fix} fileName={basename(currentReport.file_path)} />
            </div>
          )}
        </div>
      )}

      {/* ── PR Info / GitOps Details ── */}
      {currentReport.pr_url && (
        <div className="border-t border-indigo-700/30 pt-2 flex items-center justify-between gap-2 bg-indigo-950/20 -mx-4 px-4 py-2 rounded-lg">
          <div className="min-w-0 flex-1 text-xs">
            <p className="font-semibold text-indigo-300 flex items-center gap-1.5 truncate">
              <span>🚀</span>
              <span>PR #{currentReport.pr_id || "Auto"}</span>
              {currentReport.pr_status === "MERGED" && (
                <span className="px-1.5 py-0.2 text-[10px] font-bold rounded bg-teal-500/20 text-teal-300 border border-teal-500/30">
                  MERGED
                </span>
              )}
              {currentReport.pr_status === "FAILED_PIPELINE" && (
                <span className="px-1.5 py-0.2 text-[10px] font-bold rounded bg-red-500/20 text-red-300 border border-red-500/30">
                  CI FAILED
                </span>
              )}
              {(currentReport.pr_status === "OPEN" || currentReport.pr_status === "OPEN_AUTO_MERGE_ENABLED") && (
                <span className="px-1.5 py-0.2 text-[10px] font-bold rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 animate-pulse">
                  AUTO-MERGE ENABLED
                </span>
              )}
              {currentReport.pr_status === "OPEN_MANUAL_MERGE_REQUIRED" && (
                <span className="px-1.5 py-0.2 text-[10px] font-bold rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  MANUAL MERGE
                </span>
              )}
            </p>
            {currentReport.branch_name && (
              <p className="text-[10px] font-mono text-gray-400 truncate mt-0.5">
                {currentReport.branch_name}
              </p>
            )}
          </div>
          <a
            href={currentReport.pr_url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 px-2.5 py-1 text-[11px] font-semibold bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-200 border border-indigo-500/40 rounded-lg transition-colors flex items-center gap-1"
          >
            <span>PR</span>
            <span>↗</span>
          </a>
        </div>
      )}

      {/* ── Failed: error message & retry ── */}
      {isFailed && (
        <div className="border-t border-red-700/30 pt-2 space-y-1">
          <button
            onClick={() => setDetailOpen(v => !v)}
            className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1 transition-colors"
          >
            <span className={`transition-transform ${detailOpen ? "rotate-90" : ""}`}>▶</span>
            {detailOpen ? "Hide failure details" : "View failure details"}
          </button>
          {detailOpen && (
            <pre className="mt-2 text-[10px] text-red-200/80 bg-red-950/50 rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all border border-red-800/40">
              {applyError ?? currentReport.fix_error ?? "Unknown failure"}
            </pre>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleFixIt}
              className="text-xs text-amber-400 hover:text-amber-300 flex items-center gap-1 transition-colors font-medium"
            >
              ↻ Retry Fix
            </button>
            <span className="text-gray-600">•</span>
            <button
              onClick={handleRegenerate}
              className="text-xs text-gray-400 hover:text-gray-300 transition-colors"
            >
              Regenerate suggestion
            </button>
          </div>
        </div>
      )}

      {/* ── Action buttons (when not applied and not rejected) ── */}
      {!isApplied && !isRejected && (
        <div className="flex items-center gap-2 mt-auto pt-1">
          <button
            id={`fix-btn-${currentReport.id}`}
            onClick={handleFixIt}
            disabled={loading}
            className={`
              flex-1 py-2 rounded-xl text-sm font-semibold transition-all flex items-center justify-center gap-2
              ${!loading
                ? "bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white shadow-md shadow-blue-900/40 hover:shadow-blue-800/50 hover:-translate-y-0.5 active:translate-y-0"
                : "bg-gray-800/60 text-gray-500 cursor-not-allowed"
              }
            `}
          >
            {loading ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                <span>{loadingMsg}</span>
              </>
            ) : (
              <>⚡ Fix it</>
            )}
          </button>

          {!loading && (
            <button
              onClick={handleReject}
              title="Dismiss this issue"
              className="p-2 text-gray-600 hover:text-gray-400 rounded-xl hover:bg-gray-800/50 transition-all"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* ── Truthful Provider Attribution Badge ── */}
      {(currentReport.fix_attribution || currentReport.fix_provider || currentReport.fix_model) && (
        <div className="flex items-center justify-between text-[10px] text-gray-400 font-sans border-t border-white/5 pt-1.5 mt-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                currentReport.fix_provider === "apinex"
                  ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]"
                  : currentReport.fix_provider === "nvidia"
                  ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.6)]"
                  : currentReport.fix_provider === "groq"
                  ? "bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.6)]"
                  : "bg-blue-400"
              }`}
            />
            <span className="truncate text-gray-300 font-medium">
              {currentReport.fix_attribution || (
                currentReport.fix_provider === "apinex"
                  ? "Fixed using APInex GPT-6 Luna"
                  : currentReport.fix_provider === "nvidia"
                  ? "APInex unavailable — fixed using NVIDIA"
                  : currentReport.fix_provider === "groq"
                  ? "APInex and NVIDIA failed — fixed using Groq"
                  : `Fixed using ${currentReport.fix_model || "AI Model"}`
              )}
            </span>
          </div>
          {currentReport.fix_model && (
            <span className="text-[9px] text-gray-400 font-mono shrink-0 ml-1">
              {currentReport.fix_model}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
