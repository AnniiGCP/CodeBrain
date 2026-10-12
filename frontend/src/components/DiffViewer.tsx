/**
 * DiffViewer — renders a unified diff string with syntax highlighting.
 * Pure CSS implementation, no external libraries.
 *
 * Supports:
 *  - Added lines   (+)   green
 *  - Removed lines (-)   red
 *  - Hunk headers  (@@)  blue
 *  - Context lines       gray
 */

interface Props {
  diff: string;
  fileName?: string;
}

interface DiffLine {
  type: "add" | "remove" | "context" | "header" | "file";
  content: string;
  lineNum?: number;
}

function parseDiff(raw: string): DiffLine[] {
  const lines = raw.split("\n");
  const result: DiffLine[] = [];
  let addNum = 0;
  let remNum = 0;

  for (const line of lines) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      result.push({ type: "file", content: line });
    } else if (line.startsWith("@@")) {
      // Extract starting line numbers from @@ -L,S +L,S @@
      const m = line.match(/-(\d+).*\+(\d+)/);
      if (m) {
        remNum = parseInt(m[1], 10);
        addNum = parseInt(m[2], 10);
      }
      result.push({ type: "header", content: line });
    } else if (line.startsWith("+")) {
      result.push({ type: "add", content: line.slice(1), lineNum: addNum++ });
    } else if (line.startsWith("-")) {
      result.push({ type: "remove", content: line.slice(1), lineNum: remNum++ });
    } else {
      result.push({ type: "context", content: line.slice(1), lineNum: remNum++ });
      addNum++;
    }
  }
  return result;
}

const lineStyle: Record<DiffLine["type"], string> = {
  add: "bg-green-950 text-green-300 border-l-2 border-green-500",
  remove: "bg-red-950 text-red-300 border-l-2 border-red-500 line-through-none",
  context: "text-gray-400",
  header: "bg-blue-950 text-blue-300 font-semibold",
  file: "bg-gray-800 text-gray-300 font-mono text-xs py-1",
};

const linePrefix: Record<DiffLine["type"], string> = {
  add: "+",
  remove: "-",
  context: " ",
  header: "",
  file: "",
};

export default function DiffViewer({ diff, fileName }: Props) {
  if (!diff || !diff.trim()) {
    return (
      <div className="text-gray-500 text-sm text-center py-8">
        No diff available
      </div>
    );
  }

  const lines = parseDiff(diff);
  const addCount = lines.filter((l) => l.type === "add").length;
  const removeCount = lines.filter((l) => l.type === "remove").length;

  return (
    <div className="rounded-xl overflow-hidden border border-gray-700 bg-gray-950 text-xs font-mono">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <span className="text-gray-300 truncate">{fileName ?? "diff"}</span>
        <div className="flex items-center gap-3 shrink-0 ml-3">
          <span className="text-green-400">+{addCount}</span>
          <span className="text-red-400">-{removeCount}</span>
        </div>
      </div>

      {/* Diff lines */}
      <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, idx) => (
              <tr key={`${line.type}-${line.lineNum ?? idx}-${idx}`} className={`${lineStyle[line.type]} hover:brightness-125 transition-none`}>
                {/* Gutter: line number */}
                <td className="select-none text-gray-600 text-right pr-3 pl-2 w-10 shrink-0 align-top py-0.5">
                  {line.lineNum !== undefined ? line.lineNum : ""}
                </td>
                {/* Prefix symbol */}
                <td className="select-none w-4 text-center align-top py-0.5 font-bold">
                  {linePrefix[line.type]}
                </td>
                {/* Content */}
                <td className="pl-2 pr-4 py-0.5 whitespace-pre align-top">
                  {line.content}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
