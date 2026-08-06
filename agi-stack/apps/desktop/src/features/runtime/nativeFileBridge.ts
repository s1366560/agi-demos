export const MAX_RENDERER_NATIVE_FILE_BYTES = 16 * 1_048_576;
export const MAX_RENDERER_NATIVE_FILE_COUNT = 10;

export type DesktopPickedFilesResult =
  | Readonly<{ status: 'cancelled' }>
  | Readonly<{ status: 'selected'; files: readonly File[] }>;

type SaveBlobWithDesktopDialogInput = Readonly<{
  suggestedName: string;
  mimeType: string;
  blob: Blob;
}>;

export async function saveBlobWithDesktopDialog({
  suggestedName,
  mimeType,
  blob,
}: SaveBlobWithDesktopDialogInput): Promise<DesktopFileSaveResult> {
  const save =
    typeof window === 'undefined'
      ? undefined
      : window.__MEMSTACK_DESKTOP__?.files?.save;
  if (typeof save !== 'function') throw new Error('native_file_bridge_unavailable');
  if (blob.size > MAX_RENDERER_NATIVE_FILE_BYTES) {
    throw new Error('native_file_write_limit_exceeded');
  }
  const bytes = new Uint8Array(await blob.arrayBuffer());
  if (bytes.byteLength > MAX_RENDERER_NATIVE_FILE_BYTES) {
    throw new Error('native_file_write_limit_exceeded');
  }
  return save(
    Object.freeze({
      suggestedName,
      mimeType,
      bytes,
    }),
  );
}

export async function openFilesWithDesktopDialog(
  purpose: DesktopFileOpenPurpose,
): Promise<DesktopPickedFilesResult> {
  const open =
    typeof window === 'undefined'
      ? undefined
      : window.__MEMSTACK_DESKTOP__?.files?.open;
  if (typeof open !== 'function') throw new Error('native_file_bridge_unavailable');
  const result = await open(Object.freeze({ purpose }));
  if (result.status === 'cancelled') return Object.freeze({ status: 'cancelled' });
  const maxFiles = purpose === 'attachment' ? MAX_RENDERER_NATIVE_FILE_COUNT : 1;
  return Object.freeze({
    status: 'selected',
    files: nativePayloadsToFiles(result.files, maxFiles),
  });
}

export async function ingestFilesWithDesktopBridge(
  files: readonly File[],
): Promise<readonly File[]> {
  const ingest =
    typeof window === 'undefined'
      ? undefined
      : window.__MEMSTACK_DESKTOP__?.files?.ingest;
  if (typeof ingest !== 'function') throw new Error('native_file_bridge_unavailable');
  validateRendererFileBatch(files);

  const payloads: DesktopFilePayload[] = [];
  let totalBytes = 0;
  for (const file of files) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    totalBytes += bytes.byteLength;
    if (
      bytes.byteLength !== file.size ||
      bytes.byteLength > MAX_RENDERER_NATIVE_FILE_BYTES ||
      totalBytes > MAX_RENDERER_NATIVE_FILE_BYTES
    ) {
      throw new Error('native_file_ingest_limit_exceeded');
    }
    payloads.push(
      Object.freeze({
        filename: file.name,
        mimeType: file.type.trim() || 'application/octet-stream',
        bytes,
      }),
    );
  }

  const result = await ingest(
    Object.freeze({
      purpose: 'attachment',
      files: Object.freeze(payloads),
    }),
  );
  return nativePayloadsToFiles(result.files, MAX_RENDERER_NATIVE_FILE_COUNT);
}

function validateRendererFileBatch(files: readonly File[]): void {
  if (files.length === 0 || files.length > MAX_RENDERER_NATIVE_FILE_COUNT) {
    throw new Error('native_file_ingest_count_exceeded');
  }
  let totalBytes = 0;
  for (const file of files) {
    if (!Number.isSafeInteger(file.size) || file.size < 0) {
      throw new Error('native_file_ingest_limit_exceeded');
    }
    totalBytes += file.size;
    if (
      file.size > MAX_RENDERER_NATIVE_FILE_BYTES ||
      totalBytes > MAX_RENDERER_NATIVE_FILE_BYTES
    ) {
      throw new Error('native_file_ingest_limit_exceeded');
    }
  }
}

function nativePayloadsToFiles(
  payloads: readonly DesktopFilePayload[],
  maxFiles: number,
): readonly File[] {
  if (payloads.length === 0 || payloads.length > maxFiles) {
    throw new Error('native_file_result_count_invalid');
  }
  let totalBytes = 0;
  const files = payloads.map((payload) => {
    totalBytes += payload.bytes.byteLength;
    if (
      payload.bytes.byteLength > MAX_RENDERER_NATIVE_FILE_BYTES ||
      totalBytes > MAX_RENDERER_NATIVE_FILE_BYTES
    ) {
      throw new Error('native_file_result_limit_exceeded');
    }
    const ownedBytes = new Uint8Array(payload.bytes.byteLength);
    ownedBytes.set(payload.bytes);
    return new File([ownedBytes.buffer], payload.filename, { type: payload.mimeType });
  });
  return Object.freeze(files);
}
