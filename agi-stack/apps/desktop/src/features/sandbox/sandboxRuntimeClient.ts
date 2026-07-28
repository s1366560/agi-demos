import type { DesktopRuntimeConfig } from '../../types';
import type { TerminalSessionV2 } from './terminalSessionV2';

export type SandboxRuntimeCapability = {
  availability: 'available' | 'degraded' | 'unavailable' | 'not_applicable';
  contract_version: number;
  reason_code: string | null;
};

export type SandboxRuntimeCapabilities = {
  terminal_interactive: SandboxRuntimeCapability;
  terminal_resume: SandboxRuntimeCapability;
  files: SandboxRuntimeCapability;
  kasm_vnc: SandboxRuntimeCapability;
};

export const SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE: SandboxRuntimeCapabilities =
  Object.freeze({
    terminal_interactive: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'terminal_interactive_unavailable',
    },
    terminal_resume: {
      availability: 'unavailable',
      contract_version: 2,
      reason_code: 'terminal_session_v2_unavailable',
    },
    files: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'sandbox_file_api_unavailable',
    },
    kasm_vnc: {
      availability: 'unavailable',
      contract_version: 1,
      reason_code: 'kasm_proxy_contract_unavailable',
    },
  });

export type SandboxFileEntry = {
  path: string;
  name: string;
  kind: 'file' | 'directory';
  size_bytes: number | null;
  mime_type: string | null;
};

export type SandboxFileAuthority =
  | { authority: 'sandbox'; isolation: 'isolated' }
  | { authority: 'native_workspace'; isolation: 'not_applicable' };

export type SandboxFileListing = SandboxFileAuthority & {
  contract_version: 1;
  root: string;
  path: string;
  entries: SandboxFileEntry[];
  cursor?: string | null;
  revision: number | string;
};

export type SandboxFileContent = SandboxFileAuthority & {
  contract_version: 1;
  path: string;
  encoding: 'utf-8';
  content: string;
  mime_type: string;
  size_bytes: number;
  revision: string;
  truncated: boolean;
};

export type SandboxFileDownload = SandboxFileAuthority & {
  contract_version: 1;
  path: string;
  filename: string;
  mime_type: string;
  bytes: Blob;
};

export type SandboxFileListRequest = {
  path: string;
  limit?: number;
  cursor?: string;
};

export type SandboxFileReadRequest = {
  path: string;
  max_bytes?: number;
};

export type SandboxFileDownloadRequest = {
  path: string;
  max_bytes?: number;
};

export type SandboxRuntimeResult<T> =
  | { status: 'ready'; value: T }
  | { status: 'unavailable'; reason_code: string };

export type SandboxRuntimeAuthority = {
  createTerminalSession(
    projectId: string,
    runId: string,
    expectedRunRevision: number,
    signal?: AbortSignal,
  ): Promise<TerminalSessionV2>;
  resumeTerminalSession(
    projectId: string,
    sessionId: string,
    resumeToken: string,
    signal?: AbortSignal,
  ): Promise<TerminalSessionV2>;
  listFiles(
    projectId: string,
    path: string,
    signal?: AbortSignal,
  ): Promise<SandboxFileListing>;
  readFile(projectId: string, path: string, signal?: AbortSignal): Promise<ArrayBuffer>;
  downloadFile(projectId: string, path: string, signal?: AbortSignal): Promise<Blob>;
};

type ListFilesOperation = {
  (
    projectId: string,
    path: string,
    signal?: AbortSignal,
  ): Promise<SandboxFileListing>;
  (
    request: SandboxFileListRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileListing>>;
};

type ReadFileOperation = {
  (projectId: string, path: string, signal?: AbortSignal): Promise<ArrayBuffer>;
  (
    request: SandboxFileReadRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileContent>>;
};

type DownloadFileOperation = {
  (projectId: string, path: string, signal?: AbortSignal): Promise<Blob>;
  (
    request: SandboxFileDownloadRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileDownload>>;
};

export type SandboxRuntimeClient = {
  createTerminalSession: SandboxRuntimeAuthority['createTerminalSession'];
  resumeTerminalSession: SandboxRuntimeAuthority['resumeTerminalSession'];
  listFiles: ListFilesOperation;
  readFile: ReadFileOperation;
  downloadFile: DownloadFileOperation;
};

export type KasmProxySession = {
  contract_version: 1;
  project_id: string;
  protocol: 'kasmvnc-1';
  proxy_url: string;
  auth_mode: 'scoped_http_only_cookie';
};

const MAX_LIST_LIMIT = 500;
const DEFAULT_READ_LIMIT = 1_048_576;
const DEFAULT_DOWNLOAD_LIMIT = 25 * 1_048_576;
const JSON_RESPONSE_LIMIT = 2 * 1_048_576;

export function terminalInteractiveCapability(
  connectedToBoundSession: boolean,
): SandboxRuntimeCapability {
  return connectedToBoundSession
    ? {
        availability: 'available',
        contract_version: 1,
        reason_code: null,
      }
    : {
        availability: 'unavailable',
        contract_version: 1,
        reason_code: 'terminal_interactive_session_unavailable',
      };
}

export function createSandboxRuntimeClient(
  authority: SandboxRuntimeAuthority,
): SandboxRuntimeClient;
export function createSandboxRuntimeClient(
  config: DesktopRuntimeConfig,
  capabilities: SandboxRuntimeCapabilities,
): SandboxRuntimeClient;
export function createSandboxRuntimeClient(
  configOrAuthority: DesktopRuntimeConfig | SandboxRuntimeAuthority,
  capabilities?: SandboxRuntimeCapabilities,
): SandboxRuntimeClient {
  if (isSandboxRuntimeAuthority(configOrAuthority) && capabilities === undefined) {
    return wrapSandboxRuntimeAuthority(configOrAuthority);
  }
  if (isSandboxRuntimeAuthority(configOrAuthority)) {
    throw new Error('sandbox runtime client configuration is invalid');
  }
  return createHttpSandboxRuntimeClient(
    configOrAuthority,
    capabilities ?? SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE,
  );
}

export function parseKasmProxySession(
  input: unknown,
  expectedProjectId: string,
): KasmProxySession | null {
  if (!isRecord(input)) return null;
  if (
    !hasExactKeys(input, [
      'auth_mode',
      'contract_version',
      'project_id',
      'protocol',
      'proxy_url',
    ]) ||
    input.contract_version !== 1 ||
    input.project_id !== expectedProjectId ||
    input.protocol !== 'kasmvnc-1' ||
    input.auth_mode !== 'scoped_http_only_cookie' ||
    typeof input.proxy_url !== 'string'
  ) {
    return null;
  }

  const expectedProxyUrl = `/api/v1/projects/${encodeURIComponent(
    expectedProjectId,
  )}/sandbox/desktop/proxy/vnc.html`;
  if (input.proxy_url !== expectedProxyUrl) {
    return null;
  }

  return {
    contract_version: 1,
    project_id: expectedProjectId,
    protocol: 'kasmvnc-1',
    proxy_url: input.proxy_url,
    auth_mode: 'scoped_http_only_cookie',
  };
}

function wrapSandboxRuntimeAuthority(authority: SandboxRuntimeAuthority): SandboxRuntimeClient {
  return Object.freeze({
    createTerminalSession: (
      projectId: string,
      runId: string,
      expectedRunRevision: number,
      signal?: AbortSignal,
    ) => authority.createTerminalSession(projectId, runId, expectedRunRevision, signal),
    resumeTerminalSession: (
      projectId: string,
      sessionId: string,
      resumeToken: string,
      signal?: AbortSignal,
    ) => authority.resumeTerminalSession(projectId, sessionId, resumeToken, signal),
    listFiles: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.listFiles(projectId, path, signal)) as ListFilesOperation,
    readFile: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.readFile(projectId, path, signal)) as ReadFileOperation,
    downloadFile: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.downloadFile(projectId, path, signal)) as DownloadFileOperation,
  });
}

function createHttpSandboxRuntimeClient(
  config: DesktopRuntimeConfig,
  capabilities: SandboxRuntimeCapabilities,
): SandboxRuntimeClient {
  const unavailableTerminal = async (): Promise<TerminalSessionV2> => {
    throw new Error(
      capabilities.terminal_resume.reason_code ?? 'terminal_session_v2_unavailable',
    );
  };

  return Object.freeze({
    createTerminalSession: unavailableTerminal,
    resumeTerminalSession: unavailableTerminal,
    listFiles: (async (
      request: SandboxFileListRequest,
      signal?: AbortSignal,
    ): Promise<SandboxRuntimeResult<SandboxFileListing>> => {
      const unavailable = unavailableResult(capabilities.files);
      if (unavailable) return unavailable;
      const projectId = requireProjectId(config);
      const path = requireSandboxPath(request.path);
      const limit = requireBoundedInteger(request.limit ?? 200, 1, MAX_LIST_LIMIT, 'limit');
      const query = new URLSearchParams({ path, limit: String(limit) });
      if (request.cursor) query.set('cursor', request.cursor);
      const payload = await requestJson(
        config,
        `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/files?${query}`,
        signal,
      );
      return {
        status: 'ready',
        value: parseFileListing(payload, path, config.mode),
      };
    }) as ListFilesOperation,
    readFile: (async (
      request: SandboxFileReadRequest,
      signal?: AbortSignal,
    ): Promise<SandboxRuntimeResult<SandboxFileContent>> => {
      const unavailable = unavailableResult(capabilities.files);
      if (unavailable) return unavailable;
      const projectId = requireProjectId(config);
      const path = requireSandboxPath(request.path);
      const maxBytes = requireBoundedInteger(
        request.max_bytes ?? DEFAULT_READ_LIMIT,
        1,
        DEFAULT_READ_LIMIT,
        'max_bytes',
      );
      const query = new URLSearchParams({ path, max_bytes: String(maxBytes) });
      const payload = await requestJson(
        config,
        `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/files/content?${query}`,
        signal,
      );
      return {
        status: 'ready',
        value: parseFileContent(payload, path, maxBytes, config.mode),
      };
    }) as ReadFileOperation,
    downloadFile: (async (
      request: SandboxFileDownloadRequest,
      signal?: AbortSignal,
    ): Promise<SandboxRuntimeResult<SandboxFileDownload>> => {
      const unavailable = unavailableResult(capabilities.files);
      if (unavailable) return unavailable;
      const projectId = requireProjectId(config);
      const path = requireSandboxPath(request.path);
      const maxBytes = requireBoundedInteger(
        request.max_bytes ?? DEFAULT_DOWNLOAD_LIMIT,
        1,
        DEFAULT_DOWNLOAD_LIMIT,
        'max_bytes',
      );
      const query = new URLSearchParams({ path, max_bytes: String(maxBytes) });
      const response = await requestResponse(
        config,
        `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/files/download?${query}`,
        signal,
      );
      const declaredSize = parseContentLength(response.headers.get('content-length'));
      if (declaredSize !== null && declaredSize > maxBytes) {
        throw new Error('sandbox file exceeds the download limit');
      }
      const bytes = await response.blob();
      if (bytes.size > maxBytes) {
        throw new Error('sandbox file exceeds the download limit');
      }
      const authority = parseDownloadAuthority(response, config.mode);
      return {
        status: 'ready',
        value: {
          contract_version: 1,
          ...authority,
          path,
          filename: downloadFilename(response.headers.get('content-disposition'), path),
          mime_type:
            normalizedMimeType(response.headers.get('content-type')) ??
            'application/octet-stream',
          bytes,
        },
      };
    }) as DownloadFileOperation,
  });
}

function unavailableResult(
  capability: SandboxRuntimeCapability,
): { status: 'unavailable'; reason_code: string } | null {
  if (capability.availability === 'available') return null;
  return {
    status: 'unavailable',
    reason_code: capability.reason_code ?? 'sandbox_file_api_unavailable',
  };
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const response = await requestResponse(config, path, signal);
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new Error('sandbox file response is not JSON');
  }
  const declaredSize = parseContentLength(response.headers.get('content-length'));
  if (declaredSize !== null && declaredSize > JSON_RESPONSE_LIMIT) {
    throw new Error('sandbox file response exceeds the metadata limit');
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > JSON_RESPONSE_LIMIT) {
    throw new Error('sandbox file response exceeds the metadata limit');
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error('sandbox file response is malformed');
  }
}

async function requestResponse(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
): Promise<Response> {
  const headers = new Headers({ Accept: 'application/json' });
  const apiKey = config.apiKey.trim();
  if (apiKey) headers.set('Authorization', `Bearer ${apiKey}`);
  const launchCapability = config.mode === 'local' ? config.localApiToken.trim() : '';
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);

  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    headers,
    signal,
    credentials: 'same-origin',
  });
  if (!response.ok) {
    throw new Error(`sandbox file request failed with HTTP ${response.status}`);
  }
  return response;
}

function parseFileListing(
  input: unknown,
  expectedPath: string,
  mode: DesktopRuntimeConfig['mode'],
): SandboxFileListing {
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

function parseFileContent(
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
  if (
    mode === 'cloud' &&
    input.authority === 'sandbox' &&
    input.isolation === 'isolated'
  ) {
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

function parseDownloadAuthority(
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

function requireSandboxPath(input: string): string {
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

function requireBoundedInteger(
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

function parseContentLength(input: string | null): number | null {
  if (input === null) return null;
  const value = Number(input);
  return isNonNegativeInteger(value) ? value : null;
}

function downloadFilename(contentDisposition: string | null, path: string): string {
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
  const candidate =
    decoded || match?.[1]?.trim() || path.split('/').at(-1) || 'download';
  if (!candidate || candidate.includes('/') || candidate.includes('\\')) return 'download';
  return candidate;
}

function normalizedMimeType(input: string | null): string | null {
  const value = input?.split(';', 1)[0]?.trim().toLowerCase();
  return value && isMimeType(value) ? value : null;
}

function isSandboxRuntimeAuthority(
  input: DesktopRuntimeConfig | SandboxRuntimeAuthority,
): input is SandboxRuntimeAuthority {
  return (
    typeof (input as Partial<SandboxRuntimeAuthority>).createTerminalSession ===
      'function' &&
    typeof (input as Partial<SandboxRuntimeAuthority>).resumeTerminalSession ===
      'function' &&
    typeof (input as Partial<SandboxRuntimeAuthority>).listFiles === 'function' &&
    typeof (input as Partial<SandboxRuntimeAuthority>).readFile === 'function' &&
    typeof (input as Partial<SandboxRuntimeAuthority>).downloadFile === 'function'
  );
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

function absoluteUrl(baseUrl: string, path: string): string {
  return `${baseUrl.trim().replace(/\/+$/u, '')}${path.startsWith('/') ? path : `/${path}`}`;
}
