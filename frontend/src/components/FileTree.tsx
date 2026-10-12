import { useState } from "react";
import type { FileNode } from "../types";

const LANG_COLORS: Record<string, string> = {
  python: "text-blue-400",
  javascript: "text-yellow-400",
  typescript: "text-blue-300",
  java: "text-orange-400",
  cpp: "text-purple-400",
  c: "text-purple-300",
  go: "text-cyan-400",
  rust: "text-orange-300",
  markdown: "text-gray-400",
  json: "text-green-400",
  yaml: "text-green-300",
  html: "text-red-400",
  css: "text-pink-400",
  shell: "text-lime-400",
};

const LANG_ICONS: Record<string, string> = {
  python: "🐍",
  javascript: "🟨",
  typescript: "🟦",
  java: "☕",
  cpp: "⚡",
  c: "⚡",
  go: "🐹",
  rust: "🦀",
  markdown: "📝",
  json: "{}",
  yaml: "📋",
  html: "🌐",
  css: "🎨",
  shell: "🖥",
};

interface FileTreeNodeProps {
  node: FileNode;
  depth: number;
  onSelectFile?: (path: string) => void;
}

function FileTreeNode({ node, depth, onSelectFile }: FileTreeNodeProps) {
  const [open, setOpen] = useState(depth < 2);

  if (node.type === "file") {
    const lang = node.language ?? "";
    const icon = LANG_ICONS[lang] ?? "📄";
    const color = LANG_COLORS[lang] ?? "text-gray-400";
    return (
      <div
        onClick={() => node.path && onSelectFile?.(node.path)}
        className="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-[#18191d] cursor-pointer group transition-colors text-xs select-none"
        style={{ paddingLeft: `${(depth + 1) * 12}px` }}
        title={node.path}
      >
        <span className="text-xs opacity-70">{icon}</span>
        <span className={`truncate font-mono ${color}`}>{node.name}</span>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 w-full px-2 py-1 rounded hover:bg-[#18191d] transition-colors text-left text-xs select-none"
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        <span className="text-gray-500 text-[10px] w-3">{open ? "▾" : "▸"}</span>
        <span className="text-xs">📁</span>
        <span className="text-[#cccccc] truncate font-medium">{node.name}</span>
      </button>
      {open &&
        node.children?.map((child) => (
          <FileTreeNode
            key={child.path ?? child.name}
            node={child}
            depth={depth + 1}
            onSelectFile={onSelectFile}
          />
        ))}
    </div>
  );
}

interface Props {
  tree: FileNode;
  totalFiles?: number;
  onSelectFile?: (path: string) => void;
}

export default function FileTree({ tree, totalFiles, onSelectFile }: Props) {
  const hasContent = tree && ((tree.children && tree.children.length > 0) || tree.type === "file");

  if (!hasContent) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-gray-500 text-xs select-none">
        <span className="text-2xl mb-2">📂</span>
        <p className="font-semibold text-gray-400">No files found</p>
        <p className="text-[11px] text-gray-500 mt-1">Repository indexing may still be in progress...</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto min-h-0 py-1">
      {totalFiles !== undefined && totalFiles > 0 && (
        <p className="text-[10px] text-gray-500 uppercase tracking-wider font-mono px-3 py-1 mb-1 border-b border-[#2d2d2d]">
          {totalFiles} indexed source files
        </p>
      )}
      <FileTreeNode node={tree} depth={0} onSelectFile={onSelectFile} />
    </div>
  );
}
