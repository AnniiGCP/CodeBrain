export interface ChangedFileItem {
  path: string;
  name: string;
  linesAdded: number;
  linesDeleted: number;
  diff: string;
  stage?: string;
}

/**
 * Parses unified diff text into individual changed file summaries.
 * Handles both single-file diffs and multi-file diffs cleanly.
 */
export function parseDiffFiles(diffText: string, defaultPath: string = ""): ChangedFileItem[] {
  if (!diffText || !diffText.trim()) return [];
  const files: ChangedFileItem[] = [];
  const lines = diffText.split(/\r?\n/);

  let currentOrig = "";
  let currentTarget = "";
  let currentHunkLines: string[] = [];
  let currentAdded = 0;
  let currentDeleted = 0;

  const flush = () => {
    if (currentTarget || currentOrig) {
      const filePath = currentTarget || currentOrig || defaultPath;
      const cleanPath = filePath.replace(/^[ab]\//, "").trim();
      const fileName = cleanPath.split(/[/\\]/).pop() || cleanPath;
      files.push({
        path: cleanPath,
        name: fileName,
        linesAdded: currentAdded,
        linesDeleted: currentDeleted,
        diff: currentHunkLines.join("\n"),
      });
    }
    currentOrig = "";
    currentTarget = "";
    currentHunkLines = [];
    currentAdded = 0;
    currentDeleted = 0;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("--- ")) {
      flush();
      currentOrig = line.slice(4).trim().split("\t")[0];
      currentHunkLines.push(line);
    } else if (line.startsWith("+++ ")) {
      currentTarget = line.slice(4).trim().split("\t")[0];
      currentHunkLines.push(line);
    } else {
      currentHunkLines.push(line);
      if (line.startsWith("+") && !line.startsWith("+++")) {
        currentAdded++;
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        currentDeleted++;
      }
    }
  }
  flush();

  if (files.length === 0 && defaultPath) {
    let added = 0;
    let deleted = 0;
    for (const l of lines) {
      if (l.startsWith("+") && !l.startsWith("+++")) added++;
      if (l.startsWith("-") && !l.startsWith("---")) deleted++;
    }
    const cleanPath = defaultPath.replace(/^[ab]\//, "").trim();
    files.push({
      path: cleanPath,
      name: cleanPath.split(/[/\\]/).pop() || cleanPath,
      linesAdded: added,
      linesDeleted: deleted,
      diff: diffText,
    });
  }

  return files;
}
