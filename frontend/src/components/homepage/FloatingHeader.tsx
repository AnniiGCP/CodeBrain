import { useState, useEffect, useRef, type FC } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LayoutGrid } from "lucide-react";
import type { User } from "../../types";

interface FloatingHeaderProps {
  user: User | null;
  onOpenLogin: () => void;
  onOpenWorkspace: () => void;
}

export const FloatingHeader: FC<FloatingHeaderProps> = ({
  user,
  onOpenLogin,
  onOpenWorkspace,
}) => {
  const navigate = useNavigate();
  const [isAtTop, setIsAtTop] = useState(() => {
    if (typeof window !== "undefined") {
      return window.scrollY <= 50;
    }
    return true;
  });
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [isManuallyToggled, setIsManuallyToggled] = useState<boolean | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll listener: keep header extended at top of page; collapse as user scrolls down
  useEffect(() => {
    const handleScroll = () => {
      const atTop = window.scrollY <= 50;
      setIsAtTop((prev) => {
        if (prev !== atTop) {
          setIsManuallyToggled(null);
        }
        return atTop;
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Effective expanded state:
  // At the start of the page (scrollY <= 50), it stays extended.
  // As user scrolls down, it collapses into the compact pill.
  // When collapsed, hovering, focusing, or tapping expands it smoothly.
  const isExpanded =
    isManuallyToggled !== null
      ? isManuallyToggled || isHovered || isFocused
      : isAtTop || isHovered || isFocused;

  // Close on Click Outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsManuallyToggled(null);
        setIsHovered(false);
        setIsFocused(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Close on Escape Key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsManuallyToggled(null);
        setIsHovered(false);
        setIsFocused(false);
        (document.activeElement as HTMLElement)?.blur();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleNavClick = (anchorId: string) => {
    setIsManuallyToggled(null);
    setIsHovered(false);
    setIsFocused(false);
    (document.activeElement as HTMLElement)?.blur();
    const element = document.getElementById(anchorId);
    if (element) {
      element.scrollIntoView({ behavior: "smooth" });
    }
  };

  const toggleHeader = () => {
    setIsManuallyToggled((prev) => {
      const current = prev !== null ? prev : isAtTop;
      return !current;
    });
  };

  const handleLinkNavigate = (path: string) => {
    setIsManuallyToggled(null);
    setIsHovered(false);
    setIsFocused(false);
    (document.activeElement as HTMLElement)?.blur();
    navigate(path);
  };

  return (
    <div
      ref={containerRef}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        if (!isAtTop) {
          setIsManuallyToggled(null);
        }
        setIsFocused(false);
        (document.activeElement as HTMLElement)?.blur();
      }}
      onFocus={() => setIsFocused(true)}
      onBlur={(e) => {
        if (!containerRef.current?.contains(e.relatedTarget as Node)) {
          setIsFocused(false);
        }
      }}
      className="fixed top-5 left-1/2 -translate-x-1/2 z-50 pointer-events-auto"
    >
      <header
        aria-label="Main Navigation"
        className={`bg-[#1c1e22]/90 backdrop-blur-md border border-[#2d3036]/80 shadow-[0_10px_35px_rgba(0,0,0,0.5)] overflow-hidden transition-all ${
          isExpanded ? "duration-[750ms]" : "duration-[650ms]"
        } ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none motion-reduce:duration-0 ${
          isExpanded
            ? "w-[92vw] max-w-[720px] rounded-2xl md:rounded-[22px] px-5 py-2"
            : "w-[195px] rounded-[22px] px-3.5 py-2"
        }`}
      >
        <div className="flex items-center justify-between gap-3 h-9">
          {/* Brand Mark (Left, Always visible) */}
          <Link
            to="/"
            onClick={() => {
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            className="flex items-center gap-2 group shrink-0 pl-1"
            aria-label="CodeBrain Homepage"
          >
            <div className="w-6 h-6 rounded-md bg-gradient-to-tr from-purple-600 to-indigo-500 flex items-center justify-center text-xs shadow-sm group-hover:scale-105 transition-transform duration-300">
              🧠
            </div>
            <span className="font-semibold text-sm tracking-tight text-[#f3f4f6] group-hover:text-purple-300 transition-colors">
              CodeBrain
            </span>
          </Link>

          {/* Desktop Navigation Links (Middle: Single horizontal row, expands smoothly) */}
          <div
            className={`hidden md:flex flex-1 items-center justify-center overflow-hidden transition-all ${
              isExpanded ? "duration-[750ms]" : "duration-[650ms]"
            } ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none motion-reduce:duration-0 ${
              isExpanded
                ? "max-w-[520px] opacity-100 pointer-events-auto translate-x-0"
                : "max-w-0 opacity-0 pointer-events-none -translate-x-2"
            }`}
          >
            <nav
              aria-label="Primary Links"
              className="flex items-center justify-center gap-1.5 text-xs text-[#a1a1aa] whitespace-nowrap px-1 overflow-hidden"
            >
              <button
                type="button"
                onClick={() => {
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                className="bg-white/[0.12] text-white hover:bg-white/[0.18] px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer shadow-sm"
              >
                Product
              </button>
              <button
                type="button"
                onClick={() => handleNavClick("features")}
                className="hover:text-[#f3f4f6] hover:bg-white/[0.06] px-3 py-1.5 rounded-xl transition-colors cursor-pointer font-medium"
              >
                Features
              </button>
              <button
                type="button"
                onClick={() => handleLinkNavigate("/docs")}
                className="hover:text-[#f3f4f6] hover:bg-white/[0.06] px-3 py-1.5 rounded-xl transition-colors cursor-pointer font-medium"
              >
                Docs
              </button>
              <button
                type="button"
                onClick={() => handleLinkNavigate("/cicd")}
                className="hover:text-[#f3f4f6] hover:bg-white/[0.06] px-3 py-1.5 rounded-xl transition-colors cursor-pointer font-medium"
              >
                CI/CD
              </button>
              {user ? (
                <button
                  type="button"
                  onClick={() => {
                    setIsHovered(false);
                    setIsManuallyToggled(false);
                    onOpenWorkspace();
                  }}
                  className="hover:text-purple-300 hover:bg-purple-950/40 px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer text-purple-400"
                >
                  Workspace
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setIsHovered(false);
                    setIsManuallyToggled(false);
                    onOpenLogin();
                  }}
                  className="hover:text-purple-300 hover:bg-purple-950/40 px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer text-purple-400"
                >
                  Log in
                </button>
              )}
            </nav>
          </div>

          {/* Right: Grid Icon Trigger (3x3 grid dot icon ALWAYS, NO close X icon) */}
          <div className="flex items-center shrink-0 pr-1">
            <button
              id="header-grid-btn"
              type="button"
              onClick={toggleHeader}
              aria-expanded={isExpanded}
              aria-label={isExpanded ? "Collapse navigation" : "Expand navigation"}
              className="p-1.5 rounded-lg hover:bg-white/[0.08] text-[#a1a1aa] hover:text-[#f3f4f6] transition-colors cursor-pointer flex items-center justify-center shrink-0"
            >
              <LayoutGrid size={16} className="transition-transform duration-200 hover:scale-105" />
            </button>
          </div>
        </div>

        {/* Mobile Dropdown (Smooth sliding accordion for small screens without hover) */}
        <div
          className={`md:hidden overflow-hidden transition-all ${
            isExpanded ? "duration-[750ms]" : "duration-[650ms]"
          } ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none motion-reduce:duration-0 ${
            isExpanded ? "max-h-60 opacity-100 pt-3 mt-3 border-t border-[#2a2b2e]" : "max-h-0 opacity-0 pt-0 mt-0 border-t-0"
          }`}
        >
          <div className="flex flex-col gap-2 text-xs text-[#a1a1aa]">
            <button
              type="button"
              onClick={() => {
                window.scrollTo({ top: 0, behavior: "smooth" });
                setIsManuallyToggled(false);
              }}
              className="text-left py-1 hover:text-[#f3f4f6]"
            >
              Product
            </button>
            <button
              type="button"
              onClick={() => handleNavClick("features")}
              className="text-left py-1 hover:text-[#f3f4f6]"
            >
              Features
            </button>
            <button
              type="button"
              onClick={() => handleLinkNavigate("/docs")}
              className="text-left py-1 hover:text-[#f3f4f6]"
            >
              Docs
            </button>
            <button
              type="button"
              onClick={() => handleLinkNavigate("/cicd")}
              className="text-left py-1 hover:text-[#f3f4f6]"
            >
              CI/CD
            </button>
            {user ? (
              <button
                type="button"
                onClick={() => {
                  setIsManuallyToggled(false);
                  onOpenWorkspace();
                }}
                className="text-left py-1 text-purple-400 font-semibold"
              >
                Workspace →
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setIsManuallyToggled(false);
                  onOpenLogin();
                }}
                className="text-left py-1 text-purple-400 font-semibold"
              >
                Log in →
              </button>
            )}
          </div>
        </div>
      </header>
    </div>
  );
};
