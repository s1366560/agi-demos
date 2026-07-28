import { absoluteUrl } from '../../api/client';

export const TERMINAL_SESSION_V2_CONTRACT_VERSION = 2 as const;
export const TERMINAL_SESSION_V2_MIN_CONTRACT_VERSION =
  TERMINAL_SESSION_V2_CONTRACT_VERSION;
const TERMINAL_RECONNECT_LIMIT = 5;
const TERMINAL_RECONNECT_BASE_DELAY_MS = 1_000;
const TERMINAL_RECONNECT_MAX_DELAY_MS = 8_000;

export type TerminalSessionV2 = {
  contract_version: number;
  session_id: string;
  resume_token: string;
  project_id: string;
  conversation_id: string;
  run_id: string;
  run_revision: number;
  environment_id: string;
  cwd: string;
  created_at: string;
  expires_at: string;
  resumable: true;
};

export type TerminalDisconnectEvent =
  | { kind: 'normal_close' }
  | { kind: 'abnormal_close' }
  | { kind: 'session_lost' }
  | { kind: 'authority_revoked' }
  | { kind: 'output_gap' }
  | { kind: 'input_overload' };

export type TerminalReconnectDecision =
  | { action: 'resume'; delay_ms: number }
  | {
      action: 'refetch_run' | 'stop';
      reason_code:
        | 'terminal_authority_revoked'
        | 'terminal_closed'
        | 'terminal_reconnect_exhausted'
        | 'terminal_session_expired'
        | 'terminal_session_lost'
        | 'terminal_output_gap'
        | 'terminal_input_overload';
    };

export function parseTerminalSessionV2(
  input: unknown,
  nowMs = Date.now(),
): TerminalSessionV2 | null {
  if (!isRecord(input)) return null;
  if (
    !Number.isSafeInteger(input.contract_version) ||
    Number(input.contract_version) < TERMINAL_SESSION_V2_MIN_CONTRACT_VERSION ||
    input.resumable !== true ||
    !isNonEmptyString(input.session_id) ||
    !isNonEmptyString(input.resume_token) ||
    !isNonEmptyString(input.project_id) ||
    !isNonEmptyString(input.conversation_id) ||
    !isNonEmptyString(input.run_id) ||
    !Number.isSafeInteger(input.run_revision) ||
    Number(input.run_revision) < 1 ||
    !isNonEmptyString(input.environment_id) ||
    input.cwd !== '/workspace' ||
    !isNonEmptyString(input.created_at) ||
    !isNonEmptyString(input.expires_at)
  ) {
    return null;
  }
  const createdAtMs = Date.parse(input.created_at);
  const expiresAtMs = Date.parse(input.expires_at);
  if (
    !Number.isFinite(createdAtMs) ||
    !Number.isFinite(expiresAtMs) ||
    expiresAtMs <= createdAtMs ||
    expiresAtMs <= nowMs
  ) {
    return null;
  }
  return {
    contract_version: Number(input.contract_version),
    session_id: input.session_id.trim(),
    resume_token: input.resume_token.trim(),
    project_id: input.project_id.trim(),
    conversation_id: input.conversation_id.trim(),
    run_id: input.run_id.trim(),
    run_revision: Number(input.run_revision),
    environment_id: input.environment_id.trim(),
    cwd: input.cwd.trim(),
    created_at: input.created_at,
    expires_at: input.expires_at,
    resumable: true,
  };
}

export function terminalSessionV2SocketUrl(
  apiBaseUrl: string,
  session: TerminalSessionV2,
  afterSequence = 0,
): string {
  const target = new URL(
    absoluteUrl(
      apiBaseUrl,
      `/api/v1/projects/${encodeURIComponent(
        session.project_id,
      )}/sandbox/terminal/sessions/${encodeURIComponent(session.session_id)}/ws`,
    ),
  );
  if (target.protocol === 'https:') target.protocol = 'wss:';
  else if (target.protocol === 'http:') target.protocol = 'ws:';
  else throw new Error('terminal API origin must use HTTP or HTTPS');
  if (Number.isSafeInteger(afterSequence) && afterSequence > 0) {
    target.searchParams.set('after_sequence', String(afterSequence));
  }
  return target.toString();
}

export function acceptTerminalSequence(
  currentSequence: number,
  candidateSequence: number,
): { accepted: boolean; next_sequence: number; gap?: true } {
  if (
    !Number.isSafeInteger(currentSequence) ||
    currentSequence < 0 ||
    !Number.isSafeInteger(candidateSequence) ||
    candidateSequence < 1 ||
    candidateSequence <= currentSequence
  ) {
    return {
      accepted: false,
      next_sequence:
        Number.isSafeInteger(currentSequence) && currentSequence >= 0 ? currentSequence : 0,
    };
  }
  if (candidateSequence !== currentSequence + 1) {
    return { accepted: false, next_sequence: currentSequence, gap: true };
  }
  return { accepted: true, next_sequence: candidateSequence };
}

export function terminalAcknowledgementMatches(
  currentSequence: number,
  acknowledgedSequence: number,
): boolean {
  return (
    Number.isSafeInteger(currentSequence) &&
    currentSequence >= 0 &&
    Number.isSafeInteger(acknowledgedSequence) &&
    acknowledgedSequence === currentSequence
  );
}

export function terminalReconnectDecision(
  session: TerminalSessionV2,
  event: TerminalDisconnectEvent,
  attempts: number,
  nowMs = Date.now(),
): TerminalReconnectDecision {
  if (event.kind === 'session_lost') {
    return { action: 'refetch_run', reason_code: 'terminal_session_lost' };
  }
  if (event.kind === 'authority_revoked') {
    return { action: 'refetch_run', reason_code: 'terminal_authority_revoked' };
  }
  if (event.kind === 'output_gap') {
    return { action: 'refetch_run', reason_code: 'terminal_output_gap' };
  }
  if (event.kind === 'input_overload') {
    return { action: 'stop', reason_code: 'terminal_input_overload' };
  }
  if (event.kind === 'normal_close') {
    return { action: 'stop', reason_code: 'terminal_closed' };
  }
  if (Date.parse(session.expires_at) <= nowMs) {
    return { action: 'refetch_run', reason_code: 'terminal_session_expired' };
  }
  if (!Number.isSafeInteger(attempts) || attempts < 0 || attempts >= TERMINAL_RECONNECT_LIMIT) {
    return { action: 'stop', reason_code: 'terminal_reconnect_exhausted' };
  }
  return {
    action: 'resume',
    delay_ms: Math.min(
      TERMINAL_RECONNECT_BASE_DELAY_MS * 2 ** attempts,
      TERMINAL_RECONNECT_MAX_DELAY_MS,
    ),
  };
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isNonEmptyString(input: unknown): input is string {
  return typeof input === 'string' && input.trim().length > 0;
}
