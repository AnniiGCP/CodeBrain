import { useState } from "react";
import { API_BASE, devLogin, registerUser, passwordLogin } from "../api";
import type { User } from "../types";
import { CheckCircle2, Eye, EyeOff, Lock, Mail, User as UserIcon, ArrowRight, Shield } from "lucide-react";

interface LoginScreenProps {
  onDevLoginSuccess?: (user: User) => void;
}

export default function LoginScreen({ onDevLoginSuccess }: LoginScreenProps) {
  // Method / Tab state: "signin" | "signup"
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");

  // Form fields
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Status & error states
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Dev bypass state
  const [showDevModal, setShowDevModal] = useState(false);
  const [devUsername, setDevUsername] = useState("Developer");
  const [devLoading, setDevLoading] = useState(false);
  const [devError, setDevError] = useState<string | null>(null);

  const handleGitHubLogin = () => {
    window.location.href = `${API_BASE}/auth/github/login`;
  };

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    if (authMode === "signup") {
      if (!email.trim() || !username.trim() || !password) {
        setError("All fields are required.");
        return;
      }
      if (password.length < 8) {
        setError("Password must be at least 8 characters long.");
        return;
      }
      if (password !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }

      setLoading(true);
      try {
        const user = await registerUser(email.trim(), username.trim(), password);
        setSuccessMsg("Account created! Redirecting to workspace...");
        setTimeout(() => {
          if (onDevLoginSuccess) {
            onDevLoginSuccess(user);
          } else {
            window.location.href = "/dashboard";
          }
        }, 500);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Registration failed.");
      } finally {
        setLoading(false);
      }
    } else {
      // Sign in
      const identifier = email.trim();
      if (!identifier || !password) {
        setError("Email/username and password are required.");
        return;
      }

      setLoading(true);
      try {
        const user = await passwordLogin(identifier, password);
        if (onDevLoginSuccess) {
          onDevLoginSuccess(user);
        } else {
          window.location.href = "/dashboard";
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Invalid credentials.");
      } finally {
        setLoading(false);
      }
    }
  };

  const handleDevSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!devUsername.trim()) return;
    setDevLoading(true);
    setDevError(null);
    try {
      const user = await devLogin(devUsername.trim());
      if (onDevLoginSuccess) {
        onDevLoginSuccess(user);
      } else {
        window.location.href = "/dashboard";
      }
    } catch (err: unknown) {
      setDevError(err instanceof Error ? err.message : "Dev login failed");
    } finally {
      setDevLoading(false);
    }
  };

  return (
    <div className="w-full flex flex-col items-center justify-center p-4 text-[#f3f4f6] font-sans selection:bg-purple-600 selection:text-white">
      {/* Compact, Centered Authentication Card (Content-driven Height) */}
      <div className="w-full max-w-md bg-[#1b1b1d] border border-[#2a2b2e] rounded-2xl shadow-2xl p-6 sm:p-8 space-y-6">
        {/* App Logo & Header */}
        <div className="text-center space-y-2">
          <div className="w-12 h-12 mx-auto rounded-xl bg-purple-600/20 border border-purple-500/30 flex items-center justify-center text-xl shadow-lg">
            🧠
          </div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[#f3f4f6]">
            Welcome to CodeBrain
          </h1>
          <p className="text-xs text-[#a1a1aa] leading-relaxed">
            Connect your repository, inspect pipelines, and diagnose failing runs.
          </p>
        </div>

        {/* Primary Option: GitHub OAuth */}
        <button
          id="auth-github-btn"
          type="button"
          onClick={handleGitHubLogin}
          className="w-full py-2.5 px-4 bg-[#202124] hover:bg-[#26272a] text-[#f3f4f6] rounded-xl font-medium transition-all duration-150 flex items-center justify-center gap-3 border border-[#2a2b2e] hover:border-[#383a40] shadow-sm cursor-pointer text-xs sm:text-sm"
        >
          <svg className="w-4 h-4 fill-current text-white shrink-0" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
          </svg>
          <span>Continue with GitHub</span>
        </button>

        {/* Divider */}
        <div className="relative flex items-center justify-center">
          <div className="border-t border-[#2a2b2e] w-full" />
          <span className="bg-[#1b1b1d] px-3 text-[11px] uppercase tracking-wider text-[#71717a] font-mono absolute">
            or
          </span>
        </div>

        {/* Tab Switcher: Sign In vs Create Account */}
        <div className="space-y-4">
          <div className="flex bg-[#202124] p-0.5 rounded-lg border border-[#2a2b2e]">
            <button
              id="auth-tab-signin"
              type="button"
              onClick={() => { setAuthMode("signin"); setError(null); setSuccessMsg(null); }}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all cursor-pointer ${
                authMode === "signin"
                  ? "bg-[#1b1b1d] text-[#f3f4f6] shadow-sm font-semibold"
                  : "text-[#a1a1aa] hover:text-[#f3f4f6]"
              }`}
            >
              Sign In
            </button>
            <button
              id="auth-tab-signup"
              type="button"
              onClick={() => { setAuthMode("signup"); setError(null); setSuccessMsg(null); }}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all cursor-pointer ${
                authMode === "signup"
                  ? "bg-[#1b1b1d] text-[#f3f4f6] shadow-sm font-semibold"
                  : "text-[#a1a1aa] hover:text-[#f3f4f6]"
              }`}
            >
              Create Account
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleAuthSubmit} className="space-y-3">
            {/* Email/Username field */}
            <div>
              <label className="block text-[11px] font-medium text-[#a1a1aa] mb-1">
                {authMode === "signup" ? "Email Address" : "Email or Username"}
              </label>
              <div className="relative flex items-center">
                <Mail size={13} className="absolute left-3 text-[#71717a] pointer-events-none" />
                <input
                  id="auth-email-input"
                  type={authMode === "signup" ? "email" : "text"}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={authMode === "signup" ? "you@company.com" : "username or email"}
                  className="w-full bg-[#202124] border border-[#2a2b2e] focus:border-purple-500 rounded-xl pl-9 pr-3 py-2 text-xs text-[#f3f4f6] placeholder-[#71717a] outline-none transition-colors"
                  required
                />
              </div>
            </div>

            {/* Username field (signup only) */}
            {authMode === "signup" && (
              <div>
                <label className="block text-[11px] font-medium text-[#a1a1aa] mb-1">
                  Username
                </label>
                <div className="relative flex items-center">
                  <UserIcon size={13} className="absolute left-3 text-[#71717a] pointer-events-none" />
                  <input
                    id="auth-username-input"
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="yourhandle"
                    className="w-full bg-[#202124] border border-[#2a2b2e] focus:border-purple-500 rounded-xl pl-9 pr-3 py-2 text-xs text-[#f3f4f6] placeholder-[#71717a] outline-none transition-colors"
                    required
                  />
                </div>
              </div>
            )}

            {/* Password field */}
            <div>
              <label className="block text-[11px] font-medium text-[#a1a1aa] mb-1">
                Password
              </label>
              <div className="relative flex items-center">
                <Lock size={13} className="absolute left-3 text-[#71717a] pointer-events-none" />
                <input
                  id="auth-password-input"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-[#202124] border border-[#2a2b2e] focus:border-purple-500 rounded-xl pl-9 pr-9 py-2 text-xs text-[#f3f4f6] placeholder-[#71717a] outline-none transition-colors"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-3 text-[#71717a] hover:text-[#f3f4f6] transition-colors cursor-pointer"
                >
                  {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
              </div>
            </div>

            {/* Confirm Password field (signup only) */}
            {authMode === "signup" && (
              <div>
                <label className="block text-[11px] font-medium text-[#a1a1aa] mb-1">
                  Confirm Password
                </label>
                <div className="relative flex items-center">
                  <Lock size={13} className="absolute left-3 text-[#71717a] pointer-events-none" />
                  <input
                    id="auth-confirm-password-input"
                    type={showPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full bg-[#202124] border border-[#2a2b2e] focus:border-purple-500 rounded-xl pl-9 pr-3 py-2 text-xs text-[#f3f4f6] placeholder-[#71717a] outline-none transition-colors"
                    required
                  />
                </div>
              </div>
            )}

            {/* Error Message */}
            {error && (
              <div className="p-2.5 rounded-lg bg-red-950/60 border border-red-800 text-red-300 text-xs">
                {error}
              </div>
            )}

            {/* Success Message */}
            {successMsg && (
              <div className="p-2.5 rounded-lg bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-1.5">
                <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />
                <span>{successMsg}</span>
              </div>
            )}

            {/* Submit button */}
            <button
              id="auth-submit-btn"
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white font-semibold rounded-xl text-xs transition-all shadow-lg shadow-purple-900/30 flex items-center justify-center gap-2 cursor-pointer"
            >
              <span>{loading ? "Processing..." : authMode === "signup" ? "Create Account" : "Sign In"}</span>
              <ArrowRight size={13} />
            </button>
          </form>
        </div>

        {/* Developer Bypass Login (Retained for Development Testing) */}
        <div className="pt-2 border-t border-[#2a2b2e] text-center">
          {!showDevModal ? (
            <button
              id="dev-bypass-link"
              type="button"
              onClick={() => setShowDevModal(true)}
              className="text-[11px] text-[#71717a] hover:text-purple-400 transition-colors underline cursor-pointer"
            >
              Developer bypass login
            </button>
          ) : (
            <form onSubmit={handleDevSubmit} className="space-y-2 text-left bg-[#202124]/50 p-3 rounded-xl border border-[#2a2b2e]">
              <div className="flex items-center justify-between text-[11px] font-mono text-purple-300">
                <span className="flex items-center gap-1">
                  <Shield size={11} /> Developer Bypass
                </span>
                <button
                  type="button"
                  onClick={() => setShowDevModal(false)}
                  className="text-[#71717a] hover:text-white text-xs"
                >
                  ✕
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  id="dev-bypass-username-input"
                  type="text"
                  value={devUsername}
                  onChange={(e) => setDevUsername(e.target.value)}
                  className="flex-1 bg-[#161718] border border-[#2a2b2e] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-purple-500"
                  placeholder="Developer"
                />
                <button
                  id="dev-bypass-submit-btn"
                  type="submit"
                  disabled={devLoading}
                  className="px-3.5 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 cursor-pointer shadow"
                >
                  {devLoading ? "…" : "Sign In"}
                </button>
              </div>
              {devError && <p className="text-red-400 text-xs mt-1">{devError}</p>}
            </form>
          )}
        </div>

        {/* Clean Neutral Footer (BCG786 removed) */}
        <p className="text-center text-[10px] text-[#71717a]">
          CodeBrain &bull; AI Codebase Intelligence
        </p>
      </div>
    </div>
  );
}
