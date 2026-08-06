import type {
  NativeFileIngestRequest,
  NativeFileIngestResult,
  NativeFileOpenPurpose,
  NativeFileOpenRequest,
  NativeFileOpenResult,
  NativeFilePayload,
  NativeFileSaveRequest,
  NativeFileSaveResult,
} from '../main/nativeFileDialogPolicy';

export const MAX_PRELOAD_NATIVE_FILE_BYTES = 16 * 1_048_576;
export const MAX_PRELOAD_NATIVE_FILE_COUNT = 10;
const MAX_PRELOAD_SUGGESTED_NAME_CHARS = 180;
const MAX_PRELOAD_MIME_TYPE_CHARS = 272;

export function compactNativeFileSaveRequest(value: unknown): NativeFileSaveRequest {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['bytes', 'mimeType', 'suggestedName']) ||
    typeof value.suggestedName !== 'string' ||
    value.suggestedName.length === 0 ||
    value.suggestedName.length > MAX_PRELOAD_SUGGESTED_NAME_CHARS ||
    value.suggestedName !== value.suggestedName.trim() ||
    typeof value.mimeType !== 'string' ||
    value.mimeType.length === 0 ||
    value.mimeType.length > MAX_PRELOAD_MIME_TYPE_CHARS ||
    value.mimeType !== value.mimeType.trim() ||
    !(value.bytes instanceof Uint8Array)
  ) {
    throw new Error('native file save request is invalid');
  }
  if (value.bytes.byteLength > MAX_PRELOAD_NATIVE_FILE_BYTES) {
    throw new Error('native file request exceeds the preload limit');
  }
  return Object.freeze({
    suggestedName: value.suggestedName,
    mimeType: value.mimeType,
    bytes: Uint8Array.from(value.bytes),
  });
}

export function validateNativeFileOpenRequest(value: unknown): NativeFileOpenRequest {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['purpose']) ||
    (value.purpose !== 'attachment' && value.purpose !== 'skill_package')
  ) {
    throw new Error('native file open request is invalid');
  }
  return Object.freeze({ purpose: value.purpose });
}

export function validateNativeFileSaveResult(value: unknown): NativeFileSaveResult {
  if (!isRecord(value) || typeof value.status !== 'string') {
    throw new Error('native file save result is invalid');
  }
  if (value.status === 'cancelled' && hasExactKeys(value, ['status'])) {
    return Object.freeze({ status: 'cancelled' });
  }
  if (
    value.status === 'saved' &&
    hasExactKeys(value, ['bytesWritten', 'status']) &&
    Number.isSafeInteger(value.bytesWritten) &&
    Number(value.bytesWritten) >= 0 &&
    Number(value.bytesWritten) <= MAX_PRELOAD_NATIVE_FILE_BYTES
  ) {
    return Object.freeze({ status: 'saved', bytesWritten: Number(value.bytesWritten) });
  }
  throw new Error('native file save result is invalid');
}

export function compactNativeFileOpenResult(
  value: unknown,
  purpose: NativeFileOpenPurpose,
): NativeFileOpenResult {
  if (!isRecord(value) || typeof value.status !== 'string') {
    throw new Error('native file open result is invalid');
  }
  if (value.status === 'cancelled' && hasExactKeys(value, ['status'])) {
    return Object.freeze({ status: 'cancelled' });
  }
  if (value.status !== 'selected' || !hasExactKeys(value, ['files', 'status'])) {
    throw new Error('native file open result is invalid');
  }
  const files = compactNativeFilePayloads(
    value.files,
    purpose === 'attachment' ? MAX_PRELOAD_NATIVE_FILE_COUNT : 1,
    'native file open result',
  );
  if (
    purpose === 'skill_package' &&
    (files.length !== 1 || !files[0]?.filename.toLowerCase().endsWith('.zip'))
  ) {
    throw new Error('native file open result is invalid');
  }
  return Object.freeze({
    status: 'selected',
    files,
  });
}

export function compactNativeFileIngestRequest(
  value: unknown,
): NativeFileIngestRequest {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['files', 'purpose']) ||
    value.purpose !== 'attachment'
  ) {
    throw new Error('native file ingest request is invalid');
  }
  return Object.freeze({
    purpose: 'attachment',
    files: compactNativeFilePayloads(
      value.files,
      MAX_PRELOAD_NATIVE_FILE_COUNT,
      'native file ingest request',
    ),
  });
}

export function compactNativeFileIngestResult(
  value: unknown,
): NativeFileIngestResult {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['files', 'status']) ||
    value.status !== 'ingested'
  ) {
    throw new Error('native file ingest result is invalid');
  }
  return Object.freeze({
    status: 'ingested',
    files: compactNativeFilePayloads(
      value.files,
      MAX_PRELOAD_NATIVE_FILE_COUNT,
      'native file ingest result',
    ),
  });
}

function compactNativeFilePayloads(
  value: unknown,
  maxFiles: number,
  label: string,
): readonly NativeFilePayload[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > maxFiles) {
    throw new Error(`${label} is invalid`);
  }
  let totalBytes = 0;
  const files = value.map((file): NativeFilePayload => {
    if (
      !isRecord(file) ||
      !hasExactKeys(file, ['bytes', 'filename', 'mimeType']) ||
      !isSafeLeafFilename(file.filename) ||
      !isCompactMimeType(file.mimeType) ||
      !(file.bytes instanceof Uint8Array) ||
      file.bytes.BYTES_PER_ELEMENT !== 1
    ) {
      throw new Error(`${label} is invalid`);
    }
    totalBytes += file.bytes.byteLength;
    if (
      file.bytes.byteLength > MAX_PRELOAD_NATIVE_FILE_BYTES ||
      totalBytes > MAX_PRELOAD_NATIVE_FILE_BYTES
    ) {
      throw new Error(`${label} exceeds the preload limit`);
    }
    return Object.freeze({
      filename: file.filename,
      mimeType: file.mimeType,
      bytes: Uint8Array.from(file.bytes),
    });
  });
  return Object.freeze(files);
}

function isSafeLeafFilename(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= MAX_PRELOAD_SUGGESTED_NAME_CHARS &&
    value === value.trim() &&
    value !== '.' &&
    value !== '..' &&
    !/[\u0000-\u001f<>:"/\\|?*]/u.test(value) &&
    !/[. ]$/u.test(value)
  );
}

function isCompactMimeType(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= MAX_PRELOAD_MIME_TYPE_CHARS &&
    value === value.trim()
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    keys.length === sortedExpected.length &&
    keys.every((key, index) => key === sortedExpected[index])
  );
}
