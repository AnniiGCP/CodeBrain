import { useState, useEffect, useCallback } from "react";
import type { RepoSummary, DocSectionItem, DocValidationSummary, CommitDocsResponse } from "../types";
import {
  generateMasterDocs,
  fetchDocSections,
  getFormatDownloadUrl,
  commitDocsToRepo,
} from "../api";
import MermaidDiagram from "./MermaidDiagram";

interface DocPanelProps {
  repo: RepoSummary;
}

const SECTION_TITLES: { [key: number]: string } = {
  1: "Project Overview",
  2: "Technology Stack",
  3: "Repository Structure",
  4: "System Architecture",
  5: "Modules and Components",
  6: "Classes and Functions",
  7: "APIs and Interfaces",
  8: "Database and Data Model",
  9: "Database Relationships",
  10: "Dependencies",
  11: "Configuration and Environment",
  12: "Testing",
  13: "Security",
  14: "CI/CD Pipeline",
  15: "Deployment Architecture",
  16: "Setup and Developer Guide",
};

export default function DocPanel({ repo }: DocPanelProps) {
  // Suite state
  const [sections, setSections] = useState<DocSectionItem[]>([]);
  const [selectedSectionIdx, setSelectedSectionIdx] = useState<number | "master">("master");
  const [masterContent, setMasterContent] = useState<string>("");
  const [validationSummary, setValidationSummary] = useState<DocValidationSummary | null>(null);
  const [generatingSuite, setGeneratingSuite] = useState(false);
  const [committingDocs, setCommittingDocs] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitDocsResponse | null>(null);
  const [suiteError, setSuiteError] = useState<string | null>(null);

  // Copy state
  const [copied, setCopied] = useState(false);

  // Load existing sections on mount
  const loadExistingSections = useCallback(async () => {
    try {
      const data = await fetchDocSections(repo.repo_id);
      if (data.has_docs) {
        setMasterContent(data.master_content);
        setSections(data.sections);
        if (data.validation_summary) {
          setValidationSummary(data.validation_summary);
        }
      }
    } catch (err) {
      console.error("Failed to load sections", err);
    }
  }, [repo.repo_id]);

  useEffect(() => {
    loadExistingSections();
  }, [loadExistingSections]);

  const handleGenerateFullSuite = async () => {
    setGeneratingSuite(true);
    setSuiteError(null);
    setCommitResult(null);
    try {
      const res = await generateMasterDocs(repo.repo_id);
      setMasterContent(res.master_readme);
      setSections(res.sections);
      if (res.validation_summary) {
        setValidationSummary(res.validation_summary);
      }
      setSelectedSectionIdx("master");
    } catch (err: unknown) {
      setSuiteError(err instanceof Error ? err.message : "Failed to generate master documentation suite");
    } finally {
      setGeneratingSuite(false);
    }
  };

  const handleCommitToRepo = async () => {
    setCommittingDocs(true);
    setSuiteError(null);
    try {
      const res = await commitDocsToRepo(repo.repo_id);
      setCommitResult(res);
    } catch (err: unknown) {
      setSuiteError(err instanceof Error ? err.message : "Failed to commit documentation to repository");
    } finally {
      setCommittingDocs(false);
    }
  };

  const currentSection =
    selectedSectionIdx === "master"
      ? null
      : sections[selectedSectionIdx as number] || null;

  const activeContent =
    selectedSectionIdx === "master"
      ? masterContent
      : currentSection?.content || "";

  const activeTitle =
    selectedSectionIdx === "master"
      ? "Full Comprehensive 16-Section Project Documentation"
      : currentSection?.title || "Section Documentation";

  const handleCopy = () => {
    if (!activeContent) return;
    navigator.clipboard.writeText(activeContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const parseContentBlocks = (text: string): { type: "text" | "mermaid"; content: string }[] => {
    const blocks: { type: "text" | "mermaid"; content: string }[] = [];
    const regex = /```mermaid\s*([\s\S]*?)\s*```/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        const textChunk = text.substring(lastIndex, match.index).trim();
        if (textChunk) blocks.push({ type: "text", content: textChunk });
      }
      blocks.push({ type: "mermaid", content: match[1].trim() });
      lastIndex = regex.lastIndex;
    }

    if (lastIndex < text.length) {
      const textChunk = text.substring(lastIndex).trim();
      if (textChunk) blocks.push({ type: "text", content: textChunk });
    }

    return blocks;
  };

  const contentBlocks = parseContentBlocks(activeContent);

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-950 text-white overflow-hidden">
      {/* Header */}
      <div className="px-6 py-3 border-b border-gray-800 bg-gray-900 flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-base font-semibold flex items-center gap-2">
            <span>📚</span> AI Technical Documentation Suite
          </h2>
          <div className="flex items-center gap-3 mt-0.5">
            <p className="text-xs text-gray-400">
              Repository: <span className="text-blue-400 font-mono">{repo.name}</span>
            </p>
            {validationSummary && (
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-gray-500">•</span>
                <span className="text-emerald-400 font-medium flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                  {validationSummary.fully_generated} Active Sections
                </span>
                {validationSummary.fallback > 0 && (
                  <span className="text-amber-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                    {validationSummary.fallback} Fallback
                  </span>
                )}
                {validationSummary.failed > 0 && (
                  <span className="text-red-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-400"></span>
                    {validationSummary.failed} Failed
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Multi-Format Export Buttons Header */}
        <div className="flex items-center gap-2">
          {masterContent && (
            <div className="flex items-center bg-gray-800/80 p-1 rounded-xl gap-1 border border-gray-700">
              <a
                href={getFormatDownloadUrl(repo.repo_id, "pdf")}
                download
                className="px-2.5 py-1 bg-red-600/90 hover:bg-red-500 text-white text-[11px] font-medium rounded-lg transition-all flex items-center gap-1 shadow-sm"
                title="Download formatted PDF Document"
              >
                <span>📕</span> PDF
              </a>
              <a
                href={getFormatDownloadUrl(repo.repo_id, "md")}
                download
                className="px-2.5 py-1 bg-blue-600/90 hover:bg-blue-500 text-white text-[11px] font-medium rounded-lg transition-all flex items-center gap-1 shadow-sm"
                title="Download Markdown Document"
              >
                <span>📄</span> MD
              </a>
              <a
                href={getFormatDownloadUrl(repo.repo_id, "zip")}
                download
                className="px-2.5 py-1 bg-amber-600/90 hover:bg-amber-500 text-white text-[11px] font-medium rounded-lg transition-all flex items-center gap-1 shadow-sm"
                title="Download Zipped Docs Bundle (.md + .pdf)"
              >
                <span>📦</span> ZIP Bundle
              </a>
            </div>
          )}

          {/* Commit Docs to Repo Action */}
          {masterContent && (
            <button
              onClick={handleCommitToRepo}
              disabled={committingDocs || generatingSuite}
              className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 font-medium text-xs rounded-xl shadow-lg flex items-center gap-1.5 transition-all text-white"
              title="Push generated README and documentation suite to the repository (PR + auto-merge)"
            >
              {committingDocs ? (
                <>
                  <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  <span>Pushing Docs…</span>
                </>
              ) : (
                <>
                  <span>🚀</span>
                  <span>Commit Docs to Repo</span>
                </>
              )}
            </button>
          )}

          <button
            onClick={handleGenerateFullSuite}
            disabled={generatingSuite || committingDocs}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 font-medium text-xs rounded-xl shadow-lg flex items-center gap-2 transition-all"
          >
            {generatingSuite ? (
              <>
                <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Generating Suite…</span>
              </>
            ) : (
              <>
                <span>⚡</span>
                <span>{masterContent ? "Regenerate Documentation Suite" : "Generate Project Documentation"}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {commitResult && (
        <div className="mx-6 mt-3 px-4 py-2.5 bg-emerald-950/80 border border-emerald-700/80 rounded-xl text-emerald-200 text-xs flex items-center justify-between shadow-md animate-fade-in">
          <div className="flex items-center gap-2">
            <span className="text-base">🎉</span>
            <span>{commitResult.message}</span>
            {commitResult.pr_url && (
              <a
                href={commitResult.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-2 font-semibold underline text-emerald-300 hover:text-emerald-100 flex items-center gap-1"
              >
                View Pull Request #{commitResult.pr_number} ↗
              </a>
            )}
          </div>
          <button
            onClick={() => setCommitResult(null)}
            className="text-emerald-400 hover:text-emerald-200 p-0.5"
            title="Dismiss notification"
          >
            ✕
          </button>
        </div>
      )}

      {suiteError && (
        <div className="mx-6 mt-4 p-3 bg-red-950/80 border border-red-800 rounded-xl text-red-300 text-xs">
          ⚠️ {suiteError}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* 16-Section Sidebar Navigation */}
        <div className="w-72 border-r border-gray-800 bg-gray-900/60 overflow-y-auto p-3 shrink-0 space-y-1">
          <div className="px-3 py-2 text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center justify-between">
            <span>Documentation Index</span>
            <span className="text-[10px] text-gray-500 font-mono">16 Sections</span>
          </div>

          <button
            onClick={() => setSelectedSectionIdx("master")}
            className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-all flex items-center justify-between ${
              selectedSectionIdx === "master"
                ? "bg-blue-600/30 text-blue-300 border border-blue-500/40 shadow-sm"
                : "text-gray-300 hover:bg-gray-800/60"
            }`}
          >
            <span className="truncate flex items-center gap-1.5">
              <span>📋</span> Master Documentation
            </span>
            <span className="text-[10px] bg-blue-900/60 px-1.5 py-0.5 rounded text-blue-200 font-mono">Full</span>
          </button>

          <div className="h-px bg-gray-800 my-2" />

          {Array.from({ length: 16 }).map((_, i) => {
            const num = i + 1;
            const title = SECTION_TITLES[num];
            const secItemIdx = sections.findIndex(
              (s) => s.section_number === num || s.filename.startsWith(num < 10 ? `0${num}` : `${num}`)
            );
            const secItem = secItemIdx !== -1 ? sections[secItemIdx] : null;
            const isSelected = selectedSectionIdx === secItemIdx && secItemIdx !== -1;

            const status = secItem?.status ?? (secItem ? "fully_generated" : "pending");
            const hasDiag = secItem?.has_diagram ?? false;

            const statusDot: Record<string, string> = {
              fully_generated: "bg-emerald-400",
              COMPLETE: "bg-emerald-400",
              fallback: "bg-amber-400",
              failed: "bg-red-400",
              FAILED: "bg-red-400",
              pending: "bg-gray-600",
              PENDING: "bg-gray-600",
            };
            const dotClass = statusDot[status] ?? "bg-gray-600";

            return (
              <button
                key={num}
                onClick={() => {
                  if (secItemIdx !== -1) setSelectedSectionIdx(secItemIdx);
                }}
                disabled={secItemIdx === -1 && !masterContent}
                className={`w-full text-left px-3 py-2 rounded-xl text-xs transition-all flex items-center justify-between gap-2 ${
                  isSelected
                    ? "bg-blue-600 text-white font-medium shadow-md"
                    : secItemIdx !== -1
                    ? "text-gray-200 hover:bg-gray-800/80"
                    : "text-gray-600 cursor-not-allowed opacity-60"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <span className="w-5 h-5 rounded-md bg-gray-800 border border-gray-700/60 flex items-center justify-center text-[10px] font-mono shrink-0">
                    {num}
                  </span>
                  <span className="truncate">{title}</span>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {hasDiag && (
                    <span title="Contains Visual Diagram" className="text-[10px] opacity-75">
                      📊
                    </span>
                  )}
                  {secItem && (
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${dotClass}`}
                      title={
                        status === "fully_generated"
                          ? "Fully Generated with Live Data"
                          : status === "fallback"
                          ? "Generated with Fallback"
                          : "Generation Failed"
                      }
                    />
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Document Viewer & Visual Diagram Renderer */}
        <div className="flex-1 overflow-y-auto p-6 bg-gray-950 flex flex-col space-y-6">
          {activeContent ? (
            <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-2xl flex-1 flex flex-col">
              <div className="px-5 py-3 bg-gray-800/80 border-b border-gray-700/60 flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-semibold text-gray-200 truncate">{activeTitle}</span>
                  {currentSection?.status === "fallback" && (
                    <span className="text-[10px] bg-amber-900/60 text-amber-300 border border-amber-700/50 px-2 py-0.5 rounded font-mono">
                      Fallback Mode
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={handleCopy}
                    className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-xs text-gray-200 rounded-lg transition-colors"
                  >
                    {copied ? "✓ Copied!" : "📋 Copy Markdown"}
                  </button>
                </div>
              </div>

              {currentSection?.warnings && currentSection.warnings.length > 0 && (
                <div className="mx-6 mt-4 p-2.5 bg-amber-950/60 border border-amber-800/60 rounded-xl text-amber-300/90 text-xs">
                  <span className="font-semibold">Note:</span> {currentSection.warnings.join("; ")}
                </div>
              )}

              <div className="p-6 space-y-6 overflow-x-auto flex-1">
                {contentBlocks.map((block, idx) =>
                  block.type === "mermaid" ? (
                    <div key={idx} className="bg-gray-950 border border-blue-900/40 rounded-2xl p-4 shadow-xl">
                      <div className="flex items-center justify-between border-b border-gray-800 pb-2 mb-3">
                        <span className="text-xs font-semibold text-blue-400 flex items-center gap-1.5">
                          <span>📊</span> Architecture & Data Flow Diagram
                        </span>
                        <span className="text-[10px] bg-blue-950 text-blue-300 px-2 py-0.5 rounded border border-blue-800/50">
                          Visual Diagram
                        </span>
                      </div>
                      <MermaidDiagram chart={block.content} />
                    </div>
                  ) : (
                    <div
                      key={idx}
                      className="font-mono text-xs text-gray-200 whitespace-pre-wrap leading-relaxed selection:bg-blue-900 selection:text-white"
                    >
                      {block.content}
                    </div>
                  )
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 border border-dashed border-gray-800 rounded-2xl p-12 flex flex-col items-center justify-center text-center text-gray-500">
              <span className="text-5xl mb-4 block">📚</span>
              <p className="text-base font-semibold text-gray-300">16-Section Project Documentation & Visual Diagram Pipeline</p>
              <p className="text-xs text-gray-400 mt-1 max-w-md">
                Generates comprehensive documentation in <strong>PDF</strong>, <strong>HTML</strong>, <strong>Markdown</strong>, and <strong>JSON</strong> formats with visual architecture flowcharts.
              </p>
              <button
                onClick={handleGenerateFullSuite}
                disabled={generatingSuite}
                className="mt-6 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-medium transition-all shadow-lg"
              >
                ⚡ Click to Run 16-Section Documentation Engine
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
