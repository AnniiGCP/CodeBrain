import { useState, useEffect, useCallback, useRef } from "react";
import type {
  RepoSummary,
  FileNode,
  Citation,
  FixResult,
  PipelineStatusResponse,
  ErrorReport,
  User,
  FixTask,
} from "../types";
import {
  fetchRepos,
  fetchRepoFiles,
  fetchFileContent,
  deleteRepo,
  fetchPipelineStatus,
  retriggerPipeline,
  fetchErrorReports,
  generateErrorFix,
  applyErrorFix,
  rejectErrorFix,
  fetchDocSections,
  generateMasterDocs,
  applyFix,
} from "../api";
import ConnectRepoModal from "../components/ConnectRepoModal";
import ActivityBar from "../components/ActivityBar";
import type { SidebarTab } from "../components/ActivityBar";
import PrimarySidebar from "../components/PrimarySidebar";
import EditorArea from "../components/EditorArea";
import type { EditorTab } from "../components/EditorArea";
import BottomPanel from "../components/BottomPanel";
import type { BottomTabType } from "../components/BottomPanel";
import StatusBar from "../components/StatusBar";
import CommandPalette from "../components/CommandPalette";
import type { CommandItem } from "../components/CommandPalette";
import ChatPanel from "../components/ChatPanel";
import Navigation from "../components/Navigation";
import { SettingsModal } from "../components/SettingsModal";
import {
  FolderPlus,
  RefreshCw,
  BookOpen,
  Search,
  AlertTriangle,
  ListOrdered,
  LogOut,
  ChevronLeft,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Group, Panel, Separator } from "react-resizable-panels";

interface DashboardPageProps {
  user: User;
  onLogout: () => void;
}

export default function DashboardPage({ user, onLogout }: DashboardPageProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const paramFile = searchParams.get("file");
  const paramLine = searchParams.get("line");

  // Repos state
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [activeRepo, setActiveRepo] = useState<RepoSummary | null>(null);
  const activeRepoRef = useRef<RepoSummary | null>(null);
  activeRepoRef.current = activeRepo;
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Editor cursor, indentation & language state
  const [cursorPos, setCursorPos] = useState({ line: 1, col: 1 });
  const [editorIndentation, setEditorIndentation] = useState({ tabSize: 2, insertSpaces: true });
  const [activeLanguage, setActiveLanguage] = useState("Plain Text");

  // Pipeline state map
  const [pipelineStatuses, setPipelineStatuses] = useState<Record<string, PipelineStatusResponse>>({});
  const pollingRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  // Layout states
  const [activeSidebarTab, setActiveSidebarTab] = useState<SidebarTab>("explorer");
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const [isBottomPanelOpen, setIsBottomPanelOpen] = useState(true);
  const [activeBottomTab, setActiveBottomTab] = useState<BottomTabType>("problems");

  // Multi-tab Editor state
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const fetchRequestIdRef = useRef<number>(0);

  // Issues & Doc state
  const [errors, setErrors] = useState<ErrorReport[]>([]);
  const [docSections, setDocSections] = useState<any[]>([]);
  const [masterDocContent, setMasterDocContent] = useState<string>("");
  const [activeFixTask, setActiveFixTask] = useState<FixTask | null>(null);
  const [terminalLogs, setTerminalLogs] = useState<{
    command?: string;
    output?: string;
    passed?: boolean;
    error?: string;
  } | null>(null);
  const [isApplyingFix, setIsApplyingFix] = useState(false);
  const [aiActive, setAiActive] = useState(false);

  // Command Palette
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // 2. Polling helper for pipeline status
  const startPolling = useCallback((repoId: string) => {
    if (pollingRef.current[repoId]) return;

    pollingRef.current[repoId] = setInterval(async () => {
      try {
        const s = await fetchPipelineStatus(repoId);
        setPipelineStatuses((prev) => ({ ...prev, [repoId]: s }));

        if (["DONE", "FAILED"].includes(s.pipeline_status)) {
          clearInterval(pollingRef.current[repoId]);
          delete pollingRef.current[repoId];

          // Refresh errors and docs when pipeline completes
          if (s.pipeline_status === "DONE") {
            fetchErrorReports(repoId)
              .then((res) => setErrors(res.errors || []))
              .catch(() => {});
            fetchDocSections(repoId)
              .then((res) => {
                setDocSections(res.sections || []);
                if (res.master_content) setMasterDocContent(res.master_content);
              })
              .catch(() => {});
          }
        }
      } catch {
        // ignore transient network errors
      }
    }, 2000);
  }, []);

  // 3. Load repos
  useEffect(() => {
    fetchRepos()
      .then((list) => {
        setRepos(list);
        if (list.length > 0 && !activeRepo) {
          const paramRepoId = searchParams.get("repoId");
          const savedRepoId = localStorage.getItem("codebrain_active_repo_id");
          const target =
            (paramRepoId && list.find((r) => r.repo_id === paramRepoId)) ||
            (savedRepoId && list.find((r) => r.repo_id === savedRepoId)) ||
            list[0];
          setActiveRepo(target);
          try {
            localStorage.setItem("codebrain_active_repo_id", target.repo_id);
          } catch {}
        }
        list.forEach((r) => {
          if (r.pipeline_status && !["DONE", "FAILED"].includes(r.pipeline_status)) {
            startPolling(r.repo_id);
          }
        });
      })
      .catch((err) => console.error("Failed to load repos:", err));

    return () => {
      Object.values(pollingRef.current).forEach(clearInterval);
    };
  }, [startPolling]);

  // 4. Load active repo files, errors, and docs
  useEffect(() => {
    if (!activeRepo) {
      setFileTree([]);
      setErrors([]);
      setDocSections([]);
      return;
    }

    const repoId = activeRepo.repo_id;

    // Fetch files
    fetchRepoFiles(repoId)
      .then((data) => {
        const nodes = Array.isArray(data.tree)
          ? data.tree
          : data.tree?.children || [data.tree];
        setFileTree(nodes);
      })
      .catch(console.error);

    // Fetch errors
    fetchErrorReports(repoId)
      .then((res) => setErrors(res.errors || []))
      .catch(() => setErrors([]));

    // Fetch docs
    fetchDocSections(repoId)
      .then((res) => {
        setDocSections(res.sections || []);
        if (res.master_content) setMasterDocContent(res.master_content);
      })
      .catch(() => {
        setDocSections([]);
        setMasterDocContent("");
      });

    // Fetch pipeline status
    fetchPipelineStatus(repoId)
      .then((s) => {
        setPipelineStatuses((prev) => ({ ...prev, [repoId]: s }));
        if (!["DONE", "FAILED"].includes(s.pipeline_status)) {
          startPolling(repoId);
        }
      })
      .catch(console.error);
  }, [activeRepo, startPolling]);

  // 5. Global Keyboard Shortcuts (Ctrl+B, Ctrl+J, Ctrl+Shift+P)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "p") {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setActiveSidebarTab((prev) => (prev ? null : "explorer"));
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setIsBottomPanelOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // ── Tab Management Helpers ──────────────────────────────────────────────────

  const openFileTab = useCallback((rawFilePath: string, line?: number, initialContent = "", updateUrl = true) => {
    const filePath = decodeURIComponent(rawFilePath).replace(/\\/g, "/").replace(/^\/+/, "");
    const id = `file:${filePath}`;
    setActiveTabId(id);

    setTabs((prev) => {
      const existing = prev.find((t) => t.id === id);
      if (existing) {
        return prev.map((t) => (t.id === id ? { ...t, targetLine: line, ...(initialContent ? { content: initialContent } : {}) } : t));
      }
      return [
        ...prev,
        {
          id,
          type: "file",
          title: filePath.split("/").pop() || filePath,
          filePath,
          content: initialContent || `// Loading ${filePath}...`,
          targetLine: line,
        },
      ];
    });

    if (updateUrl) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("file", filePath);
        if (line) next.set("line", String(line));
        else next.delete("line");
        return next;
      }, { replace: false });
    }

    // If initialContent was not provided, fetch full file content from backend
    if (!initialContent) {
      const currentRequestId = ++fetchRequestIdRef.current;
      if (activeRepoRef.current) {
        const repoId = activeRepoRef.current.repo_id;
        fetchFileContent(repoId, filePath)
          .then((res) => {
            if (currentRequestId !== fetchRequestIdRef.current) return; // Stale request dropped
            setTabs((prev) =>
              prev.map((t) =>
                t.id === id
                  ? {
                      ...t,
                      content: res.content,
                      language: res.language,
                    }
                  : t
              )
            );
          })
          .catch((err) => {
            if (currentRequestId !== fetchRequestIdRef.current) return;
            setTabs((prev) =>
              prev.map((t) =>
                t.id === id
                  ? {
                      ...t,
                      content: `// Error loading '${filePath}':\n// ${err.message}`,
                    }
                  : t
              )
            );
          });
      }
    }
  }, [setSearchParams]);

  const openDocTab = useCallback((section: any) => {
    const isMaster = section.section_number === 0 || section.section_number === "master";
    const id = isMaster ? "doc:master" : `doc:${section.section_number}`;
    setTabs((prev) => {
      const existing = prev.find((t) => t.id === id);
      if (existing) return prev;
      return [
        ...prev,
        {
          id,
          type: "doc",
          title: isMaster ? "Master Technical Documentation" : `${section.section_number}. ${section.title}`,
          docSection: section,
          content: section.content,
        },
      ];
    });
    setActiveTabId(id);
  }, []);

  const openDiffTab = useCallback((diff: string, title: string, errorId?: string, fixResult?: FixResult) => {
    const id = `diff:${errorId || Date.now()}`;
    setTabs((prev) => {
      const existing = prev.find((t) => t.id === id);
      if (existing) return prev;
      return [
        ...prev,
        {
          id,
          type: "diff",
          title: `Diff: ${title}`,
          diff,
          errorId,
          fixResult,
        },
      ];
    });
    setActiveTabId(id);
  }, []);

  const handleSelectTab = useCallback((id: string) => {
    setActiveTabId(id);
    const tab = tabs.find((t) => t.id === id);
    if (tab && tab.type === "file" && tab.filePath) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("file", tab.filePath!);
        if (tab.targetLine) next.set("line", String(tab.targetLine));
        else next.delete("line");
        return next;
      }, { replace: false });
    } else {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("file");
        next.delete("line");
        return next;
      }, { replace: false });
    }
  }, [tabs, setSearchParams]);

  const handleCloseTab = useCallback((id: string) => {
    setTabs((prev) => {
      const filtered = prev.filter((t) => t.id !== id);
      if (activeTabId === id) {
        const nextTab = filtered.length > 0 ? filtered[filtered.length - 1] : null;
        if (nextTab) {
          setActiveTabId(nextTab.id);
          if (nextTab.type === "file" && nextTab.filePath) {
            setSearchParams((sp) => {
              const next = new URLSearchParams(sp);
              next.set("file", nextTab.filePath!);
              return next;
            }, { replace: false });
          } else {
            setSearchParams((sp) => {
              const next = new URLSearchParams(sp);
              next.delete("file");
              next.delete("line");
              return next;
            }, { replace: false });
          }
        } else {
          setActiveTabId(null);
          setSearchParams((sp) => {
            const next = new URLSearchParams(sp);
            next.delete("file");
            next.delete("line");
            return next;
          }, { replace: false });
        }
      }
      return filtered;
    });
  }, [activeTabId, setSearchParams]);

  // Synchronize browser URL parameter with open file (deep link & browser back/forward)
  useEffect(() => {
    if (paramFile) {
      const decoded = decodeURIComponent(paramFile).replace(/\\/g, "/").replace(/^\/+/, "");
      const targetLine = paramLine ? parseInt(paramLine, 10) : undefined;
      const targetId = `file:${decoded}`;
      if (activeTabId !== targetId) {
        openFileTab(decoded, targetLine, "", false);
      }
    } else {
      if (activeTabId && activeTabId.startsWith("file:")) {
        setActiveTabId(null);
      }
    }
  }, [paramFile, paramLine, activeTabId, openFileTab]);

  // Load content for any open tab that is still in Loading state once activeRepo becomes available
  useEffect(() => {
    if (!activeRepo) return;
    const repoId = activeRepo.repo_id;
    tabs.forEach((tab) => {
      if (tab.type === "file" && tab.filePath && (!tab.content || tab.content.startsWith("// Loading"))) {
        const currentReq = ++fetchRequestIdRef.current;
        fetchFileContent(repoId, tab.filePath)
          .then((res) => {
            if (currentReq !== fetchRequestIdRef.current && tab.id === activeTabId) return;
            setTabs((prev) =>
              prev.map((t) =>
                t.id === tab.id
                  ? {
                      ...t,
                      content: res.content,
                      language: res.language,
                    }
                  : t
              )
            );
          })
          .catch((err) => {
            setTabs((prev) =>
              prev.map((t) =>
                t.id === tab.id
                  ? {
                      ...t,
                      content: `// Error loading '${tab.filePath}':\n// ${err.message}`,
                    }
                  : t
              )
            );
          });
      }
    });
  }, [activeRepo]);

  const handleCursorChange = useCallback((line: number, col: number) => {
    setCursorPos((prev) => (prev.line === line && prev.col === col ? prev : { line, col }));
  }, []);

  const handleIndentationDetected = useCallback((tabSize: number, insertSpaces: boolean) => {
    setEditorIndentation((prev) => (prev.tabSize === tabSize && prev.insertSpaces === insertSpaces ? prev : { tabSize, insertSpaces }));
  }, []);

  const handleLanguageDetected = useCallback((name: string) => {
    setActiveLanguage((prev) => (prev === name ? prev : name));
  }, []);

  // ── Actions & Handlers ──────────────────────────────────────────────────────

  const countDiffLines = (diffStr: string) => {
    let added = 0;
    let deleted = 0;
    for (const line of diffStr.split("\n")) {
      if (line.startsWith("+") && !line.startsWith("+++")) added++;
      else if (line.startsWith("-") && !line.startsWith("---")) deleted++;
    }
    return { added, deleted };
  };

  const handleTriggerFix = async (err: ErrorReport) => {
    if (!activeRepo) return;
    const repoId = activeRepo.repo_id;
    setAiActive(true);
    setIsRightPanelOpen(true); // Canonical: open/focus Copilot sidebar
    setIsBottomPanelOpen(true);
    setActiveBottomTab("terminal");

    const initialTask: FixTask = {
      taskId: err.id,
      repoId,
      repoName: activeRepo.name,
      errorReport: err,
      stage: "INSPECTING",
      log: [
        {
          timestamp: new Date().toLocaleTimeString(),
          step: "Issue Collected",
          detail: `[${err.rule_id}] ${err.message} (${err.file_path}:${err.line || 1})`,
          status: "done",
        },
        {
          timestamp: new Date().toLocaleTimeString(),
          step: "Files Inspected",
          detail: `Inspected source file: ${err.file_path}`,
          status: "done",
        },
        {
          timestamp: new Date().toLocaleTimeString(),
          step: "Root-Cause Assessment",
          detail: "Formulating minimal patch and static safety verification plan",
          status: "running",
        },
      ],
      createdAt: Date.now(),
    };
    setActiveFixTask(initialTask);

    try {
      const res = await generateErrorFix(repoId, err.id);
      const diffCounts = countDiffLines(res.suggested_fix || "");

      const updatedTask: FixTask = {
        ...initialTask,
        stage: res.passed ? "READY" : "FAILED",
        explanation: res.explanation ?? undefined,
        diff: res.suggested_fix ?? undefined,
        linesAdded: diffCounts.added,
        linesDeleted: diffCounts.deleted,
        testCommand: res.test_command ?? undefined,
        testOutput: res.output ?? undefined,
        passed: res.passed,
        error: res.error ?? undefined,
        patch_status: res.patch_status,
        validation_status: res.validation_status ?? "NOT_RUN",
        validation_skipped: res.validation_skipped ?? true,
        validation_notice: res.validation_notice,
        changed_files: res.changed_files ?? (err.file_path ? [err.file_path] : []),
        log: [
          { timestamp: initialTask.log[0].timestamp, step: "Issue Collected", detail: initialTask.log[0].detail, status: "done" },
          { timestamp: initialTask.log[1].timestamp, step: "Files Inspected", detail: initialTask.log[1].detail, status: "done" },
          {
            timestamp: new Date().toLocaleTimeString(),
            step: "Root-Cause Assessment",
            detail: res.explanation ? res.explanation.slice(0, 120) + "…" : "Diagnosis complete",
            status: "done",
          },
          {
            timestamp: new Date().toLocaleTimeString(),
            step: "Patch Generated",
            detail: `${res.fix_attribution || "Fixed using APInex GPT-6 Luna"} (+${diffCounts.added} / -${diffCounts.deleted} lines in ${err.file_path})`,
            status: res.passed ? "done" : "error",
          },
          {
            timestamp: new Date().toLocaleTimeString(),
            step: "Patch Applied",
            detail: res.passed ? "Ready to apply — click Accept & Apply to write changes" : "Patch generation did not complete",
            status: res.passed ? "running" : "error",
          },
        ],
      };
      setActiveFixTask(updatedTask);

      setTerminalLogs({
        command: "static-patch-validation",
        output:
          (res.output || "Patch generated and validated statically without code execution.\n") +
          `[Target]: ${err.file_path}\n` +
          `[Changes]: +${diffCounts.added} / -${diffCounts.deleted} lines`,
        passed: res.passed,
        error: res.error || undefined,
      });

      // Refresh error item in list
      setErrors((prev) =>
        prev.map((item) =>
          item.id === err.id
            ? {
                ...item,
                fix_status: res.fix_status,
                explanation: res.explanation ?? null,
                suggested_fix: res.suggested_fix ?? null,
                fix_model: res.model_used || item.fix_model,
                fix_provider: res.provider_used || item.fix_provider,
                fix_attribution: res.fix_attribution || item.fix_attribution,
                fix_attempts: res.attempts || item.fix_attempts,
              }
            : item
        )
      );

      // Open diff tab
      openDiffTab(res.suggested_fix || "", err.file_path || "Patch", err.id, {
        symbol_id: err.symbol_id || 0,
        file_path: err.file_path,
        language: err.language || "python",
        diff: res.suggested_fix || "",
        model_used: res.model_used || "free/gpt-6-luna",
        provider: res.provider_used || "apinex",
        fix_attribution: res.fix_attribution || undefined,
      });
    } catch (e: any) {
      setActiveFixTask({
        ...initialTask,
        stage: "FAILED",
        error: e.message || "Failed to generate fix",
        log: [
          ...initialTask.log,
          {
            timestamp: new Date().toLocaleTimeString(),
            step: "Generation Error",
            detail: e.message || "AI provider or sandbox error",
            status: "error",
          },
        ],
      });
      setTerminalLogs({
        command: "generate-fix",
        output: "",
        passed: false,
        error: e.message || "Failed to generate fix",
      });
    } finally {
      setAiActive(false);
    }
  };

  const handleRejectFixTask = async (task: FixTask) => {
    if (!activeRepo) return;
    try {
      await rejectErrorFix(task.repoId, task.taskId);
      setActiveFixTask((prev) => (prev && prev.taskId === task.taskId ? { ...prev, stage: "REJECTED" } : prev));
      setErrors((prev) =>
        prev.map((e) => (e.id === task.taskId ? { ...e, fix_status: "REJECTED" } : e))
      );
      setTabs((prev) => prev.filter((t) => t.id !== `diff:${task.taskId}`));
    } catch (err: any) {
      alert(`Reject failed: ${err.message}`);
    }
  };

  const handleApplyFixTask = async (task: FixTask) => {
    if (!activeRepo || !task.diff) return;
    try {
      await handleApplyFix(
        {
          symbol_id: task.errorReport.symbol_id || 0,
          file_path: task.errorReport.file_path,
          language: task.errorReport.language || "python",
          diff: task.diff,
          model_used: "router",
        },
        task.taskId
      );
      setActiveFixTask((prev) => {
        if (!prev || prev.taskId !== task.taskId) return prev;
        const updatedLog = prev.log.map((entry) =>
          entry.step === "Patch Applied"
            ? { ...entry, status: "done" as const, detail: "Patch applied cleanly to repository files." }
            : entry
        );
        return {
          ...prev,
          stage: "APPLIED",
          patch_status: "FIX_APPLIED",
          validation_status: "NOT_RUN",
          log: updatedLog,
        };
      });
    } catch (err: any) {
      alert(`Apply failed: ${err.message}`);
    }
  };

  const handleReviewDiffTask = (task: FixTask, specificPath?: string, specificDiff?: string) => {
    const diffToOpen = specificDiff || task.diff;
    const pathToOpen = specificPath || task.errorReport.file_path;
    if (diffToOpen) {
      openDiffTab(diffToOpen, pathToOpen, task.taskId);
    }
  };

  const handleApplyFix = async (fix: FixResult, errorId?: string) => {
    if (!activeRepo) return;
    const repoId = activeRepo.repo_id;
    setIsApplyingFix(true);
    try {
      if (errorId) {
        const res = await applyErrorFix(repoId, errorId);
        setTerminalLogs({
          command: "apply-fix & git commit",
          output: res.output || `Fix applied successfully. Status: ${res.fix_status}`,
          passed: res.passed,
          error: res.error || undefined,
        });
        setErrors((prev) =>
          prev.map((e) =>
            e.id === errorId
              ? { ...e, fix_status: res.fix_status, pr_url: res.pr_url, pr_id: (res as any).pr_id ?? (res as any).pr_number }
              : e
          )
        );
      } else {
        const res = await applyFix(repoId, {
          diff: fix.diff,
          file_path: fix.file_path,
          pr_title: `Fix ${fix.file_path}`,
          pr_body: "Automated fix applied via CodeBrain IDE",
        });
        setTerminalLogs({
          command: "gitops apply-fix",
          output: `Branch '${res.branch_name}' created. PR URL: ${res.pr_url || "Local applied"}`,
          passed: true,
        });
      }
    } catch (err: any) {
      setTerminalLogs({
        command: "apply-fix",
        output: "",
        passed: false,
        error: err.message || "Failed to apply fix",
      });
    } finally {
      setIsApplyingFix(false);
    }
  };

  const handleGenerateMasterDocs = async () => {
    if (!activeRepo) return;
    const repoId = activeRepo.repo_id;
    setAiActive(true);
    setIsBottomPanelOpen(true);
    setActiveBottomTab("output");
    try {
      const res = await generateMasterDocs(repoId);
      setDocSections(res.sections || []);
      navigate("/docs");
    } catch (e: any) {
      console.error(e);
    } finally {
      setAiActive(false);
    }
  };

  const handleCitationClick = (citation: Citation) => {
    openFileTab(
      citation.file_path,
      citation.start_line,
      citation.source_code ? `// ${citation.file_path}\n\n${citation.source_code}` : ""
    );
  };

  // Command palette commands
  const commands: CommandItem[] = [
    {
      id: "connect_repo",
      title: "Connect Repository",
      category: "Repository",
      icon: FolderPlus,
      action: () => setShowConnectModal(true),
      shortcut: "Ctrl+Shift+N",
    },
    {
      id: "detect_errors",
      title: "Run Analysis & Detect Errors",
      category: "Pipeline",
      icon: RefreshCw,
      action: () => {
        if (activeRepo) {
          retriggerPipeline(activeRepo.repo_id);
          setIsBottomPanelOpen(true);
          setActiveBottomTab("output");
        }
      },
    },
    {
      id: "generate_docs",
      title: "Generate Master Documentation Suite",
      category: "Documentation",
      icon: BookOpen,
      action: handleGenerateMasterDocs,
    },
    {
      id: "search_code",
      title: "Search Codebase (Semantic)",
      category: "Search",
      icon: Search,
      action: () => setActiveSidebarTab("search"),
      shortcut: "Ctrl+Shift+F",
    },
    {
      id: "view_problems",
      title: "View Problems Panel",
      category: "View",
      icon: AlertTriangle,
      action: () => {
        setIsBottomPanelOpen(true);
        setActiveBottomTab("problems");
      },
    },
    {
      id: "view_output",
      title: "View Pipeline Output",
      category: "View",
      icon: ListOrdered,
      action: () => {
        setIsBottomPanelOpen(true);
        setActiveBottomTab("output");
      },
    },
    {
      id: "logout",
      title: "Log Out",
      category: "Account",
      icon: LogOut,
      action: onLogout,
    },
  ];

  const activeRepoId = activeRepo ? activeRepo.repo_id : "";
  const currentPipelineData = activeRepoId ? pipelineStatuses[activeRepoId] || null : null;
  const errorCount = errors.filter((e) => e.severity === "error").length;
  const warningCount = errors.filter((e) => e.severity === "warning").length;
  const activeTab = tabs.find((t) => t.id === activeTabId);
  const activeFilePath = activeTab?.type === "file" ? activeTab.filePath : undefined;

  return (
    <div className="h-screen w-screen flex flex-col bg-[#0c0d0e] text-[#cccccc] select-none overflow-hidden font-sans">
      <Navigation
        user={user}
        onLogout={onLogout}
        onToggleChat={() => setIsRightPanelOpen((prev) => !prev)}
        onToggleTerminal={() => {
          setIsBottomPanelOpen((prev) => !prev);
          setActiveBottomTab("terminal");
        }}
        isChatOpen={isRightPanelOpen}
        isTerminalOpen={isBottomPanelOpen && activeBottomTab === "terminal"}
      />
      
      {/* ── Main IDE Layout (Activity Bar + Resizable Sidebar + Editor + AI Chat) ────────── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 1. Activity Bar (48px fixed) */}
        <ActivityBar
          activeTab={activeSidebarTab}
          onTabChange={(tab) => {
            if (activeSidebarTab === tab) {
              setActiveSidebarTab(null);
            } else {
              setActiveSidebarTab(tab);
            }
          }}
          errorCount={errors.length}
          user={user}
          onLogout={onLogout}
          onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        />

        {/* 2. Main Resizable Horizontal Layout */}
        <div className="flex-1 flex overflow-hidden relative">
          <Group
            id="codebrain-horizontal-group"
            orientation="horizontal"
            className="flex-1 h-full"
            onLayoutChanged={(layout) => {
              try {
                localStorage.setItem("codebrain-ide-h-layout", JSON.stringify(layout));
              } catch {}
            }}
          >
            {/* Left Primary Sidebar Panel (Explorer / Search / Issues / Docs / GitOps) */}
            {activeSidebarTab && (
              <>
                <Panel
                  id="primary-sidebar"
                  defaultSize="18%"
                  minSize="12%"
                  maxSize="35%"
                  collapsible
                  className="h-full bg-[#0c0d0e] overflow-hidden"
                >
                  <PrimarySidebar
                    activeTab={activeSidebarTab}
                    repos={repos}
                    activeRepo={activeRepo}
                    onSelectRepo={(r) => {
                      setActiveRepo(r);
                      try {
                        localStorage.setItem("codebrain_active_repo_id", r.repo_id);
                      } catch {}
                    }}
                    onDeleteRepo={(r) => {
                      if (confirm(`Remove repository ${r.name}?`)) {
                        deleteRepo(r.repo_id).then(() => {
                          setRepos((prev) => prev.filter((item) => item.repo_id !== r.repo_id));
                          setActiveRepo(null);
                        });
                      }
                    }}
                    onOpenConnectModal={() => setShowConnectModal(true)}
                    onRetryPipeline={() => {
                      if (activeRepo) retriggerPipeline(activeRepo.repo_id);
                    }}
                    fileTree={fileTree}
                    onSelectFile={(path, line) => openFileTab(path, line)}
                    errors={errors}
                    onTriggerFix={handleTriggerFix}
                    docSections={docSections}
                    masterContent={masterDocContent}
                    onSelectDocSection={(sec) => openDocTab(sec)}
                    onOpenPR={() => {
                      if (errors.length > 0) handleTriggerFix(errors[0]);
                    }}
                    onSelectDiff={(diff, title) => openDiffTab(diff, title)}
                  />
                </Panel>
                <Separator className="w-1 bg-[#1e1f22] hover:bg-purple-500 active:bg-purple-500 transition-colors cursor-col-resize z-10" />
              </>
            )}

            {/* Center Workspace (Editor + Bottom Panel) */}
            <Panel
              id="center-workspace"
              minSize="30%"
              className="h-full bg-[#0c0d0e] overflow-hidden flex flex-col"
            >
              <Group
                id="codebrain-vertical-group"
                orientation="vertical"
                className="flex-1 h-full"
                onLayoutChanged={(layout) => {
                  try {
                    localStorage.setItem("codebrain-ide-v-layout", JSON.stringify(layout));
                  } catch {}
                }}
              >
                {/* Editor Area (Top) */}
                <Panel
                  id="editor-pane"
                  minSize="25%"
                  className="h-full overflow-hidden"
                >
                  <EditorArea
                    tabs={tabs}
                    activeTabId={activeTabId}
                    onSelectTab={handleSelectTab}
                    onCloseTab={handleCloseTab}
                    onApplyFix={handleApplyFix}
                    onRejectFix={(errorId) => {
                      setTabs((prev) => prev.filter((t) => t.errorId !== errorId));
                    }}
                    isApplyingFix={isApplyingFix}
                    onCursorChange={handleCursorChange}
                    onIndentationDetected={handleIndentationDetected}
                    onLanguageDetected={handleLanguageDetected}
                    indentation={editorIndentation}
                    errors={errors}
                    onChangeContent={(val) => {
                      if (activeTabId) {
                        setTabs((prev) => prev.map((t) => (t.id === activeTabId ? { ...t, content: val } : t)));
                      }
                    }}
                  />
                </Panel>

                {/* Bottom Panel (Problems / Output / Terminal / PR Status) */}
                {isBottomPanelOpen && (
                  <>
                    <Separator className="h-1 bg-[#1e1f22] hover:bg-purple-500 active:bg-purple-500 transition-colors cursor-row-resize z-10" />
                    <Panel
                      id="bottom-pane"
                      defaultSize="26%"
                      minSize="12%"
                      maxSize="60%"
                      collapsible
                      className="h-full bg-[#0c0d0e] overflow-hidden"
                    >
                      <BottomPanel
                        activeTab={activeBottomTab}
                        onTabChange={(tab) => setActiveBottomTab(tab)}
                        onClose={() => setIsBottomPanelOpen(false)}
                        errors={errors}
                        pipelineData={currentPipelineData}
                        terminalLogs={terminalLogs}
                        onSelectProblem={(filePath, line) => openFileTab(filePath, line)}
                        onTriggerFix={handleTriggerFix}
                        repoId={activeRepo?.repo_id}
                      />
                    </Panel>
                  </>
                )}
              </Group>
            </Panel>

            {/* Right Copilot AI Sidebar */}
            {isRightPanelOpen && activeRepo && (
              <>
                <Separator className="w-1 bg-[#1e1f22] hover:bg-purple-500 active:bg-purple-500 transition-colors cursor-col-resize z-10" />
                <Panel
                  id="ai-sidebar"
                  defaultSize="26%"
                  minSize="18%"
                  maxSize="45%"
                  collapsible
                  className="h-full bg-[#0c0d0e] overflow-hidden flex flex-col"
                >
                  <aside className="h-full w-full flex flex-col bg-[#0c0d0e] overflow-hidden" aria-label="AI Assistant">
                    <ChatPanel
                      repo={activeRepo}
                      activeFilePath={activeFilePath}
                      onFixClick={handleCitationClick}
                      activeFixTask={activeFixTask}
                      onApplyFix={handleApplyFixTask}
                      onRejectFix={handleRejectFixTask}
                      onReviewDiff={handleReviewDiffTask}
                      onClose={() => setIsRightPanelOpen(false)}
                    />
                  </aside>
                </Panel>
              </>
            )}
          </Group>

          {/* Floating reopen button if right panel is collapsed */}
          {!isRightPanelOpen && activeRepo && (
            <button
              onClick={() => setIsRightPanelOpen(true)}
              title="Open CodeBrain AI"
              className="absolute right-3 top-3 z-20 p-2 bg-purple-600 hover:bg-purple-500 text-white rounded-lg shadow-xl transition-all border border-purple-500/40 cursor-pointer"
            >
              <ChevronLeft size={16} />
            </button>
          )}
        </div>
      </div>

      {/* 5. Status Bar (22px bottom strip) */}
      <StatusBar
        activeRepo={activeRepo}
        pipelineData={currentPipelineData}
        errorCount={errorCount}
        warningCount={warningCount}
        user={user}
        aiActive={aiActive}
        cursorLine={cursorPos.line}
        cursorCol={cursorPos.col}
        indentation={editorIndentation}
        onChangeIndentation={(tabSize, insertSpaces) => setEditorIndentation({ tabSize, insertSpaces })}
        activeLanguage={activeLanguage}
        encoding="UTF-8"
        lineEnding="LF"
        onGoToLine={() => {
          const target = window.prompt("Go to line number:");
          if (target) {
            const lineNum = parseInt(target.trim(), 10);
            if (!isNaN(lineNum) && lineNum > 0 && activeTabId) {
              setTabs((prev) => prev.map((t) => (t.id === activeTabId ? { ...t, targetLine: lineNum } : t)));
            }
          }
        }}
        onOpenIssues={() => {
          setIsBottomPanelOpen(true);
          setActiveBottomTab("problems");
        }}
        onOpenOutput={() => {
          setIsBottomPanelOpen(true);
          setActiveBottomTab("output");
        }}
        onToggleCopilot={() => {
          if (!activeRepo) {
            setShowConnectModal(true);
            return;
          }
          if (!isRightPanelOpen) {
            setIsRightPanelOpen(true);
            setTimeout(() => {
              document.getElementById("chat-input")?.focus();
            }, 100);
          } else {
            const inputEl = document.getElementById("chat-input");
            if (document.activeElement === inputEl) {
              setIsRightPanelOpen(false);
            } else {
              inputEl?.focus();
            }
          }
        }}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        onOpenSettings={() => setShowSettingsModal(true)}
      />

      {/* 6. Command Palette Modal */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        commands={commands}
      />

      {/* 7. Connect Repository Modal */}
      {showConnectModal && (
        <ConnectRepoModal
          onClose={() => setShowConnectModal(false)}
          onRepoAdded={(repo) => {
            setRepos((prev) => [repo, ...prev]);
            setActiveRepo(repo);
            setShowConnectModal(false);
            startPolling(repo.repo_id);
          }}
        />
      )}

      {/* 8. Settings Modal */}
      {showSettingsModal && (
        <SettingsModal
          isOpen={showSettingsModal}
          onClose={() => setShowSettingsModal(false)}
        />
      )}
    </div>
  );
}
