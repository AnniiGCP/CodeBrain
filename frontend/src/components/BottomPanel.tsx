import { useState, useEffect, useRef, type FC, type KeyboardEvent } from "react";
import {
  Terminal as TerminalIcon,
  ChevronDown,
  Plus,
  Trash2,
  X,
  Wand2,
  AlertCircle,
  AlertTriangle,
} from "lucide-react";
import type { ErrorReport, PipelineStatusResponse, TerminalLine, TerminalSessionItem } from "../types";
import {
  fetchTerminalSessions,
  createTerminalSession,
  fetchTerminalSession,
  executeTerminalCommand,
  stopTerminalProcess,
  closeTerminalSession,
} from "../api";

export type BottomTabType = "problems" | "output" | "terminal";

interface BottomPanelProps {
  activeTab: BottomTabType;
  onTabChange: (tab: BottomTabType) => void;
  onClose: () => void;
  errors: ErrorReport[];
  pipelineData: PipelineStatusResponse | null;
  terminalLogs?: { command?: string; output?: string; passed?: boolean; error?: string } | null;
  onSelectProblem: (filePath: string, line?: number) => void;
  onTriggerFix: (error: ErrorReport) => void;
  repoId?: string;
}

const BottomPanel: FC<BottomPanelProps> = ({
  activeTab,
  onTabChange,
  onClose,
  errors,
  pipelineData,
  terminalLogs,
  onSelectProblem,
  onTriggerFix,
  repoId,
}) => {
  // ── Problems Tab State ───────────────────────────────────────────────────────
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const errorCount = errors.filter((e) => e.severity === "error" || e.category === "ERROR").length;
  const warningCount = errors.filter((e) => e.severity === "warning" || e.category === "WARNING").length;
  const totalProblemsCount = errorCount + warningCount;

  const filteredErrors = errors.filter((e) => {
    if (severityFilter === "error") return e.severity === "error" || e.category === "ERROR";
    if (severityFilter === "warning") return e.severity === "warning" || e.category === "WARNING";
    return true;
  });

  // ── Multi-Terminal VS Code State ─────────────────────────────────────────────
  const [sessions, setSessions] = useState<TerminalSessionItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionLines, setSessionLines] = useState<Record<string, TerminalLine[]>>({});
  const [commandInput, setCommandInput] = useState<string>("");
  const [inputHistory, setInputHistory] = useState<string[]>([]);
  const [historyPointer, setHistoryPointer] = useState<number>(-1);
  const [showShellDropdown, setShowShellDropdown] = useState<boolean>(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const terminalScrollRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef<boolean>(false);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;
  const activeLines = (activeSessionId && sessionLines[activeSessionId]) || [];

  const handleTerminalScroll = () => {
    if (!terminalScrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = terminalScrollRef.current;
    isUserScrolledUp.current = scrollHeight - scrollTop - clientHeight > 35;
  };

  // Focus input automatically whenever switching to terminal tab or clicking inside
  useEffect(() => {
    if (activeTab === "terminal") {
      inputRef.current?.focus();
    }
  }, [activeTab, activeSessionId]);

  // Close shell dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowShellDropdown(false);
      }
    };
    if (showShellDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showShellDropdown]);

  // Load existing sessions or create initial clean session
  useEffect(() => {
    if (!repoId || activeTab !== "terminal") return;
    let cancelled = false;

    const initSessions = async () => {
      try {
        const list = await fetchTerminalSessions(repoId);
        if (cancelled) return;
        if (list.length > 0) {
          setSessions(list);
          if (!activeSessionId || !list.some((s) => s.id === activeSessionId)) {
            setActiveSessionId(list[0].id);
          }
        } else {
          const newSess = await createTerminalSession(repoId);
          if (cancelled) return;
          setSessions([newSess]);
          setActiveSessionId(newSess.id);
        }
      } catch {
        // Safe offline mock session if network is disconnected
        if (sessions.length === 0) {
          const fallback: TerminalSessionItem = {
            id: "local-term-1",
            title: "1: powershell",
            repo_id: repoId,
            cwd: "CodeBrain",
            prompt: "PS CodeBrain>",
            status: "idle",
            created_at: new Date().toISOString(),
            line_count: 0,
          };
          setSessions([fallback]);
          setActiveSessionId(fallback.id);
        }
      }
    };

    initSessions();
    return () => {
      cancelled = true;
    };
  }, [repoId, activeTab]);

  // Poll output lines for active session while process is running or periodically
  useEffect(() => {
    if (!repoId || !activeSessionId || activeTab !== "terminal") return;

    let timer: ReturnType<typeof setInterval>;
    let cancelled = false;

    const pollSession = async () => {
      try {
        const updated = await fetchTerminalSession(repoId, activeSessionId, 0);
        if (cancelled) return;

        setSessions((prev) =>
          prev.map((s) => (s.id === updated.id ? { ...s, ...updated } : s))
        );

        if (updated.lines) {
          setSessionLines((prev) => ({
            ...prev,
            [activeSessionId]: updated.lines || [],
          }));
        }
      } catch {
        // Ignored transient error
      }
    };

    // Initial fetch on session change
    pollSession();
    timer = setInterval(pollSession, 1200);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [repoId, activeSessionId, activeTab]);

  // Auto-scroll to bottom of terminal screen on output changes only if user is not actively scrolled up
  useEffect(() => {
    if (terminalScrollRef.current && !isUserScrolledUp.current) {
      terminalScrollRef.current.scrollTop = terminalScrollRef.current.scrollHeight;
    }
  }, [activeLines, activeSessionId]);

  const handleCreateNewSession = async (title?: string, subpath?: string) => {
    if (!repoId) return;
    try {
      const newSess = await createTerminalSession(repoId, title, subpath);
      setSessions((prev) => [...prev, newSess]);
      setActiveSessionId(newSess.id);
      setShowShellDropdown(false);
      setCommandInput("");
      setTimeout(() => inputRef.current?.focus(), 50);
    } catch (err: any) {
      alert(`Could not spawn terminal session: ${err.message}`);
    }
  };

  const handleKillSession = async (sessionId?: string) => {
    const targetId = sessionId || activeSessionId;
    if (!repoId || !targetId) return;

    const targetSession = sessions.find((s) => s.id === targetId);
    if (targetSession?.is_running) {
      const confirmKill = window.confirm(
        `Process is currently running in "${targetSession.title}". Stop process and close terminal?`
      );
      if (!confirmKill) return;
    }

    try {
      await closeTerminalSession(repoId, targetId);
      const remaining = sessions.filter((s) => s.id !== targetId);
      setSessions(remaining);
      setSessionLines((prev) => {
        const copy = { ...prev };
        delete copy[targetId];
        return copy;
      });

      if (activeSessionId === targetId) {
        if (remaining.length > 0) {
          setActiveSessionId(remaining[0].id);
        } else {
          // If all sessions deleted, spawn a fresh clean session
          createTerminalSession(repoId).then((newSess) => {
            setSessions([newSess]);
            setActiveSessionId(newSess.id);
          }).catch(() => {
            setActiveSessionId(null);
          });
        }
      }
    } catch {
      // Ignored
    }
  };

  const handleKeyDown = async (e: KeyboardEvent<HTMLInputElement>) => {
    // Handle Ctrl+C / Cmd+C: allow text copying if selected, otherwise abort running process
    if (e.key === "c" && (e.ctrlKey || e.metaKey)) {
      const selection = window.getSelection();
      if (selection && selection.toString().length > 0) {
        return; // Allow native copy
      }
      if (activeSession?.is_running && repoId && activeSessionId) {
        e.preventDefault();
        stopTerminalProcess(repoId, activeSessionId).catch(() => {});
      }
      return;
    }

    if (e.key === "Enter") {
      e.preventDefault();
      const rawCmd = commandInput;
      const trimmedCmd = rawCmd.trim();
      setCommandInput("");
      setHistoryPointer(-1);

      // Reset scroll up state so screen snaps to the newly submitted command
      isUserScrolledUp.current = false;
      setTimeout(() => {
        if (terminalScrollRef.current) {
          terminalScrollRef.current.scrollTop = terminalScrollRef.current.scrollHeight;
        }
      }, 20);

      if (trimmedCmd) {
        setInputHistory((prev) => [...prev, rawCmd]);
      }

      if (!trimmedCmd || !repoId || !activeSessionId) return;

      // Handle 'cls' or 'clear' locally and remotely
      if (trimmedCmd.toLowerCase() === "cls" || trimmedCmd.toLowerCase() === "clear") {
        setSessionLines((prev) => ({ ...prev, [activeSessionId]: [] }));
        executeTerminalCommand(repoId, activeSessionId, trimmedCmd).catch(() => {});
        return;
      }

      // Optimistically record command line with the dynamic prompt
      const cmdPrompt = activeSession?.prompt || "PS CodeBrain>";
      const optimisticLine: TerminalLine = {
        index: Date.now(),
        text: `${cmdPrompt} ${rawCmd}`,
        stream: "command",
        timestamp: Date.now(),
      };
      setSessionLines((prev) => ({
        ...prev,
        [activeSessionId]: [...(prev[activeSessionId] || []), optimisticLine],
      }));

      try {
        await executeTerminalCommand(repoId, activeSessionId, trimmedCmd);
        const updated = await fetchTerminalSession(repoId, activeSessionId, 0);
        setSessions((prev) =>
          prev.map((s) => (s.id === updated.id ? { ...s, ...updated } : s))
        );
        if (updated.lines) {
          setSessionLines((prev) => ({
            ...prev,
            [activeSessionId]: updated.lines || [],
          }));
        }
      } catch (err: any) {
        const errLine: TerminalLine = {
          index: Date.now(),
          text: err.message || "Command execution failed.",
          stream: "stderr",
          timestamp: Date.now(),
        };
        setSessionLines((prev) => ({
          ...prev,
          [activeSessionId]: [...(prev[activeSessionId] || []), errLine],
        }));
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (inputHistory.length > 0) {
        const nextIndex = historyPointer === -1 ? inputHistory.length - 1 : Math.max(0, historyPointer - 1);
        setHistoryPointer(nextIndex);
        setCommandInput(inputHistory[nextIndex] || "");
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyPointer !== -1) {
        const nextIndex = historyPointer + 1;
        if (nextIndex < inputHistory.length) {
          setHistoryPointer(nextIndex);
          setCommandInput(inputHistory[nextIndex]);
        } else {
          setHistoryPointer(-1);
          setCommandInput("");
        }
      }
    } else if (e.ctrlKey && e.key.toLowerCase() === "c") {
      // Ctrl+C to abort running command
      if (activeSession?.is_running) {
        if (repoId && activeSessionId) {
          stopTerminalProcess(repoId, activeSessionId).catch(() => {});
        }
      }
      if (activeSessionId) {
        const cmdPrompt = activeSession?.prompt || "PS CodeBrain>";
        setSessionLines((prev) => ({
          ...prev,
          [activeSessionId]: [
            ...(prev[activeSessionId] || []),
            {
              index: Date.now(),
              text: `${cmdPrompt} ${commandInput}^C`,
              stream: "command",
              timestamp: Date.now(),
            },
          ],
        }));
        setCommandInput("");
      }
    }
  };

  return (
    <div className="h-full w-full bg-[#0c0d0e] flex flex-col text-xs select-none border-t border-[#1e1f22]">
      {/* ── VS Code Style Header Strip ─────────────────────────────────── */}
      <div className="flex items-center justify-between bg-[#0c0d0e] border-b border-[#1e1f22] px-3 h-[34px] shrink-0 font-sans">
        {/* Left Tabs: Strictly Problems, Output, Terminal */}
        <div className="flex items-center gap-1">
          {/* 1. Problems */}
          <button
            onClick={() => onTabChange("problems")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors ${
              activeTab === "problems"
                ? "bg-[#0c0d0e] text-white font-medium border-b-2 border-purple-500"
                : "text-[#858585] hover:text-[#cccccc]"
            }`}
          >
            <span>Problems</span>
            {totalProblemsCount > 0 && (
              <span className="bg-purple-600 text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full min-w-[16px] text-center">
                {totalProblemsCount}
              </span>
            )}
          </button>

          {/* 2. Output */}
          <button
            onClick={() => onTabChange("output")}
            className={`px-2.5 py-1 rounded text-xs transition-colors ${
              activeTab === "output"
                ? "bg-[#0c0d0e] text-white font-medium border-b-2 border-purple-500"
                : "text-[#858585] hover:text-[#cccccc]"
            }`}
          >
            <span>Output</span>
          </button>

          {/* 3. Terminal */}
          <button
            onClick={() => onTabChange("terminal")}
            className={`px-2.5 py-1 rounded text-xs transition-colors ${
              activeTab === "terminal"
                ? "bg-[#0c0d0e] text-white font-medium border-b-2 border-purple-500"
                : "text-[#858585] hover:text-[#cccccc]"
            }`}
          >
            <span>Terminal</span>
          </button>
        </div>

        {/* Right Terminal Toolbar Controls */}
        <div className="flex items-center gap-1.5 text-[#cccccc]">
          {activeTab === "terminal" && (
            <div className="flex items-center gap-1 relative" ref={dropdownRef}>
              {/* Active Shell Pill / Dropdown Switcher Button */}
              <button
                onClick={() => setShowShellDropdown((prev) => !prev)}
                title="Switch active terminal session"
                className="flex items-center gap-1.5 px-2 py-0.5 rounded hover:bg-[#1a1b1e] text-[#cccccc] text-[11px] font-mono cursor-pointer transition-colors"
              >
                <TerminalIcon size={12} className="text-[#3794ff]" />
                <span className="font-sans text-[11px]">{activeSession?.title || "1: powershell"}</span>
                {activeSession?.is_running && (
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                )}
                <ChevronDown size={11} className="text-[#858585]" />
              </button>

              {/* Shell Dropdown Menu */}
              {showShellDropdown && (
                <div className="absolute right-0 top-full mt-1 w-56 bg-[#0c0d0e] border border-[#1e1f22] rounded shadow-2xl py-1 z-50 text-[11px] font-sans">
                  <div className="px-2.5 py-1 text-[10px] text-[#858585] uppercase tracking-wider font-semibold border-b border-[#1e1f22]">
                    Terminal Sessions ({sessions.length})
                  </div>
                  {sessions.map((sess) => (
                    <div
                      key={sess.id}
                      onClick={() => {
                        setActiveSessionId(sess.id);
                        setShowShellDropdown(false);
                        inputRef.current?.focus();
                      }}
                      className={`group w-full text-left px-2.5 py-1.5 hover:bg-[#1a1b1e] flex items-center justify-between cursor-pointer ${
                        sess.id === activeSessionId ? "text-white font-medium bg-[#141518]" : "text-[#cccccc]"
                      }`}
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        <TerminalIcon size={11} className="text-[#3794ff]" />
                        <span>{sess.title}</span>
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {sess.is_running && <span className="text-[10px] text-emerald-400 font-mono">running</span>}
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleKillSession(sess.id);
                          }}
                          className="opacity-0 group-hover:opacity-100 hover:text-red-400 p-0.5 rounded text-[#858585] transition-opacity"
                          title="Delete Session"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </div>
                  ))}
                  <div className="border-t border-[#2b2b2b] my-1" />
                  <button
                    onClick={() => handleCreateNewSession()}
                    className="w-full text-left px-2.5 py-1.5 hover:bg-[#2a2d2e] text-[#3794ff] flex items-center gap-1.5"
                  >
                    <Plus size={12} /> New Terminal
                  </button>
                </div>
              )}

              {/* Plus Button: Add new independent terminal */}
              <button
                onClick={() => handleCreateNewSession()}
                title="New Terminal"
                className="p-1 hover:text-white text-[#858585] hover:bg-[#2a2d2e] rounded transition-colors"
              >
                <Plus size={13} />
              </button>

              {/* Kill Selected Terminal Session */}
              <button
                onClick={() => handleKillSession()}
                title="Kill Terminal"
                className="p-1 hover:text-red-400 text-[#858585] hover:bg-[#2a2d2e] rounded transition-colors"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )}

          {/* Close Panel Button */}
          <button
            onClick={onClose}
            title="Close Panel"
            className="p-1 hover:text-white text-[#858585] hover:bg-[#2a2d2e] rounded transition-colors ml-1"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* ── Panel Content View ─────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden flex flex-col bg-[#0c0d0e]">
        {/* ── 1. Terminal Content: VS Code Layout with Session List on Right ──────────────── */}
        {activeTab === "terminal" && (
          <div className="h-full w-full flex overflow-hidden bg-[#0c0d0e]">
            {/* Terminal Main Viewport */}
            <div
              className="flex-1 overflow-y-auto p-3 font-mono text-[13px] leading-relaxed text-[#cccccc] cursor-text bg-[#0c0d0e] select-text flex flex-col"
              ref={terminalScrollRef}
              onScroll={handleTerminalScroll}
              onClick={() => {
                const selection = window.getSelection();
                if (!selection || selection.toString().trim().length === 0) {
                  inputRef.current?.focus();
                }
              }}
              style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
            >
              {!repoId ? (
                <div className="p-4 text-gray-500 font-sans italic">
                  No repository active. Connect or open a repository to launch an isolated workspace terminal.
                </div>
              ) : (
                <div className="space-y-0.5 min-h-full flex flex-col justify-start">
                  {/* Real chronological output lines for active session */}
                  {activeLines.map((line, idx) => (
                    <div
                      key={`${line.index}-${idx}`}
                      className={`whitespace-pre-wrap break-all select-text font-mono ${
                        line.stream === "command"
                          ? "text-white font-medium"
                          : line.stream === "stderr"
                          ? "text-[#f87171]"
                          : line.stream === "system"
                          ? "text-[#34d399]"
                          : "text-[#cccccc]"
                      }`}
                    >
                      {line.text}
                    </div>
                  ))}

                  {/* If sandbox test logs are present and no output yet */}
                  {terminalLogs && activeLines.length === 0 && (
                    <div className="mb-2 text-gray-400 whitespace-pre-wrap">
                      {terminalLogs.output || terminalLogs.error}
                    </div>
                  )}

                  {/* Clean Interactive Prompt Line */}
                  <div className="flex items-center gap-1.5 mt-1 text-[13px] leading-relaxed select-none">
                    <span className="text-[#34d399] font-semibold shrink-0">
                      {activeSession?.prompt || "PS CodeBrain>"}
                    </span>
                    <input
                      ref={inputRef}
                      type="text"
                      value={commandInput}
                      onChange={(e) => setCommandInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      disabled={activeSession?.is_running}
                      placeholder={activeSession?.is_running ? "Running command... (Press Ctrl+C to abort)" : ""}
                      className="flex-1 bg-transparent text-white outline-none border-none p-0 font-mono text-[13px] leading-relaxed placeholder:text-gray-500 placeholder:italic select-text caret-purple-400"
                      autoFocus
                      spellCheck={false}
                      autoComplete="off"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Right Terminal Sessions Sidebar (VS Code Style) */}
            <div className="w-48 border-l border-[#1e1f22] bg-[#0c0d0e] flex flex-col shrink-0 text-xs hidden sm:flex">
              <div className="px-3 py-1.5 border-b border-[#1e1f22] bg-[#0c0d0e] flex items-center justify-between text-[#858585] font-semibold text-[10px] uppercase tracking-wider font-sans">
                <span>TERMINALS ({sessions.length})</span>
                <button
                  type="button"
                  onClick={() => handleCreateNewSession()}
                  className="p-0.5 hover:text-white rounded hover:bg-[#2d2d2d] transition-colors"
                  title="New Terminal"
                >
                  <Plus size={12} />
                </button>
              </div>

              {/* Sessions list with delete icon on hover */}
              <div className="flex-1 overflow-y-auto py-1">
                {sessions.map((sess) => {
                  const isSelected = sess.id === activeSessionId;
                  return (
                    <div
                      key={sess.id}
                      onClick={() => {
                        setActiveSessionId(sess.id);
                        setTimeout(() => inputRef.current?.focus(), 50);
                      }}
                      className={`group flex items-center justify-between px-2.5 py-1.5 cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-[#141518] text-white font-medium border-l-2 border-[#007acc]"
                          : "text-[#969696] hover:bg-[#1a1b1e] hover:text-[#cccccc]"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 min-w-0 flex-1">
                        <TerminalIcon
                          size={12}
                          className={isSelected ? "text-[#3794ff]" : "text-[#858585]"}
                        />
                        <span className="truncate text-[11px] font-mono">{sess.title}</span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {sess.is_running && (
                          <span
                            className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"
                            title="Process running"
                          />
                        )}
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleKillSession(sess.id);
                          }}
                          title="Kill Terminal"
                          className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#1a1b1e] text-[#858585] hover:text-red-400 transition-opacity"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Bottom Quick Preset / Action */}
              <div className="p-2 border-t border-[#1e1f22] mt-auto font-sans bg-[#0c0d0e]">
                <button
                  type="button"
                  onClick={() => handleCreateNewSession()}
                  className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded bg-[#0c0d0e] hover:bg-[#1a1b1e] border border-[#1e1f22] text-[#cccccc] hover:text-white text-[11px] font-medium transition-colors"
                >
                  <Plus size={11} />
                  <span>New Terminal</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── 2. Problems Content ───────────────────────────────────────── */}
        {activeTab === "problems" && (
          <div className="flex-1 overflow-y-auto p-3 font-mono text-xs">
            {/* Filter buttons */}
            <div className="flex items-center gap-2 mb-2 font-sans text-[11px]">
              <span className="text-[#858585]">Filter:</span>
              <button
                onClick={() => setSeverityFilter("all")}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  severityFilter === "all" ? "bg-[#0c0d0e] text-purple-400 border border-purple-500 font-bold" : "bg-[#0c0d0e] border border-[#1e1f22] text-gray-400 hover:text-white"
                }`}
              >
                All ({errors.length})
              </button>
              <button
                onClick={() => setSeverityFilter("error")}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  severityFilter === "error" ? "bg-[#0c0d0e] text-red-400 border border-red-500 font-bold" : "bg-[#0c0d0e] border border-[#1e1f22] text-gray-400 hover:text-white"
                }`}
              >
                Errors ({errorCount})
              </button>
              <button
                onClick={() => setSeverityFilter("warning")}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  severityFilter === "warning" ? "bg-[#0c0d0e] text-yellow-400 border border-yellow-500 font-bold" : "bg-[#0c0d0e] border border-[#1e1f22] text-gray-400 hover:text-white"
                }`}
              >
                Warnings ({warningCount})
              </button>
            </div>

            {filteredErrors.length === 0 ? (
              <div className="p-8 text-center text-gray-500 font-sans">No problems detected in workspace.</div>
            ) : (
              <div className="space-y-1">
                {filteredErrors.map((err) => (
                  <div
                    key={err.id}
                    onClick={() => onSelectProblem(err.file_path, err.line || 1)}
                    className="flex items-center justify-between p-1.5 hover:bg-[#1a1b1e] rounded cursor-pointer text-xs transition-colors"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      {err.severity === "error" || err.category === "ERROR" ? (
                        <AlertCircle size={13} className="text-red-400 shrink-0" />
                      ) : (
                        <AlertTriangle size={13} className="text-yellow-400 shrink-0" />
                      )}
                      <span className="text-white truncate font-sans">{err.message}</span>
                      <span className="text-[#858585] text-[11px] font-mono shrink-0">
                        {err.file_path}:{err.line || 1}
                      </span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onTriggerFix(err);
                      }}
                      className="px-2 py-0.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-[10px] font-medium shrink-0 ml-2 font-sans flex items-center gap-1"
                    >
                      <Wand2 size={11} /> Fix
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── 3. Output Content ─────────────────────────────────────────── */}
        {activeTab === "output" && (
          <div className="flex-1 overflow-y-auto p-3 space-y-2 text-xs font-mono">
            <div className="flex items-center justify-between border-b border-[#1e1f22] pb-1.5 font-sans">
              <span className="text-[#858585] font-semibold">Repository Ingestion & Analysis Log</span>
              <span className="text-purple-400 font-bold">[{pipelineData?.pipeline_status || "DONE"}]</span>
            </div>
            <div className="space-y-1 text-gray-300 font-mono text-[11px]">
              <p className="text-gray-500">[{new Date().toLocaleTimeString()}] Pipeline Service Active</p>
              {pipelineData?.message && <p className="text-blue-400">[{pipelineData.pipeline_status}] {pipelineData.message}</p>}
              {pipelineData?.error && <p className="text-red-400 font-bold bg-red-950/30 p-2 rounded">ERROR: {pipelineData.error}</p>}
              {pipelineData?.meta_summary && (
                <div className="p-2.5 bg-[#0c0d0e] rounded border border-[#1e1f22] space-y-1 mt-2 text-[11px]">
                  <p className="text-white font-bold font-sans">Analysis Summary:</p>
                  <p>• Total Files Indexed: {pipelineData.meta_summary.total_files || 0}</p>
                  <p>• Symbols Extracted: {pipelineData.meta_summary.total_symbols || 0}</p>
                  <p>• Code Issues Detected: {pipelineData.meta_summary.total_issues || 0}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default BottomPanel;
