import { useState, useCallback } from "react";
import type { FixResult, ValidationResult } from "../types";
import { generateFix, explainSymbol, validatePatch } from "../api";
import DiffViewer from "./DiffViewer";

type PanelTab = "explain" | "fix";
type FixStage = "idle" | "generating" | "ready" | "testing" | "passed" | "failed";

interface Props {
  symbolId: number;
  symbolName: string;
  symbolType: string;
  filePath: string;
  repoId: string;
  onClose: () => void;
  onAccepted: (fix: FixResult) => void;
}

export default function FixPanel({
  symbolId,
  symbolName,
  symbolType,
  filePath,
  repoId,
  onClose,
  onAccepted,
}: Props) {
  const [tab, setTab] = useState<PanelTab>("explain");

  // ── Explain state ──────────────────────────────────────────────────────────
  const [explanation, setExplanation] = useState<string | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);

  // ── Fix state ──────────────────────────────────────────────────────────────
  const [issue, setIssue] = useState("");
  const [fix, setFix] = useState<FixResult | null>(null);
  const [stage, setStage] = useState<FixStage>("idle");
  const [fixError, setFixError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  // ── Explain ────────────────────────────────────────────────────────────────
  const handleExplain = useCallback(async () => {
    setExplainLoading(true);
    setExplainError(null);
    try {
      const res = await explainSymbol(symbolId);
      setExplanation(res.explanation);
    } catch (e: unknown) {
      setExplainError(e instanceof Error ? e.message : String(e));
    } finally {
      setExplainLoading(false);
    }
  }, [symbolId]);

  // ── Generate fix ──────────────────────────────────────────────────────────
  const handleGenerateFix = useCallback(async () => {
    if (!issue.trim()) return;
    setStage("generating");
    setFixError(null);
    setFix(null);
    setValidation(null);
    try {
      const result = await generateFix(symbolId, issue);
      setFix(result);
      setStage("ready");
    } catch (e: unknown) {
      setFixError(e instanceof Error ? e.message : String(e));
      setStage("idle");
    }
  }, [symbolId, issue]);

  // ── Run tests ─────────────────────────────────────────────────────────────
  const handleRunTests = useCallback(async () => {
    if (!fix) return;
    if (!fix.diff || !fix.diff.trim()) {
      setValidation({
        repo_id: repoId,
        file_path: fix.file_path,
        passed: false,
        test_command: "(none)",
        exit_code: -1,
        output: "",
        error: "Cannot run tests: The generated fix does not contain a valid diff.",
      });
      setStage("failed");
      return;
    }
    setStage("testing");
    setValidation(null);
    try {
      const result = await validatePatch(repoId, fix.file_path, fix.diff);
      setValidation(result);
      setStage(result.passed ? "passed" : "failed");
    } catch (e: unknown) {
      setValidation({
        repo_id: repoId,
        file_path: fix.file_path,
        passed: false,
        test_command: "",
        exit_code: -1,
        output: "",
        error: e instanceof Error ? e.message : String(e),
      });
      setStage("failed");
    }
  }, [fix, repoId]);

  // ── Accept ────────────────────────────────────────────────────────────────
  const handleAccept = () => {
    if (fix && (stage === "ready" || stage === "passed" || stage === "failed")) onAccepted(fix);
  };

  const statusBadge = () => {
    const map: Record<FixStage, { label: string; color: string }> = {
      idle: { label: "Ready", color: "text-gray-400" },
      generating: { label: "Generating…", color: "text-yellow-400 animate-pulse" },
      ready: { label: "Diff ready", color: "text-blue-400" },
      testing: { label: "Running tests…", color: "text-yellow-400 animate-pulse" },
      passed: { label: "Tests passed", color: "text-green-400" },
      failed: { label: "Tests failed", color: "text-red-400" },
    };
    const { label, color } = map[stage];
    return <span className={`text-xs font-medium ${color}`}>{label}</span>;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Side panel */}
      <div className="relative z-10 flex flex-col h-full w-full max-w-2xl bg-gray-900 border-l border-gray-700 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-800 bg-gray-900/80 backdrop-blur-md shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 uppercase tracking-wider">{symbolType}</span>
              <span className="text-sm font-semibold text-white font-mono truncate">{symbolName}</span>
            </div>
            <p className="text-xs text-gray-500 truncate mt-0.5">{filePath}</p>
          </div>
          {statusBadge()}
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none ml-2">
            &times;
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800 shrink-0">
          {(["explain", "fix"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
                tab === t
                  ? "text-blue-400 border-b-2 border-blue-500"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              {t === "explain" ? "🔍 Explain" : "🔧 Fix"}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {tab === "explain" ? (
            /* ── EXPLAIN TAB ── */
            <div className="space-y-4">
              {!explanation && !explainLoading && (
                <div className="text-center py-12">
                  <p className="text-gray-400 text-sm mb-4">
                    Get a natural language explanation of <code className="text-blue-300">{symbolName}</code>.
                  </p>
                  <button
                    id="explain-btn"
                    onClick={handleExplain}
                    className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
                  >
                    Explain this symbol
                  </button>
                </div>
              )}

              {explainLoading && (
                <div className="flex flex-col items-center py-12 gap-3">
                  <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  <p className="text-gray-400 text-sm">Analyzing symbol with AI…</p>
                </div>
              )}

              {explainError && (
                <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg p-3">
                  {explainError}
                </div>
              )}

              {explanation && (
                <div className="prose prose-invert prose-sm max-w-none">
                  <div className="text-gray-200 text-sm leading-relaxed whitespace-pre-wrap">
                    {explanation}
                  </div>
                  <button
                    onClick={handleExplain}
                    className="mt-4 text-xs text-gray-500 hover:text-gray-300 underline"
                  >
                    Regenerate
                  </button>
                </div>
              )}
            </div>
          ) : (
            /* ── FIX TAB ── */
            <div className="space-y-5">
              {/* Issue input */}
              <div>
                <label className="block text-xs text-gray-400 font-medium mb-1.5">
                  Describe the issue to fix
                </label>
                <textarea
                  id="issue-description"
                  value={issue}
                  onChange={(e) => setIssue(e.target.value)}
                  rows={3}
                  placeholder="e.g. 'The hash comparison is vulnerable to timing attacks — use hmac.compare_digest instead of =='"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none transition-colors"
                  disabled={stage === "generating" || stage === "testing"}
                />
                <button
                  id="generate-fix-btn"
                  onClick={handleGenerateFix}
                  disabled={!issue.trim() || stage === "generating" || stage === "testing"}
                  className="mt-2 w-full py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {stage === "generating" ? "Generating diff…" : "Generate Fix"}
                </button>
              </div>

              {fixError && (
                <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg p-3">
                  {fixError}
                </div>
              )}

              {/* Diff viewer */}
              {fix && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                      Proposed Diff
                    </h3>
                    <div className="text-right">
                      <span className="text-xs text-emerald-400 font-medium">
                        {fix.fix_attribution || `Fixed using ${fix.model_display_name || fix.model_used}`}
                      </span>
                      <span className="block text-[10px] text-gray-500 font-mono">Model ID: {fix.model_used}</span>
                    </div>
                  </div>
                  <DiffViewer diff={fix.diff} fileName={fix.file_path} />

                  {/* Manual Validation Notice */}
                  <div className="text-xs text-blue-300 bg-blue-950/40 border border-blue-800/40 rounded-lg p-2.5 flex items-start gap-2">
                    <span className="text-blue-400 font-bold shrink-0">ℹ</span>
                    <span>Execution-based validation is skipped by default. You can accept and apply this fix directly, or optionally run sandbox tests below.</span>
                  </div>

                  {/* Test runner (optional manual check) */}
                  <button
                    id="run-tests-btn"
                    onClick={handleRunTests}
                    disabled={stage === "testing" || stage === "generating"}
                    className="w-full py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 disabled:opacity-40 text-gray-200 rounded-lg text-sm font-medium transition-colors"
                  >
                    {stage === "testing" ? "Running tests…" : "Run Tests Manually (Optional)"}
                  </button>
                </div>
              )}

              {/* Test results */}
              {validation && (
                <div
                  className={`rounded-xl border p-4 space-y-2 text-sm ${
                    validation.passed
                      ? "border-green-700 bg-green-950/40"
                      : "border-red-700 bg-red-950/40"
                  }`}
                >
                  <div className="flex items-center gap-2 font-semibold">
                    <span>{validation.passed ? "✅" : "❌"}</span>
                    <span className={validation.passed ? "text-green-400" : "text-red-400"}>
                      {validation.passed ? "All tests passed" : "Tests failed"}
                    </span>
                    <span className="text-gray-500 text-xs ml-auto font-mono">
                      exit {validation.exit_code}
                    </span>
                  </div>
                  {validation.test_command && (
                    <p className="text-xs text-gray-500 font-mono">
                      $ {validation.test_command}
                    </p>
                  )}
                  {(validation.output || validation.error) && (
                    <pre className="text-xs bg-gray-950 rounded-lg p-3 max-h-48 overflow-y-auto text-gray-300 whitespace-pre-wrap">
                      {validation.error || validation.output}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer actions */}
        {tab === "fix" && fix && (
          <div className="shrink-0 px-5 py-4 border-t border-gray-800 flex items-center gap-3 bg-gray-900">
            <button
              onClick={onClose}
              className="flex-1 py-2 border border-gray-600 text-gray-300 hover:text-white rounded-lg text-sm transition-colors"
            >
              Reject
            </button>
            <button
              id="accept-fix-btn"
              onClick={handleAccept}
              disabled={stage === "generating" || stage === "idle"}
              title="Accept this fix"
              className="flex-1 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg text-sm font-semibold transition-colors"
            >
              ✓ Accept Fix
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
