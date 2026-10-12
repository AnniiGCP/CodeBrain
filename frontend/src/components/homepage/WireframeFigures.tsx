import type { FC } from "react";

/**
 * FIG 0.1 — Understand Your Codebase
 * Precision line-art repository structure & module dependency graph.
 * Shows connected architectural modules with directional dependency edges and a central index root.
 */
export const Fig01Codebase: FC<{ className?: string }> = ({ className = "w-full h-44" }) => {
  return (
    <svg
      viewBox="0 0 320 220"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FIG 0.1 Codebase Architecture & Dependency Graph"
    >
      <defs>
        <linearGradient id="fig1-node-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#25262a" />
          <stop offset="100%" stopColor="#18191c" />
        </linearGradient>
      </defs>

      {/* Background Subtle Coordinate Grid Rays */}
      <line x1="40" y1="110" x2="280" y2="110" stroke="#2a2b2e" strokeWidth="0.75" strokeDasharray="4 4" />
      <line x1="160" y1="30" x2="160" y2="190" stroke="#2a2b2e" strokeWidth="0.75" strokeDasharray="4 4" />

      {/* Inter-Module Dependency Edges */}
      {/* Root to Left Branch */}
      <path d="M160 55 L85 105" stroke="#71717a" strokeWidth="1" strokeDasharray="3 3" />
      {/* Root to Right Branch */}
      <path d="M160 55 L235 105" stroke="#71717a" strokeWidth="1" strokeDasharray="3 3" />
      {/* Root to Center Direct */}
      <path d="M160 55 L160 115" stroke="#8b5cf6" strokeWidth="1.25" />
      {/* Left to Sub-modules */}
      <path d="M85 105 L60 165" stroke="#52525b" strokeWidth="1" />
      <path d="M85 105 L115 165" stroke="#52525b" strokeWidth="1" strokeDasharray="2 2" />
      {/* Right to Sub-modules */}
      <path d="M235 105 L205 165" stroke="#52525b" strokeWidth="1" strokeDasharray="2 2" />
      <path d="M235 105 L260 165" stroke="#52525b" strokeWidth="1" />
      {/* Lateral cross-module coupling */}
      <path d="M115 165 C 140 180, 180 180, 205 165" stroke="#8b5cf6" strokeWidth="0.75" strokeDasharray="3 3" opacity="0.6" fill="none" />

      {/* ROOT NODE: Repository Entrypoint / AST Index */}
      <rect x="135" y="35" width="50" height="28" rx="6" fill="url(#fig1-node-grad)" stroke="#d4d4d8" strokeWidth="1.25" />
      <circle cx="150" cy="49" r="3" fill="#a855f7" />
      <line x1="158" y1="49" x2="175" y2="49" stroke="#f3f4f6" strokeWidth="1.5" strokeLinecap="round" />

      {/* TIER 2: Primary Modules */}
      {/* Left Module (e.g. backend / core) */}
      <rect x="60" y="90" width="50" height="26" rx="6" fill="url(#fig1-node-grad)" stroke="#a1a1aa" strokeWidth="1" />
      <line x1="72" y1="103" x2="98" y2="103" stroke="#a1a1aa" strokeWidth="1.25" strokeLinecap="round" />

      {/* Center Module (e.g. models / schemas) */}
      <rect x="135" y="105" width="50" height="26" rx="6" fill="#1e1f23" stroke="#a855f7" strokeWidth="1.2" />
      <circle cx="147" cy="118" r="2.5" fill="#34d399" />
      <line x1="155" y1="118" x2="173" y2="118" stroke="#f3f4f6" strokeWidth="1.25" strokeLinecap="round" />

      {/* Right Module (e.g. frontend / api) */}
      <rect x="210" y="90" width="50" height="26" rx="6" fill="url(#fig1-node-grad)" stroke="#a1a1aa" strokeWidth="1" />
      <line x1="222" y1="103" x2="248" y2="103" stroke="#a1a1aa" strokeWidth="1.25" strokeLinecap="round" />

      {/* TIER 3: Leaf Packages & AST Nodes */}
      <rect x="42" y="155" width="36" height="20" rx="4" fill="#161718" stroke="#52525b" strokeWidth="0.75" />
      <line x1="50" y1="165" x2="68" y2="165" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />

      <rect x="98" y="155" width="36" height="20" rx="4" fill="#161718" stroke="#52525b" strokeWidth="0.75" />
      <line x1="106" y1="165" x2="124" y2="165" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />

      <rect x="187" y="155" width="36" height="20" rx="4" fill="#161718" stroke="#52525b" strokeWidth="0.75" />
      <line x1="195" y1="165" x2="213" y2="165" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />

      <rect x="242" y="155" width="36" height="20" rx="4" fill="#161718" stroke="#52525b" strokeWidth="0.75" />
      <line x1="250" y1="165" x2="268" y2="165" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />

      {/* Central Core Resonance Ring */}
      <circle cx="160" cy="118" r="32" stroke="#8b5cf6" strokeWidth="0.75" strokeDasharray="3 3" opacity="0.4" />
    </svg>
  );
};

/**
 * FIG 0.2 — Find Issues. Fix With Context.
 * Precision line-art source-code diagnostics & AI-reviewed patch indicator.
 * Displays code lines, diagnostic error marker, and an verified auto-fix diff card.
 */
export const Fig02Issues: FC<{ className?: string }> = ({ className = "w-full h-44" }) => {
  return (
    <svg
      viewBox="0 0 320 220"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FIG 0.2 Source Code Diagnostic & Contextual Patch"
    >
      <defs>
        <linearGradient id="fig2-card-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#222327" />
          <stop offset="100%" stopColor="#17181a" />
        </linearGradient>
      </defs>

      {/* Main Source Editor Card */}
      <rect x="45" y="32" width="230" height="156" rx="8" fill="url(#fig2-card-grad)" stroke="#383a40" strokeWidth="1" />
      
      {/* Editor Header */}
      <line x1="45" y1="58" x2="275" y2="58" stroke="#2a2b2e" strokeWidth="1" />
      <circle cx="60" cy="45" r="3" fill="#f87171" opacity="0.8" />
      <circle cx="70" cy="45" r="3" fill="#fbbf24" opacity="0.8" />
      <circle cx="80" cy="45" r="3" fill="#34d399" opacity="0.8" />
      <line x1="100" y1="45" x2="160" y2="45" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />

      {/* Code Lines — Regular */}
      <line x1="65" y1="74" x2="120" y2="74" stroke="#71717a" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="65" y1="88" x2="180" y2="88" stroke="#a1a1aa" strokeWidth="1.5" strokeLinecap="round" />

      {/* Failing / Problem Code Line with Alert Marker */}
      <rect x="58" y="99" width="204" height="20" rx="4" fill="#451a1a" fillOpacity="0.3" stroke="#f87171" strokeWidth="0.75" />
      {/* Red squiggly underline indicator */}
      <path d="M 68 111 Q 72 114 76 111 T 84 111 T 92 111 T 100 111 T 108 111 T 116 111 T 124 111 T 132 111 T 140 111" stroke="#f87171" strokeWidth="1" fill="none" />
      <line x1="68" y1="107" x2="140" y2="107" stroke="#fca5a5" strokeWidth="1.5" strokeLinecap="round" />

      {/* Diagnostic Warning Pill Badge */}
      <rect x="180" y="101" width="74" height="16" rx="4" fill="#202124" stroke="#f87171" strokeWidth="0.75" />
      <circle cx="190" cy="109" r="2.5" fill="#f87171" />
      <line x1="197" y1="109" x2="246" y2="109" stroke="#fca5a5" strokeWidth="1" strokeLinecap="round" />

      {/* Code Lines below */}
      <line x1="65" y1="130" x2="150" y2="130" stroke="#71717a" strokeWidth="1.5" strokeLinecap="round" />

      {/* Overlay: AI Reviewed Patch Card (Floating Fix) */}
      <rect x="110" y="132" width="170" height="58" rx="8" fill="#1b1b1d" stroke="#8b5cf6" strokeWidth="1.25" filter="drop-shadow(0 8px 16px rgba(0,0,0,0.6))" />
      <line x1="110" y1="152" x2="280" y2="152" stroke="#2a2b2e" strokeWidth="1" />
      
      {/* Fix Card Header */}
      <circle cx="124" cy="142" r="3" fill="#34d399" />
      <line x1="134" y1="142" x2="185" y2="142" stroke="#34d399" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="235" y="137" width="36" height="10" rx="3" fill="#2e1065" stroke="#a855f7" strokeWidth="0.75" />
      <line x1="242" y1="142" x2="264" y2="142" stroke="#d8b4fe" strokeWidth="1" strokeLinecap="round" />

      {/* Patch diff lines */}
      <line x1="124" y1="162" x2="130" y2="162" stroke="#34d399" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="135" y1="162" x2="245" y2="162" stroke="#f3f4f6" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="124" y1="174" x2="130" y2="174" stroke="#71717a" strokeWidth="1" strokeLinecap="round" />
      <line x1="135" y1="174" x2="210" y2="174" stroke="#a1a1aa" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
};

/**
 * FIG 0.3 — Documentation That Explains The System
 * Precision line-art structured technical documentation leaves & architectural blueprints.
 * Shows multi-layered document suite with heading hierarchy, prose lines, and an embedded architecture diagram.
 */
export const Fig03Docs: FC<{ className?: string }> = ({ className = "w-full h-44" }) => {
  return (
    <svg
      viewBox="0 0 320 220"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="FIG 0.3 Technical Documentation & Architecture Blueprint"
    >
      <defs>
        <linearGradient id="fig3-sheet-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#222327" />
          <stop offset="100%" stopColor="#18191c" />
        </linearGradient>
      </defs>

      {/* Layer 1: Background Secondary Document Sheet */}
      <rect x="100" y="24" width="150" height="170" rx="6" fill="#161718" stroke="#383a40" strokeWidth="0.75" opacity="0.6" transform="rotate(4 100 24)" />

      {/* Layer 2: Main Foreground Document Sheet */}
      <rect x="75" y="30" width="170" height="165" rx="8" fill="url(#fig3-sheet-grad)" stroke="#d4d4d8" strokeWidth="1.2" />

      {/* Document Title / Heading */}
      <rect x="95" y="48" width="65" height="7" rx="2" fill="#a855f7" />
      <line x1="95" y1="64" x2="225" y2="64" stroke="#71717a" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="95" y1="74" x2="200" y2="74" stroke="#52525b" strokeWidth="1.5" strokeLinecap="round" />

      {/* Embedded Architecture Diagram Container */}
      <rect x="95" y="86" width="130" height="52" rx="5" fill="#141517" stroke="#3f3f46" strokeWidth="0.75" />
      
      {/* Embedded Diagram Nodes & Flow */}
      <rect x="105" y="100" width="28" height="18" rx="3" fill="#202124" stroke="#8b5cf6" strokeWidth="1" />
      <line x1="110" y1="109" x2="128" y2="109" stroke="#d8b4fe" strokeWidth="1" strokeLinecap="round" />

      <line x1="135" y1="109" x2="150" y2="109" stroke="#71717a" strokeWidth="1" strokeDasharray="2 2" />

      <rect x="152" y="100" width="28" height="18" rx="3" fill="#202124" stroke="#34d399" strokeWidth="1" />
      <line x1="157" y1="109" x2="175" y2="109" stroke="#6ee7b7" strokeWidth="1" strokeLinecap="round" />

      <line x1="182" y1="109" x2="197" y2="109" stroke="#71717a" strokeWidth="1" strokeDasharray="2 2" />

      <rect x="199" y="100" width="20" height="18" rx="3" fill="#202124" stroke="#71717a" strokeWidth="0.75" />
      <circle cx="209" cy="109" r="2" fill="#a1a1aa" />

      {/* Follow-up Document Paragraph Lines */}
      <line x1="95" y1="149" x2="225" y2="149" stroke="#71717a" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="95" y1="159" x2="210" y2="159" stroke="#52525b" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="95" y1="169" x2="160" y2="169" stroke="#52525b" strokeWidth="1.5" strokeLinecap="round" />

      {/* Verified Complete Check Badge at bottom right of document */}
      <circle cx="230" cy="180" r="7" fill="#064e3b" stroke="#34d399" strokeWidth="1" />
      <path d="M228 180 L230 182 L233 178" stroke="#34d399" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};
