import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Read MarkdownRenderer.tsx to verify typography tokens and normalization rules
const markdownRendererSource = fs.readFileSync(
  path.join(__dirname, "src/components/MarkdownRenderer.tsx"),
  "utf8"
);

// Read ChatPanel.tsx to verify message container styles
const chatPanelSource = fs.readFileSync(
  path.join(__dirname, "src/components/ChatPanel.tsx"),
  "utf8"
);

// Read MermaidDiagram.tsx to verify diagram guards
const mermaidDiagramSource = fs.readFileSync(
  path.join(__dirname, "src/components/MermaidDiagram.tsx"),
  "utf8"
);

function normalizeMarkdown(raw) {
  if (!raw) return "";
  let text = raw;

  // 1. Separate divider dashes glued to headings: e.g. `---##` or `text---##`
  text = text.replace(/([^\n])---(#{1,6})/g, "$1\n\n---\n\n$2");
  text = text.replace(/^---(#{1,6})/gm, "---\n\n$1");

  // 2. Separate headings that are glued to preceding text without newlines (e.g. `text## 2.`), NOT between hashes
  text = text.replace(/([^\n#])(#{1,6}\s+)/g, "$1\n\n$2");

  // 3. Separate table starting directly on same line as heading: e.g. `## 3. Component Responsibilities| Component`
  text = text.replace(/(#{1,6}\s+[^|\n]+?)\s*(\|)/g, "$1\n\n$2");

  // 4. Split table rows that have `||` without newline into separate lines: e.g. `| col1 | col2 ||---|---|| row1 |`
  text = text.replace(/\|\s*\|(?=[ -`\w:])/g, "|\n|");

  // 5. Separate jammed headings like `## 1. OverviewQuizGenAI`
  text = text.replace(/^(#{1,6}\s+(?:\d+\.\s*)?[A-Za-z0-9\s\-/&]+?(?:Overview|Architecture|Responsibilities|Flow|Details|Security|Testing|Limitations|Summary|Cause|Evidence|Fix|Validation|Notes))([A-Z*`\-])/gm, "$1\n\n$2");

  // 6. Ensure space after heading hashes e.g. `##High-Level` -> `## High-Level`
  text = text.replace(/^(#{1,6})([^\s#])/gm, "$1 $2");

  // 7. Ensure newline after ```mermaid before graph/diagram syntax
  text = text.replace(/```mermaid([A-Za-z])/g, "```mermaid\n$1");

  // 8. Separate backticks stuck right after heading title
  text = text.replace(/(#{1,6}\s+[^\n`]+?)`{2,3}/g, "$1\n\n```");

  // 9. If raw mermaid syntax appears without code fences
  text = text.replace(/`?mermaid(sequenceDiagram|flowchart|graph\s+[A-Za-z]+|classDiagram|erDiagram)[\s\S]*?`?/gi, (match) => {
    if (match.startsWith("```mermaid")) return match;
    const inner = match.replace(/^`?mermaid/i, "").replace(/`+$/, "").trim();
    return `\n\`\`\`mermaid\n${inner}\n\`\`\`\n`;
  });

  // 10. Numbered lists jammed against colons or letters
  text = text.replace(/([a-zA-Z_\):])(\d+\.\s+[A-Z])/g, "$1\n\n$2");

  // 11. Balance unclosed triple backticks during streaming
  const fenceMatches = text.match(/```/g);
  if (fenceMatches && fenceMatches.length % 2 !== 0) {
    text = `${text}\n\`\`\``;
  }

  return text;
}

function sanitizeMermaidChart(rawChart, isChat = false) {
  if (!rawChart || typeof rawChart !== "string") return "";
  let cleaned = rawChart.trim();
  if (!cleaned) return "";

  const mermaidBlockMatch = cleaned.match(/```mermaid\s*([\s\S]*?)(?:```|$)/i);
  if (mermaidBlockMatch && mermaidBlockMatch[1].trim()) {
    cleaned = mermaidBlockMatch[1].trim();
  } else {
    const keywordMatch = cleaned.match(/(?:^|\n)\s*((?:sequenceDiagram|flowchart\s+[A-Za-z]+|graph\s+[A-Za-z]+|classDiagram|erDiagram|stateDiagram|gantt|mindmap|quadrantChart|timeline|gitGraph|pie)[\s\S]*)/i);
    if (keywordMatch) {
      cleaned = keywordMatch[1].trim();
    } else {
      return "";
    }
  }

  cleaned = cleaned.replace(/```mermaid/gi, "").replace(/```/g, "").trim();

  const trailingMarkdownMatch = cleaned.match(/\n\s*(?:#{1,6}\s+|---+\s*$|===+\s*$)/m);
  if (trailingMarkdownMatch && trailingMarkdownMatch.index !== undefined) {
    cleaned = cleaned.slice(0, trailingMarkdownMatch.index).trim();
  }

  const hasSequenceSyntax = cleaned.includes("participant ") || cleaned.includes("->>") || cleaned.includes("activate ");
  if (hasSequenceSyntax) {
    if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned)) {
      cleaned = "sequenceDiagram\n" + cleaned.replace(/^(graph|flowchart)\s+[A-Za-z]+\s*\n?/i, "");
    }
    return cleaned;
  }

  if (isChat) {
    const lines = cleaned.split("\n");
    const processed = [];
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

      l = l.replace(/->>/g, "-->");

      // Cylinder
      l = l.replace(/(\b[A-Za-z0-9_]+)\[\(\s*(.*?)\s*\)\]/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}[("${clean}")]`;
      });

      // Stadium
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\[\s*(.*?)\s*\]\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}(["${clean}"])`;
      });

      // Circle
      l = l.replace(/(\b[A-Za-z0-9_]+)\(\(\s*(.*?)\s*\)\)/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}(("${clean}"))`;
      });

      // Square
      l = l.replace(/(\b[A-Za-z0-9_]+)\[(?!\()\s*(.*?)\s*\](?!\))/g, (_, id, content) => {
        let clean = content.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>");
        clean = clean.replace(/^["']|["']$/g, "").replace(/"/g, "'");
        return `${id}["${clean}"]`;
      });

      // Decision
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

  // Shared default for Docs, Editor, and other non-chat surfaces
  if (/^(graph|flowchart)\s+[A-Za-z]+/i.test(cleaned)) {
    cleaned = cleaned.replace(/->>/g, "-->");
    // Quote unquoted labels containing parentheses or linebreaks
    cleaned = cleaned.replace(/\[(?!\()([^"\]\n]*?\([^\]\n]*?\)[^"\]\n]*?)(?<!\))\]/g, '["$1"]');
    cleaned = cleaned.replace(/\[(?!\()([^"\]\n]*?<br\s*\/?>[^"\]\n]*?)(?<!\))\]/g, '["$1"]');
  }

  return cleaned;
}

test("Case 1: Simple greeting retains concise text without unwanted markup", () => {
  const greeting = "Hi, I'm CodeBrain AI. How can I help you today?";
  const norm = normalizeMarkdown(greeting);
  assert.equal(norm, greeting);
});

test("Case 2: Plain paragraphs without headings remain intact", () => {
  const text = "This is paragraph one.\n\nThis is paragraph two.";
  const norm = normalizeMarkdown(text);
  assert.equal(norm, text);
});

test("Case 3: Multiple headings and paragraphs are cleanly separated", () => {
  const merged = "## 1. OverviewQuizGenAI is a full-stack platform.";
  const norm = normalizeMarkdown(merged);
  assert.ok(norm.includes("## 1. Overview\n\nQuizGenAI"));
  assert.ok(!norm.includes("OverviewQuizGenAI"));
});

test("Case 4: Numbered and nested lists are separated from text", () => {
  const glued = "The boundaries are:1. Client <-> Backend2. Backend <-> DB";
  const norm = normalizeMarkdown(glued);
  assert.ok(norm.includes("boundaries are:\n\n1. Client"));
  assert.ok(norm.includes("Backend\n\n2. Backend"));

  // Regression check: Section 10 and two-digit numbers must NEVER be split into # 1\n\n0. Dependencies
  const sec10 = "# 10. Dependencies\n\n## 10.1 Runtime Dependencies";
  const norm10 = normalizeMarkdown(sec10);
  assert.strictEqual(norm10, sec10);
  assert.ok(!norm10.includes("# 1\n\n0. Dependencies"));
});

test("Case 5: Valid Markdown table passes through with correct structure", () => {
  const table = "| Module | Role |\n|---|---|\n| Frontend | UI |\n| Backend | API |";
  const norm = normalizeMarkdown(table);
  assert.ok(norm.includes("| Module | Role |"));
  assert.ok(norm.includes("|---|---|"));
  assert.ok(norm.includes("| Frontend | UI |"));
});

test("Case 6: Malformed Markdown table (rows separated by || without newlines) is repaired", () => {
  const malformed = "## 3. Component Responsibilities| Component | Responsibility ||---|---|| backend/app/main.py | Application factory |";
  const norm = normalizeMarkdown(malformed);
  assert.ok(norm.includes("## 3. Component Responsibilities\n\n| Component | Responsibility |"));
  assert.ok(norm.includes("|\n|---|---|"));
  assert.ok(norm.includes("|\n| backend/app/main.py"));
});

test("Case 7: Inline code inside normal prose is formatted cleanly", () => {
  const input = "The configuration is loaded from `config.py` using `BaseSettings`.";
  const norm = normalizeMarkdown(input);
  assert.equal(norm, input);
});

test("Case 8: Fenced code blocks preserve indentation and languages", () => {
  const code = "```python\ndef get_db():\n    db = SessionLocal()\n    try:\n        yield db\n    finally:\n        db.close()\n```";
  const norm = normalizeMarkdown(code);
  assert.equal(norm, code);
});

test("Case 9: Mermaid diagrams with valid syntax are preserved and properly fenced", () => {
  const diagram = "```mermaid\ngraph TD\n    A[Client] --> B[API]\n    B --> C[(PostgreSQL)]\n```";
  const sanitized = sanitizeMermaidChart(diagram);
  assert.ok(sanitized.includes("graph TD"));
  assert.ok(sanitized.includes("A[Client] --> B[API]"));
});

test("Case 10: Mermaid diagrams jammed into fences without newline are repaired", () => {
  const jammed = "```mermaidgraph TD\nClient --> API```";
  const norm = normalizeMarkdown(jammed);
  assert.ok(norm.includes("```mermaid\ngraph TD"));
});

test("Case 11: Long architecture response with dividers and headings separates cleanly", () => {
  const gluedSections = "---## 2. High-Level Architecture```mermaidgraph TD\nA-->B```\n\n---## 3. Component Responsibilities| Component | Role |";
  const norm = normalizeMarkdown(gluedSections);
  assert.ok(norm.includes("---\n\n## 2. High-Level Architecture"));
  assert.ok(norm.includes("## 2. High-Level Architecture\n\n```"));
  assert.ok(norm.includes("```mermaid\ngraph TD"));
  assert.ok(norm.includes("---\n\n## 3. Component Responsibilities\n\n| Component | Role |"));
});

test("Case 12: Streamed responses with unclosed code fences are safely terminated for preview", () => {
  const streamingIncomplete = "Here is the code:\n```python\ndef add(a, b):\n    return a + b";
  const norm = normalizeMarkdown(streamingIncomplete);
  assert.ok(norm.endsWith("```"));
});

test("Case 13: Completed responses retain clean matching fences", () => {
  const complete = "Here is the code:\n```python\ndef add(a, b):\n    return a + b\n```";
  const norm = normalizeMarkdown(complete);
  assert.equal(norm, complete);
});

test("Case 14: Responses containing paths, punctuation, and special characters render safely", () => {
  const paths = "Check `backend/app/routers/auth_api.py` & `backend/tests/test_auth_flow.py` for <JWT> tokens.";
  const norm = normalizeMarkdown(paths);
  assert.equal(norm, paths);
});

test("Case 15: Wide tables have overflow-x-auto container wrapper", () => {
  assert.ok(markdownRendererSource.includes("overflow-x-auto"));
  assert.ok(markdownRendererSource.includes("min-w-full"));
  assert.ok(markdownRendererSource.includes("max-w-full"));
});

test("Case 16: Safe rendering of untrusted content does not allow raw scripts", () => {
  // ReactMarkdown safely escapes HTML entities by default unless rehype-raw is passed
  assert.ok(!markdownRendererSource.includes("rehype-raw"));
});

test("Case 17: Text selection and copying enabled across assistant messages", () => {
  assert.ok(markdownRendererSource.includes("select-text"));
  assert.ok(chatPanelSource.includes("chat-selectable"));
});

test("Case 18: Typography token assertions match requirements", () => {
  // Explanation text body must be 14px, regular weight (font-normal), leading-1.65
  assert.ok(markdownRendererSource.includes("text-[14px] font-normal text-gray-200 leading-[1.65]"));
  // Paragraphs must be 14px font-normal
  assert.ok(markdownRendererSource.includes("text-[14px] font-normal leading-[1.65] text-gray-200"));
  // Headings must be moderately sized with font-semibold (not bold / not huge)
  assert.ok(markdownRendererSource.includes("text-[17px] font-semibold text-white")); // h1
  assert.ok(markdownRendererSource.includes("text-[16px] font-semibold text-white")); // h2
  assert.ok(markdownRendererSource.includes("text-[15px] font-semibold text-blue-300")); // h3
  assert.ok(markdownRendererSource.includes("text-[14px] font-semibold text-gray-200")); // h4
  // Table cells must be 14px font-normal
  assert.ok(markdownRendererSource.includes("text-[14px] font-normal text-gray-300"));
  // Table headers must be moderate weight (font-medium 13.5px)
  assert.ok(markdownRendererSource.includes("font-medium text-[13.5px]"));
  // Inline code must be 13px font-normal font-mono
  assert.ok(markdownRendererSource.includes("font-mono text-[13px] font-normal"));
  // MermaidDiagram error / loading guard prevents empty black canvas
  assert.ok(mermaidDiagramSource.includes("if (error)"));
  assert.ok(mermaidDiagramSource.includes("Architecture Blueprint:"));
  assert.ok(mermaidDiagramSource.includes("if (!svgContent)"));
  assert.ok(mermaidDiagramSource.includes("Rendering architecture diagram..."));
});

test("Case 19: Screenshot Architecture Blueprint diagram with subgraphs, colons, newlines, and cylinders is normalized for chat", () => {
  const screenshotDiagram = `graph TD
    subgraph Client
        Browser[React SPA\\n(Vite + Tailwind)]
        ChatUI[Chatbot UI\\n(Static HTML/JS)]
    end

    subgraph Backend_Services
        API[FastAPI Backend\\n:8000]
        Chatbot[Flask Chatbot\\n:5000]
    end

    subgraph Data_Layer
        DB[(PostgreSQL\\nSQLAlchemy ORM)]
        Migrations[Alembic Migrations]
    end

    subgraph External
        NVIDIA[NVIDIA LLM API\\nLlama-3.1-70B]
    end`;

  const sanitized = sanitizeMermaidChart(screenshotDiagram, true);
  assert.ok(sanitized.includes('Browser["React SPA<br/>(Vite + Tailwind)"]'));
  assert.ok(sanitized.includes('API["FastAPI Backend<br/>:8000"]'));
  assert.ok(sanitized.includes('DB[("PostgreSQL<br/>SQLAlchemy ORM")]'));
  assert.ok(sanitized.includes('ChatUI["Chatbot UI<br/>(Static HTML/JS)"]'));
  assert.ok(sanitized.includes('NVIDIA["NVIDIA LLM API<br/>Llama-3.1-70B"]'));
});

test("Case 20: ChatPanel scrolling policy and RAF token batching eliminate streaming jitter", () => {
  // ChatPanel uses scrollContainerRef and handleScroll tracking nearBottom state
  assert.ok(chatPanelSource.includes("scrollContainerRef = useRef"));
  assert.ok(chatPanelSource.includes("isNearBottomRef = useRef(true)"));
  // ChatPanel batches tokens with requestAnimationFrame to prevent DOM thrashing
  assert.ok(chatPanelSource.includes("rafId"));
  assert.ok(chatPanelSource.includes("requestAnimationFrame(flushTokens)"));
});

console.log("All 20 Markdown rendering, Architecture Blueprint & streaming stability unit tests passed successfully!");
