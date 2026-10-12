import { type FC } from "react";
import {
  Files,
  Search,
  GitBranch,
  AlertTriangle,
  BookOpen,
  GitMerge,
  History,
  LogOut,
  Command,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { User } from "../types";

export type SidebarTab = "explorer" | "search" | "git" | "issues" | "docs" | null;

interface ActivityBarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  errorCount: number;
  openPRCount?: number;
  user: User | null;
  onLogout: () => void;
  onOpenCommandPalette: () => void;
}

const ActivityBar: FC<ActivityBarProps> = ({
  activeTab,
  onTabChange,
  errorCount,
  openPRCount = 0,
  user,
  onLogout,
  onOpenCommandPalette,
}) => {
  const navigate = useNavigate();

  const handleItemClick = (tab: SidebarTab) => {
    if (activeTab === tab) {
      onTabChange(null);
    } else {
      onTabChange(tab);
    }
  };

  return (
    <aside
      className="w-12 h-full bg-[#0c0d0e] flex flex-col justify-between items-center py-2 select-none border-r border-[#1e1f22] z-20 shrink-0 font-sans"
      aria-label="Activity Bar"
    >
      {/* Top Section - Navigation Icons */}
      <div className="flex flex-col items-center gap-1 w-full">
        {/* Explorer */}
        <button
          onClick={() => handleItemClick("explorer")}
          title="Explorer (Ctrl+Shift+E)"
          className={`relative w-full h-11 flex items-center justify-center transition-colors ${
            activeTab === "explorer"
              ? "activity-bar-active text-white"
              : "text-[#858585] hover:text-white"
          }`}
        >
          <Files size={20} strokeWidth={1.75} />
        </button>

        {/* Search */}
        <button
          onClick={() => handleItemClick("search")}
          title="Search Codebase (Ctrl+Shift+F)"
          className={`relative w-full h-11 flex items-center justify-center transition-colors ${
            activeTab === "search"
              ? "activity-bar-active text-white"
              : "text-[#858585] hover:text-white"
          }`}
        >
          <Search size={20} strokeWidth={1.75} />
        </button>

        {/* Source Control */}
        <button
          onClick={() => handleItemClick("git")}
          title="Source Control & GitOps"
          className={`relative w-full h-11 flex items-center justify-center transition-colors ${
            activeTab === "git"
              ? "activity-bar-active text-white"
              : "text-[#858585] hover:text-white"
          }`}
        >
          <GitBranch size={20} strokeWidth={1.75} />
          {openPRCount > 0 && (
            <span className="absolute top-1.5 right-2 bg-purple-600 text-white text-[10px] font-bold px-1 rounded-full min-w-[14px] text-center leading-tight">
              {openPRCount}
            </span>
          )}
        </button>

        {/* Issues */}
        <button
          onClick={() => handleItemClick("issues")}
          title="Problems & AI Bug Fixes"
          className={`relative w-full h-11 flex items-center justify-center transition-colors ${
            activeTab === "issues"
              ? "activity-bar-active text-white"
              : "text-[#858585] hover:text-white"
          }`}
        >
          <AlertTriangle size={20} strokeWidth={1.75} />
          {errorCount > 0 && (
            <span className="absolute top-1.5 right-2 bg-[#f87171] text-black text-[10px] font-bold px-1 rounded-full min-w-[14px] text-center leading-tight">
              {errorCount}
            </span>
          )}
        </button>

        {/* Documentation Suite */}
        <button
          onClick={() => handleItemClick("docs")}
          title="Technical Documentation Suite"
          className={`relative w-full h-11 flex items-center justify-center transition-colors ${
            activeTab === "docs"
              ? "activity-bar-active text-white"
              : "text-[#858585] hover:text-white"
          }`}
        >
          <BookOpen size={20} strokeWidth={1.75} />
        </button>

        {/* Divider */}
        <div className="w-6 h-px bg-[#1e1f22] my-1" />

        {/* CI/CD Quick Link */}
        <button
          onClick={() => navigate("/cicd")}
          title="CI/CD Setup & Workflows"
          className="w-full h-11 flex items-center justify-center text-[#858585] hover:text-purple-400 transition-colors"
        >
          <GitMerge size={20} strokeWidth={1.75} />
        </button>

        {/* History Quick Link */}
        <button
          onClick={() => navigate("/history")}
          title="Project Ingestion History"
          className="w-full h-11 flex items-center justify-center text-[#858585] hover:text-purple-400 transition-colors"
        >
          <History size={20} strokeWidth={1.75} />
        </button>
      </div>

      {/* Bottom Section - User & Command Palette */}
      <div className="flex flex-col items-center gap-1 w-full">
        {/* Command Palette Trigger */}
        <button
          onClick={onOpenCommandPalette}
          title="Command Palette (Ctrl+Shift+P)"
          className="w-full h-10 flex items-center justify-center text-[#858585] hover:text-white transition-colors"
        >
          <Command size={18} strokeWidth={1.75} />
        </button>

        {/* User profile / Avatar */}
        {user && (
          <div
            title={`Logged in as ${user.github_username}`}
            className="w-full h-10 flex items-center justify-center relative group"
          >
            {user.github_avatar_url ? (
              <img
                src={user.github_avatar_url}
                alt={user.github_username}
                className="w-6 h-6 rounded-full border border-gray-600 object-cover"
              />
            ) : (
              <div className="w-6 h-6 rounded-full bg-purple-600 text-white flex items-center justify-center text-xs font-bold">
                {user.github_username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
        )}

        {/* Logout */}
        <button
          onClick={onLogout}
          title="Log Out"
          className="w-full h-10 flex items-center justify-center text-[#858585] hover:text-[#f48771] transition-colors"
        >
          <LogOut size={16} strokeWidth={1.75} />
        </button>
      </div>
    </aside>
  );
};

export default ActivityBar;
