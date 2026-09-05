import type { DesktopRuntimeConfig } from '../types';
import type {
  SandboxFileListing,
  SandboxFileEntry,
  SandboxFileContent,
  SandboxFileAuthority,
} from '../features/sandbox/sandboxRuntimeClient';
export function parseFileListing(
  input: unknown,
  expectedPath: string,
  mode: DesktopRuntimeConfig['mode'],
): SandboxFileListing {
  // The Local file route declares /workspace as its virtual root and omits root on the wire.
  if (mode === 'local' && isRecord(input) && !Object.hasOwn(input, 'root'))
    input = { ...input, root: '/workspace' };
  const authority = parseFileAuthority(input, mode);
  if (
    !isRecord(input) ||
    !hasExactKeys(input, [
      'authority',
      'contract_version',
      'cursor',
      'entries',
      'isolation',
      'path',
      'revision',
      'root',
    ]) ||
    input.contract_version !== 1 ||
    typeof input.root !== 'string' ||
    input.path !== expectedPath ||
    !Array.isArray(input.entries) ||
    !(input.cursor === null || typeof input.cursor === 'string') ||
    !isRevision(input.revision)
  ) {
    throw new Error('sandbox file listing contract is invalid');
  }
  const root = requireSandboxPath(input.root);
  const entries = input.entries.map((entry) => parseFileEntry(entry, root));
  return {
    contract_version: 1,
    ...authority,
    root,
    path: expectedPath,
    entries,
    cursor: input.cursor,
    revision: input.revision,
  };
}

function parseFileEntry(input: unknown, root: string): SandboxFileEntry {
  if (
    !isRecord(input) ||
    !hasExactKeys(input, ['kind', 'mime_type', 'name', 'path', 'size_bytes']) ||
    typeof input.path !== 'string' ||
    typeof input.name !== 'string' ||
    (input.kind !== 'file' && input.kind !== 'directory') ||
    !(input.size_bytes === null || isNonNegativeInteger(input.size_bytes)) ||
    !(input.mime_type === null || isMimeType(input.mime_type))
  ) {
    throw new Error('sandbox file entry contract is invalid');
  }
  const path = requireSandboxPath(input.path);
  if (root !== '/' && path !== root && !path.startsWith(`${root}/`)) {
    throw new Error('sandbox file entry contract is invalid');
  }
  if (!input.name || input.name.includes('/') || input.name.includes('\\')) {
    throw new Error('sandbox file entry contract is invalid');
  }
  return {
    path,
    name: input.name,
    kind: input.kind,
    size_bytes: input.size_bytes,
    mime_type: input.mime_type,
  };
}

export function parseFileContent(
  input: unknown,
  expectedPath: string,
  maxBytes: number,
  mode: DesktopRuntimeConfig['mode'],
): SandboxFileContent {
  const authority = parseFileAuthority(input, mode);
  if (
    !isRecord(input) ||
    !hasExactKeys(input, [
      'authority',
      'content',
      'contract_version',
      'encoding',
      'isolation',
      'mime_type',
      'path',
      'revision',
      'size_bytes',
      'truncated',
    ]) ||
    input.contract_version !== 1 ||
    input.path !== expectedPath ||
    input.encoding !== 'utf-8' ||
    typeof input.content !== 'string' ||
    !isMimeType(input.mime_type) ||
    !isNonNegativeInteger(input.size_bytes) ||
    !isRevision(input.revision) ||
    typeof input.truncated !== 'boolean' ||
    input.size_bytes > maxBytes ||
    new TextEncoder().encode(input.content).byteLength > maxBytes
  ) {
    throw new Error('sandbox file content contract is invalid');
  }
  return {
    contract_version: 1,
    ...authority,
    path: expectedPath,
    encoding: 'utf-8',
    content: input.content,
    mime_type: input.mime_type,
    size_bytes: input.size_bytes,
    revision: input.revision,
    truncated: input.truncated,
  };
}

function parseFileAuthority(
  input: unknown,
  mode: DesktopRuntimeConfig['mode'],
): SandboxFileAuthority {
  if (!isRecord(input)) {
    throw new Error('sandbox file authority contract is invalid');
  }
  if (mode === 'cloud' && input.authority === 'sandbox' && input.isolation === 'isolated') {
    return { authority: 'sandbox', isolation: 'isolated' };
  }
  if (
    mode === 'local' &&
    input.authority === 'native_workspace' &&
    input.isolation === 'not_applicable'
  ) {
    return {
      authority: 'native_workspace',
      isolation: 'not_applicable',
    };
  }
  throw new Error('sandbox file authority contract is invalid');
}

export function parseDownloadAuthority(
  response: Response,
  mode: DesktopRuntimeConfig['mode'],
): SandboxFileAuthority {
  if (response.headers.get('x-memstack-file-contract-version') !== '1') {
    throw new Error('sandbox file authority contract is invalid');
  }
  return parseFileAuthority(
    {
      authority: response.headers.get('x-memstack-file-authority'),
      isolation: response.headers.get('x-memstack-file-isolation'),
    },
    mode,
  );
}

function requireProjectId(config: DesktopRuntimeConfig): string {
  const projectId = config.projectId.trim();
  if (!projectId) throw new Error('sandbox project scope is unavailable');
  return projectId;
}

export function requireSandboxPath(input: string): string {
  if (
    !input.startsWith('/') ||
    input.includes('\0') ||
    input.includes('\\') ||
    input.split('/').some((segment) => segment === '..' || segment === '.')
  ) {
    throw new Error('sandbox file path is invalid');
  }
  return input;
}

export function requireBoundedInteger(
  input: number,
  minimum: number,
  maximum: number,
  field: string,
): number {
  if (!Number.isInteger(input) || input < minimum || input > maximum) {
    throw new Error(`sandbox ${field} is invalid`);
  }
  return input;
}

export function parseContentLength(input: string | null): number | null {
  if (input === null) return null;
  const value = Number(input);
  return isNonNegativeInteger(value) ? value : null;
}

export function downloadFilename(contentDisposition: string | null, path: string): string {
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/iu)?.[1];
  let decoded = '';
  if (encoded) {
    try {
      decoded = decodeURIComponent(encoded.trim());
    } catch {
      decoded = '';
    }
  }
  const match = contentDisposition?.match(/filename="([^"]+)"/iu);
  const candidate = decoded || match?.[1]?.trim() || path.split('/').at(-1) || 'download';
  if (!candidate || candidate.includes('/') || candidate.includes('\\')) return 'download';
  return candidate;
}

export function normalizedMimeType(input: string | null): string | null {
  const value = input?.split(';', 1)[0]?.trim().toLowerCase();
  return value && isMimeType(value) ? value : null;
}

function hasExactKeys(input: Record<string, unknown>, expected: string[]): boolean {
  const actual = Object.keys(input).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isNonNegativeInteger(input: unknown): input is number {
  return typeof input === 'number' && Number.isInteger(input) && input >= 0;
}

function isMimeType(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    input.length <= 127 &&
    /^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+-]*$/iu.test(input)
  );
}

function isRevision(input: unknown): input is string {
  return typeof input === 'string' && input.length > 0 && input.length <= 256;
}
