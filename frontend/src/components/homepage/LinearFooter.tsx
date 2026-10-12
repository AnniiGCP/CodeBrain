import type { FC } from "react";
import { Link } from "react-router-dom";
import type { User } from "../../types";

interface LinearFooterProps {
  user: User | null;
  onOpenLogin: () => void;
}

export const LinearFooter: FC<LinearFooterProps> = ({ user, onOpenLogin }) => {
  return (
    <footer className="w-full border-t border-[#303136]/60 bg-[#161718] py-14 px-6 sm:px-8 text-xs text-[#71717a]">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
        {/* Brand & info */}
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 rounded bg-purple-600/30 border border-purple-500/50 flex items-center justify-center text-[10px]">
            🧠
          </div>
          <span className="font-semibold text-xs text-[#f3f4f6]">CodeBrain</span>
          <span className="text-[#52525b]">•</span>
          <span>The AI workspace for understanding and shipping code.</span>
        </div>

        {/* Links */}
        <div className="flex items-center gap-6 text-[12px] text-[#a1a1aa]">
          {user ? (
            <Link to="/dashboard" className="hover:text-white transition-colors">
              Workspace
            </Link>
          ) : (
            <button onClick={onOpenLogin} className="hover:text-white transition-colors cursor-pointer">
              Log in
            </button>
          )}
          <Link to="/docs" className="hover:text-white transition-colors">
            Documentation
          </Link>
          <Link to="/cicd" className="hover:text-white transition-colors">
            CI/CD Pipeline
          </Link>
          <Link to="/history" className="hover:text-white transition-colors">
            History
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto mt-8 pt-6 border-t border-[#303136]/30 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px] text-[#52525b]">
        <p>&copy; {new Date().getFullYear()} CodeBrain. All rights reserved.</p>
        <p>Built for modern developer teams with automated GitOps &amp; AST intelligence.</p>
      </div>
    </footer>
  );
};
