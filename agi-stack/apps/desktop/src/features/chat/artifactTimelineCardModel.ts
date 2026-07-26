import type { AgentTimelineItem } from '../../types';
import { isSafeArtifactUrl } from './assistantArtifactReferenceModel';

export type ArtifactTimelineStatus = 'uploading' | 'ready' | 'error';
export type ArtifactTimelineIconKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'document'
  | 'code'
  | 'archive'
  | 'file';

export type ArtifactTimelineCard = {
  artifactId: string;
  filename: string;
  mimeType: string;
  category: string;
  sizeBytes: number | null;
  sourceTool: string | null;
  status: ArtifactTimelineStatus;
  downloadUrl: string | null;
  previewUrl: string | null;
  previewKind: 'image' | 'none';
  iconKind: ArtifactTimelineIconKind;
  error: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function structuredString(
  item: AgentTimelineItem,
  payload: Record<string, unknown> | null,
  keys: string[],
): string | null {
  for (const source of [item, payload]) {
    if (!source) continue;
    for (const key of keys) {
      const value = source[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
  }
  return null;
}

function structuredSize(
  item: AgentTimelineItem,
  payload: Record<string, unknown> | null,
): number | null {
  for (const source of [item, payload]) {
    if (!source) continue;
    for (const key of ['sizeBytes', 'size_bytes']) {
      const value = source[key];
      if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) {
        return value;
      }
    }
  }
  return null;
}

function artifactIconKind(mimeType: string): ArtifactTimelineIconKind {
  const mime = mimeType.toLowerCase();
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';
  if (
    [
      'application/zip',
      'application/x-7z-compressed',
      'application/x-rar-compressed',
      'application/x-tar',
      'application/gzip',
    ].includes(mime)
  ) {
    return 'archive';
  }
  if (
    [
      'application/javascript',
      'application/typescript',
      'application/x-python',
      'text/javascript',
      'text/typescript',
      'text/x-python',
      'text/x-rust',
      'text/x-shellscript',
    ].includes(mime)
  ) {
    return 'code';
  }
  if (
    mime.startsWith('text/') ||
    mime === 'application/pdf' ||
    mime.startsWith('application/vnd.ms-') ||
    mime.startsWith('application/vnd.openxmlformats-officedocument.')
  ) {
    return 'document';
  }
  return 'file';
}

export function artifactTimelineCard(item: AgentTimelineItem): ArtifactTimelineCard {
  const payload = isRecord(item.payload) ? item.payload : null;
  const artifactId =
    structuredString(item, payload, ['artifactId', 'artifact_id']) ?? item.id;
  const filename =
    structuredString(item, payload, ['filename']) ?? artifactId;
  const mimeType =
    structuredString(item, payload, ['mimeType', 'mime_type']) ?? '';
  const category =
    structuredString(item, payload, ['category']) ?? '';
  const sourceTool =
    structuredString(item, payload, ['sourceTool', 'source_tool']);
  const error =
    structuredString(item, payload, ['error', 'errorMessage', 'error_message']);
  const rawUrl = structuredString(item, payload, ['url']);
  const rawPreviewUrl =
    structuredString(item, payload, ['previewUrl', 'preview_url']);
  const status: ArtifactTimelineStatus =
    item.type === 'artifact_error' || error
      ? 'error'
      : item.type === 'artifact_ready' || rawUrl
        ? 'ready'
        : 'uploading';
  const safeDownloadUrl =
    status === 'ready' && rawUrl && isSafeArtifactUrl(rawUrl) ? rawUrl : null;
  const imagePreviewCandidate = rawPreviewUrl ?? rawUrl;
  const safePreviewUrl =
    status === 'ready' &&
    mimeType.toLowerCase().startsWith('image/') &&
    imagePreviewCandidate &&
    isSafeArtifactUrl(imagePreviewCandidate)
      ? imagePreviewCandidate
      : null;

  return {
    artifactId,
    filename,
    mimeType,
    category,
    sizeBytes: structuredSize(item, payload),
    sourceTool,
    status,
    downloadUrl: safeDownloadUrl,
    previewUrl: safePreviewUrl,
    previewKind: safePreviewUrl ? 'image' : 'none',
    iconKind: artifactIconKind(mimeType),
    error,
  };
}

export function formatArtifactTimelineSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
