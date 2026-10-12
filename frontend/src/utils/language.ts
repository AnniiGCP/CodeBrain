import type { FileNode } from "../types";

export interface LanguageInfo {
  id: string; // Monaco language ID
  name: string; // Human-friendly display name
  defaultTabSize: number;
  insertSpaces: boolean;
  category: "markup" | "stylesheet" | "script" | "config" | "data" | "compiled" | "documentation" | "other";
}

// Complete extension and special filename mapping to Monaco languages
const EXTENSION_MAP: Record<string, LanguageInfo> = {
  // YAML
  yml: { id: "yaml", name: "YAML", defaultTabSize: 2, insertSpaces: true, category: "config" },
  yaml: { id: "yaml", name: "YAML", defaultTabSize: 2, insertSpaces: true, category: "config" },

  // JSON & Data
  json: { id: "json", name: "JSON", defaultTabSize: 2, insertSpaces: true, category: "data" },
  jsonc: { id: "json", name: "JSON with Comments", defaultTabSize: 2, insertSpaces: true, category: "data" },
  toml: { id: "toml", name: "TOML", defaultTabSize: 2, insertSpaces: true, category: "config" },
  xml: { id: "xml", name: "XML", defaultTabSize: 2, insertSpaces: true, category: "markup" },
  svg: { id: "xml", name: "XML (SVG)", defaultTabSize: 2, insertSpaces: true, category: "markup" },

  // Python
  py: { id: "python", name: "Python", defaultTabSize: 4, insertSpaces: true, category: "script" },
  pyw: { id: "python", name: "Python", defaultTabSize: 4, insertSpaces: true, category: "script" },
  ipynb: { id: "json", name: "Jupyter Notebook", defaultTabSize: 2, insertSpaces: true, category: "data" },

  // TypeScript & JavaScript
  ts: { id: "typescript", name: "TypeScript", defaultTabSize: 2, insertSpaces: true, category: "script" },
  tsx: { id: "typescript", name: "TypeScript React", defaultTabSize: 2, insertSpaces: true, category: "script" },
  mts: { id: "typescript", name: "TypeScript", defaultTabSize: 2, insertSpaces: true, category: "script" },
  cts: { id: "typescript", name: "TypeScript", defaultTabSize: 2, insertSpaces: true, category: "script" },
  js: { id: "javascript", name: "JavaScript", defaultTabSize: 2, insertSpaces: true, category: "script" },
  jsx: { id: "javascript", name: "JavaScript React", defaultTabSize: 2, insertSpaces: true, category: "script" },
  mjs: { id: "javascript", name: "JavaScript", defaultTabSize: 2, insertSpaces: true, category: "script" },
  cjs: { id: "javascript", name: "JavaScript", defaultTabSize: 2, insertSpaces: true, category: "script" },

  // Markdown & Documentation
  md: { id: "markdown", name: "Markdown", defaultTabSize: 2, insertSpaces: true, category: "documentation" },
  markdown: { id: "markdown", name: "Markdown", defaultTabSize: 2, insertSpaces: true, category: "documentation" },
  mdx: { id: "markdown", name: "MDX", defaultTabSize: 2, insertSpaces: true, category: "documentation" },
  txt: { id: "plaintext", name: "Plain Text", defaultTabSize: 4, insertSpaces: true, category: "documentation" },
  log: { id: "plaintext", name: "Log", defaultTabSize: 4, insertSpaces: true, category: "documentation" },

  // Web
  html: { id: "html", name: "HTML", defaultTabSize: 2, insertSpaces: true, category: "markup" },
  htm: { id: "html", name: "HTML", defaultTabSize: 2, insertSpaces: true, category: "markup" },
  css: { id: "css", name: "CSS", defaultTabSize: 2, insertSpaces: true, category: "stylesheet" },
  scss: { id: "scss", name: "SCSS", defaultTabSize: 2, insertSpaces: true, category: "stylesheet" },
  sass: { id: "scss", name: "Sass", defaultTabSize: 2, insertSpaces: true, category: "stylesheet" },
  less: { id: "less", name: "Less", defaultTabSize: 2, insertSpaces: true, category: "stylesheet" },

  // Systems / Backend
  go: { id: "go", name: "Go", defaultTabSize: 4, insertSpaces: false, category: "compiled" },
  rs: { id: "rust", name: "Rust", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  java: { id: "java", name: "Java", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  c: { id: "c", name: "C", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  h: { id: "c", name: "C Header", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  cpp: { id: "cpp", name: "C++", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  cc: { id: "cpp", name: "C++", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  cxx: { id: "cpp", name: "C++", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  hpp: { id: "cpp", name: "C++ Header", defaultTabSize: 4, insertSpaces: true, category: "compiled" },
  cs: { id: "csharp", name: "C#", defaultTabSize: 4, insertSpaces: true, category: "compiled" },

  // Shell & Scripts
  sh: { id: "shell", name: "Shell Script", defaultTabSize: 2, insertSpaces: true, category: "script" },
  bash: { id: "shell", name: "Bash", defaultTabSize: 2, insertSpaces: true, category: "script" },
  zsh: { id: "shell", name: "Zsh", defaultTabSize: 2, insertSpaces: true, category: "script" },
  ps1: { id: "powershell", name: "PowerShell", defaultTabSize: 4, insertSpaces: true, category: "script" },
  bat: { id: "bat", name: "Batch", defaultTabSize: 4, insertSpaces: true, category: "script" },
  cmd: { id: "bat", name: "Batch", defaultTabSize: 4, insertSpaces: true, category: "script" },

  // Databases & Others
  sql: { id: "sql", name: "SQL", defaultTabSize: 2, insertSpaces: true, category: "data" },
  graphql: { id: "graphql", name: "GraphQL", defaultTabSize: 2, insertSpaces: true, category: "data" },
  gql: { id: "graphql", name: "GraphQL", defaultTabSize: 2, insertSpaces: true, category: "data" },
  ini: { id: "ini", name: "INI", defaultTabSize: 2, insertSpaces: true, category: "config" },
  conf: { id: "ini", name: "Configuration", defaultTabSize: 2, insertSpaces: true, category: "config" },
  dockerfile: { id: "dockerfile", name: "Dockerfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
};

// Exact filename matching
const FILENAME_MAP: Record<string, LanguageInfo> = {
  dockerfile: { id: "dockerfile", name: "Dockerfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  containerfile: { id: "dockerfile", name: "Dockerfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  makefile: { id: "makefile", name: "Makefile", defaultTabSize: 4, insertSpaces: false, category: "config" },
  gnumakefile: { id: "makefile", name: "Makefile", defaultTabSize: 4, insertSpaces: false, category: "config" },
  jenkinsfile: { id: "groovy", name: "Jenkinsfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  procfile: { id: "shell", name: "Procfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  gemfile: { id: "ruby", name: "Gemfile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  rakefile: { id: "ruby", name: "Rakefile", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".gitignore": { id: "ini", name: "Git Ignore", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".gitattributes": { id: "ini", name: "Git Attributes", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".gitmodules": { id: "ini", name: "Git Modules", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".editorconfig": { id: "ini", name: "EditorConfig", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".env": { id: "ini", name: "Dotenv", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".env.example": { id: "ini", name: "Dotenv Example", defaultTabSize: 2, insertSpaces: true, category: "config" },
  ".env.local": { id: "ini", name: "Dotenv Local", defaultTabSize: 2, insertSpaces: true, category: "config" },
  "package.json": { id: "json", name: "JSON (package.json)", defaultTabSize: 2, insertSpaces: true, category: "config" },
  "tsconfig.json": { id: "json", name: "JSON (tsconfig.json)", defaultTabSize: 2, insertSpaces: true, category: "config" },
  "pyproject.toml": { id: "toml", name: "TOML (pyproject.toml)", defaultTabSize: 4, insertSpaces: true, category: "config" },
  "requirements.txt": { id: "plaintext", name: "Python Requirements", defaultTabSize: 4, insertSpaces: true, category: "config" },
  "cargo.toml": { id: "toml", name: "TOML (Cargo.toml)", defaultTabSize: 4, insertSpaces: true, category: "config" },
  "go.mod": { id: "go", name: "Go Module", defaultTabSize: 4, insertSpaces: false, category: "config" },
  "docker-compose.yml": { id: "yaml", name: "YAML (Compose)", defaultTabSize: 2, insertSpaces: true, category: "config" },
  "docker-compose.yaml": { id: "yaml", name: "YAML (Compose)", defaultTabSize: 2, insertSpaces: true, category: "config" },
};

/**
 * Detect language information from a file path
 */
export function getLanguageInfo(filePath?: string): LanguageInfo {
  if (!filePath) {
    return { id: "plaintext", name: "Plain Text", defaultTabSize: 4, insertSpaces: true, category: "other" };
  }

  const cleanPath = filePath.replace(/\\/g, "/");
  const fileName = cleanPath.split("/").pop() || cleanPath;
  const lowerName = fileName.toLowerCase();

  // 1. Exact filename check
  if (FILENAME_MAP[lowerName]) {
    return FILENAME_MAP[lowerName];
  }

  // 2. Special prefix checks (e.g., .env.*, Dockerfile.*)
  if (lowerName.startsWith(".env.")) {
    return { id: "ini", name: "Dotenv", defaultTabSize: 2, insertSpaces: true, category: "config" };
  }
  if (lowerName.startsWith("dockerfile.")) {
    return { id: "dockerfile", name: "Dockerfile", defaultTabSize: 2, insertSpaces: true, category: "config" };
  }

  // 3. Extension check
  const ext = lowerName.split(".").pop();
  if (ext && EXTENSION_MAP[ext]) {
    return EXTENSION_MAP[ext];
  }

  // 4. Default fallback
  return { id: "plaintext", name: "Plain Text", defaultTabSize: 4, insertSpaces: true, category: "other" };
}

/**
 * Returns Monaco language ID for a file path
 */
export function detectLanguage(filePath?: string): string {
  return getLanguageInfo(filePath).id;
}

/**
 * Returns human-friendly display name for the status bar
 */
export function getLanguageDisplayName(filePath?: string, overrideLanguageId?: string): string {
  if (filePath) {
    return getLanguageInfo(filePath).name;
  }
  if (overrideLanguageId) {
    const match = Object.values(EXTENSION_MAP).find((info) => info.id === overrideLanguageId);
    if (match) return match.name;
    return overrideLanguageId.toUpperCase();
  }
  return "Plain Text";
}

/**
 * Detect default or content-driven indentation
 */
export function detectIndentation(filePath?: string, content?: string): { tabSize: number; insertSpaces: boolean } {
  const info = getLanguageInfo(filePath);

  if (content) {
    const lines = content.split("\n").slice(0, 100);
    let space2Count = 0;
    let space4Count = 0;
    let tabCount = 0;

    for (const line of lines) {
      if (line.startsWith("\t")) tabCount++;
      else if (line.startsWith("    ") && !line.startsWith("      ")) space4Count++;
      else if (line.startsWith("  ") && !line.startsWith("    ")) space2Count++;
    }

    if (tabCount > space2Count && tabCount > space4Count) {
      return { tabSize: 4, insertSpaces: false };
    }
    if (space4Count > space2Count && space4Count > 2) {
      return { tabSize: 4, insertSpaces: true };
    }
    if (space2Count > space4Count && space2Count > 2) {
      return { tabSize: 2, insertSpaces: true };
    }
  }

  return { tabSize: info.defaultTabSize, insertSpaces: info.insertSpaces };
}

/**
 * Detect normalized project technology stack from file tree and meta summary
 */
export function detectProjectTechStack(
  fileTree: FileNode[],
  metaSummary?: { total_files?: number | null; language_dist?: Record<string, number> | null } | null
): {
  primaryLanguage: string;
  frameworks: string[];
  tools: string[];
  summary: string;
} {
  const allPaths: string[] = [];
  const collectPaths = (nodes: FileNode[]) => {
    for (const node of nodes) {
      if (node.path) allPaths.push(node.path.replace(/\\/g, "/").toLowerCase());
      if (node.children) collectPaths(node.children);
    }
  };
  collectPaths(fileTree);

  const frameworks: string[] = [];
  const tools: string[] = [];

  // Inspect manifest files & extensions
  const hasRequirements = allPaths.some((p) => p.endsWith("requirements.txt") || p.endsWith("pyproject.toml"));
  const hasPackageJson = allPaths.some((p) => p.endsWith("package.json"));
  const hasDocker = allPaths.some((p) => p.includes("dockerfile") || p.includes("docker-compose"));
  const hasGithubActions = allPaths.some((p) => p.includes(".github/workflows"));
  const hasAlembic = allPaths.some((p) => p.includes("alembic") || p.includes("migrations"));
  const hasPostgres = allPaths.some((p) => p.includes("postgres") || p.includes("psycopg") || p.includes("alembic.ini"));
  const hasFastAPI = allPaths.some((p) => p.includes("fastapi") || p.includes("main.py") || p.includes("uvicorn"));
  const hasVite = allPaths.some((p) => p.includes("vite.config"));
  const hasReact = allPaths.some((p) => p.endsWith(".tsx") || p.endsWith(".jsx"));

  if (hasFastAPI) frameworks.push("FastAPI");
  if (hasReact) frameworks.push("React");
  if (hasAlembic || hasPostgres) frameworks.push("PostgreSQL / SQLAlchemy");
  if (hasDocker) tools.push("Docker");
  if (hasGithubActions) tools.push("GitHub Actions");
  if (hasVite) tools.push("Vite");

  // Determine primary language from metaSummary or file extensions
  let primaryLanguage = "Unknown";
  if (metaSummary?.language_dist && Object.keys(metaSummary.language_dist).length > 0) {
    const sorted = Object.entries(metaSummary.language_dist).sort((a, b) => b[1] - a[1]);
    const top = sorted[0][0];
    primaryLanguage = top.charAt(0).toUpperCase() + top.slice(1);
  } else if (hasRequirements) {
    primaryLanguage = "Python";
  } else if (hasPackageJson) {
    primaryLanguage = allPaths.some((p) => p.endsWith(".ts") || p.endsWith(".tsx")) ? "TypeScript" : "JavaScript";
  }

  const stackParts = [primaryLanguage, ...frameworks.slice(0, 2), ...tools.slice(0, 1)].filter(Boolean);
  const summary = stackParts.join(" • ") || primaryLanguage;

  return {
    primaryLanguage,
    frameworks,
    tools,
    summary,
  };
}
