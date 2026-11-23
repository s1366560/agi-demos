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

export const SANDBOX_RUNTIME_CAPABILITIES_UNAVAILABLE: SandboxRuntimeCapabilities = Object.freeze({
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
  listFiles(projectId: string, path: string, signal?: AbortSignal): Promise<SandboxFileListing>;
  readFile(projectId: string, path: string, signal?: AbortSignal): Promise<ArrayBuffer>;
  downloadFile(projectId: string, path: string, signal?: AbortSignal): Promise<Blob>;
};

type ListFilesOperation = {
  (projectId: string, path: string, signal?: AbortSignal): Promise<SandboxFileListing>;
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
  createTerminalSession(
    projectId: string,
    runId: string,
    expectedRunRevision: number,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<TerminalSessionV2>>;
  resumeTerminalSession(
    projectId: string,
    sessionId: string,
    resumeToken: string,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<TerminalSessionV2>>;
  listFiles: ListFilesOperation;
  readFile: ReadFileOperation;
  downloadFile: DownloadFileOperation;
};

export type SandboxRuntimeFileClient = {
  listFiles(
    request: SandboxFileListRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileListing>>;
  readFile(
    request: SandboxFileReadRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileContent>>;
  downloadFile(
    request: SandboxFileDownloadRequest,
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<SandboxFileDownload>>;
};

export type KasmProxySession = {
  contract_version: 1;
  project_id: string;
  protocol: 'kasmvnc-1';
  proxy_url: string;
  auth_mode: 'scoped_http_only_cookie';
};

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
): SandboxRuntimeClient {
  if (!isSandboxRuntimeAuthority(authority))
    throw new Error('sandbox runtime authority is required');
  return wrapSandboxRuntimeAuthority(authority);
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
    ) =>
      authority
        .createTerminalSession(projectId, runId, expectedRunRevision, signal)
        .then((value) => ({ status: 'ready' as const, value })),
    resumeTerminalSession: (
      projectId: string,
      sessionId: string,
      resumeToken: string,
      signal?: AbortSignal,
    ) =>
      authority
        .resumeTerminalSession(projectId, sessionId, resumeToken, signal)
        .then((value) => ({ status: 'ready' as const, value })),
    listFiles: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.listFiles(projectId, path, signal)) as ListFilesOperation,
    readFile: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.readFile(projectId, path, signal)) as ReadFileOperation,
    downloadFile: ((projectId: string, path: string, signal?: AbortSignal) =>
      authority.downloadFile(projectId, path, signal)) as DownloadFileOperation,
  });
}

function isSandboxRuntimeAuthority(input: unknown): input is SandboxRuntimeAuthority {
  return (
    isRecord(input) &&
    typeof (input as Partial<SandboxRuntimeAuthority>).createTerminalSession === 'function' &&
    typeof (input as Partial<SandboxRuntimeAuthority>).resumeTerminalSession === 'function' &&
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
