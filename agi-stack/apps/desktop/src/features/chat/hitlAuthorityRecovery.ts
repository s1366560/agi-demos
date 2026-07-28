import { DesktopApiError } from '../../api/client';

export type HitlAuthorityRecovery = {
  canonicalRefetch: boolean;
  settledByAuthority: boolean;
  reasonCode: string | null;
};

const SETTLED_REASON_CODES = new Set([
  'hitl_already_answered',
  'hitl_request_expired',
]);

export function classifyHitlAuthorityRecovery(
  error: unknown,
): HitlAuthorityRecovery {
  if (!(error instanceof DesktopApiError) || (error.status !== 409 && error.status !== 410)) {
    return {
      canonicalRefetch: false,
      settledByAuthority: false,
      reasonCode: null,
    };
  }
  const reasonCode = structuredReasonCode(error.payload);
  return {
    canonicalRefetch: true,
    settledByAuthority: reasonCode ? SETTLED_REASON_CODES.has(reasonCode) : false,
    reasonCode,
  };
}

function structuredReasonCode(payload: unknown): string | null {
  const root = recordValue(payload);
  if (!root) return null;
  const detail = recordValue(root.detail);
  for (const value of [
    root.reason_code,
    root.code,
    detail?.reason_code,
    detail?.code,
  ]) {
    if (
      typeof value === 'string' &&
      /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u.test(value)
    ) {
      return value;
    }
  }
  return null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
