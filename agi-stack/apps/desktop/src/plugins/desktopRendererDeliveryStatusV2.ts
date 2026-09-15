const CREDENTIAL_REQUIRED = 'renderer_credential_required';

export type DesktopRendererDeliveryUnavailableV2 = Readonly<{
  status: 'unavailable';
  reason_code: typeof CREDENTIAL_REQUIRED;
}>;

/** Preserve the exact sidecar protocol failure across Electron's error boundary. */
export function desktopRendererDeliveryUnavailableV2(
  error: unknown,
): DesktopRendererDeliveryUnavailableV2 | null {
  return error instanceof Error && error.message === CREDENTIAL_REQUIRED
    ? Object.freeze({ status: 'unavailable', reason_code: CREDENTIAL_REQUIRED })
    : null;
}

export function assertDesktopRendererDeliveryAvailableV2(value: unknown): void {
  if (
    value !== null &&
    typeof value === 'object' &&
    'status' in value && value.status === 'unavailable' &&
    'reason_code' in value && value.reason_code === CREDENTIAL_REQUIRED &&
    Object.keys(value).length === 2
  ) {
    throw Object.assign(new Error(CREDENTIAL_REQUIRED), { code: CREDENTIAL_REQUIRED });
  }
}

export function isDesktopRendererCredentialRequiredV2(error: unknown): boolean {
  return error instanceof Error && 'code' in error && error.code === CREDENTIAL_REQUIRED;
}
