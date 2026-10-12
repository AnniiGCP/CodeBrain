export const CODEBRAIN_THEME_NAME = "codebrain-dark";

/**
 * Register the CodeBrain Dark theme with Monaco Editor
 * Perfectly matches the obsidian workspace color palette (#12151c, #161922, #242834)
 */
export function registerCodeBrainTheme(monaco: any) {
  if (!monaco?.editor) return;

  monaco.editor.defineTheme(CODEBRAIN_THEME_NAME, {
    base: "vs-dark",
    inherit: true,
    colors: {
      // Workspace and Gutter alignment (Neutral Near-Black)
      "editor.background": "#0c0d0e",
      "editorGutter.background": "#0c0d0e",
      "editorLineNumber.foreground": "#484f58",
      "editorLineNumber.activeForeground": "#e6edf3",

      // Line Highlight & Cursor
      "editor.lineHighlightBackground": "#141518",
      "editor.lineHighlightBorder": "#1f243000",
      "editorCursor.foreground": "#c084fc",

      // Selection & Highlights
      "editor.selectionBackground": "#2b283888",
      "editor.inactiveSelectionBackground": "#1f1d2866",
      "editor.selectionHighlightBackground": "#25213666",
      "editor.wordHighlightBackground": "#2a243d66",
      "editor.wordHighlightStrongBackground": "#332a4e88",

      // Whitespace & Guides
      "editorWhitespace.foreground": "#222329",
      "editorIndentGuide.background1": "#18191e",
      "editorIndentGuide.activeBackground1": "#2d2f38",
      "editorRuler.foreground": "#1a1b20",

      // Scrollbar & Minimap
      "scrollbarSlider.background": "#22232a66",
      "scrollbarSlider.hoverBackground": "#2b2c36aa",
      "scrollbarSlider.activeBackground": "#3b3d4add",
      "minimap.background": "#0c0d0e",
      "minimapGutter.background": "#0c0d0e",
      "minimap.selectionHighlight": "#332a4eaa",

      // Popups, Suggestions & Overlays
      "editorWidget.background": "#141518",
      "editorWidget.border": "#1e1f23",
      "editorSuggestWidget.background": "#141518",
      "editorSuggestWidget.border": "#1e1f23",
      "editorSuggestWidget.foreground": "#c9d1d9",
      "editorSuggestWidget.selectedBackground": "#1e2028",
      "editorSuggestWidget.highlightForeground": "#c084fc",
      "editorHoverWidget.background": "#141518",
      "editorHoverWidget.border": "#1e1f23",
      "peekView.border": "#8b5cf6",
      "peekViewEditor.background": "#0c0d0e",
      "peekViewResult.background": "#141518",
      "peekViewTitle.background": "#0e0f11",
    },
    rules: [
      // ── YAML Rules ──
      { token: "type.yaml", foreground: "7ee787" },
      { token: "key.yaml", foreground: "79c0ff", fontStyle: "bold" },
      { token: "string.yaml", foreground: "a5d6ff" },
      { token: "number.yaml", foreground: "79c0ff" },
      { token: "comment.yaml", foreground: "8b949e", fontStyle: "italic" },
      { token: "keyword.yaml", foreground: "ff7b72" },
      { token: "delimiter.yaml", foreground: "d2a8ff" },

      // ── JSON Rules ──
      { token: "string.key.json", foreground: "79c0ff", fontStyle: "bold" },
      { token: "string.value.json", foreground: "a5d6ff" },
      { token: "number.json", foreground: "79c0ff" },
      { token: "keyword.json", foreground: "ff7b72" },
      { token: "delimiter.json", foreground: "8b949e" },

      // ── Python Rules ──
      { token: "keyword.python", foreground: "ff7b72" },
      { token: "keyword.def.python", foreground: "ff7b72", fontStyle: "bold" },
      { token: "identifier.python", foreground: "e6edf3" },
      { token: "string.python", foreground: "a5d6ff" },
      { token: "comment.python", foreground: "8b949e", fontStyle: "italic" },
      { token: "number.python", foreground: "79c0ff" },
      { token: "type.python", foreground: "ffa657" },

      // ── TypeScript & JavaScript Rules ──
      { token: "keyword.ts", foreground: "ff7b72" },
      { token: "keyword.tsx", foreground: "ff7b72" },
      { token: "keyword.js", foreground: "ff7b72" },
      { token: "type.ts", foreground: "ffa657" },
      { token: "type.tsx", foreground: "ffa657" },
      { token: "string.ts", foreground: "a5d6ff" },
      { token: "string.tsx", foreground: "a5d6ff" },
      { token: "string.js", foreground: "a5d6ff" },
      { token: "comment.ts", foreground: "8b949e", fontStyle: "italic" },
      { token: "comment.tsx", foreground: "8b949e", fontStyle: "italic" },
      { token: "comment.js", foreground: "8b949e", fontStyle: "italic" },
      { token: "tag.tsx", foreground: "7ee787" },
      { token: "tag.jsx", foreground: "7ee787" },

      // ── Markdown Rules ──
      { token: "strong", fontStyle: "bold", foreground: "ffa657" },
      { token: "emphasis", fontStyle: "italic", foreground: "a5d6ff" },
      { token: "keyword.md", foreground: "ff7b72" },
      { token: "string.link.md", foreground: "58a6ff" },

      // ── General Fallback Syntax Rules ──
      { token: "keyword", foreground: "ff7b72" },
      { token: "string", foreground: "a5d6ff" },
      { token: "comment", foreground: "8b949e", fontStyle: "italic" },
      { token: "number", foreground: "79c0ff" },
      { token: "type", foreground: "ffa657" },
      { token: "delimiter", foreground: "c9d1d9" },
      { token: "operator", foreground: "79c0ff" },
    ],
  });
}
