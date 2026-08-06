import { randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { open, rename, unlink } from 'node:fs/promises';
import { basename, dirname, extname, isAbsolute, join } from 'node:path';

import { RENDERER_PROTOCOL_HOST, RENDERER_PROTOCOL_SCHEME } from './rendererProtocol';

export const MAX_NATIVE_FILE_BYTES = 16 * 1_048_576;
export const MAX_NATIVE_FILE_COUNT = 10;
export const MAX_NATIVE_FILE_WRITE_BYTES = MAX_NATIVE_FILE_BYTES;
export const MAX_NATIVE_FILE_IMPORT_BYTES = MAX_NATIVE_FILE_BYTES;

export type NativeFileOpenPurpose = 'attachment' | 'skill_package';

export type NativeFilePayload = Readonly<{
  filename: string;
  mimeType: string;
  bytes: Uint8Array;
}>;

export type NativeFileSaveRequest = Readonly<{
  suggestedName: string;
  mimeType: string;
  bytes: Uint8Array;
}>;

export type NativeFileSaveResult =
  | Readonly<{ status: 'cancelled' }>
  | Readonly<{ status: 'saved'; bytesWritten: number }>;

export type NativeFileOpenRequest = Readonly<{
  purpose: NativeFileOpenPurpose;
}>;

export type NativeFileOpenResult =
  | Readonly<{ status: 'cancelled' }>
  | Readonly<{
      status: 'selected';
      files: readonly NativeFilePayload[];
    }>;

export type NativeFileIngestRequest = Readonly<{
  purpose: 'attachment';
  files: readonly NativeFilePayload[];
}>;

export type NativeFileIngestResult = Readonly<{
  status: 'ingested';
  files: readonly NativeFilePayload[];
}>;

export type NativeFileDialogFilter = Readonly<{
  name: string;
  extensions: readonly string[];
}>;

export type NativeFileDialogAuthority = Readonly<{
  chooseSaveTarget(input: Readonly<{
    suggestedName: string;
    mimeType: string;
    filters: readonly NativeFileDialogFilter[];
  }>): Promise<string | null>;
  chooseOpenTargets(input: Readonly<{
    purpose: NativeFileOpenPurpose;
    allowMultiple: boolean;
    filters: readonly NativeFileDialogFilter[];
  }>): Promise<readonly string[] | null>;
  readFileNoFollow(path: string, maxBytes: number): Promise<Uint8Array>;
  writeFileAtomically(path: string, bytes: Uint8Array): Promise<void>;
}>;

export type NativeFileReadHandle = Readonly<{
  stat(): Promise<Readonly<{ isFile: boolean; size: number }>>;
  read(
    buffer: Uint8Array,
    offset: number,
    length: number,
    position: number,
  ): Promise<number>;
  close(): Promise<void>;
}>;

const APPLICATION_MIME_ALLOWLIST = new Set([
  'application/gzip',
  'application/javascript',
  'application/json',
  'application/msword',
  'application/octet-stream',
  'application/pdf',
  'application/rtf',
  'application/vnd.ms-excel',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/wasm',
  'application/x-7z-compressed',
  'application/x-ndjson',
  'application/x-tar',
  'application/xml',
  'application/yaml',
  'application/zip',
]);

const OPEN_EXTENSIONS = Object.freeze({
  attachment: Object.freeze([
    '7z',
    'aac',
    'avif',
    'avi',
    'bmp',
    'c',
    'cc',
    'cfg',
    'conf',
    'cpp',
    'csv',
    'css',
    'doc',
    'docx',
    'flac',
    'gif',
    'go',
    'gz',
    'h',
    'heic',
    'heif',
    'hpp',
    'htm',
    'html',
    'ico',
    'ini',
    'ipynb',
    'java',
    'jpeg',
    'jpg',
    'json',
    'jsonl',
    'js',
    'jsx',
    'log',
    'm4a',
    'm4v',
    'md',
    'mjs',
    'mov',
    'mp3',
    'mp4',
    'mpeg',
    'ndjson',
    'odp',
    'ods',
    'odt',
    'ogg',
    'parquet',
    'pdf',
    'php',
    'png',
    'ppt',
    'pptx',
    'py',
    'rb',
    'rs',
    'sh',
    'sql',
    'svg',
    'tar',
    'toml',
    'ts',
    'tsv',
    'tsx',
    'txt',
    'wav',
    'webm',
    'webp',
    'xls',
    'xlsx',
    'xml',
    'yaml',
    'yml',
    'zip',
  ]),
  skill_package: Object.freeze(['zip']),
} satisfies Record<NativeFileOpenPurpose, readonly string[]>);

const MIME_BY_EXTENSION: Readonly<Record<string, string>> = Object.freeze({
  csv: 'text/csv',
  css: 'text/css',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  gif: 'image/gif',
  html: 'text/html',
  htm: 'text/html',
  jpeg: 'image/jpeg',
  jpg: 'image/jpeg',
  json: 'application/json',
  jsonl: 'application/x-ndjson',
  js: 'text/javascript',
  jsx: 'text/javascript',
  log: 'text/plain',
  md: 'text/markdown',
  mjs: 'text/javascript',
  mp3: 'audio/mpeg',
  mp4: 'video/mp4',
  pdf: 'application/pdf',
  png: 'image/png',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  svg: 'image/svg+xml',
  toml: 'text/plain',
  ts: 'text/plain',
  tsv: 'text/tab-separated-values',
  tsx: 'text/plain',
  txt: 'text/plain',
  wav: 'audio/wav',
  webm: 'video/webm',
  webp: 'image/webp',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  xml: 'application/xml',
  yaml: 'application/yaml',
  yml: 'application/yaml',
  zip: 'application/zip',
});

export function validateNativeFileSaveRequest(
  value: unknown,
  maxBytes = MAX_NATIVE_FILE_WRITE_BYTES,
): NativeFileSaveRequest {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['bytes', 'mimeType', 'suggestedName']) ||
    !(value.bytes instanceof Uint8Array) ||
    value.bytes.BYTES_PER_ELEMENT !== 1
  ) {
    throw new Error('native file bytes are invalid');
  }
  const suggestedName = validateSuggestedFilename(value.suggestedName);
  const mimeType = validateDeclaredMime(value.mimeType);
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 0 || value.bytes.byteLength > maxBytes) {
    throw new Error('file exceeds the native write limit');
  }
  return Object.freeze({ suggestedName, mimeType, bytes: value.bytes });
}

export function nativeFileSaveDialogFilters(
  suggestedName: string,
  mimeType: string,
): readonly NativeFileDialogFilter[] {
  const extension = extname(suggestedName).slice(1).toLowerCase();
  if (!/^[a-z0-9][a-z0-9+_-]{0,15}$/u.test(extension)) return Object.freeze([]);
  return Object.freeze([
    Object.freeze({
      name: mimeType.split(';', 1)[0] ?? mimeType,
      extensions: Object.freeze([extension]),
    }),
  ]);
}

export function nativeFileOpenDialogFilters(
  purpose: NativeFileOpenPurpose,
): readonly NativeFileDialogFilter[] {
  const extensions = OPEN_EXTENSIONS[purpose];
  if (!extensions) throw new Error('native file open request is invalid');
  return Object.freeze([
    Object.freeze({
      name: purpose === 'skill_package' ? 'Skill ZIP packages' : 'Attachment files',
      extensions,
    }),
  ]);
}

export async function saveNativeFileWithDialog(
  request: unknown,
  authority: NativeFileDialogAuthority,
): Promise<NativeFileSaveResult> {
  const validated = validateNativeFileSaveRequest(request);
  const selectedTarget = await authority.chooseSaveTarget({
    suggestedName: validated.suggestedName,
    mimeType: validated.mimeType,
    filters: nativeFileSaveDialogFilters(validated.suggestedName, validated.mimeType),
  });
  if (selectedTarget === null) return Object.freeze({ status: 'cancelled' });
  validateDialogSelectedPath(selectedTarget, 'save');
  await authority.writeFileAtomically(selectedTarget, validated.bytes);
  return Object.freeze({
    status: 'saved',
    bytesWritten: validated.bytes.byteLength,
  });
}

export async function openNativeFileWithDialog(
  request: unknown,
  authority: NativeFileDialogAuthority,
): Promise<NativeFileOpenResult> {
  const purpose = validateOpenRequest(request);
  const allowMultiple = purpose === 'attachment';
  const selectedTargets = await authority.chooseOpenTargets({
    purpose,
    allowMultiple,
    filters: nativeFileOpenDialogFilters(purpose),
  });
  if (selectedTargets === null) return Object.freeze({ status: 'cancelled' });
  const maxFiles = purpose === 'attachment' ? MAX_NATIVE_FILE_COUNT : 1;
  if (
    !Array.isArray(selectedTargets) ||
    selectedTargets.length === 0 ||
    selectedTargets.length > maxFiles ||
    (!allowMultiple && selectedTargets.length !== 1)
  ) {
    throw new Error('native file selection count is invalid');
  }

  const files: NativeFilePayload[] = [];
  let totalBytes = 0;
  for (const selectedTarget of selectedTargets) {
    validateDialogSelectedPath(selectedTarget, 'open');
    const filename = validateSuggestedFilename(basename(selectedTarget));
    const extension = extname(filename).slice(1).toLowerCase();
    if (!OPEN_EXTENSIONS[purpose].includes(extension)) {
      throw new Error('selected import file extension is not allowed');
    }

    const remainingBytes = MAX_NATIVE_FILE_IMPORT_BYTES - totalBytes;
    const bytes = await authority.readFileNoFollow(selectedTarget, remainingBytes);
    if (!(bytes instanceof Uint8Array) || bytes.byteLength > remainingBytes) {
      throw new Error('file exceeds the native import limit');
    }
    if (purpose === 'skill_package' && !hasZipFileSignature(bytes)) {
      throw new Error('selected Skill package is not a ZIP archive');
    }
    totalBytes += bytes.byteLength;
    files.push(
      Object.freeze({
        filename,
        mimeType: mimeTypeForFilename(filename),
        bytes,
      }),
    );
  }
  return Object.freeze({
    status: 'selected',
    files: Object.freeze(files),
  });
}

export function ingestNativeFiles(request: unknown): NativeFileIngestResult {
  if (
    !isRecord(request) ||
    !hasExactKeys(request, ['files', 'purpose']) ||
    request.purpose !== 'attachment' ||
    !Array.isArray(request.files) ||
    request.files.length === 0 ||
    request.files.length > MAX_NATIVE_FILE_COUNT
  ) {
    throw new Error('native file ingest request is invalid');
  }

  let totalBytes = 0;
  const files = request.files.map((file): NativeFilePayload => {
    if (
      !isRecord(file) ||
      !hasExactKeys(file, ['bytes', 'filename', 'mimeType']) ||
      !(file.bytes instanceof Uint8Array) ||
      file.bytes.BYTES_PER_ELEMENT !== 1
    ) {
      throw new Error('native file ingest request is invalid');
    }
    let filename: string;
    let mimeType: string;
    try {
      filename = validateSuggestedFilename(file.filename);
      mimeType = validateDeclaredMime(file.mimeType);
    } catch {
      throw new Error('native file ingest request is invalid');
    }
    const extension = extname(filename).slice(1).toLowerCase();
    if (!OPEN_EXTENSIONS.attachment.includes(extension)) {
      throw new Error('native file ingest request is invalid');
    }
    totalBytes += file.bytes.byteLength;
    if (
      file.bytes.byteLength > MAX_NATIVE_FILE_IMPORT_BYTES ||
      totalBytes > MAX_NATIVE_FILE_IMPORT_BYTES
    ) {
      throw new Error('native file ingest exceeds the native import limit');
    }
    return Object.freeze({
      filename,
      mimeType,
      bytes: Uint8Array.from(file.bytes),
    });
  });
  return Object.freeze({ status: 'ingested', files: Object.freeze(files) });
}

export async function readNativeFileNoFollow(
  path: string,
  maxBytes = MAX_NATIVE_FILE_IMPORT_BYTES,
): Promise<Uint8Array> {
  validateDialogSelectedPath(path, 'open');
  if (
    !Number.isSafeInteger(maxBytes) ||
    maxBytes < 0 ||
    typeof constants.O_NOFOLLOW !== 'number' ||
    constants.O_NOFOLLOW === 0
  ) {
    throw new Error('native nofollow file reads are unavailable');
  }
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  return readBoundedNativeFileHandle(
    {
      async stat() {
        const metadata = await handle.stat();
        return { isFile: metadata.isFile(), size: metadata.size };
      },
      async read(buffer, offset, length, position) {
        const result = await handle.read(buffer, offset, length, position);
        return result.bytesRead;
      },
      async close() {
        await handle.close();
      },
    },
    maxBytes,
  );
}

export async function readBoundedNativeFileHandle(
  handle: NativeFileReadHandle,
  maxBytes = MAX_NATIVE_FILE_IMPORT_BYTES,
): Promise<Uint8Array> {
  try {
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 0) {
      throw new Error('native import limit is invalid');
    }
    const metadata = await handle.stat();
    if (
      !metadata.isFile ||
      !Number.isSafeInteger(metadata.size) ||
      metadata.size < 0
    ) {
      throw new Error('selected import file is invalid');
    }
    if (metadata.size > maxBytes) {
      throw new Error('file exceeds the native import limit');
    }

    const buffer = new Uint8Array(maxBytes + 1);
    let bytesRead = 0;
    while (bytesRead < buffer.byteLength) {
      const count = await handle.read(
        buffer,
        bytesRead,
        buffer.byteLength - bytesRead,
        bytesRead,
      );
      if (!Number.isSafeInteger(count) || count < 0 || count > buffer.byteLength - bytesRead) {
        throw new Error('selected import file read is invalid');
      }
      if (count === 0) break;
      bytesRead += count;
    }
    if (bytesRead > maxBytes) {
      throw new Error('file exceeds the native import limit');
    }
    return buffer.slice(0, bytesRead);
  } finally {
    await handle.close();
  }
}

export async function writeNativeFileAtomically(
  path: string,
  bytes: Uint8Array,
): Promise<void> {
  validateDialogSelectedPath(path, 'save');
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_NATIVE_FILE_WRITE_BYTES) {
    throw new Error('file exceeds the native write limit');
  }
  const tempPath = join(
    dirname(path),
    `.${basename(path)}.${randomUUID()}.tmp`,
  );
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  let renamed = false;
  try {
    handle = await open(tempPath, 'wx', 0o600);
    const metadata = await handle.stat();
    if (!metadata.isFile() || metadata.nlink !== 1) {
      throw new Error('native temporary save target is invalid');
    }
    await handle.writeFile(bytes);
    await handle.sync();
    await handle.close();
    handle = null;
    await rename(tempPath, path);
    renamed = true;
  } finally {
    if (handle) await handle.close().catch(() => undefined);
    if (!renamed) await unlink(tempPath).catch(() => undefined);
  }
}

export function isTrustedNativeFileFrameUrl(
  frameUrl: string,
  developmentUrl: URL | null,
): boolean {
  let target: URL;
  try {
    target = new URL(frameUrl);
  } catch {
    return false;
  }
  if (target.username || target.password) return false;
  if (developmentUrl) {
    return target.origin === developmentUrl.origin;
  }
  return (
    target.protocol === `${RENDERER_PROTOCOL_SCHEME}:` &&
    target.hostname === RENDERER_PROTOCOL_HOST &&
    !target.port
  );
}

function validateSuggestedFilename(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 180 ||
    value !== value.trim() ||
    value === '.' ||
    value === '..' ||
    basename(value) !== value ||
    /[\u0000-\u001f<>:"/\\|?*]/u.test(value) ||
    /[. ]$/u.test(value) ||
    /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/iu.test(value)
  ) {
    throw new Error('native suggested filename is invalid');
  }
  return value;
}

function validateDeclaredMime(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim()) {
    throw new Error('native declared MIME type is invalid');
  }
  const parts = value.toLowerCase().split(';').map((part) => part.trim());
  const essence = parts[0] ?? '';
  const parameters = parts.slice(1);
  if (
    !/^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$/u.test(
      essence,
    ) ||
    parameters.length > 1 ||
    (parameters.length === 1 &&
      (parameters[0] !== 'charset=utf-8' || !essence.startsWith('text/'))) ||
    !isAllowedMimeEssence(essence)
  ) {
    throw new Error('native declared MIME type is invalid');
  }
  return parameters.length === 1 ? `${essence};charset=utf-8` : essence;
}

function isAllowedMimeEssence(essence: string): boolean {
  return (
    essence.startsWith('audio/') ||
    essence.startsWith('font/') ||
    essence.startsWith('image/') ||
    essence.startsWith('text/') ||
    essence.startsWith('video/') ||
    APPLICATION_MIME_ALLOWLIST.has(essence)
  );
}

function validateOpenRequest(value: unknown): NativeFileOpenPurpose {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['purpose']) ||
    (value.purpose !== 'attachment' && value.purpose !== 'skill_package')
  ) {
    throw new Error('native file open request is invalid');
  }
  return value.purpose;
}

function validateDialogSelectedPath(value: unknown, operation: 'open' | 'save'): string {
  if (typeof value !== 'string' || !isAbsolute(value) || value.includes('\u0000')) {
    throw new Error(`native ${operation} dialog selected path is invalid`);
  }
  return value;
}

function mimeTypeForFilename(filename: string): string {
  const extension = extname(filename).slice(1).toLowerCase();
  return MIME_BY_EXTENSION[extension] ?? 'application/octet-stream';
}

function hasZipFileSignature(bytes: Uint8Array): boolean {
  if (bytes.byteLength < 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b) return false;
  return (
    (bytes[2] === 0x03 && bytes[3] === 0x04) ||
    (bytes[2] === 0x05 && bytes[3] === 0x06) ||
    (bytes[2] === 0x07 && bytes[3] === 0x08)
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
