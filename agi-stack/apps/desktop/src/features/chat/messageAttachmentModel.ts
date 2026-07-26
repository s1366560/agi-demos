import type { AgentTimelineItem } from '../../types';

export type TimelineMessageAttachment = {
  filename: string;
  sandboxPath: string | null;
  mimeType: string;
  sizeBytes: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function attachmentArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function normalizeAttachment(value: unknown): TimelineMessageAttachment | null {
  if (!isRecord(value)) return null;
  const filename = nonEmptyString(value.filename);
  const mimeType = nonEmptyString(value.mime_type ?? value.mimeType);
  const sizeBytes = value.size_bytes ?? value.sizeBytes;
  if (
    !filename ||
    !mimeType ||
    typeof sizeBytes !== 'number' ||
    !Number.isSafeInteger(sizeBytes) ||
    sizeBytes < 0
  ) {
    return null;
  }
  return {
    filename,
    sandboxPath: nonEmptyString(value.sandbox_path ?? value.sandboxPath),
    mimeType,
    sizeBytes,
  };
}

function attachmentIdentity(attachment: TimelineMessageAttachment): string {
  return attachment.sandboxPath
    ? `path:${attachment.sandboxPath}`
    : `record:${attachment.filename}\u0000${attachment.mimeType}\u0000${attachment.sizeBytes}`;
}

/**
 * Read only structured attachment protocol fields. Message text and filenames
 * never participate in attachment discovery or MIME classification.
 */
export function timelineMessageAttachments(
  item: AgentTimelineItem,
): TimelineMessageAttachment[] {
  const metadata = isRecord(item.metadata) ? item.metadata : {};
  const payload = isRecord(item.payload) ? item.payload : {};
  const directFileMetadata = (item as AgentTimelineItem & { fileMetadata?: unknown }).fileMetadata;
  const candidates = [
    ...attachmentArray(metadata.fileMetadata),
    ...attachmentArray(metadata.file_metadata),
    ...attachmentArray(payload.fileMetadata),
    ...attachmentArray(payload.file_metadata),
    ...attachmentArray(directFileMetadata),
  ];
  const seen = new Set<string>();
  const attachments: TimelineMessageAttachment[] = [];

  for (const candidate of candidates) {
    const attachment = normalizeAttachment(candidate);
    if (!attachment) continue;
    const identity = attachmentIdentity(attachment);
    if (seen.has(identity)) continue;
    seen.add(identity);
    attachments.push(attachment);
  }
  return attachments;
}

export function formatTimelineAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
