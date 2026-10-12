/**
 * PipelineProgress.tsx
 * ---------------------
 * Animated pipeline progress bar shown while the auto-pipeline is running.
 * Displays each step with its current state (pending / active / done / failed).
 */
import type { PipelineStatus } from "../types";

interface Props {
  status: PipelineStatus;
  message: string;
  error?: string | null;
  metaSummary?: {
    total_files?: number | null;
    total_symbols?: number | null;
    total_issues?: number | null;
  } | null;
  onRetry?: () => void;
}

const STEPS: { key: PipelineStatus; label: string; icon: string }[] = [
  { key: "CLONING",          label: "Cloning",        icon: "📥" },
  { key: "PARSING",          label: "Parsing",        icon: "🔍" },
  { key: "EMBEDDING",        label: "Indexing",       icon: "🧠" },
  { key: "ANALYZING",        label: "Analysing",      icon: "📊" },
  { key: "DETECTING_ERRORS", label: "Scanning",       icon: "🛡️" },
  { key: "AUTO_FIXING",      label: "Auto-Fixing",    icon: "⚡" },
  { key: "DONE",             label: "Done",           icon: "✅" },
];

const STATUS_ORDER: Record<PipelineStatus, number> = {
  PENDING: -1,
  CLONING: 0,
  PARSING: 1,
  EMBEDDING: 2,
  ANALYZING: 3,
  DETECTING_ERRORS: 4,
  AUTO_FIXING: 5,
  DONE: 6,
  FAILED: 6,
};

export default function PipelineProgress({ status, message, error, metaSummary, onRetry }: Props) {
  const currentIdx = STATUS_ORDER[status] ?? -1;
  const isFailed = status === "FAILED";
  const isDone = status === "DONE";

  if (isDone) {
    return (
      <div className="flex flex-col gap-2 px-3 pb-3">
        <div className="flex items-center gap-2 text-xs text-green-400">
          <span className="text-base">✅</span>
          <span className="font-semibold">Ready to chat</span>
        </div>
        {metaSummary && (
          <div className="grid grid-cols-3 gap-1 text-xs text-gray-400">
            {metaSummary.total_files != null && (
              <span>{metaSummary.total_files} files</span>
            )}
            {metaSummary.total_symbols != null && (
              <span>{metaSummary.total_symbols} symbols</span>
            )}
            {metaSummary.total_issues != null && (
              <span className={metaSummary.total_issues > 0 ? "text-yellow-400" : "text-green-400"}>
                {metaSummary.total_issues} issues
              </span>
            )}
          </div>
        )}
      </div>
    );
  }

  if (isFailed) {
    return (
      <div className="px-3 pb-3 space-y-2">
        <div className="flex items-center gap-2 text-xs text-red-400">
          <span>❌</span>
          <span className="font-semibold">Pipeline failed</span>
        </div>
        {error && (
          <p className="text-xs text-red-300 bg-red-900/20 rounded-lg px-2 py-1 break-all">{error}</p>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            className="w-full text-xs py-1.5 rounded-lg bg-red-900/40 hover:bg-red-700 text-red-300 hover:text-white transition-colors"
          >
            ↻ Retry pipeline
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="px-3 pb-3 space-y-2">
      {/* Step pills */}
      <div className="flex flex-wrap gap-1">
        {STEPS.filter(s => s.key !== "DONE").map((step) => {
          const stepIdx = STATUS_ORDER[step.key];
          const isDoneStep = stepIdx < currentIdx;
          const isActive = stepIdx === currentIdx;

          return (
            <span
              key={step.key}
              className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border transition-all ${
                isActive
                  ? "border-blue-500 bg-blue-900/40 text-blue-300 animate-pulse"
                  : isDoneStep
                  ? "border-green-700 bg-green-900/20 text-green-400"
                  : "border-gray-700 bg-gray-800/30 text-gray-500"
              }`}
            >
              {isDoneStep ? "✓" : isActive ? "⟳" : step.icon}
              <span>{step.label}</span>
            </span>
          );
        })}
      </div>
      {/* Current message */}
      <p className="text-xs text-gray-400 animate-pulse">{message}</p>
    </div>
  );
}
