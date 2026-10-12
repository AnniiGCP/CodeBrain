import { useState, type FC } from "react";
import {
  Search,
  ExternalLink,
  ChevronDown,
  Clock,
  ArrowUp,
  Maximize2,
  Minus,
  X,
  RotateCcw,
} from "lucide-react";

export const HeroWorkspaceShowcase: FC = () => {
  const [activeTab, setActiveTab] = useState<string>("faster-launch");

  return (
    <div className="relative w-full max-w-6xl mx-auto mt-12 rounded-2xl border border-[#303136] bg-[#161718] shadow-[0_24px_80px_rgba(0,0,0,0.65)] overflow-hidden transition-all duration-300">
      {/* Subtle top glare/specular highlight */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#52525b]/40 to-transparent pointer-events-none" />

      {/* Main Showcase Layout: Sidebar + Canvas */}
      <div className="grid grid-cols-1 md:grid-cols-12 min-h-[580px] text-xs">
        {/* Left Navigation Rail (col 1-3) */}
        <div className="hidden md:flex md:col-span-3 lg:col-span-3 flex-col justify-between border-r border-[#303136] bg-[#161718] p-3 text-[#a1a1aa]">
          <div className="space-y-4">
            {/* Top Workspace Picker */}
            <div className="flex items-center justify-between px-2 py-1.5 rounded-lg hover:bg-[#202124] transition-colors cursor-pointer text-[#f3f4f6]">
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded bg-purple-600/30 border border-purple-500/50 flex items-center justify-center text-[10px]">
                  🧠
                </div>
                <span className="font-semibold text-xs">CodeBrain</span>
                <ChevronDown size={12} className="text-[#71717a]" />
              </div>
              <div className="flex items-center gap-2 text-[#71717a]">
                <Search size={13} />
                <ExternalLink size={13} />
              </div>
            </div>

            {/* Main navigation list */}
            <div className="space-y-0.5">
              {[
                { name: "Pulse", icon: "⚡" },
                { name: "Inbox", icon: "📥", count: "3" },
                { name: "My issues", icon: "🎯" },
                { name: "Reviews", icon: "⚖️", count: "1" },
              ].map((item) => (
                <div
                  key={item.name}
                  className="flex items-center justify-between px-2.5 py-1.5 rounded-lg hover:bg-[#202124] transition-colors cursor-pointer hover:text-[#f3f4f6]"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[12px]">{item.icon}</span>
                    <span>{item.name}</span>
                  </div>
                  {item.count && (
                    <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-[#26272b] text-[#71717a]">
                      {item.count}
                    </span>
                  )}
                </div>
              ))}
            </div>

            {/* Workspace Initiatives */}
            <div className="pt-2">
              <span className="px-2.5 text-[10px] font-semibold tracking-wider uppercase text-[#71717a]">
                Workspace
              </span>
              <div className="mt-1 space-y-0.5">
                {["Initiatives", "Projects", "More"].map((item) => (
                  <div
                    key={item}
                    className="px-2.5 py-1.5 rounded-lg hover:bg-[#202124] transition-colors cursor-pointer hover:text-[#f3f4f6]"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>

            {/* Favorites Section */}
            <div className="pt-2">
              <span className="px-2.5 text-[10px] font-semibold tracking-wider uppercase text-[#71717a]">
                Favorites
              </span>
              <div className="mt-1 space-y-0.5">
                {[
                  { id: "faster-launch", name: "Faster app launch", icon: "⭐", active: true },
                  { id: "agent-tasks", name: "Agent tasks", icon: "🤖" },
                  { id: "insights", name: "Agent Insights", icon: "📊" },
                  { id: "refresh", name: "UI Refresh", icon: "🎨" },
                ].map((fav) => (
                  <div
                    key={fav.id}
                    onClick={() => setActiveTab(fav.id)}
                    className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors cursor-pointer ${
                      activeTab === fav.id
                        ? "bg-[#202124] text-[#f3f4f6] font-medium"
                        : "hover:bg-[#202124] hover:text-[#f3f4f6]"
                    }`}
                  >
                    <span className="text-[11px] text-amber-400">{fav.icon}</span>
                    <span className="truncate">{fav.name}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* User footer pill */}
          <div className="pt-3 border-t border-[#303136] flex items-center justify-between px-1 text-[11px]">
            <span className="text-[#71717a]">dev/kinetic-mobile</span>
            <span className="text-emerald-400 font-mono text-[10px]">● synced</span>
          </div>
        </div>

        {/* Center Canvas Area (col 4-12) */}
        <div className="col-span-1 md:col-span-9 lg:col-span-9 flex flex-col justify-between bg-[#1b1b1d] relative overflow-hidden">
          {/* Top Canvas Bar */}
          <div className="h-10 px-6 border-b border-[#303136] flex items-center justify-between bg-[#161718]/60 text-[11px] text-[#a1a1aa]">
            <div className="flex items-center gap-2">
              <span className="text-amber-400">⭐</span>
              <span className="font-mono text-[#71717a]">DRV-8852</span>
              <span className="text-[#f3f4f6] font-medium">Faster app launch</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[#71717a] font-mono">1 / 84 ↑ ↓</span>
              <button className="text-[11px] text-[#a1a1aa] hover:text-white flex items-center gap-1">
                <RotateCcw size={11} />
                <span>Revert</span>
              </button>
            </div>
          </div>

          {/* Main Issue / Investigation Content */}
          <div className="p-6 sm:p-8 space-y-6 max-w-2xl">
            <div>
              <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-[#f3f4f6]">
                Faster app launch
              </h2>
              <p className="mt-2 text-xs text-[#a1a1aa] leading-relaxed">
                Render UI before <code className="text-[#f3f4f6] px-1.5 py-0.5 rounded bg-[#202124] font-mono">vehicle_state</code> sync: when minimum required state is present, instead of blocking on full refresh during iOS startup.
              </p>
            </div>

            {/* Timeline / Activity Section */}
            <div className="space-y-3 pt-2">
              <span className="text-xs font-semibold text-[#f3f4f6] block">Activity</span>

              <div className="space-y-3 text-[11px]">
                {/* Event 1 */}
                <div className="flex items-start gap-2.5 text-[#a1a1aa]">
                  <div className="w-5 h-5 rounded-full bg-purple-950/80 border border-purple-800 text-purple-300 flex items-center justify-center shrink-0 text-[10px]">
                    🤖
                  </div>
                  <div className="space-y-0.5">
                    <p>
                      <strong className="text-[#f3f4f6]">CodeBrain</strong> created the issue via AST Indexing <span className="text-[#71717a]">• 2min ago</span>
                    </p>
                    <p className="text-[10px] text-[#71717a]">
                      Triage Intelligence added labels <span className="text-purple-300">Performance</span> and <span className="text-blue-300">iOS</span>
                    </p>
                  </div>
                </div>

                {/* Event 2 */}
                <div className="flex items-start gap-2.5 text-[#a1a1aa]">
                  <div className="w-5 h-5 rounded-full bg-[#26272b] text-[#f3f4f6] flex items-center justify-center shrink-0 font-semibold text-[10px]">
                    K
                  </div>
                  <div>
                    <span className="text-[#f3f4f6] font-medium">karri</span> <span className="text-[#71717a]">• 4 min ago</span>
                    <p className="text-[#a1a1aa] mt-0.5 leading-relaxed">
                      Right now we show a spinner forever, which makes it look like the car disappeared...
                    </p>
                  </div>
                </div>

                {/* Event 3 */}
                <div className="flex items-start gap-2.5 text-[#a1a1aa]">
                  <div className="w-5 h-5 rounded-full bg-indigo-900 text-indigo-200 flex items-center justify-center shrink-0 font-semibold text-[10px]">
                    J
                  </div>
                  <div>
                    <span className="text-[#f3f4f6] font-medium">jori</span> <span className="text-[#71717a]">• just now</span>
                    <p className="text-purple-300 mt-0.5">
                      @codebrain can you take a stab at this?
                    </p>
                  </div>
                </div>

                {/* Event 4 */}
                <div className="flex items-center gap-2.5 text-[#71717a] pl-1">
                  <div className="w-3 h-3 rounded-full bg-emerald-500/20 border border-emerald-500/60 flex items-center justify-center">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  </div>
                  <span>Changed 2 files • Draft PR awaiting your review • 2 min ago</span>
                </div>
              </div>
            </div>
          </div>

          {/* Floating Linear-Style Agent Assistant Drawer (Pinned Bottom-Right) */}
          <div className="mx-4 mb-4 md:absolute md:bottom-4 md:right-6 md:w-[380px] bg-[#161718] border border-[#303136] rounded-2xl shadow-2xl p-4 space-y-3 z-20 backdrop-blur-md">
            {/* Window bar */}
            <div className="flex items-center justify-between border-b border-[#303136] pb-2 text-[11px]">
              <div className="flex items-center gap-2 text-[#f3f4f6] font-medium">
                <div className="w-2 h-2 rounded-full bg-purple-500 animate-pulse" />
                <span>CodeBrain Opus 5</span>
              </div>
              <div className="flex items-center gap-2 text-[#71717a]">
                <Minus size={11} className="hover:text-white cursor-pointer" />
                <Maximize2 size={11} className="hover:text-white cursor-pointer" />
                <X size={11} className="hover:text-white cursor-pointer" />
              </div>
            </div>

            {/* Prompt Bubble */}
            <div className="p-2.5 rounded-xl bg-[#202124] border border-[#303136] text-[11px] text-[#f3f4f6]">
              <p>Fix the dimmed ride rows that never reset and open a PR</p>
              <span className="text-[10px] text-[#71717a] block mt-1 font-mono">
                DRV-364 added to context
              </span>
            </div>

            {/* AI Agent Processing & Answer */}
            <div className="space-y-2 text-[11px]">
              <div className="flex items-center gap-1.5 text-purple-400 font-mono text-[10px]">
                <Clock size={10} />
                <span>Worked for 10 sec ▸</span>
              </div>

              <p className="text-[#a1a1aa] leading-relaxed">
                Pushed and opened a draft PR. Removed <code className="text-[#f3f4f6] font-mono">dimmedIds</code> — <code className="text-[#f3f4f6] font-mono">isItemDimmed</code> now checks <code className="text-[#f3f4f6] font-mono">waitingStatusById</code> directly.
              </p>

              {/* Code Changes Pill */}
              <div className="p-2 rounded-xl bg-[#1b1b1d] border border-[#303136] flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-[#f3f4f6]">Changed 2 files</span>
                    <span className="text-emerald-400 font-mono text-[10px]">+22</span>
                    <span className="text-red-400 font-mono text-[10px]">-10</span>
                  </div>
                  <span className="text-[10px] text-[#71717a] font-mono block mt-0.5">
                    master ← ride/drv-364-reset-dimmed-rows
                  </span>
                </div>
                <button className="px-2 py-1 rounded bg-[#26272b] hover:bg-[#303136] text-[#f3f4f6] text-[10px] font-medium border border-[#303136] transition-colors">
                  Preview
                </button>
              </div>
            </div>

            {/* Simulated Reply Bar */}
            <div className="pt-1">
              <div className="h-8 px-2.5 rounded-xl bg-[#1b1b1d] border border-[#303136] flex items-center justify-between text-[11px] text-[#71717a]">
                <span>Reply...</span>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#202124] text-[#a1a1aa]">
                    Skills ⌵
                  </span>
                  <div className="w-5 h-5 rounded-full bg-purple-600/40 text-white flex items-center justify-center">
                    <ArrowUp size={11} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
