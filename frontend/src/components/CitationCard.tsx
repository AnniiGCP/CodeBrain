import { useState } from "react";
import type { Citation } from "../types";

interface Props {
  citation: Citation;
  repoId?: string;
  onFixClick?: (citation: Citation) => void;
}

export default function CitationCard({ citation, onFixClick }: Props) {
  const [expanded, setExpanded] = useState(false);
  const lineRef = `${citation.file_path}:${citation.start_line}`;

  return (
    <div className="mt-1 border border-[#242834] bg-[#12151c] rounded-lg overflow-hidden text-xs">
      <div className="flex items-center gap-1 bg-[#1a1e28]/70 px-2.5 py-1.5">
        {/* Clickable Citation link navigating to file and line */}
        <button
          type="button"
          onClick={() => onFixClick?.(citation)}
          className="flex-1 flex items-center gap-2 hover:text-white transition-colors text-left min-w-0 group"
          title={`Open ${citation.file_path} at line ${citation.start_line}`}
        >
          <span className="text-blue-400 group-hover:underline font-mono truncate flex-1 text-xs">
            {lineRef}
          </span>
          <span className="text-gray-400 text-[10px] uppercase font-mono px-1.5 py-0.5 bg-[#12151c] rounded border border-[#242834] shrink-0">
            {citation.symbol_type}
          </span>
        </button>

        {/* Expand / Collapse Code Snippet Toggle */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((prev) => !prev);
          }}
          title={expanded ? "Collapse code snippet" : "Expand code snippet"}
          className="p-1 text-gray-400 hover:text-white hover:bg-[#252a38] rounded transition-colors text-xs shrink-0"
        >
          {expanded ? "▲" : "▼"}
        </button>

        {/* Quick Auto-Fix Wrench Button */}
        {onFixClick && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onFixClick(citation);
            }}
            title="Inspect & Auto-Fix"
            className="p-1 text-amber-400 hover:text-amber-300 hover:bg-amber-950/40 rounded transition-colors text-xs font-medium shrink-0"
          >
            🔧
          </button>
        )}
      </div>

      {expanded && citation.source_code && (
        <pre className="bg-[#0e1117] text-gray-300 overflow-x-auto p-3 text-xs font-mono leading-relaxed max-h-60 border-t border-[#242834]">
          <code>{citation.source_code}</code>
        </pre>
      )}
    </div>
  );
}
