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

  // Sequence diagram check
  const hasSequenceSyntax = cleaned.includes("participant ") || cleaned.includes("->>") || cleaned.includes("activate ");
  if (hasSequenceSyntax) {
    if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned)) {
      cleaned = "sequenceDiagram\n" + cleaned.replace(/^(graph|flowchart)\s+[A-Za-z]+\s*\n?/i, "");
    }
    return cleaned;
  }

  // Universal flowchart and architecture blueprint normalization (applies to Docs, Editor, and Chat)
  if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned) || isChat) {
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

      // Sanitize unicode bullets inside line
      l = l.replace(/•/g, "-");

      // Normalize escaped and literal newlines in node labels to <br/> and quote unquoted labels
      // 1. Cylinder: ID[(...)]
      l = l.replace(/(\b[A-Za-z0-9_]+)\[\(\s*(.*?)\s*\)\]/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")");
        return `${id}[("${clean}")]`;
      });

      // 2. Stadium: ID([ ... ])
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\[\s*(.*?)\s*\]\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")");
        return `${id}(["${clean}"])`;
      });

      // 3. Circle: ID(( ... ))
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\(\s*(.*?)\s*\)\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")");
        return `${id}(("${clean}"))`;
      });

      // 4. Square: ID["..."] with inner brackets or quotes, or unquoted ID[...]
      l = l.replace(/(\b[A-Za-z0-9_]+)\["([^"]*)"\]/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/\[/g, "(").replace(/\]/g, ")").replace(/•/g, "-");
        return `${id}["${clean}"]`;
      });
      l = l.replace(/(\b[A-Za-z0-9_]+)\[(?!\()\s*([^\]"]*?)\s*\](?!\))/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")").replace(/•/g, "-");
        return `${id}["${clean}"]`;
      });

      // 5. Rhombus / Decision: ID{ ... }
      l = l.replace(/(\b[A-Za-z0-9_]+)\{\s*(.*?)\s*\}/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")");
        return `${id}{"${clean}"}`;
      });

      const indent = line.match(/^\s*/)?.[0] || "";
      processed.push(indent + l);
    }

    while (subgraphCount > endCount) {
      processed.push("    end");
      endCount++;
    }

    cleaned = processed.join("\n").trim();
  }

  return cleaned;
}

export function generateNativeFallbackSvg(chartText: string, title?: string): string {
  if (!chartText || typeof chartText !== "string") return "";
  const lines = chartText.split("\n");
  const nodes: { id: string; label: string; sublabel?: string }[] = [];
  const edges: { from: string; to: string; label?: string }[] = [];
  const seenNodes = new Set<string>();

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("%%") || line.startsWith("graph") || line.startsWith("flowchart")) continue;

    // Match edge: a -->|label| b or a --> b
    const edgeMatch = line.match(/^([A-Za-z0-9_]+)\s*-->(?:\|(.*?)\|)?\s*([A-Za-z0-9_]+)/);
    if (edgeMatch) {
      const from = edgeMatch[1];
      const lbl = edgeMatch[2] ? edgeMatch[2].trim() : undefined;
      const to = edgeMatch[3];
      edges.push({ from, to, label: lbl });
      if (!seenNodes.has(from)) {
        nodes.push({ id: from, label: from });
        seenNodes.add(from);
      }
      if (!seenNodes.has(to)) {
        nodes.push({ id: to, label: to });
        seenNodes.add(to);
      }
      continue;
    }

    // Match node: id["label<br/>sublabel"] or id["label"] or id[label]
    const nodeMatch = line.match(/^([A-Za-z0-9_]+)\s*\["([^"]*)"\]/) || line.match(/^([A-Za-z0-9_]+)\s*\["?(.*?)"?\]/);
    if (nodeMatch) {
      const id = nodeMatch[1];
      const rawContent = nodeMatch[2] || id;
      const parts = rawContent.split(/<br\s*\/?>/i);
      const label = parts[0]?.trim() || id;
      const sublabel = parts.slice(1).join(" • ").trim();

      const existing = nodes.find((n) => n.id === id);
      if (existing) {
        existing.label = label;
        existing.sublabel = sublabel;
      } else {
        nodes.push({ id, label, sublabel: sublabel || undefined });
        seenNodes.add(id);
      }
    }
  }

  if (nodes.length === 0) {
    return "";
  }

  // Layout calculation (multi-column responsive grid)
  const nodeW = 190;
  const nodeH = 68;
  const padX = 36;
  const padY = 56;
  const cols = Math.min(3, Math.max(1, nodes.length));
  const rows = Math.ceil(nodes.length / cols);
  const totalW = Math.max(820, cols * (nodeW + padX) + padX);
  const totalH = rows * (nodeH + padY) + padY + 30;

  const posMap = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, idx) => {
    const c = idx % cols;
    const r = Math.floor(idx / cols);
    const rowCount = Math.min(cols, nodes.length - r * cols);
    const rowOffset = (totalW - (rowCount * (nodeW + padX) - padX)) / 2;
    const x = rowOffset + c * (nodeW + padX);
    const y = 36 + r * (nodeH + padY);
    posMap.set(node.id, { x, y });
  });

  const svgParts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalW} ${totalH}" width="100%" height="${totalH}px" style="background:#090d16; border-radius:12px; font-family:ui-sans-serif,system-ui,sans-serif;">`,
    `  <defs>`,
    `    <marker id="fb-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">`,
    `      <path d="M 0 1 L 10 5 L 0 9 z" fill="#8b5cf6" />`,
    `    </marker>`,
    `    <filter id="fb-shadow" x="-5%" y="-5%" width="115%" height="115%">`,
    `      <feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#000" flood-opacity="0.5" />`,
    `    </filter>`,
    `  </defs>`,
  ];

  if (title) {
    svgParts.push(`  <text x="36" y="24" fill="#a78bfa" font-size="12" font-weight="700" letter-spacing="0.02em">${title}</text>`);
  }

  // Draw edges
  for (const edge of edges) {
    const p1 = posMap.get(edge.from);
    const p2 = posMap.get(edge.to);
    if (!p1 || !p2) continue;
    const startX = p1.x + nodeW / 2;
    const startY = p1.y + nodeH;
    const endX = p2.x + nodeW / 2;
    const endY = p2.y;
    svgParts.push(`  <path d="M ${startX} ${startY} C ${startX} ${startY + 26}, ${endX} ${endY - 26}, ${endX} ${endY}" stroke="#6b7280" stroke-width="1.5" fill="none" marker-end="url(#fb-arrow)" />`);
    if (edge.label) {
      const midX = (startX + endX) / 2;
      const midY = (startY + endY) / 2;
      svgParts.push(`  <rect x="${midX - 32}" y="${midY - 9}" width="64" height="18" rx="4" fill="#1e1e24" stroke="#374151" stroke-width="0.8" />`);
      svgParts.push(`  <text x="${midX}" y="${midY + 4}" fill="#a78bfa" font-size="9" text-anchor="middle" font-family="monospace">${edge.label}</text>`);
    }
  }

  // Draw nodes
  for (const node of nodes) {
    const p = posMap.get(node.id);
    if (!p) continue;
    svgParts.push(`  <g filter="url(#fb-shadow)">`);
    svgParts.push(`    <rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="8" fill="#141720" stroke="#2e2e38" stroke-width="1.2" />`);
    svgParts.push(`    <rect x="${p.x}" y="${p.y}" width="4" height="${nodeH}" rx="2" fill="#8b5cf6" />`);
    svgParts.push(`    <text x="${p.x + 14}" y="${p.y + 25}" fill="#f3f4f6" font-size="12" font-weight="600">${node.label.length > 22 ? node.label.slice(0, 20) + "..." : node.label}</text>`);
    if (node.sublabel) {
      svgParts.push(`    <text x="${p.x + 14}" y="${p.y + 46}" fill="#9ca3af" font-size="10" font-family="monospace">${node.sublabel.length > 25 ? node.sublabel.slice(0, 23) + "..." : node.sublabel}</text>`);
    }
    svgParts.push(`  </g>`);
  }

  svgParts.push(`</svg>`);
  return svgParts.join("\n");
}

export function repairMermaidSyntax(chart: string): string {
  let repaired = chart.trim();
  // Strip any raw HTML tags except <br/> (e.g. <small>...</small>, <span>, etc.)
  repaired = repaired.replace(/<\/?(?:small|span|div|b|i|font|p|em|strong|h\d)[^>]*>/gi, "");
  repaired = repaired.replace(/<br\s*\/?>/gi, "<br/>");
  repaired = repaired.replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&").replace(/•/g, "-");

  const lines = repaired.split("\n");
  const processed: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    let l = lines[i].trim();
    if (!l) {
      processed.push("");
      continue;
    }
    // Clean inner unescaped quotes, bullets, and brackets in node labels
    l = l.replace(/(\b[A-Za-z0-9_]+)\["([^"]*)"\]/g, (_, id, content) => {
      const clean = content.replace(/"/g, "'").replace(/\[/g, "(").replace(/\]/g, ")").replace(/•/g, "-");
      return `${id}["${clean}"]`;
    });
    l = l.replace(/->>/g, "-->");
    processed.push(l);
  }
  return processed.join("\n").trim();
}

export default function MermaidDiagram({ chart, title, figureCaption, isChat = false }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svgContent, setSvgContent] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [cleanedDiagram, setCleanedDiagram] = useState<string>("");
  const [zoom, setZoom] = useState<number>(1.0);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    const sanitized = sanitizeMermaidChart(chart, isChat);

    if (!sanitized) {
      const fallbackSvg = generateNativeFallbackSvg(chart, title);
      if (fallbackSvg) {
        if (isMounted) {
          setSvgContent(fallbackSvg);
          setCleanedDiagram(chart);
          setError(null);
        }
        return;
      }
      if (isMounted) {
        setSvgContent("");
        setCleanedDiagram("");
        setError(chart && chart.trim() ? "NO_DIAGRAM_SYNTAX" : "EMPTY_DIAGRAM");
      }
      return;
    }

    if (isMounted) {
      setCleanedDiagram(sanitized);
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
      .catch((primaryErr) => {
        const repaired = repairMermaidSyntax(sanitized);
        if (repaired && repaired !== sanitized) {
          const fallbackId = `mermaid-rep-${Math.random().toString(36).substring(2, 9)}`;
          mermaid
            .render(fallbackId, repaired)
            .then((fallbackRes) => {
              if (isMounted) {
                setSvgContent(fallbackRes.svg);
                setError(null);
              }
            })
            .catch(() => {
              const fallbackSvg = generateNativeFallbackSvg(repaired || sanitized || chart, title);
              if (fallbackSvg) {
                if (isMounted) {
                  setSvgContent(fallbackSvg);
                  setError(null);
                }
              } else if (isMounted) {
                setError(primaryErr?.message || "Failed to render diagram");
              }
            });
        } else {
          const fallbackSvg = generateNativeFallbackSvg(sanitized || chart, title);
          if (fallbackSvg) {
            if (isMounted) {
              setSvgContent(fallbackSvg);
              setError(null);
            }
          } else if (isMounted) {
            setError(primaryErr?.message || "Failed to render diagram");
          }
        }
      });

    return () => {
      isMounted = false;
      document.querySelectorAll(`[id^="${id}"]`).forEach((el) => el.remove());
      document.querySelectorAll('.mermaid-error-svg, [id^="dmermaid"]').forEach((el) => el.remove());
    };
  }, [chart, isChat, title]);

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.15, 2.5));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.15, 0.4));
  const handleZoomReset = () => setZoom(1.0);

  const handleCopyMermaid = () => {
    navigator.clipboard.writeText(cleanedDiagram || chart);
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

  if (!chart || !chart.trim() || error === "EMPTY_DIAGRAM" || error === "NO_DIAGRAM_SYNTAX") {
    return (
      <div className="my-3 px-4 py-3 bg-[#0d1017] border border-[#242834] rounded-xl flex items-center gap-2 text-xs text-gray-400 font-mono">
        <span>📊 Architecture Blueprint:</span>
        <span className="text-gray-500">No visual diagram specification available.</span>
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
            {cleanedDiagram || chart}
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

