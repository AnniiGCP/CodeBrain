import type { FC } from "react";
import { useRef, useEffect } from "react";
import Editor from "@monaco-editor/react";
import { X, FileCode, BookOpen, GitCompare, Check, ExternalLink } from "lucide-react";
import MermaidDiagram from "./MermaidDiagram";
import MarkdownRenderer from "./MarkdownRenderer";
import DiffViewer from "./DiffViewer";
import type { FixResult, ErrorReport } from "../types";
import { detectLanguage, getLanguageDisplayName, detectIndentation, getLanguageInfo } from "../utils/language";
import { registerCodeBrainTheme, CODEBRAIN_THEME_NAME } from "../utils/editorTheme";

export type EditorTabType = "file" | "doc" | "diff";

export interface EditorTab {
  id: string;
  type: EditorTabType;
  title: string;
  filePath?: string;
  content?: string;
  language?: string;
  targetLine?: number;
  docSection?: any;
  fixResult?: FixResult;
  diff?: string;
  errorId?: string;
}

interface EditorAreaProps {
  tabs: EditorTab[];
  activeTabId: string | null;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
  onApplyFix?: (fix: FixResult, errorId?: string) => Promise<void>;
  onRejectFix?: (errorId?: string) => void;
  onOpenPR?: () => void;
  isApplyingFix?: boolean;
  onCursorChange?: (line: number, col: number) => void;
  onIndentationDetected?: (tabSize: number, insertSpaces: boolean) => void;
  onLanguageDetected?: (displayName: string, langId: string) => void;
  indentation?: { tabSize: number; insertSpaces: boolean };
  errors?: ErrorReport[];
  onChangeContent?: (newContent: string) => void;
  readOnly?: boolean;
}

function getTabIcon(tab: EditorTab) {
  if (tab.type === "doc") {
    return <BookOpen size={13} className="text-[#89d185]" />;
  }
  if (tab.type === "diff") {
    return <GitCompare size={13} className="text-[#f48771]" />;
  }

  const langInfo = getLanguageInfo(tab.filePath);
  switch (langInfo.id) {
    case "yaml":
      return <span className="text-[12px]" title="YAML">📋</span>;
    case "json":
      return <span className="text-[11px] font-mono text-yellow-400 font-bold" title="JSON">{"{}"}</span>;
    case "python":
      return <span className="text-[12px]" title="Python">🐍</span>;
    case "typescript":
      return <span className="text-[11px] font-mono font-bold text-blue-400" title="TypeScript">TS</span>;
    case "javascript":
      return <span className="text-[11px] font-mono font-bold text-yellow-300" title="JavaScript">JS</span>;
    case "markdown":
      return <span className="text-[12px]" title="Markdown">📝</span>;
    case "dockerfile":
      return <span className="text-[12px]" title="Docker">🐳</span>;
    default:
      return <FileCode size={13} className="text-[#75beff]" />;
  }
}

const EditorArea: FC<EditorAreaProps> = ({
  tabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
  onApplyFix,
  onRejectFix,
  onOpenPR,
  isApplyingFix = false,
  onCursorChange,
  onIndentationDetected,
  onLanguageDetected,
  indentation,
  errors = [],
  onChangeContent,
  readOnly = false,
}) => {
  const activeTab = tabs.find((t) => t.id === activeTabId);
  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);

  const lastNotifiedLangRef = useRef<string>("");
  const lastNotifiedIndentRef = useRef<string>("");

  // Detect and notify language and indentation whenever active tab changes
  useEffect(() => {
    if (activeTab && activeTab.type === "file" && activeTab.filePath) {
      const detectedLangId = detectLanguage(activeTab.filePath);
      const displayName = getLanguageDisplayName(activeTab.filePath);
      const langKey = `${activeTab.id}:${displayName}:${detectedLangId}`;
      if (lastNotifiedLangRef.current !== langKey) {
        lastNotifiedLangRef.current = langKey;
        onLanguageDetected?.(displayName, detectedLangId);
      }

      const detectedIndent = detectIndentation(activeTab.filePath, activeTab.content);
      const indentKey = `${activeTab.id}:${detectedIndent.tabSize}:${detectedIndent.insertSpaces}`;
      if (lastNotifiedIndentRef.current !== indentKey) {
        lastNotifiedIndentRef.current = indentKey;
        onIndentationDetected?.(detectedIndent.tabSize, detectedIndent.insertSpaces);
      }
    }
  }, [activeTab?.id, activeTab?.filePath, activeTab?.content, onLanguageDetected, onIndentationDetected]);

  // Synchronize model value if tab content updates externally (e.g. async fetch completes)
  useEffect(() => {
    if (editorRef.current && activeTab && activeTab.type === "file" && activeTab.content !== undefined) {
      const currentVal = editorRef.current.getValue();
      if (currentVal !== activeTab.content) {
        editorRef.current.setValue(activeTab.content);
      }
    }
  }, [activeTab?.id, activeTab?.content]);

  // Jump to target line when activeTab or targetLine changes
  useEffect(() => {
    if (activeTab?.targetLine && editorRef.current) {
      editorRef.current.revealLineInCenter(activeTab.targetLine);
      editorRef.current.setPosition({ lineNumber: activeTab.targetLine, column: 1 });
      onCursorChange?.(activeTab.targetLine, 1);
    }
  }, [activeTab?.targetLine, activeTabId, onCursorChange]);

  // Update editor markers (diagnostics / problem squiggles) when errors or active file changes
  useEffect(() => {
    if (!editorRef.current || !monacoRef.current || !activeTab?.filePath) return;
    const model = editorRef.current.getModel();
    if (!model) return;

    const fileErrors = errors.filter(
      (e) => e.file_path && activeTab.filePath && (activeTab.filePath.endsWith(e.file_path) || e.file_path.endsWith(activeTab.filePath))
    );

    const markers = fileErrors.map((err) => {
      const line = err.line && err.line > 0 ? err.line : 1;
      const isError = err.severity === "error" || err.category === "ERROR";
      return {
        startLineNumber: line,
        startColumn: 1,
        endLineNumber: line,
        endColumn: model.getLineMaxColumn(line) || 80,
        message: `[${err.rule_id || "CodeBrain"}] ${err.message}`,
        severity: isError ? monacoRef.current.MarkerSeverity.Error : monacoRef.current.MarkerSeverity.Warning,
      };
    });

    monacoRef.current.editor.setModelMarkers(model, "codebrain-errors", markers);
  }, [errors, activeTab?.filePath, activeTabId]);

  // Update indentation dynamically on current model if indentation prop updates
  useEffect(() => {
    if (editorRef.current && indentation) {
      const model = editorRef.current.getModel();
      if (model) {
        model.updateOptions({
          tabSize: indentation.tabSize,
          insertSpaces: indentation.insertSpaces,
        });
      }
    }
  }, [indentation]);

  const handleEditorWillMount = (monaco: any) => {
    monacoRef.current = monaco;
    registerCodeBrainTheme(monaco);
  };

  const handleEditorDidMount = (editor: any, monaco: any) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Apply custom theme immediately
    monaco.editor.setTheme(CODEBRAIN_THEME_NAME);

    // Initial position & cursor tracking
    const pos = editor.getPosition();
    if (pos) {
      onCursorChange?.(pos.lineNumber, pos.column);
    }

    editor.onDidChangeCursorPosition((e: any) => {
      onCursorChange?.(e.position.lineNumber, e.position.column);
    });

    // Content change handler for live editing
    editor.onDidChangeModelContent(() => {
      const val = editor.getValue();
      onChangeContent?.(val);
    });

    // Auto-indentation setup
    if (activeTab?.filePath) {
      const detectedIndent = detectIndentation(activeTab.filePath, activeTab.content);
      const model = editor.getModel();
      if (model) {
        model.updateOptions({
          tabSize: indentation?.tabSize ?? detectedIndent.tabSize,
          insertSpaces: indentation?.insertSpaces ?? detectedIndent.insertSpaces,
        });
      }
    }

    if (activeTab?.targetLine) {
      editor.revealLineInCenter(activeTab.targetLine);
      editor.setPosition({ lineNumber: activeTab.targetLine, column: 1 });
      onCursorChange?.(activeTab.targetLine, 1);
    }
  };

  const detectedLanguage = activeTab?.filePath ? detectLanguage(activeTab.filePath) : "plaintext";
  const effectiveIndentation = activeTab?.filePath
    ? detectIndentation(activeTab.filePath, activeTab.content)
    : { tabSize: 2, insertSpaces: true };

  return (
    <div className="h-full w-full bg-[#0c0d0e] flex flex-col overflow-hidden select-none">
      {/* ── Tabs Bar ────────────────────────────────────────────────────── */}
      <div className="flex items-center bg-[#0c0d0e] border-b border-[#1e1f22] overflow-x-auto shrink-0 h-9 scrollbar-none">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTabId;
          return (
            <div
              key={tab.id}
              onClick={() => onSelectTab(tab.id)}
              className={`group flex items-center gap-2 px-3 h-full border-r border-[#1e1f22] cursor-pointer text-xs transition-colors shrink-0 ${
                isActive
                  ? "bg-[#0c0d0e] text-white tab-active-top-border font-medium"
                  : "bg-[#0c0d0e] text-[#858585] hover:bg-[#141518] hover:text-[#cccccc]"
              }`}
            >
              {getTabIcon(tab)}
              <span className="truncate max-w-[160px] font-mono text-[11px]">{tab.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onCloseTab(tab.id);
                }}
                className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-[#18191c] hover:text-white rounded transition-all ml-1"
                title="Close Tab"
              >
                <X size={12} />
              </button>
            </div>
          );
        })}
      </div>

      {/* ── Breadcrumb Bar ─────────────────────────────────────────────── */}
      {activeTab && activeTab.type === "file" && activeTab.filePath && (
        <div className="h-6 bg-[#0c0d0e] border-b border-[#1e1f22] px-3 flex items-center gap-1.5 text-[11px] text-[#7d8590] shrink-0 font-mono select-none overflow-x-auto">
          {activeTab.filePath.split("/").map((part, idx, arr) => (
            <span key={idx} className="flex items-center gap-1">
              <span className={idx === arr.length - 1 ? "text-[#e6edf3] font-medium" : "hover:text-[#adbac7] cursor-pointer"}>
                {part}
              </span>
              {idx < arr.length - 1 && <span className="text-[#484f58]">›</span>}
            </span>
          ))}
        </div>
      )}

      {/* ── Main Tab Content ────────────────────────────────────────────── */}
      <div className="flex-1 relative overflow-hidden bg-[#0c0d0e]">
        {!activeTab ? (
          /* Empty Workspace Watermark */
          <div className="h-full w-full flex flex-col items-center justify-center text-[#858585] p-6 text-center select-none bg-[#0c0d0e]">
            <div className="w-16 h-16 rounded-2xl bg-[#0c0d0e] border border-[#1e1f22] flex items-center justify-center mb-4 text-purple-400">
              <FileCode size={32} />
            </div>
            <h2 className="text-sm font-semibold text-[#cccccc] mb-1">No Open Files</h2>
            <p className="text-xs text-[#858585] max-w-sm mb-4">
              Select a file from the Explorer, search symbols, or open technical documentation.
            </p>
            <div className="flex flex-col gap-1.5 text-xs text-[#666666] font-mono">
              <div>
                <span className="bg-[#0c0d0e] border border-[#1e1f22] px-1.5 py-0.5 rounded text-gray-300">Ctrl+Shift+P</span> Command Palette
              </div>
              <div>
                <span className="bg-[#0c0d0e] border border-[#1e1f22] px-1.5 py-0.5 rounded text-gray-300">Ctrl+Shift+F</span> Search Codebase
              </div>
              <div>
                <span className="bg-[#0c0d0e] border border-[#1e1f22] px-1.5 py-0.5 rounded text-gray-300">Ctrl+B</span> Toggle Primary Sidebar
              </div>
            </div>
          </div>
        ) : activeTab.type === "file" ? (
          /* Monaco Code Editor with isolated buffer model per tab */
          <Editor
            key={activeTab.id}
            path={activeTab.filePath || activeTab.id}
            height="100%"
            language={detectedLanguage}
            theme={CODEBRAIN_THEME_NAME}
            value={activeTab.content || ""}
            beforeMount={handleEditorWillMount}
            options={{
              readOnly,
              minimap: { enabled: true, maxColumn: 80 },
              fontSize: 13,
              fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace",
              scrollBeyondLastLine: false,
              wordWrap: "off",
              automaticLayout: true,
              lineNumbers: "on",
              renderLineHighlight: "all",
              glyphMargin: true,
              folding: true,
              renderWhitespace: "selection",
              bracketPairColorization: { enabled: true },
              guides: { indentation: true, bracketPairs: true },
              smoothScrolling: true,
              tabSize: indentation?.tabSize ?? effectiveIndentation.tabSize,
              insertSpaces: indentation?.insertSpaces ?? effectiveIndentation.insertSpaces,
              formatOnPaste: true,
              formatOnType: true,
              autoClosingBrackets: "always",
              autoClosingQuotes: "always",
              suggestOnTriggerCharacters: true,
            }}
            onMount={handleEditorDidMount}
          />
        ) : activeTab.type === "doc" ? (
          /* Rendered Documentation Section matching Docs Master Document */
          <div className="h-full w-full overflow-y-auto p-8 text-[#cccccc] bg-[#0c0d0e]">
            <div className="max-w-4xl mx-auto w-full bg-[#0c0d0e] border border-[#1e1f22] rounded-2xl p-8 shadow-xl space-y-6">
              <div className="border-b border-[#1e1f22] pb-4 flex items-center justify-between">
                <div>
                  <h1 className="text-xl font-bold text-white flex items-center gap-2">
                    <span className="text-purple-400 bg-purple-950/40 px-2.5 py-1 rounded-lg text-sm font-mono border border-purple-800/60">
                      {activeTab.docSection?.section_number === 0 ? "MASTER" : (activeTab.docSection?.section_number || 1)}
                    </span>
                    <span>{activeTab.docSection?.title || activeTab.title}</span>
                  </h1>
                  <p className="text-xs text-gray-400 mt-1 font-mono">
                    {activeTab.docSection?.filename || "documentation.md"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs px-2.5 py-1 rounded-lg font-mono font-medium uppercase border ${
                      activeTab.docSection?.status === "fully_generated"
                        ? "bg-emerald-950/80 text-emerald-300 border-emerald-800"
                        : "bg-yellow-950/80 text-yellow-300 border-yellow-800"
                    }`}
                  >
                    {activeTab.docSection?.status || "GENERATED"}
                  </span>
                </div>
              </div>

              {/* Render Visual Diagram if explicitly separated or embedded */}
              {activeTab.docSection?.has_diagram && !String(activeTab.docSection?.content || "").includes("```mermaid") && (
                <MermaidDiagram
                  chart={activeTab.docSection.content}
                  title={`Figure ${activeTab.docSection.section_number || 1}.1 — ${activeTab.docSection.title || activeTab.title} Blueprint`}
                />
              )}

              {/* Rich Markdown & Diagram Renderer */}
              <div className="selection:bg-purple-900/60">
                <MarkdownRenderer
                  content={activeTab.docSection?.content || activeTab.content || ""}
                />
              </div>
            </div>
          </div>
        ) : activeTab.type === "diff" ? (
          /* Diff Viewer for Automated Fixes */
          <div className="h-full w-full flex flex-col overflow-hidden bg-[#0c0d0e]">
            {/* Floating Action Bar */}
            <div className="px-4 py-2.5 bg-[#0c0d0e] border-b border-[#1e1f22] flex items-center justify-between z-10 shrink-0">
              <div className="flex items-center gap-2">
                <GitCompare size={16} className="text-[#f87171]" />
                <span className="text-xs font-semibold text-white">{activeTab.title}</span>
                <span className="text-[11px] text-[#858585] font-mono">
                  ({activeTab.filePath || "patch.diff"})
                </span>
              </div>
              <div className="flex items-center gap-2">
                {onRejectFix && (
                  <button
                    onClick={() => onRejectFix(activeTab.errorId)}
                    className="px-3 py-1 bg-[#141518] hover:bg-[#1a1b1e] text-white rounded text-xs font-medium transition-colors border border-[#1e1f22]"
                  >
                    Reject
                  </button>
                )}
                {onApplyFix && activeTab.fixResult && (
                  <button
                    onClick={() => onApplyFix(activeTab.fixResult!, activeTab.errorId)}
                    disabled={isApplyingFix}
                    className="px-3 py-1 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded text-xs font-medium flex items-center gap-1.5 transition-colors"
                  >
                    <Check size={14} />
                    {isApplyingFix ? "Applying & Testing…" : "Apply Fix to Repo"}
                  </button>
                )}
                {onOpenPR && (
                  <button
                    onClick={onOpenPR}
                    className="px-3 py-1 bg-purple-700 hover:bg-purple-600 text-white rounded text-xs font-medium flex items-center gap-1.5 transition-colors"
                  >
                    <ExternalLink size={14} /> Open PR
                  </button>
                )}
              </div>
            </div>

            {/* Diff content view */}
            <div className="flex-1 overflow-y-auto p-4 font-mono text-xs">
              <DiffViewer diff={activeTab.diff || activeTab.fixResult?.diff || ""} />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default EditorArea;
