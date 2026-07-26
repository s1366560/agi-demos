export type AssistantArtifactReference = {
  key: string;
  label: string;
  url: string;
  mimeType: string | null;
  sizeBytes: number | null;
  source: string | null;
};

type ArtifactReferenceCarrier = {
  artifacts?: unknown;
  metadata?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function isSafeArtifactUrl(value: string): boolean {
  if (/\s/u.test(value)) return false;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:') return true;
    if (url.protocol !== 'http:') return false;
    const host = url.hostname.toLowerCase();
    return (
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '[::1]' ||
      host === '::1'
    );
  } catch {
    return false;
  }
}

function artifactLabel(objectKey: string | null, url: string): string {
  const source = objectKey ?? url;
  try {
    const parsed = new URL(source, 'https://memstack.local');
    const filename = parsed.pathname.split('/').filter(Boolean).at(-1);
    return filename ? safeDecodeURIComponent(filename) : source;
  } catch {
    const filename = source.split('/').filter(Boolean).at(-1);
    return filename ? safeDecodeURIComponent(filename) : source;
  }
}

function normalizeArtifactReference(value: unknown): AssistantArtifactReference | null {
  if (!isRecord(value)) return null;
  const url = nonEmptyString(value.url);
  if (!url || !isSafeArtifactUrl(url)) return null;
  const objectKey = nonEmptyString(value.object_key ?? value.objectKey);
  const rawSize = value.size_bytes ?? value.sizeBytes;
  const sizeBytes =
    typeof rawSize === 'number' && Number.isSafeInteger(rawSize) && rawSize >= 0
      ? rawSize
      : null;
  return {
    key: `${url}\u0000${objectKey ?? ''}`,
    label: artifactLabel(objectKey, url),
    url,
    mimeType: nonEmptyString(value.mime_type ?? value.mimeType),
    sizeBytes,
    source: nonEmptyString(value.source),
  };
}

function artifactCandidates(carrier: ArtifactReferenceCarrier): unknown[] {
  if (Array.isArray(carrier.artifacts)) return carrier.artifacts;
  const metadata = isRecord(carrier.metadata) ? carrier.metadata : null;
  return metadata && Array.isArray(metadata.artifacts) ? metadata.artifacts : [];
}

/**
 * Read only structured completion artifact fields. Top-level protocol data wins
 * over the metadata replay fallback, matching the Web message contract.
 */
export function assistantArtifactReferences(
  carrier: ArtifactReferenceCarrier,
): AssistantArtifactReference[] {
  const seen = new Set<string>();
  const references: AssistantArtifactReference[] = [];
  for (const candidate of artifactCandidates(carrier)) {
    const reference = normalizeArtifactReference(candidate);
    if (!reference || seen.has(reference.key)) continue;
    seen.add(reference.key);
    references.push(reference);
  }
  return references;
}

export function formatAssistantArtifactSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
