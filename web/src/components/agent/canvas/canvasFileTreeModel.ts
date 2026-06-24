import type { Artifact } from '@/types/agent';

export type CanvasFileSource = 'sandbox' | 'artifacts';
export type CanvasFileNodeKind = 'directory' | 'file';

export interface CanvasFileNode {
  id: string;
  source: CanvasFileSource;
  kind: CanvasFileNodeKind;
  name: string;
  path: string;
  children: CanvasFileNode[];
  artifact?: Artifact | undefined;
}

export interface CanvasFileOpenRequest {
  source: CanvasFileSource;
  path: string;
  name: string;
  artifact?: Artifact | undefined;
}

interface MutableCanvasFileNode extends CanvasFileNode {
  children: MutableCanvasFileNode[];
}

const SANDBOX_ROOT = '/workspace';

function normalizeSandboxPath(path: string, rootPath = SANDBOX_ROOT): string {
  const trimmed = path.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith(`${rootPath}/`) || trimmed === rootPath) return trimmed;
  if (trimmed.startsWith('/')) return trimmed;
  return `${rootPath}/${trimmed}`;
}

function splitDisplayPath(path: string, rootPath?: string): string[] {
  const normalizedRoot = rootPath?.replace(/\/+$/, '');
  const withoutRoot =
    normalizedRoot && path.startsWith(`${normalizedRoot}/`)
      ? path.slice(normalizedRoot.length + 1)
      : path.replace(/^\/+/, '');
  return withoutRoot
    .split('/')
    .map((part) => part.trim())
    .filter(Boolean);
}

function isUsableGlobLine(line: string): boolean {
  const trimmed = line.trim();
  return (
    trimmed.length > 0 &&
    !trimmed.startsWith('Error:') &&
    !trimmed.startsWith('Hint:') &&
    !trimmed.startsWith('Suggestions:') &&
    !trimmed.startsWith('No files found matching:') &&
    !trimmed.startsWith('...') &&
    !trimmed.includes(' more files')
  );
}

export function parseSandboxGlobPaths(globText: string, rootPath = SANDBOX_ROOT): string[] {
  const seen = new Set<string>();
  const paths: string[] = [];

  for (const line of globText.split('\n')) {
    if (!isUsableGlobLine(line)) continue;
    const normalized = normalizeSandboxPath(line, rootPath);
    if (!normalized || normalized === rootPath || seen.has(normalized)) continue;
    seen.add(normalized);
    paths.push(normalized);
  }

  return paths;
}

function ensureDirectory(
  siblings: MutableCanvasFileNode[],
  params: {
    id: string;
    source: CanvasFileSource;
    name: string;
    path: string;
  }
): MutableCanvasFileNode {
  const existing = siblings.find((node) => node.kind === 'directory' && node.path === params.path);
  if (existing) return existing;

  const next: MutableCanvasFileNode = {
    id: params.id,
    source: params.source,
    kind: 'directory',
    name: params.name,
    path: params.path,
    children: [],
  };
  siblings.push(next);
  return next;
}

function insertFilePath(
  root: MutableCanvasFileNode[],
  params: {
    source: CanvasFileSource;
    fullPath: string;
    parts: string[];
    idBase: string;
    artifact?: Artifact | undefined;
    rootPath?: string | undefined;
  }
): void {
  if (params.parts.length === 0) return;

  let siblings = root;
  let currentPath = params.rootPath?.replace(/\/+$/, '') ?? '';

  params.parts.forEach((part, index) => {
    const isFile = index === params.parts.length - 1;
    currentPath = currentPath ? `${currentPath}/${part}` : part;
    if (!isFile) {
      const directory = ensureDirectory(siblings, {
        id: `${params.source}:dir:${currentPath}`,
        source: params.source,
        name: part,
        path: currentPath,
      });
      siblings = directory.children;
      return;
    }

    siblings.push({
      id: `${params.source}:file:${params.idBase}`,
      source: params.source,
      kind: 'file',
      name: part,
      path: params.fullPath,
      children: [],
      artifact: params.artifact,
    });
  });
}

function sortTree(nodes: CanvasFileNode[]): CanvasFileNode[] {
  return nodes
    .map((node) => ({
      ...node,
      children: sortTree(node.children),
    }))
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'directory' ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
    });
}

export function buildSandboxFileTree(paths: string[], rootPath = SANDBOX_ROOT): CanvasFileNode[] {
  const root: MutableCanvasFileNode[] = [];

  paths.forEach((rawPath) => {
    const fullPath = normalizeSandboxPath(rawPath, rootPath);
    const parts = splitDisplayPath(fullPath, rootPath);
    insertFilePath(root, {
      source: 'sandbox',
      fullPath,
      parts,
      idBase: fullPath,
      rootPath,
    });
  });

  return sortTree(root);
}

export function buildArtifactFileTree(artifacts: Artifact[]): CanvasFileNode[] {
  const root: MutableCanvasFileNode[] = [];

  artifacts
    .filter((artifact) => artifact.status === 'ready')
    .forEach((artifact) => {
      const fullPath = artifact.sourcePath?.trim() || artifact.filename;
      const parts = splitDisplayPath(fullPath);
      insertFilePath(root, {
        source: 'artifacts',
        fullPath,
        parts: parts.length > 0 ? parts : [artifact.filename],
        idBase: artifact.id,
        artifact,
      });
    });

  return sortTree(root);
}
