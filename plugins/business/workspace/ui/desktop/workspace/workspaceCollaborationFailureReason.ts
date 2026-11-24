/** Select a bounded protocol code without exposing arbitrary upstream error text. */
export function workspaceCollaborationFailureReason(error: unknown, fallback: string): string {
  if (!isRecord(error)) return fallback;
  const payload = isRecord(error.payload) ? error.payload : null;
  const detail = payload && isRecord(payload.detail) ? payload.detail : null;
  for (const value of [detail?.reason_code, error.reason_code, error.reasonCode, error.code]) {
    if (typeof value === 'string' && /^[a-z][a-z0-9_:-]{0,255}$/.test(value)) return value;
  }
  return fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
