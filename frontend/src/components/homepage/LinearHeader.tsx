import { useState, type FC } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Menu, X } from "lucide-react";
import type { User } from "../../types";

interface LinearHeaderProps {
  user: User | null;
  onOpenLogin: () => void;
}

export const LinearHeader: FC<LinearHeaderProps> = ({ user, onOpenLogin }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const scrollToSection = (id: string) => {
    setMobileMenuOpen(false);
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <header className="sticky top-0 z-50 w-full bg-[#161718]/90 backdrop-blur-md border-b border-[#303136]/70 transition-colors">
      <div className="max-w-7xl mx-auto px-6 sm:px-8 h-14 flex items-center justify-between">
        {/* Left: Brand Logo & Navigation */}
        <div className="flex items-center gap-8">
          <Link
            to="/"
            className="flex items-center gap-2.5 text-[#f3f4f6] hover:opacity-90 transition-opacity"
            aria-label="CodeBrain Homepage"
          >
            {/* Official CodeBrain Logo Mark */}
            <img src="/logo-mark.png" alt="CodeBrain" className="w-6 h-6 rounded-md object-contain shadow-sm ring-1 ring-white/10" />
            <span className="font-semibold text-sm tracking-tight text-[#f3f4f6]">
              CodeBrain
            </span>
          </Link>

          {/* Desktop Navigation Links */}
          <nav className="hidden md:flex items-center gap-6 text-[13px] text-[#a1a1aa]">
            <button
              onClick={() => scrollToSection("hero")}
              className="hover:text-[#f3f4f6] transition-colors cursor-pointer"
            >
              Product
            </button>
            <button
              onClick={() => scrollToSection("features")}
              className="hover:text-[#f3f4f6] transition-colors cursor-pointer"
            >
              Features
            </button>
            <Link
              to={user ? "/docs" : "#features"}
              onClick={(e) => {
                if (!user) {
                  e.preventDefault();
                  scrollToSection("features");
                }
              }}
              className="hover:text-[#f3f4f6] transition-colors cursor-pointer"
            >
              Documentation
            </Link>
            <button
              onClick={() => scrollToSection("cicd")}
              className="hover:text-[#f3f4f6] transition-colors cursor-pointer"
            >
              CI/CD
            </button>
          </nav>
        </div>

        {/* Right: Actions */}
        <div className="hidden md:flex items-center gap-4">
          {user ? (
            <div className="flex items-center gap-3">
              <span className="text-xs text-[#71717a] font-mono">
                @{user.github_username}
              </span>
              <Link
                to="/dashboard"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#202124] hover:bg-[#26272b] border border-[#303136] text-xs font-medium text-[#f3f4f6] transition-colors"
              >
                <span>Open Workspace</span>
                <ArrowRight size={13} className="text-[#a1a1aa]" />
              </Link>
            </div>
          ) : (
            <div className="flex items-center gap-4 text-[13px]">
              <button
                onClick={onOpenLogin}
                className="text-[#a1a1aa] hover:text-[#f3f4f6] transition-colors cursor-pointer"
              >
                Log in
              </button>
              <button
                onClick={onOpenLogin}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-[#202124] hover:bg-[#26272b] border border-[#303136] text-xs font-medium text-[#f3f4f6] shadow-sm transition-all cursor-pointer hover:border-[#52525b]"
              >
                <span>Get started</span>
                <ArrowRight size={12} className="text-[#a1a1aa]" />
              </button>
            </div>
          )}
        </div>

        {/* Mobile Menu Trigger */}
        <div className="flex md:hidden">
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-1.5 text-[#a1a1aa] hover:text-[#f3f4f6] rounded-md transition-colors"
            aria-label="Toggle Navigation"
          >
            {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden border-b border-[#303136] bg-[#161718] px-6 py-4 space-y-3 animate-fade-in text-xs">
          <button
            onClick={() => scrollToSection("hero")}
            className="block w-full text-left py-1.5 text-[#a1a1aa] hover:text-white"
          >
            Product
          </button>
          <button
            onClick={() => scrollToSection("features")}
            className="block w-full text-left py-1.5 text-[#a1a1aa] hover:text-white"
          >
            Features
          </button>
          <button
            onClick={() => scrollToSection("cicd")}
            className="block w-full text-left py-1.5 text-[#a1a1aa] hover:text-white"
          >
            CI/CD Pipeline
          </button>
          <div className="pt-3 border-t border-[#303136] flex flex-col gap-2">
            {user ? (
              <Link
                to="/dashboard"
                className="w-full text-center py-2 bg-[#202124] border border-[#303136] rounded-lg text-white font-medium"
              >
                Open Workspace
              </Link>
            ) : (
              <>
                <button
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onOpenLogin();
                  }}
                  className="w-full text-center py-2 text-[#a1a1aa] hover:text-white"
                >
                  Log in
                </button>
                <button
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onOpenLogin();
                  }}
                  className="w-full text-center py-2 bg-[#202124] border border-[#303136] rounded-lg text-white font-medium"
                >
                  Get started
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
};
