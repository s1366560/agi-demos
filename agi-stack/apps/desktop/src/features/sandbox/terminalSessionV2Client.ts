import type { DesktopRuntimeConfig } from '../../types';
import {
  parseTerminalSessionV2,
  type TerminalSessionV2,
} from './terminalSessionV2';

const TERMINAL_JSON_RESPONSE_LIMIT = 2 * 1_048_576;

type TerminalSessionReady = {
  status: 'ready';
  value: TerminalSessionV2;
};

export class SandboxTerminalSessionError extends Error {
  readonly reason_code: string;
  readonly status: number | null;

  constructor(reasonCode: string, status: number | null = null) {
    super(reasonCode);
    this.name = 'SandboxTerminalSessionError';
    this.reason_code = reasonCode;
    this.status = status;
  }
}

export async function createCloudTerminalSession(
  config: DesktopRuntimeConfig,
  requestedProjectId: string,
  runId: string,
  expectedRunRevision: number,
  signal?: AbortSignal,
): Promise<TerminalSessionReady> {
  const projectId = requireProjectScope(config, requestedProjectId);
  const normalizedRunId = requireIdentifier(runId, 'run_id');
  if (!Number.isSafeInteger(expectedRunRevision) || expectedRunRevision < 1) {
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_run_revision_invalid',
    );
  }
  const payload = await postTerminalJson(
    config,
    `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/terminal/sessions`,
    {
      run_id: normalizedRunId,
      expected_run_revision: expectedRunRevision,
    },
    signal,
  );
  const session = parseTerminalSessionV2(payload);
  if (
    session === null ||
    session.project_id !== projectId ||
    session.run_id !== normalizedRunId ||
    session.run_revision !== expectedRunRevision
  ) {
    throw new SandboxTerminalSessionError('terminal_session_v2_contract_invalid');
  }
  return { status: 'ready', value: session };
}

export async function resumeCloudTerminalSession(
  config: DesktopRuntimeConfig,
  requestedProjectId: string,
  sessionId: string,
  resumeToken: string,
  signal?: AbortSignal,
): Promise<TerminalSessionReady> {
  const projectId = requireProjectScope(config, requestedProjectId);
  const normalizedSessionId = requireIdentifier(sessionId, 'session_id');
  const normalizedResumeToken = requireIdentifier(resumeToken, 'resume_token');
  const payload = await postTerminalJson(
    config,
    `/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/sandbox/terminal/sessions/${encodeURIComponent(normalizedSessionId)}/resume`,
    { resume_token: normalizedResumeToken },
    signal,
  );
  const session = parseTerminalSessionV2(payload);
  if (
    session === null ||
    session.project_id !== projectId ||
    session.session_id !== normalizedSessionId
  ) {
    throw new SandboxTerminalSessionError('terminal_session_v2_contract_invalid');
  }
  return { status: 'ready', value: session };
}

async function postTerminalJson(
  config: DesktopRuntimeConfig,
  path: string,
  body: Readonly<Record<string, number | string>>,
  signal?: AbortSignal,
): Promise<unknown> {
  const apiKey = config.apiKey.trim();
  if (!apiKey) {
    throw new SandboxTerminalSessionError('terminal_session_v2_auth_unavailable');
  }
  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: 'POST',
    headers: new Headers({
      Accept: 'application/json',
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(body),
    signal,
    credentials: 'same-origin',
  });
  const payload = await readJson(response);
  if (!response.ok) {
    throw new SandboxTerminalSessionError(
      failureReason(payload),
      response.status,
    );
  }
  return payload;
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    if (!response.ok) return null;
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_response_not_json',
      response.status,
    );
  }
  const declaredSize = Number(response.headers.get('content-length'));
  if (
    Number.isFinite(declaredSize) &&
    declaredSize > TERMINAL_JSON_RESPONSE_LIMIT
  ) {
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_response_too_large',
      response.status,
    );
  }
  const text = await response.text();
  if (
    new TextEncoder().encode(text).byteLength > TERMINAL_JSON_RESPONSE_LIMIT
  ) {
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_response_too_large',
      response.status,
    );
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (!response.ok) return null;
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_response_malformed',
      response.status,
    );
  }
}

function failureReason(payload: unknown): string {
  if (!isRecord(payload)) return 'terminal_session_v2_request_failed';
  const detail = isRecord(payload.detail) ? payload.detail : null;
  const candidates = [
    payload.reason_code,
    payload.code,
    detail?.reason_code,
    detail?.code,
  ];
  const reasonCode = candidates.find(
    (candidate): candidate is string =>
      typeof candidate === 'string' && candidate.trim().length > 0,
  );
  return reasonCode?.trim() ?? 'terminal_session_v2_request_failed';
}

function requireProjectScope(
  config: DesktopRuntimeConfig,
  requestedProjectId: string,
): string {
  const projectId = config.projectId.trim();
  if (
    config.mode !== 'cloud' ||
    !projectId ||
    requestedProjectId.trim() !== projectId
  ) {
    throw new SandboxTerminalSessionError(
      'terminal_session_v2_project_scope_mismatch',
    );
  }
  return projectId;
}

function requireIdentifier(input: string, field: string): string {
  const value = input.trim();
  if (
    !value ||
    value.length > 4_096 ||
    [...value].some((character) => character < ' ')
  ) {
    throw new SandboxTerminalSessionError(
      `terminal_session_v2_${field}_invalid`,
    );
  }
  return value;
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function absoluteUrl(baseUrl: string, path: string): string {
  return `${baseUrl.trim().replace(/\/+$/u, '')}${path}`;
}
