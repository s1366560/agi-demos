import { absoluteUrl, desktopApiCredential } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  AcceptedInvitation,
  InvitationVerification,
} from './invitationAcceptanceModel';

type Fetch = typeof globalThis.fetch;

export type InvitationAcceptanceClient = Readonly<{
  verify(
    token: string,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<InvitationVerification>;
  accept(
    token: string,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<AcceptedInvitation>;
}>;

export class InvitationAcceptanceError extends Error {
  readonly reasonCode: string;
  readonly status: number | null;

  constructor(reasonCode: string, status: number | null = null) {
    super(reasonCode);
    this.name = 'InvitationAcceptanceError';
    this.reasonCode = reasonCode;
    this.status = status;
  }
}

export function createInvitationAcceptanceClient(
  config: DesktopRuntimeConfig,
  dependencies: Readonly<{ fetch?: Fetch }> = {},
): InvitationAcceptanceClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchImpl = dependencies.fetch ?? globalThis.fetch;
  const ensureCloud = () => {
    if (runtimeConfig.mode !== 'cloud') {
      throw new InvitationAcceptanceError(
        'local_tenant_invitation_not_applicable',
      );
    }
  };
  return Object.freeze({
    async verify(token, options) {
      ensureCloud();
      if (!validToken(token)) {
        throw new InvitationAcceptanceError('invitation_token_invalid');
      }
      const response = await fetchImpl(
        invitationUrl(runtimeConfig.apiBaseUrl, 'verify', token),
        {
          method: 'GET',
          headers: new Headers({ Accept: 'application/json' }),
          signal: options?.signal,
        },
      );
      const payload = await jsonPayload(response);
      if (!response.ok) {
        throw new InvitationAcceptanceError(
          reasonCodeForStatus(response.status, 'verification'),
          response.status,
        );
      }
      if (!isInvitationVerification(payload)) {
        if (isExactRecord(payload, ['valid']) && payload.valid === false) {
          throw new InvitationAcceptanceError('invitation_token_invalid');
        }
        throw new InvitationAcceptanceError(
          'invitation_verification_contract_invalid',
          response.status,
        );
      }
      return Object.freeze({ ...payload });
    },
    async accept(token, options) {
      ensureCloud();
      if (!validToken(token)) {
        throw new InvitationAcceptanceError('invitation_token_invalid');
      }
      const credential = desktopApiCredential(runtimeConfig);
      if (!credential) {
        throw new InvitationAcceptanceError(
          'invitation_acceptance_authentication_required',
          401,
        );
      }
      const response = await fetchImpl(
        invitationUrl(runtimeConfig.apiBaseUrl, 'accept', token),
        {
          method: 'POST',
          headers: new Headers({
            Accept: 'application/json',
            Authorization: `Bearer ${credential}`,
            'Content-Type': 'application/json',
          }),
          signal: options?.signal,
          body: '{}',
        },
      );
      const payload = await jsonPayload(response);
      if (!response.ok) {
        throw new InvitationAcceptanceError(
          reasonCodeForStatus(response.status, 'acceptance'),
          response.status,
        );
      }
      if (!isAcceptedInvitation(payload)) {
        throw new InvitationAcceptanceError(
          'invitation_acceptance_contract_invalid',
          response.status,
        );
      }
      return Object.freeze({ ...payload });
    },
  });
}

function invitationUrl(
  apiBaseUrl: string,
  action: 'verify' | 'accept',
  token: string,
): string {
  return absoluteUrl(
    apiBaseUrl,
    `/api/v1/invitations/${action}/${encodeURIComponent(token)}`,
  );
}

async function jsonPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  return contentType.toLowerCase().includes('application/json')
    ? response.json().catch(() => null)
    : null;
}

function reasonCodeForStatus(
  status: number,
  phase: 'verification' | 'acceptance',
): string {
  if (status === 400) return 'invitation_token_invalid_or_expired';
  if (status === 401) return 'invitation_acceptance_authentication_required';
  if (status === 403) return 'invitation_acceptance_forbidden';
  if (status === 404 || status === 410) return 'invitation_token_invalid_or_expired';
  if (status === 409) return 'invitation_acceptance_conflict';
  if (status === 429) return 'invitation_acceptance_rate_limited';
  if (status === 502 || status === 503 || status === 504) {
    return 'invitation_authority_unavailable';
  }
  return phase === 'verification'
    ? 'invitation_verification_failed'
    : 'invitation_acceptance_failed';
}

function isInvitationVerification(value: unknown): value is InvitationVerification {
  return (
    isExactRecord(value, ['valid', 'email', 'tenant_id', 'role', 'expires_at']) &&
    value.valid === true &&
    isString(value.email) &&
    isNonEmptyString(value.tenant_id) &&
    isNonEmptyString(value.role) &&
    isNonEmptyString(value.expires_at)
  );
}

function isAcceptedInvitation(value: unknown): value is AcceptedInvitation {
  return (
    isExactRecord(value, [
      'id',
      'tenant_id',
      'email',
      'role',
      'status',
      'invited_by',
      'expires_at',
      'created_at',
    ]) &&
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.tenant_id) &&
    isString(value.email) &&
    isNonEmptyString(value.role) &&
    value.status === 'accepted' &&
    isNonEmptyString(value.invited_by) &&
    isNonEmptyString(value.expires_at) &&
    isNonEmptyString(value.created_at)
  );
}

function validToken(value: string): boolean {
  return value.length > 0 && value.length <= 512;
}

function isExactRecord(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length &&
    actual.every((key, index) => key === expected[index]);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
