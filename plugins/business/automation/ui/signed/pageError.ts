export const getErrorMessage = (cause: unknown) =>
  cause instanceof Error ? cause.message : String(cause);
