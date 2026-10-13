import { Link, useLocation } from "react-router-dom";
import { User, Code, Book, GitMerge, History, Settings, Terminal, MessageSquare } from "lucide-react";
import type { User as UserType } from "../types";
import { useState } from "react";
import { SettingsModal } from "./SettingsModal";

interface NavigationProps {
  user: UserType | null;
  onLogout?: () => void;
  onToggleChat?: () => void;
  onToggleTerminal?: () => void;
  isChatOpen?: boolean;
  isTerminalOpen?: boolean;
}

export default function Navigation({
  user,
  onToggleChat,
  onToggleTerminal,
  isChatOpen,
  isTerminalOpen,
}: NavigationProps) {
  const location = useLocation();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <>
      <header className="h-11 w-full bg-[#0c0d0e] border-b border-[#1e1f22] flex items-center justify-between px-3.5 shrink-0 shadow-sm z-30 select-none font-sans">
        {/* Left: Brand + Navigation Links */}
        <div className="flex items-center gap-5">
          <Link
            to="/dashboard"
            className="flex items-center gap-2 text-white font-bold text-sm tracking-tight hover:text-purple-300 transition-colors"
          >
            <img src="/logo-mark.png" alt="CodeBrain" className="w-6 h-6 rounded-md object-contain shadow-md" />
            <span className="font-semibold text-xs tracking-wider uppercase text-gray-200">
              Code<span className="text-purple-400 font-bold">Brain</span>
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            <Link
              to="/dashboard"
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                location.pathname.startsWith("/dashboard")
                  ? "bg-[#0c0d0e] text-white font-semibold border border-purple-500/50"
                  : "text-gray-400 hover:text-gray-200 hover:bg-[#141518]"
              }`}
            >
              <Code size={12} className={location.pathname.startsWith("/dashboard") ? "text-purple-400" : ""} />
              <span>Workspace</span>
            </Link>
            <Link
              to="/docs"
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                location.pathname.startsWith("/docs")
                  ? "bg-[#0c0d0e] text-white font-semibold border border-purple-500/50"
                  : "text-gray-400 hover:text-gray-200 hover:bg-[#141518]"
              }`}
            >
              <Book size={12} className={location.pathname.startsWith("/docs") ? "text-purple-400" : ""} />
              <span>Docs</span>
            </Link>
            <Link
              to="/cicd"
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                location.pathname.startsWith("/cicd")
                  ? "bg-[#0c0d0e] text-white font-semibold border border-purple-500/50"
                  : "text-gray-400 hover:text-gray-200 hover:bg-[#141518]"
              }`}
            >
              <GitMerge size={12} className={location.pathname.startsWith("/cicd") ? "text-purple-400" : ""} />
              <span>CI/CD</span>
            </Link>
            <Link
              to="/history"
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                location.pathname.startsWith("/history")
                  ? "bg-[#0c0d0e] text-white font-semibold border border-purple-500/50"
                  : "text-gray-400 hover:text-gray-200 hover:bg-[#141518]"
              }`}
            >
              <History size={12} className={location.pathname.startsWith("/history") ? "text-purple-400" : ""} />
              <span>History</span>
            </Link>
          </nav>
        </div>

        {/* Right: Terminal Toggle, Chat Toggle, Settings, User Profile */}
        <div className="flex items-center gap-1.5">
          {onToggleTerminal && (
            <button
              type="button"
              onClick={onToggleTerminal}
              className={`flex items-center gap-1 text-xs transition-colors p-1.5 rounded-md hover:bg-[#141518] border border-transparent hover:border-[#1e1f22] ${
                isTerminalOpen ? "text-purple-400 bg-[#0c0d0e] border-[#1e1f22]" : "text-gray-400 hover:text-white"
              }`}
              title="Toggle Terminal Panel"
            >
              <Terminal size={14} />
            </button>
          )}

          {onToggleChat && (
            <button
              type="button"
              onClick={onToggleChat}
              className={`flex items-center gap-1 text-xs transition-colors p-1.5 rounded-md hover:bg-[#141518] border border-transparent hover:border-[#1e1f22] ${
                isChatOpen ? "text-purple-400 bg-[#0c0d0e] border-[#1e1f22]" : "text-gray-400 hover:text-white"
              }`}
              title="Toggle CodeBrain AI Chat"
            >
              <MessageSquare size={14} />
            </button>
          )}

          {user && (
            <div className="flex items-center gap-1.5 ml-1">
              <button
                type="button"
                onClick={() => setShowSettings(true)}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors p-1.5 rounded-md hover:bg-[#141518] border border-transparent hover:border-[#1e1f22]"
                title="AI Providers & Settings"
              >
                <Settings size={13} />
              </button>
              <div className="flex items-center gap-1.5 text-xs text-gray-300 bg-[#0c0d0e] px-2 py-0.5 rounded-md border border-[#1e1f22]">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                {user.github_avatar_url ? (
                  <img src={user.github_avatar_url} alt="" className="w-3.5 h-3.5 rounded-full" />
                ) : (
                  <User size={12} />
                )}
                <span className="text-[11px] font-mono text-gray-300">@{user.github_username || user.username || "Developer"}</span>
              </div>
            </div>
          )}
        </div>
      </header>

      {user && (
        <SettingsModal 
          isOpen={showSettings} 
          onClose={() => setShowSettings(false)} 
        />
      )}
    </>
  );
}
