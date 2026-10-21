import { useState, useEffect, useRef, useMemo, type FC } from "react";
import { useSearchParams } from "react-router-dom";
import {
  fetchRepos,
  fetchDocSections,
  fetchReadme,
  generateMasterDocs,
  generateReadme,
  getFormatDownloadUrl,
  commitDocsToRepo,
  fetchDocGenProgress,
  type DocGenProgressResponse,
} from "../api";
import type { RepoSummary, DocSectionItem, DocValidationSummary, User } from "../types";
import Navigation from "../components/Navigation";
import MermaidDiagram from "../components/MermaidDiagram";
import MarkdownRenderer from "../components/MarkdownRenderer";
import {
  BookOpen,
  RefreshCw,
  FileText,
  FileArchive,
  File,
  Layers,
  Network,
  Compass,
  Sparkles,
  CheckCircle2,
  Copy,
  Check,
  Send,
} from "lucide-react";

interface DocumentationPageProps {
  user: User;
  onLogout: () => void;
}

type DocTab = "suite" | "diagrams" | "relationships" | "readme" | "master";

export const DocumentationPage: FC<DocumentationPageProps> = ({ user, onLogout }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const initialTab = (searchParams.get("tab") as DocTab) || "suite";
  const [activeTab, setActiveTab] = useState<DocTab>(initialTab);

  const handleTabChange = (tab: DocTab) => {
    setActiveTab(tab);
    setReadmeError(null);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", tab);
        return next;
      },
      { replace: true }
    );
  };

  // Suite state
  const [docSections, setDocSections] = useState<DocSectionItem[]>([]);
  const [masterContent, setMasterContent] = useState<string>("");
  const [validationSummary, setValidationSummary] = useState<DocValidationSummary | null>(null);
  const [selectedSectionNumber, setSelectedSectionNumber] = useState<number>(1);
  const [isSuiteComplete, setIsSuiteComplete] = useState<boolean>(false);

  // Readme state
  const [readmeContent, setReadmeContent] = useState<string>("");
  const [loadingReadme, setLoadingReadme] = useState(false);
  const [generatingReadme, setGeneratingReadme] = useState(false);
  const [readmeError, setReadmeError] = useState<string | null>(null);
  const inFlightReadmeRef = useRef<string | null>(null);

  // Action states
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genProgress, setGenProgress] = useState<DocGenProgressResponse | null>(null);
  const [committing, setCommitting] = useState(false);
  const [commitMessage, setCommitMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // 1. Initial repos load
  useEffect(() => {
    fetchRepos().then((list) => {
      setRepos(list);
      if (list.length > 0) {
        const saved = localStorage.getItem("codebrain_active_repo_id");
        const found = saved && list.find((r) => r.repo_id === saved);
        if (found) {
          setSelectedRepoId(found.repo_id);
        } else {
          setSelectedRepoId(list[0].repo_id);
          try {
            localStorage.setItem("codebrain_active_repo_id", list[0].repo_id);
          } catch {}
        }
      }
    });
  }, []);

  // 2. Fetch sections & saved README on selected repo change
  useEffect(() => {
    if (selectedRepoId) {
      setLoading(true);
      setCommitMessage(null);
      setDocSections([]);
      setMasterContent("");
      setValidationSummary(null);
      setIsSuiteComplete(false);
      setReadmeError(null);

      // Fetch documentation sections
      fetchDocSections(selectedRepoId)
        .then((res) => {
          setDocSections(res.sections || []);
          setMasterContent(res.master_content || "");
          setIsSuiteComplete(Boolean(res.is_complete));
          if (res.validation_summary) setValidationSummary(res.validation_summary);
          if (res.readme_content && !readmeContent) {
            setReadmeContent(res.readme_content);
          }
        })
        .catch(() => {
          setDocSections([]);
          setMasterContent("");
          setIsSuiteComplete(false);
        })
        .finally(() => setLoading(false));

      // Fetch saved README from persistent storage without triggering AI generation
      setReadmeError(null);
      setLoadingReadme(true);
      fetchReadme(selectedRepoId)
        .then((res) => {
          if (res.has_readme && res.readme) {
            setReadmeContent(res.readme);
          } else {
            setReadmeContent("");
          }
        })
        .catch((err) => {
          console.warn("Failed to load saved README:", err);
          setReadmeError(null);
        })
        .finally(() => setLoadingReadme(false));
    }
  }, [selectedRepoId]);

  // 3. Tab switch to readme: check storage first
  useEffect(() => {
    if (activeTab === "readme" && selectedRepoId) {
      setReadmeError(null);
      if (!readmeContent && !loadingReadme && !generatingReadme) {
        setLoadingReadme(true);
        fetchReadme(selectedRepoId)
          .then((res) => {
            if (res.has_readme && res.readme) {
              setReadmeContent(res.readme);
            }
          })
          .catch((err) => {
            console.warn("Failed to check saved README:", err);
            setReadmeError(null);
          })
          .finally(() => setLoadingReadme(false));
      }
    }
  }, [activeTab, selectedRepoId]);

  useEffect(() => {
    if (docSections.length > 0) {
      if (!docSections.some((s) => s.section_number === selectedSectionNumber)) {
        setSelectedSectionNumber(docSections[0].section_number ?? 1);
      }
    }
  }, [docSections, selectedSectionNumber]);

  // 4. Handlers
  const handleGenerateFullSuite = async () => {
    if (!selectedRepoId) return;
    const isRegenerate = docSections.length > 0;
    setGenerating(true);
    setCommitMessage(null);
    setGenProgress({
      status: "generating",
      percentage: 0,
      current_section: isRegenerate ? "Cleaning cached documentation..." : "Initializing documentation engine...",
      section_number: 1,
      completed: 0,
      total: 16,
    });

    // Start real-time progress polling
    const pollInterval = window.setInterval(async () => {
      try {
        const prog = await fetchDocGenProgress(selectedRepoId);
        if (prog && prog.status === "generating") {
          setGenProgress(prog);
        }
      } catch (err) {
        // Keep polling even on transient network glitches
      }
    }, 600);

    try {
      const res = await generateMasterDocs(selectedRepoId, isRegenerate);
      setDocSections(res.sections || []);
      setMasterContent(res.master_readme || "");
      setIsSuiteComplete(Boolean(res.is_complete));
      if (res.validation_summary) setValidationSummary(res.validation_summary);
      setGenProgress({
        status: "complete",
        percentage: 100,
        current_section: "All 16 sections generated successfully",
        section_number: 16,
        completed: 16,
        total: 16,
      });
    } catch (e: any) {
      alert(`Master Documentation generation failed: ${e.message}`);
    } finally {
      clearInterval(pollInterval);
      setGenerating(false);
      setTimeout(() => setGenProgress(null), 3500);
    }
  };

  const handleGenerateReadme = async (force: boolean = false) => {
    if (!selectedRepoId) return;

    // Concurrency deduplication: prevent simultaneous in-flight requests for the same repo
    const requestKey = `${selectedRepoId}:${force}`;
    if (inFlightReadmeRef.current === requestKey || generatingReadme) return;
    inFlightReadmeRef.current = requestKey;

    setGeneratingReadme(true);
    setReadmeError(null);
    try {
      const res = await generateReadme(selectedRepoId, force);
      if (res.readme) {
        setReadmeContent(res.readme);
      }
    } catch (e: any) {
      const errMsg = e?.message || "README generation failed";
      if (!errMsg.toLowerCase().includes("method not allowed")) {
        setReadmeError(errMsg);
      } else {
        setReadmeError(null);
      }
      // Preserve existing readmeContent on failure!
    } finally {
      setGeneratingReadme(false);
      inFlightReadmeRef.current = null;
    }
  };

  const handleCommitDocs = async () => {
    if (!selectedRepoId) return;
    setCommitting(true);
    try {
      const res = await commitDocsToRepo(selectedRepoId);
      setCommitMessage(res.message || "Documentation committed successfully!");
    } catch (e: any) {
      alert(`Commit docs failed: ${e.message}`);
    } finally {
      setCommitting(false);
    }
  };

  const handleCopyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  interface ExtractedDiagramItem {
    sectionNumber: number;
    sectionTitle: string;
    diagramIndex: number;
    diagramCode: string;
  }

  // Helper to extract genuine Mermaid diagrams from sections that actually contain diagram code
  const extractedDiagrams: ExtractedDiagramItem[] = useMemo(() => {
    const list: ExtractedDiagramItem[] = [];
    const mermaidRegex = /```mermaid\s*([\s\S]*?)```/gi;

    for (const sec of docSections) {
      if (!sec.content) continue;
      let match;
      let idx = 1;
      while ((match = mermaidRegex.exec(sec.content)) !== null) {
        const code = match[1]?.trim();
        if (code) {
          list.push({
            sectionNumber: sec.section_number ?? 0,
            sectionTitle: sec.title || `Section ${sec.section_number}`,
            diagramIndex: idx++,
            diagramCode: code,
          });
        }
      }
    }
    return list;
  }, [docSections]);

  const currentSection = docSections.find((s) => s.section_number === selectedSectionNumber) || docSections[0] || null;

  const totalSecCount = docSections.length;
  const completedSecCount = validationSummary?.fully_generated ?? docSections.filter(s => s.is_complete).length;

  return (
    <div className="h-screen w-screen flex flex-col bg-[#161718] text-[#cccccc] font-sans overflow-hidden">
      <Navigation user={user} onLogout={onLogout} />

      {/* Top Controls Bar - Fixed stable height, no layout shifts */}
      <div className="h-14 px-6 bg-[#18191b] border-b border-[#2a2b2e] flex items-center justify-between gap-4 shrink-0 shadow-sm z-10">
        {/* Left: Suite Branding + Project Selector */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="p-1.5 bg-purple-600/20 text-purple-400 rounded-lg shrink-0">
            <BookOpen size={17} />
          </div>
          <div className="shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white tracking-tight">AI Documentation Suite</span>
              <span className="text-[10px] text-amber-400 bg-amber-950/80 border border-amber-800 px-2 py-0.5 rounded-full font-mono">
                {totalSecCount > 0 ? (isSuiteComplete ? `${totalSecCount}/${totalSecCount} COMPLETE` : `${completedSecCount}/${totalSecCount} Draft`) : "16 SECTIONS"}
              </span>
            </div>
            <p className="text-[10px] text-[#71717a] hidden sm:block">Technical documentation & architecture blueprints</p>
          </div>

          <div className="h-5 w-px bg-[#2a2b2e] hidden md:block" />

          {/* Repo selector */}
          <select
            value={selectedRepoId}
            onChange={(e) => {
              setSelectedRepoId(e.target.value);
              try {
                localStorage.setItem("codebrain_active_repo_id", e.target.value);
              } catch {}
            }}
            className="bg-[#202124] border border-[#2a2b2e] text-[#f3f4f6] px-3 py-1.5 rounded-xl text-xs outline-none focus:border-purple-500 font-mono shrink-0"
          >
            {repos.map((r) => (
              <option key={r.repo_id} value={r.repo_id}>
                {r.name} ({r.source_type})
              </option>
            ))}
          </select>
        </div>

        {/* Center: Sub-Navigation Tabs */}
        <div className="hidden xl:flex items-center bg-[#161718] p-1 rounded-xl border border-[#2a2b2e] shrink-0">
          <button
            onClick={() => handleTabChange("suite")}
            className={`px-3 py-1 text-xs rounded-lg font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "suite" ? "bg-[#26272a] text-white shadow-sm font-semibold" : "text-[#71717a] hover:text-white"
            }`}
          >
            <Layers size={13} />
            <span>16-Section Suite</span>
          </button>
          <button
            onClick={() => handleTabChange("diagrams")}
            className={`px-3 py-1 text-xs rounded-lg font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "diagrams" ? "bg-[#26272a] text-white shadow-sm font-semibold" : "text-[#71717a] hover:text-white"
            }`}
          >
            <Compass size={13} />
            <span>Architecture Flowcharts</span>
          </button>
          <button
            onClick={() => handleTabChange("relationships")}
            className={`px-3 py-1 text-xs rounded-lg font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "relationships" ? "bg-[#26272a] text-white shadow-sm font-semibold" : "text-[#71717a] hover:text-white"
            }`}
          >
            <Network size={13} />
            <span>Relationships</span>
          </button>
          <button
            onClick={() => handleTabChange("readme")}
            className={`px-3 py-1 text-xs rounded-lg font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "readme" ? "bg-[#26272a] text-white shadow-sm font-semibold" : "text-[#71717a] hover:text-white"
            }`}
          >
            <FileText size={13} />
            <span>README.md</span>
          </button>
          <button
            onClick={() => handleTabChange("master")}
            className={`px-3 py-1 text-xs rounded-lg font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              activeTab === "master" ? "bg-[#26272a] text-white shadow-sm font-semibold" : "text-[#71717a] hover:text-white"
            }`}
          >
            <Sparkles size={13} className="text-yellow-400" />
            <span>Master Document</span>
          </button>
        </div>

        {/* Right: Export Controls (PDF, MD, ZIP) & Regenerate */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex items-center gap-1.5 bg-[#161718] p-1 rounded-xl border border-[#2a2b2e]">
            <a
              href={selectedRepoId ? getFormatDownloadUrl(selectedRepoId, "pdf", !isSuiteComplete) : "#"}
              download
              className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors flex items-center gap-1 shadow-sm ${
                !selectedRepoId ? "opacity-40 pointer-events-none text-zinc-500" : isSuiteComplete ? "bg-red-600/80 hover:bg-red-500 text-white" : "bg-red-950/60 hover:bg-red-900 text-red-200 border border-red-800/40"
              }`}
              title={isSuiteComplete ? "Download formatted PDF" : "Download Draft PDF"}
            >
              <File size={12} />
              <span>PDF{isSuiteComplete ? "" : " (Draft)"}</span>
            </a>
            <a
              href={selectedRepoId ? getFormatDownloadUrl(selectedRepoId, "md", !isSuiteComplete) : "#"}
              download
              className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors flex items-center gap-1 shadow-sm ${
                !selectedRepoId ? "opacity-40 pointer-events-none text-zinc-500" : "bg-purple-600/80 hover:bg-purple-500 text-white"
              }`}
              title="Download Markdown"
            >
              <FileText size={12} />
              <span>MD</span>
            </a>
            <a
              href={selectedRepoId ? getFormatDownloadUrl(selectedRepoId, "zip", !isSuiteComplete) : "#"}
              download
              className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors flex items-center gap-1 shadow-sm ${
                !selectedRepoId ? "opacity-40 pointer-events-none text-zinc-500" : isSuiteComplete ? "bg-amber-600/80 hover:bg-amber-500 text-white" : "bg-amber-950/60 hover:bg-amber-900 text-amber-200 border border-amber-800/40"
              }`}
              title={isSuiteComplete ? "Download Zipped Bundle" : "Download Draft ZIP"}
            >
              <FileArchive size={12} />
              <span>ZIP{isSuiteComplete ? "" : " (Draft)"}</span>
            </a>
          </div>

          <button
            onClick={handleGenerateFullSuite}
            disabled={generating || !selectedRepoId}
            className="px-3.5 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold shadow-lg shadow-purple-900/30 flex items-center gap-1.5 transition-all cursor-pointer shrink-0"
          >
            {generating ? (
              <>
                <RefreshCw size={13} className="animate-spin text-purple-200" />
                <span>
                  {genProgress && genProgress.percentage > 0
                    ? `${genProgress.percentage}% (${genProgress.completed}/${genProgress.total || 16})`
                    : "Generating..."}
                </span>
              </>
            ) : (
              <>
                <Sparkles size={13} />
                <span>{docSections.length > 0 ? "Regenerate" : "Generate Suite"}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Real-time Generation Progress Bar Banner */}
      {generating && genProgress && (
        <div className="bg-[#121315] border-b border-purple-500/30 px-6 py-2.5 flex flex-col gap-1.5 shadow-md animate-fade-in z-20">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span className="flex h-2 w-2 relative shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-purple-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-purple-500"></span>
              </span>
              <span className="font-semibold text-white shrink-0">
                Generating Section {genProgress.section_number || 1} of {genProgress.total || 16}:
              </span>
              <span className="text-purple-300 font-medium truncate">
                {genProgress.current_section || "Analyzing repository architecture..."}
              </span>
            </div>
            <div className="flex items-center gap-2 font-mono text-xs shrink-0 pl-2">
              <span className="text-purple-400 font-bold">{genProgress.percentage}%</span>
              <span className="text-zinc-500">({genProgress.completed}/{genProgress.total || 16})</span>
            </div>
          </div>
          <div className="w-full bg-[#1e1f23] rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-gradient-to-r from-purple-600 via-indigo-500 to-purple-400 h-1.5 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${Math.max(4, Math.min(100, genProgress.percentage))}%` }}
            />
          </div>
        </div>
      )}

      {/* Commit Result Banner */}
      {commitMessage && (
        <div className="mx-6 mt-3 px-4 py-2 bg-emerald-950 border border-emerald-700 rounded-xl text-emerald-200 text-xs flex items-center justify-between shadow animate-fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-400" />
            <span>{commitMessage}</span>
          </div>
          <button onClick={() => setCommitMessage(null)} className="text-emerald-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Main Tab Content View */}
      <main className="flex-1 flex overflow-hidden">
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-3">
            <RefreshCw className="animate-spin text-blue-400" size={32} />
            <p className="text-sm">Loading documentation artifacts...</p>
          </div>
        ) : docSections.length === 0 && !masterContent && activeTab !== "readme" ? (
          /* Empty State - Prompt to Generate */
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center max-w-lg mx-auto">
            <div className="w-16 h-16 rounded-3xl bg-blue-600/10 border border-blue-500/30 flex items-center justify-center mb-4 text-blue-400 shadow-xl">
              <BookOpen size={32} />
            </div>
            <h2 className="text-lg font-bold text-white mb-2">No Documentation Generated Yet</h2>
            <p className="text-xs text-gray-400 mb-6 leading-relaxed">
              CodeBrain analyzes your AST symbols, API endpoints, ORM models, and call graphs to automatically produce a 16-section master technical suite with visual Mermaid blueprints.
            </p>
            <button
              onClick={handleGenerateFullSuite}
              disabled={generating || !selectedRepoId}
              className="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold shadow-xl shadow-blue-900/40 flex items-center gap-2 transition-all"
            >
              {generating ? <RefreshCw className="animate-spin" size={16} /> : <Sparkles size={16} />}
              <span>Generate 16-Section Documentation Suite</span>
            </button>
          </div>
        ) : activeTab === "suite" ? (
          /* Tab 1: 16-Section Interactive Suite */
          <div className="flex-1 flex overflow-hidden">
            {/* Sidebar with 16 sections */}
            <div className="w-80 bg-[#18191b] border-r border-[#2a2b2e] overflow-y-auto p-3 shrink-0 space-y-1">
              <div className="px-3 py-2 text-[11px] font-bold text-[#a1a1aa] uppercase tracking-wider flex items-center justify-between border-b border-[#2a2b2e] mb-2 font-mono">
                <span>Documentation Index</span>
                <span className="text-purple-400">{docSections.length} sections</span>
              </div>

              {docSections.map((secItem, idx) => {
                const num = secItem.section_number;
                const title = secItem.title;
                const isSelected = selectedSectionNumber === num;

                return (
                  <button
                    key={num ?? idx}
                    onClick={() => setSelectedSectionNumber(num ?? 1)}
                    className={`w-full text-left px-3 py-2.5 rounded-xl text-xs transition-all flex items-center justify-between gap-2 cursor-pointer ${
                      isSelected
                        ? "bg-purple-600 text-white font-semibold shadow-md"
                        : "text-[#a1a1aa] hover:bg-[#202124] hover:text-white"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className="w-5 h-5 rounded-md bg-[#161718] border border-[#2a2b2e] flex items-center justify-center text-[10px] font-mono shrink-0 text-[#71717a]">
                        {num}
                      </span>
                      <span className="truncate">{title}</span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {secItem?.status === "FAILED" ? (
                        <span title="Validation Failed" className="text-[9px] text-red-400 bg-red-950 px-1 py-0.5 rounded border border-red-800 font-mono">
                          ERR
                        </span>
                      ) : secItem?.status === "PENDING" ? (
                        <span title="Pending Generation" className="text-[9px] text-amber-400 bg-amber-950 px-1 py-0.5 rounded border border-amber-800 font-mono">
                          PEND
                        </span>
                      ) : (
                        <span title="Validated Section" className="text-[9px] text-emerald-400 bg-emerald-950/60 px-1 py-0.5 rounded font-mono">
                          ✓
                        </span>
                      )}

                      {secItem?.has_diagram && (
                        <span title="Contains Visual Diagram" className="text-[10px] text-purple-300 bg-purple-950 px-1.5 py-0.5 rounded border border-purple-800">
                          📊
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Section Reader Area */}
            <div className="flex-1 overflow-y-auto p-8 bg-[#161718] flex flex-col space-y-6">
              {currentSection ? (
                <div className="max-w-4xl mx-auto w-full bg-[#18191b] border border-[#2a2b2e] rounded-2xl p-8 shadow-xl space-y-6">
                  <div className="flex items-center justify-between border-b border-[#2a2b2e] pb-4">
                    <div>
                      <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <span className="text-purple-400 bg-purple-950/80 px-2.5 py-1 rounded-lg text-sm font-mono border border-purple-800">
                          {currentSection.section_number}
                        </span>
                        <span>{currentSection.title}</span>
                      </h2>
                      <p className="text-xs text-[#71717a] mt-1 font-mono">{currentSection.filename}</p>
                    </div>

                    <button
                      onClick={() => handleCopyText(currentSection.content)}
                      className="px-3 py-1.5 bg-[#202124] hover:bg-[#26272a] text-[#a1a1aa] hover:text-white rounded-lg text-xs flex items-center gap-1.5 transition-colors border border-[#2a2b2e] cursor-pointer"
                    >
                      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                      <span>{copied ? "Copied" : "Copy Markdown"}</span>
                    </button>
                  </div>

                  {/* Section Markdown Body */}
                  <div className="selection:bg-purple-900 text-[#f3f4f6]">
                    <MarkdownRenderer
                      content={currentSection.content}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : activeTab === "diagrams" ? (
          /* Tab 2: Visual Architecture Diagrams Gallery */
          <div className="flex-1 overflow-y-auto p-8 bg-[#1e1e1e] space-y-8 max-w-5xl mx-auto w-full">
            <div className="border-b border-[#3c3c3c] pb-4">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Compass size={20} className="text-blue-400" />
                <span>Architecture & Data Flow Diagrams</span>
              </h2>
              <p className="text-xs text-gray-400 mt-1">
                Visual blueprints auto-derived from AST symbols, network routes, and framework relationships.
              </p>
            </div>

            {extractedDiagrams.length === 0 ? (
              <div className="p-8 text-center text-gray-500 text-xs">No diagrams found. Generate the documentation suite first.</div>
            ) : (
              extractedDiagrams.map((diag, idx) => (
                <div key={idx} className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-xl space-y-4">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span className="text-blue-400 font-mono">#{diag.sectionNumber}</span>
                    <span>{diag.sectionTitle}</span>
                    {diag.diagramIndex > 1 && (
                      <span className="text-xs text-gray-400 font-mono">Part {diag.diagramIndex}</span>
                    )}
                  </h3>
                  <MermaidDiagram
                    chart={diag.diagramCode}
                    title={`Figure ${diag.sectionNumber}.${diag.diagramIndex} — ${diag.sectionTitle}`}
                    figureCaption={`Figure ${diag.sectionNumber}.${diag.diagramIndex}: Verified structural diagram for section ${diag.sectionNumber}`}
                  />
                </div>
              ))
            )}
          </div>
        ) : activeTab === "relationships" ? (
          /* Tab 3: Module & Dependency Relationships */
          <div className="flex-1 overflow-y-auto p-8 bg-[#1e1e1e] max-w-5xl mx-auto w-full space-y-6">
            <div className="border-b border-[#3c3c3c] pb-4">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Network size={20} className="text-purple-400" />
                <span>Module & Class Relationships</span>
              </h2>
              <p className="text-xs text-gray-400 mt-1">
                Cross-file call graphs, class inheritances, and ORM entity dependency mappings.
              </p>
            </div>

            <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-6 shadow-xl">
              {(() => {
                // Priority order: Section 9 (DB Rel), Section 8 (DB Schema), Section 5 (Module Rel), Section 4 (Architecture)
                const relCandidates = [9, 8, 5, 4];
                let targetDiag: ExtractedDiagramItem | undefined = undefined;
                for (const num of relCandidates) {
                  targetDiag = extractedDiagrams.find((d: ExtractedDiagramItem) => d.sectionNumber === num);
                  if (targetDiag) break;
                }
                if (!targetDiag && extractedDiagrams.length > 0) {
                  targetDiag = extractedDiagrams[0];
                }

                if (targetDiag) {
                  return (
                    <MermaidDiagram
                      chart={targetDiag.diagramCode}
                      title={`Figure ${targetDiag.sectionNumber}.${targetDiag.diagramIndex} — ${targetDiag.sectionTitle} Relationships`}
                      figureCaption={`Figure ${targetDiag.sectionNumber}.${targetDiag.diagramIndex}: Verified component and architectural relationships.`}
                    />
                  );
                }

                return (
                  <div className="p-12 text-center text-gray-400 text-xs">
                    No architectural or entity relationship diagrams detected in this repository.
                    Click <strong>Generate Suite</strong> to analyze and extract verified relationships.
                  </div>
                );
              })()}
            </div>
          </div>

        ) : activeTab === "readme" ? (
          /* Tab 4: Plain-Language README.md Generator */
          <div className="flex-1 overflow-y-auto p-8 bg-[#1e1e1e] max-w-4xl mx-auto w-full space-y-6">
            <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <FileText size={20} className="text-emerald-400" />
                  <span>Plain-Language README.md</span>
                </h2>
                <p className="text-xs text-gray-400 mt-1">
                  Written for someone unfamiliar with the project, explaining what it is, how it works, and how to run it.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleGenerateReadme(true)}
                  disabled={generatingReadme || !selectedRepoId}
                  className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow transition-all"
                  title="Re-synthesize README with fresh AI analysis"
                >
                  <RefreshCw size={13} className={generatingReadme ? "animate-spin" : ""} />
                  <span>{generatingReadme ? "Regenerating..." : readmeContent ? "Regenerate README" : "Generate README"}</span>
                </button>
                {readmeContent && (
                  <button
                    onClick={() => handleCopyText(readmeContent)}
                    className="px-3 py-1.5 bg-[#2d2d2d] hover:bg-[#3c3c3c] text-gray-300 rounded-xl text-xs flex items-center gap-1.5 transition-colors border border-[#3c3c3c]"
                  >
                    {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    <span>{copied ? "Copied" : "Copy"}</span>
                  </button>
                )}
              </div>
            </div>

            {/* Actionable Error Banner if generation failed (preserves previous content) */}
            {readmeError && !readmeError.toLowerCase().includes("method not allowed") && (
              <div className="px-4 py-3 bg-red-950/40 border border-red-800/50 rounded-xl text-xs text-red-300 flex items-center justify-between gap-3 animate-fade-in">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-red-400">Notice:</span>
                  <span>{readmeError}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleGenerateReadme(true)}
                    className="px-2.5 py-1 bg-red-900/60 hover:bg-red-800/80 text-white rounded-lg text-xs font-semibold shrink-0"
                  >
                    Retry
                  </button>
                  <button
                    onClick={() => setReadmeError(null)}
                    className="px-2 py-1 hover:bg-red-900/40 text-red-400 hover:text-red-300 rounded text-xs font-semibold"
                    aria-label="Dismiss notice"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {/* In-progress banner when regenerating while keeping previous content visible */}
            {generatingReadme && readmeContent && (
              <div className="px-4 py-2.5 bg-emerald-950/40 border border-emerald-800/40 rounded-xl text-xs text-emerald-300 flex items-center gap-2 animate-fade-in">
                <RefreshCw size={13} className="animate-spin text-emerald-400 shrink-0" />
                <span>Synthesizing fresh README.md with AI... Current saved version displayed below.</span>
              </div>
            )}

            {/* Body */}
            {loadingReadme && !readmeContent ? (
              <div className="py-16 flex flex-col items-center justify-center text-gray-400 gap-3">
                <RefreshCw className="animate-spin text-emerald-400" size={32} />
                <p className="text-sm">Loading saved README.md...</p>
              </div>
            ) : generatingReadme && !readmeContent ? (
              <div className="py-16 flex flex-col items-center justify-center text-gray-400 gap-3">
                <RefreshCw className="animate-spin text-emerald-400" size={32} />
                <p className="text-sm">Synthesizing plain-language README.md with AI...</p>
              </div>
            ) : readmeContent ? (
              <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-8 shadow-xl">
                <MarkdownRenderer content={readmeContent} />
              </div>
            ) : (
              <div className="p-12 text-center bg-[#252526] border border-[#3c3c3c] rounded-2xl">
                <FileText size={48} className="text-gray-600 mx-auto mb-3" />
                <p className="text-sm font-semibold text-white">No README.md generated yet</p>
                <p className="text-xs text-gray-400 mt-1 mb-4">Click below to synthesize a clean, official README for this project.</p>
                <button
                  onClick={() => handleGenerateReadme(false)}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition-all shadow"
                >
                  Generate Plain-Language README
                </button>
              </div>
            )}
          </div>
        ) : (
          /* Tab 5: Master Professional Document */
          <div className="flex-1 overflow-y-auto p-8 bg-[#1e1e1e] max-w-5xl mx-auto w-full space-y-6">
            <div className="flex items-center justify-between border-b border-[#3c3c3c] pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Sparkles size={20} className="text-yellow-400" />
                  <span>Master Professional Documentation Document</span>
                </h2>
                <p className="text-xs text-gray-400 mt-1">
                  Merged 16-section comprehensive technical document ready for submission, handoff, or PDF export.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleCommitDocs}
                  disabled={committing || !selectedRepoId || !masterContent}
                  className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow transition-all"
                >
                  <Send size={12} />
                  <span>{committing ? "Pushing..." : "Commit Docs to Repo"}</span>
                </button>
                {masterContent && (
                  <button
                    onClick={() => handleCopyText(masterContent)}
                    className="px-3 py-1.5 bg-[#2d2d2d] hover:bg-[#3c3c3c] text-gray-300 rounded-xl text-xs flex items-center gap-1.5 transition-colors border border-[#3c3c3c]"
                  >
                    {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    <span>{copied ? "Copied" : "Copy Document"}</span>
                  </button>
                )}
              </div>
            </div>

            {masterContent ? (
              <div className="space-y-4">
                {!isSuiteComplete && (
                  <div className="p-3 bg-amber-950/80 border border-amber-700 rounded-xl text-amber-200 text-xs flex items-center justify-between shadow">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-amber-300">⚠️ DRAFT SUITE:</span>
                      <span>This master document is an incomplete draft. All 16 canonical sections must be fully generated and pass validation before release.</span>
                    </div>
                  </div>
                )}
                <div className="bg-[#252526] border border-[#3c3c3c] rounded-2xl p-8 shadow-xl">
                  <MarkdownRenderer content={masterContent} />
                </div>
              </div>
            ) : (
              <div className="p-12 text-center bg-[#252526] border border-[#3c3c3c] rounded-2xl">
                <BookOpen size={48} className="text-gray-600 mx-auto mb-3" />
                <p className="text-sm font-semibold text-white">Master Document Not Yet Compiled</p>
                <p className="text-xs text-gray-400 mt-1 mb-4">Click generate to produce the full 16-section master document suite.</p>
                <button
                  onClick={handleGenerateFullSuite}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold transition-all shadow"
                >
                  Generate Master Suite
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
};

export default DocumentationPage;
