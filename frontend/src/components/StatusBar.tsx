import { useState, useRef, useEffect, type FC } from "react";
import {
  GitBranch,
  FolderGit2,
  AlertCircle,
  AlertTriangle,
  Sparkles,
  Zap,
  CheckCircle2,
  RotateCcw,
} from "lucide-react";
import type { RepoSummary, PipelineStatusResponse, User, ApinexQuotaResponse } from "../types";
import { fetchApinexQuota } from "../api";

interface StatusBarProps {
  activeRepo: RepoSummary | null;
  pipelineData: PipelineStatusResponse | null;
  errorCount: number;
  warningCount: number;
  user: User | null;
  aiActive?: boolean;
  onOpenIssues: () => void;
  onOpenOutput: () => void;
  onToggleCopilot?: () => void;
  onOpenCommandPalette?: () => void;
  onOpenSettings?: () => void;
  cursorLine?: number;
  cursorCol?: number;
  indentation?: { tabSize: number; insertSpaces: boolean };
  onChangeIndentation?: (tabSize: number, insertSpaces: boolean) => void;
  activeLanguage?: string;
  encoding?: string;
  lineEnding?: string;
  onGoToLine?: () => void;
}

const StatusBar: FC<StatusBarProps> = ({
  activeRepo,
  pipelineData,
  errorCount,
  warningCount,
  user: _user,
  aiActive = false,
  onOpenIssues,
  onOpenOutput,
  onToggleCopilot,
  onOpenCommandPalette,
  onOpenSettings: _onOpenSettings,
  cursorLine = 1,
  cursorCol = 1,
  indentation = { tabSize: 2, insertSpaces: true },
  onChangeIndentation,
  activeLanguage = "Plain Text",
  encoding = "UTF-8",
  lineEnding = "LF",
  onGoToLine,
}) => {
  const status = pipelineData?.pipeline_status ?? activeRepo?.pipeline_status ?? "IDLE";
  const [showIndentMenu, setShowIndentMenu] = useState(false);
  const indentMenuRef = useRef<HTMLDivElement>(null);

  // ── APInex Quota Control State ───────────────────────────────────────────────
  const [showApinexCard, setShowApinexCard] = useState(false);
  const [quotaData, setQuotaData] = useState<ApinexQuotaResponse | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const apinexCardRef = useRef<HTMLDivElement>(null);

  // Load live APInex quota from authoritative backend
  const loadQuota = async () => {
    try {
      setQuotaLoading(true);
      const res = await fetchApinexQuota();
      if (res) {
        setQuotaData(res);
      }
    } catch {
      // Offline or unconfigured
    } finally {
      setQuotaLoading(false);
    }
  };

  // Poll APInex quota periodically (every 45s) and on initial mount
  useEffect(() => {
    loadQuota();
    const interval = setInterval(loadQuota, 45000);
    return () => clearInterval(interval);
  }, []);

  // Close menus on outside click or Escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (indentMenuRef.current && !indentMenuRef.current.contains(e.target as Node)) {
        setShowIndentMenu(false);
      }
      if (apinexCardRef.current && !apinexCardRef.current.contains(e.target as Node)) {
        setShowApinexCard(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setShowIndentMenu(false);
        setShowApinexCard(false);
      }
    };

    if (showIndentMenu || showApinexCard) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [showIndentMenu, showApinexCard]);

  const handleSelectIndent = (tabSize: number, insertSpaces: boolean) => {
    onChangeIndentation?.(tabSize, insertSpaces);
    setShowIndentMenu(false);
  };

  const indentLabel = indentation.insertSpaces ? `Spaces: ${indentation.tabSize}` : `Tabs: ${indentation.tabSize}`;

  // Format token counts cleanly (e.g. 184.2K or 184,200)
  const formatTokens = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return num.toLocaleString();
  };

  const dailyBudget = quotaData?.daily_limit || 315000;
  const usedTokens = quotaData?.total_tokens || 0;
  const remainingTokens = quotaData?.remaining_tokens ?? Math.max(0, dailyBudget - usedTokens);
  const percentUsed = quotaData?.percent_used ?? (dailyBudget > 0 ? (usedTokens / dailyBudget) * 100 : 0);
  const isExhausted = quotaData?.is_exhausted || remainingTokens <= 0;
  const isWarning = quotaData?.warning || (!isExhausted && percentUsed >= 80);

  return (
    <footer
      className="h-[22px] bg-[#0c0d0e] border-t border-[#1e1f22] text-[#adbac7] flex items-center justify-between px-2 text-[11px] select-none shrink-0 font-sans z-30 relative"
      aria-label="Status Bar"
    >
      {/* ── Left Section: Truthful Workspace Indicators (NO hardcoded tech stack labels) ── */}
      <div className="flex items-center gap-2.5">
        {/* Branch / Source Control */}
        <div
          onClick={onOpenCommandPalette}
          title={activeRepo ? "Git: main branch" : "Git: No active repository"}
          className="flex items-center gap-1 hover:bg-white/10 px-1.5 py-0.5 rounded cursor-pointer transition-colors"
        >
          <GitBranch size={12} />
          <span>main</span>
        </div>

        {/* Active Workspace / Repository Name */}
        {activeRepo ? (
          <div
            onClick={onOpenCommandPalette}
            title={`Active Repository: ${activeRepo.name}`}
            className="flex items-center gap-1 hover:bg-white/10 px-1.5 py-0.5 rounded cursor-pointer transition-colors"
          >
            <FolderGit2 size={12} />
            <span className="font-semibold text-white truncate max-w-[150px]">{activeRepo.name}</span>
          </div>
        ) : (
          <div
            onClick={onOpenCommandPalette}
            title="No repository loaded"
            className="flex items-center gap-1 text-gray-500 px-1.5 py-0.5"
          >
            <FolderGit2 size={12} />
            <span>No Workspace</span>
          </div>
        )}

        {/* Live Pipeline State Pill */}
        <div
          onClick={onOpenOutput}
          title="Click to view repository pipeline & build output"
          className="flex items-center gap-1 hover:bg-white/10 px-1.5 py-0.5 rounded cursor-pointer transition-colors"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              status === "DONE"
                ? "bg-green-400 shadow-sm shadow-green-500/50"
                : status === "FAILED"
                ? "bg-red-400 shadow-sm shadow-red-500/50"
                : status === "IDLE"
                ? "bg-gray-400"
                : "bg-yellow-400 animate-pulse"
            }`}
          />
          <span className="text-[10px]">Pipeline: {status}</span>
        </div>

        {/* Live Problems & Issues Count */}
        <div
          onClick={onOpenIssues}
          title="Click to view CodeBase Problems"
          className="flex items-center gap-2 hover:bg-white/10 px-1.5 py-0.5 rounded cursor-pointer transition-colors font-mono"
        >
          <span className="flex items-center gap-0.5">
            <AlertCircle size={11} className={errorCount > 0 ? "text-red-400" : "text-gray-400"} />
            <span className={errorCount > 0 ? "text-red-300 font-bold" : ""}>{errorCount}</span>
          </span>
          <span className="flex items-center gap-0.5">
            <AlertTriangle size={11} className={warningCount > 0 ? "text-yellow-400" : "text-gray-400"} />
            <span className={warningCount > 0 ? "text-yellow-300 font-bold" : ""}>{warningCount}</span>
          </span>
        </div>
      </div>

      {/* ── Right Section: Cursor, Indent, Language, Copilot & Compact APInex Control ── */}
      <div className="flex items-center gap-2">
        {/* Editor Cursor Position: Real Ln / Col */}
        <button
          type="button"
          onClick={onGoToLine || onOpenCommandPalette}
          title="Go to Line / Column (Click to navigate)"
          className="hover:bg-white/10 px-1 py-0.5 rounded cursor-pointer transition-colors hover:text-white font-mono text-[11px]"
        >
          Ln {cursorLine}, Col {cursorCol}
        </button>

        {/* Indentation configuration popover */}
        <div className="relative" ref={indentMenuRef}>
          <button
            type="button"
            onClick={() => setShowIndentMenu((prev) => !prev)}
            title="Indentation: Click to change Tab Size & Spaces"
            className="hover:bg-white/10 px-1 py-0.5 rounded cursor-pointer transition-colors hover:text-white font-mono text-[11px]"
          >
            {indentLabel}
          </button>

          {showIndentMenu && (
            <div className="absolute bottom-full right-0 mb-1 w-44 bg-[#0c0d0e] border border-[#1e1f22] rounded-md shadow-2xl py-1 text-xs z-50">
              <div className="px-2.5 py-1 text-[10px] font-bold text-gray-400 uppercase tracking-wider border-b border-[#1e1f22]">
                Indentation Mode
              </div>
              <button
                type="button"
                onClick={() => handleSelectIndent(2, true)}
                className={`w-full text-left px-2.5 py-1 hover:bg-[#1a1b1e] hover:text-white flex items-center justify-between ${
                  indentation.insertSpaces && indentation.tabSize === 2 ? "text-purple-400 font-bold" : "text-gray-300"
                }`}
              >
                <span>Indent with Spaces: 2</span>
                {indentation.insertSpaces && indentation.tabSize === 2 && <span>✓</span>}
              </button>
              <button
                type="button"
                onClick={() => handleSelectIndent(4, true)}
                className={`w-full text-left px-2.5 py-1 hover:bg-[#1a1b1e] hover:text-white flex items-center justify-between ${
                  indentation.insertSpaces && indentation.tabSize === 4 ? "text-purple-400 font-bold" : "text-gray-300"
                }`}
              >
                <span>Indent with Spaces: 4</span>
                {indentation.insertSpaces && indentation.tabSize === 4 && <span>✓</span>}
              </button>
              <button
                type="button"
                onClick={() => handleSelectIndent(8, true)}
                className={`w-full text-left px-2.5 py-1 hover:bg-[#1a1b1e] hover:text-white flex items-center justify-between ${
                  indentation.insertSpaces && indentation.tabSize === 8 ? "text-purple-400 font-bold" : "text-gray-300"
                }`}
              >
                <span>Indent with Spaces: 8</span>
                {indentation.insertSpaces && indentation.tabSize === 8 && <span>✓</span>}
              </button>
              <button
                type="button"
                onClick={() => handleSelectIndent(4, false)}
                className={`w-full text-left px-2.5 py-1 hover:bg-[#1a1b1e] hover:text-white flex items-center justify-between border-t border-[#1e1f22] ${
                  !indentation.insertSpaces ? "text-purple-400 font-bold" : "text-gray-300"
                }`}
              >
                <span>Indent with Tabs: 4</span>
                {!indentation.insertSpaces && <span>✓</span>}
              </button>
            </div>
          )}
        </div>

        {/* Encoding */}
        <span
          title="File Character Encoding: UTF-8"
          className="hover:bg-white/10 px-1 py-0.5 rounded cursor-pointer transition-colors hover:text-white font-mono text-[11px]"
        >
          {encoding}
        </span>

        {/* Line Ending */}
        <span
          title="Line Feed Endings: LF"
          className="hover:bg-white/10 px-1 py-0.5 rounded cursor-pointer transition-colors hover:text-white font-mono text-[11px]"
        >
          {lineEnding}
        </span>

        {/* Real Active File Language */}
        <button
          type="button"
          onClick={onOpenCommandPalette}
          title={`Active Language: ${activeLanguage} (Click to change Language Mode)`}
          className="hover:bg-white/10 px-1.5 py-0.5 rounded cursor-pointer transition-colors text-white font-medium hover:text-blue-300 font-mono text-[11px]"
        >
          {activeLanguage}
        </button>

        {/* ── Compact APInex Usage Control Popover Card ────────────────────── */}
        <div className="relative" ref={apinexCardRef}>
          <button
            type="button"
            onClick={() => {
              setShowApinexCard((prev) => !prev);
              if (!showApinexCard) loadQuota();
            }}
            title="APInex GPT-6 Luna Quota & Usage Status (Click to inspect)"
            className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors border cursor-pointer ${
              showApinexCard
                ? "bg-[#0c0d0e] border-purple-500 text-white"
                : isExhausted
                ? "bg-red-950/40 border-red-800 text-red-300 hover:bg-red-900/40"
                : isWarning
                ? "bg-amber-950/40 border-amber-800 text-amber-300 hover:bg-amber-900/40"
                : "bg-[#0c0d0e] border-[#1e1f22] text-gray-300 hover:text-white hover:bg-[#1a1b1e]"
            }`}
          >
            <Zap size={11} className={isExhausted ? "text-red-400" : isWarning ? "text-amber-400" : "text-purple-400"} />
            <span className="font-mono text-[10px]">
              APInex: {formatTokens(usedTokens)} / {formatTokens(dailyBudget)}
            </span>
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isExhausted ? "bg-red-400" : isWarning ? "bg-amber-400" : "bg-emerald-400"
              }`}
            />
          </button>

          {/* Compact Quota Modal Card */}
          {showApinexCard && (
            <div className="absolute bottom-full right-0 mb-1.5 w-72 bg-[#0c0d0e] border border-[#1e1f22] rounded-lg shadow-2xl p-3 text-xs z-50 animate-in fade-in zoom-in-95">
              {/* Header */}
              <div className="flex items-center justify-between pb-2 border-b border-[#1e1f22] mb-2.5">
                <div className="flex items-center gap-1.5">
                  <Zap size={14} className="text-purple-400" />
                  <div>
                    <div className="font-bold text-white text-[11px] leading-tight">APInex Quota Status</div>
                    <div className="text-[10px] text-gray-400 font-mono">GPT-6 Luna (Default)</div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={loadQuota}
                    title="Refresh quota"
                    className="p-1 hover:text-white text-gray-400 hover:bg-[#1a1b1e] rounded"
                  >
                    <RotateCcw size={11} className={quotaLoading ? "animate-spin" : ""} />
                  </button>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[9px] font-bold font-mono uppercase ${
                      !quotaData?.configured
                        ? "bg-gray-800 text-gray-400"
                        : isExhausted
                        ? "bg-red-950 text-red-300 border border-red-800"
                        : isWarning
                        ? "bg-amber-950 text-amber-300 border border-amber-800"
                        : "bg-emerald-950 text-emerald-300 border border-emerald-800"
                    }`}
                  >
                    {!quotaData?.configured
                      ? "Unconfigured"
                      : isExhausted
                      ? "Exhausted"
                      : isWarning
                      ? "Approaching Limit"
                      : "Available"}
                  </span>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="space-y-1 mb-2.5">
                <div className="flex justify-between text-[10px] font-mono">
                  <span className="text-gray-400">Daily Token Consumption</span>
                  <span className="text-white font-semibold">{percentUsed.toFixed(1)}%</span>
                </div>
                <div className="w-full h-1.5 bg-[#0c0d0e] rounded-full overflow-hidden border border-[#1e1f22]">
                  <div
                    className={`h-full transition-all duration-500 rounded-full ${
                      isExhausted ? "bg-red-500" : isWarning ? "bg-amber-400" : "bg-gradient-to-r from-purple-500 to-indigo-400"
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, percentUsed))}%` }}
                  />
                </div>
              </div>

              {/* Quota Grid */}
              <div className="grid grid-cols-2 gap-2 text-[10px] bg-[#0c0d0e] p-2 rounded border border-[#1e1f22] mb-2 font-mono">
                <div>
                  <div className="text-gray-500">Daily Budget</div>
                  <div className="text-white font-bold">{dailyBudget.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-gray-500">Recorded Usage</div>
                  <div className="text-purple-300 font-bold">
                    {usedTokens.toLocaleString()}{" "}
                    <span className="text-[8px] text-gray-500">
                      ({quotaData?.is_estimated ? "Est." : "Real"})
                    </span>
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">Remaining</div>
                  <div className={remainingTokens > 0 ? "text-emerald-300 font-bold" : "text-red-400 font-bold"}>
                    {remainingTokens.toLocaleString()}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500">Requests Today</div>
                  <div className="text-white font-bold">{quotaData?.request_count ?? 0}</div>
                </div>
              </div>

              {/* Status Note & Quota Reset */}
              <div className="text-[9px] text-gray-400 space-y-0.5 border-t border-[#1e1f22] pt-1.5 flex items-center justify-between">
                <span>Resets daily at 00:00 UTC</span>
                <span className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 size={10} /> Active Quota
                </span>
              </div>
            </div>
          )}
        </div>

        {/* CodeBrain AI Assistant Status (Replaces Developer label on far right) */}
        <button
          type="button"
          onClick={onToggleCopilot}
          title="Toggle CodeBrain AI Assistant"
          className="flex items-center gap-1.5 px-2 py-0.5 rounded hover:bg-white/10 text-[#adbac7] hover:text-white transition-colors cursor-pointer active:scale-95"
        >
          <Sparkles size={11} className={aiActive ? "animate-spin text-purple-400" : "text-purple-400"} />
          <span className="font-semibold text-purple-300">CodeBrain AI:</span>
          <span className="text-gray-300">{aiActive ? "Generating…" : "Ready"}</span>
        </button>
      </div>
    </footer>
  );
};

export default StatusBar;
