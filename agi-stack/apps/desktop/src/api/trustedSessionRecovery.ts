/** Authentication failure is distinct from an unavailable authority or transport. */
export class TrustedSessionAuthenticationInvalidError extends Error {
  constructor() {
    super("trusted_session_authentication_invalid");
    this.name = "TrustedSessionAuthenticationInvalidError";
  }
}

export async function settleTrustedSessionRestoreFailure(
  error: unknown,
  clearInvalidSession: () => Promise<void>,
): Promise<"reauthenticate" | "retry"> {
  if (!(error instanceof TrustedSessionAuthenticationInvalidError))
    return "retry";
  await clearInvalidSession();
  return "reauthenticate";
}

export function decodeTrustedSessionRestoreError(value: unknown): void {
  if (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === 2 &&
    (value as Record<string, unknown>).status === "restore_error" &&
    (value as Record<string, unknown>).reason === "authentication_invalid"
  ) {
    throw new TrustedSessionAuthenticationInvalidError();
  }
}
