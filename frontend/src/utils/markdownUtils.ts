/**
 * Preprocess and normalize raw LLM markdown output to ensure:
 * 1. Headings have space after hashes (`##Heading` -> `## Heading`)
 * 2. Headings jammed against text on the same line are separated
 * 3. Headings glued to divider dashes (`---##`) are properly separated
 * 4. Jammed tables starting directly after headings are separated
 * 5. Table rows concatenated with `||` without newlines are split into separate lines
 * 6. Jammed mermaid diagrams without newlines (````mermaidgraph`) are separated
 * 7. Dangling unclosed code fences during streaming are safely closed for live preview
 */
export function normalizeMarkdown(raw: string): string {
  if (!raw) return "";

  let text = raw;

  // 1. Separate divider dashes glued to headings: e.g. `---##` or `text---##`
  text = text.replace(/([^\n])---(#{1,6})/g, "$1\n\n---\n\n$2");
  text = text.replace(/^---(#{1,6})/gm, "---\n\n$1");

  // 2. Separate headings that are glued to preceding text without newlines (e.g. `text## 2.`), NOT between hashes
  text = text.replace(/([^\n#])(#{1,6}\s+)/g, "$1\n\n$2");

  // 3. Separate table starting directly on same line as heading: e.g. `## 3. Component Responsibilities| Component` -> `## 3. Component Responsibilities\n\n| Component`
  text = text.replace(/(#{1,6}\s+[^|\n]+?)\s*(\|)/g, "$1\n\n$2");

  // 4. Split table rows that have `||` without newline into separate lines: e.g. `| col1 | col2 ||---|---|| row1 |`
  text = text.replace(/\|\s*\|(?=[ -`\w:])/g, "|\n|");

  // 5. Separate jammed headings like `## 1. OverviewQuizGenAI` -> `## 1. Overview\n\nQuizGenAI`
  text = text.replace(/^(#{1,6}\s+(?:\d+\.\s*)?[A-Za-z0-9\s\-/&]+?(?:Overview|Architecture|Responsibilities|Flow|Details|Security|Testing|Limitations|Summary|Cause|Evidence|Fix|Validation|Notes))([A-Z*`\-])/gm, "$1\n\n$2");

  // 6. Ensure space after heading hashes e.g. `##High-Level` -> `## High-Level`
  text = text.replace(/^(#{1,6})([^\s#])/gm, "$1 $2");

  // 7. Ensure newline after ```mermaid before graph/diagram syntax: e.g. ````mermaidgraph TD` -> ````mermaid\ngraph TD`
  text = text.replace(/```mermaid([A-Za-z])/g, "```mermaid\n$1");

  // 8. Separate backticks stuck right after heading title e.g. `Architecture``` -> `Architecture\n\n```
  text = text.replace(/(#{1,6}\s+[^\n`]+?)`{2,3}/g, "$1\n\n```");

  // 9. If raw mermaid syntax appears without code fences (e.g. `mermaidsequenceDiagram ...` or `sequenceDiagram\nparticipant...`)
  text = text.replace(/`?mermaid(sequenceDiagram|flowchart|graph\s+[A-Za-z]+|classDiagram|erDiagram)[\s\S]*?`?/gi, (match) => {
    if (match.startsWith("```mermaid")) return match;
    const inner = match.replace(/^`?mermaid/i, "").replace(/`+$/, "").trim();
    return `\n\`\`\`mermaid\n${inner}\n\`\`\`\n`;
  });

  // 10. Ensure numbered lists jammed against colons or letters get clean linebreaks e.g. `boundaries are:1. Client` -> `boundaries are:\n\n1. Client`
  text = text.replace(/([a-zA-Z_\):])(\d+\.\s+[A-Z])/g, "$1\n\n$2");

  // 11. Handle dangling backtick count: if text ends with an unclosed triple fence, close it for live preview
  const fenceMatches = text.match(/```/g);
  if (fenceMatches && fenceMatches.length % 2 !== 0) {
    text = `${text}\n\`\`\``;
  }

  return text;
}
