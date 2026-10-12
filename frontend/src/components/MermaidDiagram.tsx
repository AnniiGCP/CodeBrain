import { useEffect, useRef, useState, useCallback } from "react";
import mermaid from "mermaid";
import {
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Maximize2,
  Minimize2,
  Download,
  Copy,
  Check,
  Image as ImageIcon,
} from "lucide-react";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
  suppressErrorRendering: true,
  fontFamily: "ui-sans-serif, system-ui, sans-serif",
});

interface MermaidDiagramProps {
  chart: string;
  title?: string;
  figureCaption?: string;
  isChat?: boolean;
}

export function sanitizeMermaidChart(rawChart: string, isChat: boolean = false): string {
  if (!rawChart || typeof rawChart !== "string") return "";
  let cleaned = rawChart.trim();
  if (!cleaned) return "";

  // 1. If wrapped in ```mermaid ... ``` (or unclosed during streaming)
  const mermaidBlockMatch = cleaned.match(/```mermaid\s*([\s\S]*?)(?:```|$)/i);
  if (mermaidBlockMatch && mermaidBlockMatch[1].trim()) {
    cleaned = mermaidBlockMatch[1].trim();
  } else {
    // 2. Check if a valid diagram keyword appears
    const keywordMatch = cleaned.match(/(?:^|\n)\s*((?:sequenceDiagram|flowchart\s+[A-Za-z]+|graph\s+[A-Za-z]+|classDiagram|erDiagram|stateDiagram|gantt|mindmap|quadrantChart|timeline|gitGraph|pie)[\s\S]*)/i);
    if (keywordMatch) {
      cleaned = keywordMatch[1].trim();
    } else {
      // If neither code block nor diagram keyword exists, this is non-diagram prose
      return "";
    }
  }

  // 3. Strip remaining markdown code fences if any
  cleaned = cleaned.replace(/```mermaid/gi, "").replace(/```/g, "").trim();

  // 4. Truncate at trailing markdown section headers (e.g. \n## Section)
  const trailingMarkdownMatch = cleaned.match(/\n\s*(?:#{1,6}\s+|---+\s*$|===+\s*$)/m);
  if (trailingMarkdownMatch && trailingMarkdownMatch.index !== undefined) {
    cleaned = cleaned.slice(0, trailingMarkdownMatch.index).trim();
  }

  // 5. Check if it contains sequence diagram syntax
  const hasSequenceSyntax = cleaned.includes("participant ") || cleaned.includes("->>") || cleaned.includes("activate ");

  if (hasSequenceSyntax) {
    if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned)) {
      cleaned = "sequenceDiagram\n" + cleaned.replace(/^(graph|flowchart)\s+[A-Za-z]+\s*\n?/i, "");
    }
    return cleaned;
  }

  if (isChat) {
    // Chat-specific architecture blueprint normalization
    const lines = cleaned.split("\n");
    const processed: string[] = [];
    let subgraphCount = 0;
    let endCount = 0;

    for (const line of lines) {
      let l = line.trim();
      if (!l) {
        processed.push("");
        continue;
      }

      if (/^subgraph\b/i.test(l)) {
        subgraphCount++;
      } else if (/^end\b/i.test(l)) {
        endCount++;
      }

      // Replace sequence arrows ->> with -->
      l = l.replace(/->>/g, "-->");

      // Normalize escaped and literal newlines in node labels to <br/> and quote unquoted labels
      // 1. Cylinder: ID[(...)]
      l = l.replace(/(\b[A-Za-z0-9_]+)\[\(\s*(.*?)\s*\)\]/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}[("${clean}")]`;
      });

      // 2. Stadium: ID([ ... ])
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\[\s*(.*?)\s*\]\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}(["${clean}"])`;
      });

      // 3. Circle: ID(( ... ))
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\(\s*(.*?)\s*\)\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}(("${clean}"))`;
      });

      // 4. Square: ID[ ... ] (ensure not part of [("...")])
      l = l.replace(/(\b[A-Za-z0-9_]+)\[(?!\()\s*(.*?)\s*\](?!\))/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}["${clean}"]`;
      });

      // 5. Rhombus / Decision: ID{ ... }
      l = l.replace(/(\b[A-Za-z0-9_]+)\{\s*(.*?)\s*\}/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}{"${clean}"}`;
      });

      const indent = line.match(/^\s*/)?.[0] || "";
      processed.push(indent + l);
    }

    while (subgraphCount > endCount) {
      processed.push("    end");
      endCount++;
    }

    return processed.join("\n").trim();
  }

  // Shared default for other surfaces
  if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned)) {
    cleaned = cleaned.replace(/->>/g, "-->");
    cleaned = cleaned.replace(/\[(?!\()([^"\]\n]*?\([^\]\n]*?\)[^"\]\n]*?)(?<!\))\]/g, '["$1"]');
  }

  return cleaned;
}

export default function MermaidDiagram({ chart, title, figureCaption, isChat = false }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svgContent, setSvgContent] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState<number>(1.0);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    const sanitized = sanitizeMermaidChart(chart, isChat);

    if (!sanitized) {
      if (isMounted) {
        setSvgContent("");
        setError(chart && chart.trim() ? "NO_DIAGRAM_SYNTAX" : "EMPTY_DIAGRAM");
      }
      return;
    }

    const id = `mermaid-${Math.random().toString(36).substring(2, 9)}`;

    mermaid
      .render(id, sanitized)
      .then((res) => {
        if (isMounted) {
          setSvgContent(res.svg);
          setError(null);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.warn("Mermaid render error:", err);
          setError(err?.message || "Failed to render diagram");
        }
      });

    return () => {
      isMounted = false;
      document.querySelectorAll(`[id^="${id}"]`).forEach((el) => el.remove());
      document.querySelectorAll('.mermaid-error-svg, [id^="dmermaid"]').forEach((el) => el.remove());
    };
  }, [chart]);

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.15, 2.5));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.15, 0.4));
  const handleZoomReset = () => setZoom(1.0);

  const handleCopyMermaid = () => {
    navigator.clipboard.writeText(chart);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadSVG = useCallback(() => {
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `diagram_${Date.now()}.svg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [svgContent]);

  const handleDownloadPNG = useCallback(() => {
    if (!svgContent) return;
    const parser = new DOMParser();
    const doc = parser.parseFromString(svgContent, "image/svg+xml");
    const svgEl = doc.querySelector("svg");
    if (!svgEl) return;

    const width = parseInt(svgEl.getAttribute("width") || "1200", 10) || 1200;
    const height = parseInt(svgEl.getAttribute("height") || "800", 10) || 800;

    const canvas = document.createElement("canvas");
    canvas.width = width * 2;
    canvas.height = height * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.fillStyle = "#090d16";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const svgBlob = new Blob([svgContent], { type: "image/svg+xml;charset=utf-8" });
    const URLObj = window.URL || window.webkitURL || window;
    const blobURL = URLObj.createObjectURL(svgBlob);
    const image = new Image();

    image.onload = () => {
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const pngURL = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = pngURL;
      a.download = `diagram_${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URLObj.revokeObjectURL(blobURL);
    };
    image.src = blobURL;
  }, [svgContent]);

  if (!chart || !chart.trim() || error === "EMPTY_DIAGRAM") {
    return (
      <div className="my-3 px-4 py-3 bg-[#0d1017] border border-[#242834] rounded-xl flex items-center gap-2 text-xs text-gray-400 font-mono">
        <span>📊 Architecture Blueprint:</span>
        <span className="text-gray-500">No diagram specification available.</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="my-4 bg-[#090d16] border border-amber-900/60 rounded-2xl overflow-hidden shadow-xl text-xs font-mono">
        <div className="px-4 py-2.5 bg-[#14100c] border-b border-amber-900/40 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-amber-300 font-medium">
            <span>⚠️</span>
            <span className="font-semibold">{title || "Architecture Blueprint"}</span>
            <span className="text-[10px] bg-amber-950 text-amber-400 px-2 py-0.5 rounded border border-amber-800/80">
              Syntax Fallback
            </span>
          </div>
          <button
            onClick={handleCopyMermaid}
            title="Copy Diagram Source"
            className="flex items-center gap-1 px-2.5 py-1 bg-[#1e2029] hover:bg-[#282b37] text-gray-300 hover:text-white rounded-lg transition-colors text-[11px]"
          >
            {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            <span>{copied ? "Copied" : "Copy Source"}</span>
          </button>
        </div>
        <div className="p-4 bg-[#07090f] space-y-2">
          <p className="text-[11px] text-amber-400/90 font-sans">
            Visual SVG rendering could not parse this diagram syntax. Displaying usable structural blueprint:
          </p>
          <pre className="text-gray-300 bg-[#0d1017] p-3 rounded-xl overflow-x-auto border border-[#242834] leading-relaxed text-[12px]">
            {chart}
          </pre>
        </div>
      </div>
    );
  }

  if (!svgContent) {
    return (
      <div className="my-3 px-4 py-3 bg-[#0d1017] border border-[#242834] rounded-xl flex items-center gap-2 text-xs text-gray-400 font-mono">
        <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
        <span>Rendering architecture diagram...</span>
      </div>
    );
  }

  const diagramBody = (
    <div
      ref={containerRef}
      style={{
        transform: `scale(${zoom})`,
        transformOrigin: "center center",
        transition: "transform 0.15s ease-out",
        maxWidth: "100%",
      }}
      className="flex justify-center items-center w-full min-h-[120px] py-3 overflow-x-auto [&_svg]:max-w-full [&_svg]:h-auto"
      dangerouslySetInnerHTML={{ __html: svgContent }}
    />
  );

  return (
    <>
      <div className="my-4 bg-[#090d16] border border-[#2d3748] rounded-2xl overflow-hidden shadow-2xl flex flex-col">
        {/* Visual Controls Header */}
        <div className="px-4 py-2.5 bg-[#0f172a] border-b border-[#1e293b] flex items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 text-gray-300 font-medium">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="font-semibold text-white tracking-wide">
              {title || "Architecture Diagram"}
            </span>
            <span className="text-[10px] bg-blue-950/80 text-blue-400 px-2 py-0.5 rounded border border-blue-800 font-mono">
              Vector SVG
            </span>
          </div>

          {/* Interactive Toolbar */}
          <div className="flex items-center gap-1">
            <button
              onClick={handleZoomIn}
              title="Zoom In"
              className="p-1.5 hover:bg-[#1e293b] text-gray-400 hover:text-white rounded-lg transition-colors"
            >
              <ZoomIn size={14} />
            </button>
            <button
              onClick={handleZoomOut}
              title="Zoom Out"
              className="p-1.5 hover:bg-[#1e293b] text-gray-400 hover:text-white rounded-lg transition-colors"
            >
              <ZoomOut size={14} />
            </button>
            <button
              onClick={handleZoomReset}
              title="Reset Zoom"
              className="p-1.5 hover:bg-[#1e293b] text-gray-400 hover:text-white rounded-lg transition-colors"
            >
              <RotateCcw size={13} />
            </button>

            <div className="h-3.5 w-px bg-[#334155] mx-1" />

            <button
              onClick={handleDownloadSVG}
              title="Download SVG"
              className="p-1.5 hover:bg-[#1e293b] text-blue-400 hover:text-blue-300 rounded-lg transition-colors flex items-center gap-1 text-[11px]"
            >
              <Download size={13} />
              <span className="hidden sm:inline">SVG</span>
            </button>

            <button
              onClick={handleDownloadPNG}
              title="Download PNG (High-Res)"
              className="p-1.5 hover:bg-[#1e293b] text-emerald-400 hover:text-emerald-300 rounded-lg transition-colors flex items-center gap-1 text-[11px]"
            >
              <ImageIcon size={13} />
              <span className="hidden sm:inline">PNG</span>
            </button>

            <button
              onClick={handleCopyMermaid}
              title="Copy Diagram Source"
              className="p-1.5 hover:bg-[#1e293b] text-gray-400 hover:text-white rounded-lg transition-colors"
            >
              {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
            </button>

            <button
              onClick={() => setIsFullscreen(true)}
              title="Expand Fullscreen"
              className="p-1.5 hover:bg-[#1e293b] text-purple-400 hover:text-purple-300 rounded-lg transition-colors"
            >
              <Maximize2 size={13} />
            </button>
          </div>
        </div>

        {/* Diagram Canvas */}
        <div className="p-4 overflow-x-auto overflow-y-hidden bg-[#070b12] flex items-center justify-center min-h-[220px]">
          {diagramBody}
        </div>

        {/* Caption Footer */}
        {figureCaption && (
          <div className="px-4 py-2 bg-[#0c121e] border-t border-[#1e293b] text-[11px] text-gray-400 italic text-center font-mono">
            {figureCaption}
          </div>
        )}
      </div>

      {/* Fullscreen Overlay Modal */}
      {isFullscreen && (
        <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex flex-col p-6 animate-fade-in">
          <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
            <div className="flex items-center gap-3">
              <span className="text-base font-bold text-white">{title || "Architecture Diagram Blueprint"}</span>
              {figureCaption && <span className="text-xs text-gray-400 font-mono">({figureCaption})</span>}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleZoomIn}
                className="p-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition"
                title="Zoom In"
              >
                <ZoomIn size={16} />
              </button>
              <button
                onClick={handleZoomOut}
                className="p-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition"
                title="Zoom Out"
              >
                <ZoomOut size={16} />
              </button>
              <button
                onClick={handleZoomReset}
                className="p-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition"
                title="Reset Zoom"
              >
                <RotateCcw size={16} />
              </button>
              <button
                onClick={handleDownloadSVG}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5"
              >
                <Download size={14} /> Download SVG
              </button>
              <button
                onClick={handleDownloadPNG}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5"
              >
                <ImageIcon size={14} /> Download PNG
              </button>
              <button
                onClick={() => setIsFullscreen(false)}
                className="p-2 bg-red-600/80 hover:bg-red-500 text-white rounded-lg transition ml-2"
                title="Exit Fullscreen"
              >
                <Minimize2 size={16} />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto flex items-center justify-center p-8 bg-[#090d16] rounded-2xl border border-gray-800">
            {diagramBody}
          </div>
        </div>
      )}
    </>
  );
}

