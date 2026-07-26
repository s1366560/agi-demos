import { isSafeArtifactUrl } from './assistantArtifactReferenceModel';

export type MarkdownArtifactImageResolution = {
  key: string;
  sourcePath: string;
  url: string;
  mimeType: string;
};

const WORKSPACE_ROOT = '/workspace';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function decodePath(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/**
 * Normalize only explicit workspace paths. Bare filenames deliberately remain
 * unresolved so one conversation cannot accidentally select an unrelated
 * artifact with the same display name.
 */
export function normalizeMarkdownArtifactImagePath(value: string): string | null {
  const trimmed = value.trim();
  const decoded = decodePath(trimmed);
  if (!decoded || decoded.includes('\\') || decoded.includes('\u0000')) return null;
  const expanded = decoded.startsWith('~/') ? `${WORKSPACE_ROOT}/${decoded.slice(2)}` : decoded;
  if (expanded !== WORKSPACE_ROOT && !expanded.startsWith(`${WORKSPACE_ROOT}/`)) return null;

  const parts: string[] = [];
  for (const part of expanded.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (parts.length <= 1) return null;
      parts.pop();
      continue;
    }
    parts.push(part);
  }
  return `/${parts.join('/')}`;
}

function artifactCandidates(carrier: unknown): Record<string, unknown>[] {
  if (!isRecord(carrier)) return [];
  const payload = isRecord(carrier.payload) ? carrier.payload : null;
  const metadata = isRecord(carrier.metadata) ? carrier.metadata : null;
  const candidates: Record<string, unknown>[] = [
    payload ? { ...payload, ...carrier } : carrier,
  ];

  for (const collection of [carrier.artifacts, metadata?.artifacts, payload?.artifacts]) {
    if (!Array.isArray(collection)) continue;
    for (const candidate of collection) {
      if (isRecord(candidate)) candidates.push(candidate);
    }
  }
  return candidates;
}

function exactStructuredKey(value: unknown): string | null {
  const key = nonEmptyString(value);
  if (
    !key ||
    key.includes('\\') ||
    key.includes('\u0000') ||
    /\s/u.test(key) ||
    !key.includes('/')
  ) {
    return null;
  }
  return key;
}

function candidateMatchesSource(candidate: Record<string, unknown>, source: string): boolean {
  const normalizedSourcePath = normalizeMarkdownArtifactImagePath(source);
  for (const field of [
    candidate.sourcePath,
    candidate.source_path,
    candidate.sandboxPath,
    candidate.sandbox_path,
  ]) {
    const candidatePath = nonEmptyString(field);
    if (
      normalizedSourcePath &&
      candidatePath &&
      normalizeMarkdownArtifactImagePath(candidatePath) === normalizedSourcePath
    ) {
      return true;
    }
  }

  const sourceKey = exactStructuredKey(source);
  if (sourceKey) {
    for (const field of [candidate.objectKey, candidate.object_key]) {
      if (exactStructuredKey(field) === sourceKey) return true;
    }
  }

  return [candidate.url, candidate.previewUrl, candidate.preview_url].some(
    (field) => nonEmptyString(field) === source && isSafeArtifactUrl(source),
  );
}

function candidateResolution(
  candidate: Record<string, unknown>,
  source: string,
): MarkdownArtifactImageResolution | null {
  const mimeType = nonEmptyString(candidate.mimeType ?? candidate.mime_type);
  if (!mimeType?.toLowerCase().startsWith('image/')) return null;
  if (!candidateMatchesSource(candidate, source)) return null;

  const url = nonEmptyString(candidate.previewUrl ?? candidate.preview_url ?? candidate.url);
  if (!url || !isSafeArtifactUrl(url)) return null;
  const sourcePath = normalizeMarkdownArtifactImagePath(source) ?? source.trim();
  return {
    key: `${sourcePath}\u0000${url}`,
    sourcePath,
    url,
    mimeType,
  };
}

/**
 * Resolve a Markdown image source using only structured artifacts already
 * present in the current conversation. Ambiguous matches fail closed.
 */
export function resolveMarkdownArtifactImage(
  source: string,
  carriers: readonly unknown[],
): MarkdownArtifactImageResolution | null {
  const matches = new Map<string, MarkdownArtifactImageResolution>();
  for (const carrier of carriers) {
    for (const candidate of artifactCandidates(carrier)) {
      const resolution = candidateResolution(candidate, source);
      if (resolution) matches.set(resolution.url, resolution);
    }
  }
  return matches.size === 1 ? [...matches.values()][0] : null;
}
