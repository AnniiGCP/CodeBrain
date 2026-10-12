import { useState, memo, type FC } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MermaidDiagram from "./MermaidDiagram";
import { Check, Copy } from "lucide-react";
import { normalizeMarkdown } from "../utils/markdownUtils";

interface MarkdownRendererProps {
  content: string;
  isChat?: boolean;
}

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-white hover:bg-[#222838] px-2 py-0.5 rounded transition-colors"
      title="Copy code to clipboard"
    >
      {copied ? (
        <>
          <Check size={11} className="text-emerald-400" />
          <span className="text-emerald-400">Copied</span>
        </>
      ) : (
        <>
          <Copy size={11} />
          <span>Copy</span>
        </>
      )}
    </button>
  );
}

export const MarkdownRenderer: FC<MarkdownRendererProps> = memo(({ content, isChat = true }) => {
  const normalized = normalizeMarkdown(content);

  return (
    <div className="text-[14px] font-normal text-gray-200 leading-[1.65] font-sans select-text">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-[17px] font-semibold text-white border-b border-[#242834] pb-1.5 mt-4 mb-2 select-text tracking-tight">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-[16px] font-semibold text-white mt-4 mb-2 select-text tracking-tight">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-[15px] font-semibold text-blue-300 mt-3 mb-1.5 select-text tracking-tight">
              {children}
            </h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-[14px] font-semibold text-gray-200 mt-2.5 mb-1 select-text">
              {children}
            </h4>
          ),
          p: ({ children }) => (
            <p className="mb-2.5 text-[14px] font-normal leading-[1.65] text-gray-200 select-text">
              {children}
            </p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-white select-text">
              {children}
            </strong>
          ),
          b: ({ children }) => (
            <strong className="font-semibold text-white select-text">
              {children}
            </strong>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 space-y-1.5 my-2.5 text-[14px] font-normal text-gray-200 select-text">
              {children}
            </ul>
          ),
          ol: ({ children, start }) => (
            <ol start={start} className="list-decimal pl-5 space-y-1.5 my-2.5 text-[14px] font-normal text-gray-200 select-text">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="text-[14px] font-normal leading-[1.65] select-text">
              {children}
            </li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-blue-500/80 pl-3.5 py-1.5 my-2.5 bg-[#161922] rounded-r text-[14px] font-normal text-gray-300 italic select-text">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-3.5 border border-[#242834] rounded-xl shadow-md max-w-full">
              <table className="min-w-full divide-y divide-[#242834] text-left text-[14px] bg-[#161922]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-[#1c202c] text-white font-medium text-[13.5px]">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-[#242834]/60 font-normal">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-[#1f2432] transition-colors">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-3.5 py-2 font-medium text-[13.5px] text-gray-200 border-b border-[#242834] whitespace-nowrap">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3.5 py-2 text-[14px] font-normal text-gray-300 align-top">
              {children}
            </td>
          ),
          hr: () => (
            <hr className="my-4 border-t border-[#242834]" />
          ),
          code: ({ className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || "");
            const isMermaid = match && match[1] === "mermaid";
            if (isMermaid) {
              return (
                <div className="my-3 overflow-hidden rounded-xl border border-[#242834] bg-[#0d1017]">
                  <MermaidDiagram chart={String(children).replace(/\n$/, "")} isChat={isChat !== false} />
                </div>
              );
            }

            const isInline = !match && !String(children).includes("\n");
            if (isInline) {
              return (
                <code
                  className="px-1.5 py-0.5 rounded bg-[#1c202c] border border-[#2d3242] text-[#c9d1d9] font-mono text-[13px] font-normal inline-block mx-0.5 select-text"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            const rawCode = String(children).replace(/\n$/, "");
            const lang = match ? match[1] : "code";

            return (
              <div className="my-3 bg-[#0d1017] border border-[#242834] rounded-xl overflow-hidden font-mono text-[13px] shadow-sm">
                <div className="bg-[#161922] px-3.5 py-1.5 text-xs text-gray-400 border-b border-[#242834] flex items-center justify-between select-none">
                  <span className="font-mono text-[11px] text-gray-300">{lang}</span>
                  <CopyCodeButton code={rawCode} />
                </div>
                <pre className="p-3.5 overflow-x-auto text-gray-200 leading-relaxed font-mono text-[13px] font-normal select-text">
                  <code {...props}>{children}</code>
                </pre>
              </div>
            );
          },
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
});

MarkdownRenderer.displayName = "MarkdownRenderer";

export default MarkdownRenderer;
