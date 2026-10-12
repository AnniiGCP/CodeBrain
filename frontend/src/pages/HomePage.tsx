import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, X, Sparkles } from "lucide-react";
import type { User } from "../types";
import LoginScreen from "../components/LoginScreen";
import { FloatingHeader } from "../components/homepage/FloatingHeader";
import { AuthenticWorkspaceShowcase } from "../components/homepage/AuthenticWorkspaceShowcase";
import { ThreeFeatureColumns } from "../components/homepage/ThreeFeatureColumns";
import { BuildReviewShipSection } from "../components/homepage/BuildReviewShipSection";
import { LinearFooter } from "../components/homepage/LinearFooter";

interface HomePageProps {
  user: User | null;
  authLoading: boolean;
  onDevLoginSuccess: (u: User) => void;
}

export default function HomePage({ user, authLoading, onDevLoginSuccess }: HomePageProps) {
  const navigate = useNavigate();
  const [showLoginModal, setShowLoginModal] = useState<boolean>(false);

  // If already logged in and tried to open login modal, redirect to dashboard
  useEffect(() => {
    if (showLoginModal && user) {
      setShowLoginModal(false);
      navigate("/dashboard");
    }
  }, [showLoginModal, user, navigate]);

  const handlePrimaryCta = () => {
    if (user) {
      navigate("/dashboard");
    } else {
      setShowLoginModal(true);
    }
  };

  const scrollToFeatures = () => {
    const el = document.getElementById("features");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen w-full bg-[#161718] text-[#f3f4f6] font-sans selection:bg-purple-600 selection:text-white flex flex-col overflow-x-hidden relative">
      {/* 1. GoodsgGo-Inspired Floating Expandable/Collapsible Header (Homepage Only) */}
      <FloatingHeader
        user={user}
        onOpenLogin={() => setShowLoginModal(true)}
        onOpenWorkspace={() => navigate("/dashboard")}
      />

      {/* 2. SECTION 1: HERO AND AUTHENTIC CODEBRAIN WORKSPACE SHOWCASE */}
      <section id="hero" className="relative w-full pt-28 sm:pt-36 pb-28 px-6 sm:px-8 overflow-hidden">
        {/* Subtle ambient lighting behind hero */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[650px] h-[320px] bg-gradient-to-b from-purple-900/10 to-transparent rounded-full blur-3xl pointer-events-none" />

        <div className="max-w-7xl mx-auto space-y-16 relative z-10">
          {/* Headline + Copy Block */}
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-8 max-w-5xl">
            <div className="space-y-6">
              {/* Eyebrow badge */}
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#202124] border border-[#2a2b2e] text-purple-300 text-xs font-medium">
                <Sparkles size={12} className="text-purple-400" />
                <span>AI-powered codebase intelligence</span>
              </div>

              {/* Main Headline */}
              <h1 className="text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-[#f3f4f6] leading-[1.08] max-w-4xl">
                Understand your codebase. Ship with confidence.
              </h1>

              {/* Description */}
              <p className="text-base sm:text-lg text-[#a1a1aa] leading-relaxed max-w-2xl font-normal">
                Explore repositories, uncover code issues, generate documentation, and move toward reliable releases with CodeBrain.
              </p>

              {/* Action CTAs */}
              <div className="flex flex-wrap items-center gap-4 pt-2">
                <button
                  id="hero-get-started-btn"
                  type="button"
                  onClick={handlePrimaryCta}
                  disabled={authLoading}
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#f3f4f6] hover:bg-white text-[#161718] font-semibold text-xs sm:text-sm shadow-sm hover:shadow transition-all cursor-pointer disabled:opacity-50"
                >
                  <span>{user ? "Open Workspace" : "Get started"}</span>
                  <ArrowRight size={14} className="text-[#161718]" />
                </button>

                <button
                  id="hero-explore-features-btn"
                  type="button"
                  onClick={scrollToFeatures}
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#202124] hover:bg-[#26272a] border border-[#2a2b2e] text-[#a1a1aa] hover:text-[#f3f4f6] font-medium text-xs sm:text-sm transition-colors cursor-pointer"
                >
                  <span>Explore features</span>
                </button>
              </div>
            </div>
          </div>

          {/* Authentic CodeBrain Workspace Showcase (Reference C) */}
          <AuthenticWorkspaceShowcase />
        </div>
      </section>

      {/* 3. SECTION 2: THREE FEATURE COLUMNS (Codebase, Issues, Docs) */}
      <ThreeFeatureColumns />

      {/* 4. SECTION 3: BUILD, TEST, AND SHIP WITH CI/CD (Reference A Fading Visual) */}
      <BuildReviewShipSection />

      {/* 5. Minimal Site Footer */}
      <LinearFooter user={user} onOpenLogin={() => setShowLoginModal(true)} />

      {/* Login / Connect Modal Overlay */}
      {showLoginModal && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto animate-fade-in">
          <div className="relative w-full max-w-md my-8">
            {/* Modal Close Button */}
            <button
              id="modal-close-btn"
              onClick={() => setShowLoginModal(false)}
              className="absolute top-4 right-4 z-50 p-2 text-[#a1a1aa] hover:text-white bg-[#202124] hover:bg-[#26272a] border border-[#2a2b2e] rounded-full transition-colors cursor-pointer"
              aria-label="Close Login Modal"
            >
              <X size={16} />
            </button>

            {/* Embed authentic LoginScreen */}
            <LoginScreen
              onDevLoginSuccess={(u) => {
                setShowLoginModal(false);
                onDevLoginSuccess(u);
                navigate("/dashboard");
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
