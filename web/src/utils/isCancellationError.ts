/**
 * Requests in flight during a tenant switch (or a web-operation generation
 * refresh) are deliberately aborted. Those cancellations are expected noise,
 * not failures, so they must not surface as error logs or error UI.
 */
export const isCancellationError = (error: unknown): boolean => {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  const code = (error as { code?: unknown } | null)?.code;
  if (code === 'ERR_CANCELED') return true;
  return error instanceof Error && error.message === 'canceled';
};
