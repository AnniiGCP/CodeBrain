import { useState, type FC } from "react";
import {
  Folder,
  FolderOpen,
  FileText,
  AlertTriangle,
  Terminal,
  Code2,
  GitBranch,
  BookOpen,
  Settings,
  ChevronDown,
  ChevronRight,
  Send,
  Mic,
  Sliders,
  FileCode2,
  Search,
  Sparkles,
  Maximize2,
  X,
} from "lucide-react";

export const AuthenticWorkspaceShowcase: FC = () => {
  const [activeTab, setActiveTab] = useState<"problems" | "output" | "terminal">("terminal");

  return (
    <div className="w-full max-w-7xl mx-auto rounded-2xl border border-[#2a2b2e] bg-[#161718] shadow-[0_25px_80px_rgba(0,0,0,0.85)] overflow-hidden font-sans select-none transition-all duration-300">
      {/* ── Top Application Navigation Bar ──────── */}
      <div className="h-10 bg-[#161718] border-b border-[#2a2b2e] px-3 flex items-center justify-between text-xs text-[#a1a1aa]">
        {/* Left: CodeBrain Wordmark + Top Nav Tabs */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 font-bold tracking-wider text-xs text-white">
            <span className="text-base">🧠</span>
            <span className="font-mono text-purple-400">CODEBRAIN</span>
          </div>

          <div className="flex items-center gap-1">
            <div className="px-2.5 py-1 bg-[#202124] text-[#f3f4f6] font-medium rounded border border-[#2a2b2e] flex items-center gap-1.5 shadow-sm text-[11px]">
              <Code2 size={12} className="text-purple-400" />
              <span>Workspace</span>
            </div>
            <div className="px-2 py-1 text-[#71717a] hover:text-[#a1a1aa] transition-colors cursor-default text-[11px]">
              Docs
            </div>
            <div className="px-2 py-1 text-[#71717a] hover:text-[#a1a1aa] transition-colors cursor-default text-[11px]">
              CI/CD
            </div>
            <div className="px-2 py-1 text-[#71717a] hover:text-[#a1a1aa] transition-colors cursor-default text-[11px]">
              History
            </div>
          </div>
        </div>

        {/* Right: Quick shortcuts & user badge */}
        <div className="flex items-center gap-2.5 text-[11px]">
          <Terminal size={12} className="text-[#71717a]" />
          <Settings size={12} className="text-[#71717a]" />
          <div className="flex items-center gap-1.5 bg-[#202124] border border-[#2a2b2e] px-2 py-0.5 rounded-full text-[#a1a1aa]">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>Developer</span>
          </div>
        </div>
      </div>

      {/* ── Workspace Main Flex: Activity Rail + Explorer + Editor + AI Panel (Zero Gap) ── */}
      <div className="flex min-h-[580px] bg-[#161718] border-b border-[#2a2b2e]">
        {/* 1. Far Left Activity Bar */}
        <div className="hidden sm:flex w-11 shrink-0 bg-[#131416] border-r border-[#2a2b2e] flex-col items-center py-3 justify-between">
          <div className="flex flex-col items-center gap-5 text-[#71717a]">
            {/* Active Explorer Item */}
            <div className="relative text-purple-400">
              <div className="absolute -left-3 top-0 bottom-0 w-0.5 bg-purple-500 rounded-r" />
              <FileText size={17} />
            </div>
            <GitBranch size={16} className="hover:text-[#a1a1aa]" />
            <AlertTriangle size={16} className="text-amber-500/80 hover:text-amber-400" />
            <BookOpen size={16} className="hover:text-[#a1a1aa]" />
            <Code2 size={16} className="hover:text-[#a1a1aa]" />
            <Search size={16} className="hover:text-[#a1a1aa]" />
            <Terminal size={16} className="hover:text-[#a1a1aa]" />
          </div>
          <div className="text-[#71717a]">
            <Settings size={16} className="hover:text-[#a1a1aa]" />
          </div>
        </div>

        {/* 2. Primary Sidebar — Explorer */}
        <div className="hidden md:flex flex-col w-56 shrink-0 bg-[#18191b] border-r border-[#2a2b2e] p-2.5 text-xs text-[#a1a1aa] overflow-hidden">
          <div className="flex items-center justify-between pb-2 text-[10px] uppercase font-mono tracking-wider text-[#71717a] font-semibold border-b border-[#2a2b2e]/60">
            <span>Explorer</span>
            <ChevronDown size={12} />
          </div>

          {/* Repo Card (CodeBrain as requested) */}
          <div className="my-2 p-2 rounded-lg bg-[#202124] border border-[#2a2b2e] space-y-1">
            <div className="text-[10px] uppercase font-mono text-[#71717a]">Repository</div>
            <div className="flex items-center justify-between text-xs font-medium text-[#f3f4f6]">
              <span className="flex items-center gap-1.5 truncate">
                <span>🧠</span> CodeBrain
              </span>
              <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-950/70 border border-emerald-800 text-emerald-400 font-mono font-bold">
                DONE
              </span>
            </div>
          </div>

          {/* File Tree (Matching Reference Image 2) */}
          <div className="space-y-1 font-mono text-[11px] pt-1 overflow-y-auto">
            <div className="text-[10px] text-[#71717a] uppercase font-sans font-semibold">Files (11)</div>
            
            <div className="space-y-0.5 text-[#a1a1aa]">
              <div className="flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-[#202124]">
                <FileCode2 size={11} className="text-zinc-500" />
                <span>.hintrc</span>
              </div>
              <div className="flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-[#202124]">
                <FileCode2 size={11} className="text-blue-400" />
                <span>app.py</span>
              </div>
              {/* Selected index.html */}
              <div className="flex items-center gap-1.5 py-0.5 px-1 rounded bg-[#202124] text-[#f3f4f6] font-medium border border-[#2a2b2e]/80">
                <FileCode2 size={11} className="text-purple-400" />
                <span>index.html</span>
              </div>

              {/* Folder: db */}
              <div className="pt-1">
                <div className="flex items-center gap-1 text-[#f3f4f6] py-0.5 px-1">
                  <ChevronDown size={11} className="text-[#71717a]" />
                  <FolderOpen size={11} className="text-purple-400" />
                  <span>db</span>
                </div>
                <div className="pl-4 space-y-0.5 text-[10px] text-[#a1a1aa]">
                  <div className="flex items-center gap-1 text-[#71717a]">
                    <ChevronRight size={10} />
                    <Folder size={10} />
                    <span>migrations</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileText size={10} className="text-zinc-400" />
                    <span>README.md</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileCode2 size={10} className="text-blue-400" />
                    <span>__init__.py</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileCode2 size={10} className="text-zinc-400" />
                    <span>alembic.ini</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileCode2 size={10} className="text-blue-400" />
                    <span>config.py</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileCode2 size={10} className="text-blue-400" />
                    <span>database.py</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <FileCode2 size={10} className="text-blue-400" />
                    <span>models.py</span>
                  </div>
                </div>
              </div>

              {/* Other folders */}
              <div className="flex items-center gap-1 text-[#71717a] py-0.5 px-1">
                <ChevronRight size={10} />
                <Folder size={10} />
                <span>docs</span>
              </div>
              <div className="flex items-center gap-1 text-[#71717a] py-0.5 px-1">
                <ChevronRight size={10} />
                <Folder size={10} />
                <span>frontend</span>
              </div>
            </div>
          </div>
        </div>

        {/* 3. Central Editor & Full-Width Terminal Area */}
        <div className="flex-1 min-w-0 bg-[#161718] flex flex-col justify-between border-r border-[#2a2b2e]">
          {/* Top Editor Tab Bar */}
          <div className="h-8 bg-[#18191b] border-b border-[#2a2b2e] flex items-center justify-between px-2">
            <div className="flex items-center">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-[#161718] text-[#f3f4f6] text-xs font-mono border-r border-[#2a2b2e] border-t-2 border-t-purple-500">
                <FileCode2 size={12} className="text-purple-400" />
                <span>index.html</span>
                <X size={11} className="text-[#71717a] hover:text-white cursor-pointer ml-1" />
              </div>
            </div>
            <div className="text-[10px] text-[#71717a] font-mono pr-2">
              chatbot &gt; index.html
            </div>
          </div>

          {/* Code Editor Body (Matching Reference Image 2) */}
          <div className="flex-1 p-3 overflow-y-auto font-mono text-xs leading-relaxed bg-[#161718] text-[#f3f4f6]">
            <div className="space-y-0.5">
              {[
                { line: 1, code: "<!DOCTYPE html>", cls: "text-[#71717a]" },
                { line: 2, code: "<html>", cls: "text-purple-300" },
                { line: 3, code: "<head>", cls: "text-purple-300" },
                { line: 4, code: '  <meta charset="UTF-8">', cls: "text-[#a1a1aa]" },
                { line: 5, code: '  <meta name="viewport" content="width=device-width, initial-scale=1.0">', cls: "text-[#a1a1aa]" },
                { line: 6, code: "  <title>Friend Chatbot</title>", cls: "text-[#f3f4f6]" },
                { line: 7, code: "  <style>", cls: "text-purple-300" },
                { line: 8, code: "    /* Global Styles */", cls: "text-[#52525b] italic" },
                { line: 9, code: "    body {", cls: "text-amber-300" },
                { line: 10, code: "      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;", cls: "text-[#a1a1aa]" },
                { line: 11, code: "      background: #f0ffef; /* Light green background */", cls: "text-[#a1a1aa]" },
                { line: 12, code: "      display: flex;", cls: "text-[#a1a1aa]" },
                { line: 13, code: "      justify-content: center;", cls: "text-[#a1a1aa]" },
                { line: 14, code: "      align-items: center;", cls: "text-[#a1a1aa]" },
                { line: 15, code: "      min-height: 100vh; /* Ensure it takes full viewport height */", cls: "text-[#a1a1aa]" },
                { line: 16, code: "      margin: 0;", cls: "text-[#a1a1aa]" },
                { line: 17, code: "    }", cls: "text-amber-300" },
                { line: 18, code: "", cls: "" },
                { line: 19, code: "    /* Chat Container */", cls: "text-[#52525b] italic" },
                { line: 20, code: "    #chat {", cls: "text-amber-300" },
                { line: 21, code: "      width: 400px;", cls: "text-[#a1a1aa]" },
                { line: 22, code: "      height: 550px; /* Fixed height for the whole chat box */", cls: "text-[#a1a1aa]" },
                { line: 23, code: "      background: white;", cls: "text-[#a1a1aa]" },
                { line: 24, code: "      padding: 20px;", cls: "text-[#a1a1aa]" },
                { line: 25, code: "      border-radius: 12px;", cls: "text-[#a1a1aa]" },
                { line: 26, code: "      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);", cls: "text-[#a1a1aa]" },
              ].map((row) => (
                <div key={row.line} className="flex items-start hover:bg-[#202124]/40 px-1 rounded">
                  <span className="w-7 shrink-0 text-right pr-3 text-[#52525b] select-none text-[11px]">
                    {row.line}
                  </span>
                  <span className={`flex-1 ${row.cls}`}>{row.code}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Bottom Panel — Terminal Active, Full Width Black Area (No Secondary Sidebar) */}
          <div className="border-t border-[#2a2b2e] bg-[#101112] text-xs">
            {/* Panel Tabs Header */}
            <div className="h-8 border-b border-[#2a2b2e] px-3 flex items-center justify-between bg-[#18191b]">
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => setActiveTab("problems")}
                  className={`flex items-center gap-1.5 text-[11px] font-medium transition-colors ${
                    activeTab === "problems" ? "text-purple-400 border-b-2 border-purple-500 py-1" : "text-[#71717a]"
                  }`}
                >
                  <span>Problems</span>
                  <span className="px-1.5 py-0.2 rounded-full bg-purple-950 text-purple-300 font-mono text-[9px] border border-purple-800">
                    4
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("output")}
                  className={`text-[11px] transition-colors ${
                    activeTab === "output" ? "text-purple-400 border-b-2 border-purple-500 py-1" : "text-[#71717a]"
                  }`}
                >
                  Output
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("terminal")}
                  className={`text-[11px] font-medium transition-colors ${
                    activeTab === "terminal" ? "text-[#f3f4f6] border-b-2 border-purple-500 py-1" : "text-[#71717a]"
                  }`}
                >
                  Terminal
                </button>
              </div>

              {/* Window controls */}
              <div className="flex items-center gap-2 text-[#71717a]">
                <Maximize2 size={11} className="hover:text-white cursor-pointer" />
                <X size={11} className="hover:text-white cursor-pointer" />
              </div>
            </div>

            {/* Terminal Body: Full Width, Deep Charcoal/Black, No Extra Sidebar */}
            <div className="p-3.5 h-28 bg-[#0c0d0e] font-mono text-[11px] text-[#f3f4f6] flex flex-col justify-start">
              <div className="flex items-center gap-1.5 text-purple-300">
                <span className="text-emerald-400 font-bold">PS CodeBrain&gt;</span>
                <span className="text-[#a1a1aa]">codebrain ci --verify --workspace</span>
              </div>
              <div className="text-[#71717a] pt-1">
                [OK] AST index loaded (11 modules indexed, 0 syntax violations)
              </div>
              <div className="flex items-center gap-1.5 pt-1 text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>Ready for commands</span>
                <span className="animate-pulse inline-block w-2 h-3.5 bg-purple-400 ml-1" />
              </div>
            </div>
          </div>
        </div>

        {/* 4. Right CodeBrain AI Conversation Panel */}
        <div className="hidden lg:flex flex-col w-80 shrink-0 bg-[#18191b] text-xs">
          {/* AI Header */}
          <div className="h-8 border-b border-[#2a2b2e] px-3 flex items-center justify-between text-[#71717a]">
            <div className="flex items-center gap-1.5 text-xs text-[#f3f4f6] font-medium">
              <Sparkles size={12} className="text-purple-400" />
              <span>CodeBrain AI</span>
            </div>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-[#a1a1aa]">Ready</span>
              <Sliders size={12} />
            </div>
          </div>

          {/* Chat Messages */}
          <div className="flex-1 p-3 space-y-3 overflow-y-auto">
            {/* AI Welcome message */}
            <div className="flex justify-start">
              <div className="bg-[#202124] text-[#a1a1aa] p-3 rounded-xl rounded-tl-sm text-[11px] max-w-[95%] border border-[#2a2b2e] space-y-1.5">
                <p className="text-[#f3f4f6] leading-relaxed">
                  Hi, I'm CodeBrain AI. How can I help you with <strong className="text-purple-300">CodeBrain</strong>? Ask me anything, attach an image, or speak using the microphone.
                </p>
              </div>
            </div>
          </div>

          {/* Changed Files summary bar */}
          <div className="px-3 py-1.5 bg-[#161718] border-t border-[#2a2b2e] flex items-center justify-between text-[10px] text-[#71717a]">
            <span>0 Files With Changes</span>
            <span className="hover:text-[#f3f4f6] cursor-pointer">Review Changes</span>
          </div>

          {/* Chat Input & Model Selector */}
          <div className="p-2.5 border-t border-[#2a2b2e] bg-[#161718] space-y-2">
            <div className="bg-[#202124] border border-[#2a2b2e] rounded-xl p-2 focus-within:border-purple-500/80 transition-colors">
              <input
                type="text"
                readOnly
                placeholder="Ask anything, @ to mention, / for actions"
                className="w-full bg-transparent text-[11px] text-[#f3f4f6] placeholder-[#71717a] outline-none"
              />
            </div>

            <div className="flex items-center justify-between pt-0.5">
              {/* Default Model: GPT-6 Luna */}
              <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[#202124] border border-[#2a2b2e] text-[10px] font-mono text-purple-300">
                <span>+</span>
                <span>GPT-6 Luna</span>
                <ChevronDown size={10} className="text-[#71717a]" />
              </div>

              <div className="flex items-center gap-1 text-[#71717a]">
                <button type="button" className="p-1 hover:text-white transition-colors" title="Voice Input">
                  <Mic size={13} />
                </button>
                <button type="button" className="p-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg transition-colors shadow-sm" title="Send">
                  <Send size={11} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Status Bar Strip at the very bottom ── */}
      <div className="h-6 bg-[#131416] px-3 flex items-center justify-between text-[10px] font-mono text-[#71717a]">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-[#a1a1aa]">
            <GitBranch size={10} /> main
          </span>
          <span className="text-purple-400">CodeBrain</span>
          <span className="text-emerald-400 font-semibold">● Pipeline: DONE</span>
          <span>0 errors</span>
          <span className="text-amber-400">4 warnings</span>
        </div>
        <div className="flex items-center gap-3">
          <span>Ln 1, Col 1</span>
          <span>Spaces: 2</span>
          <span>UTF-8</span>
          <span>HTML</span>
          <span className="text-purple-300 font-bold">APINex: 0.0k / 315.0k</span>
          <span className="text-emerald-400 font-semibold">● CodeBrain AI: Ready</span>
        </div>
      </div>
    </div>
  );
};
