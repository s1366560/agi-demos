export type ToastKind = 'success' | 'error' | 'info';

export type Toast = Readonly<{
  id: string;
  kind: ToastKind;
  message: string;
  detail?: string;
}>;

export const MAX_VISIBLE_TOASTS = 3;

export const TOAST_AUTO_DISMISS_MS: Readonly<Record<ToastKind, number>> = Object.freeze({
  success: 5000,
  info: 5000,
  error: 8000,
});

export function toastDismissDelay(kind: ToastKind): number {
  return TOAST_AUTO_DISMISS_MS[kind];
}

export function toastAriaRole(kind: ToastKind): 'status' | 'alert' {
  return kind === 'error' ? 'alert' : 'status';
}

export type ToastIdFactory = () => string;

let fallbackToastOrdinal = 0;

function nextFallbackToastOrdinal(): number {
  fallbackToastOrdinal += 1;
  return fallbackToastOrdinal;
}

export function createToastIdFactory(
  nextOrdinal: () => number = nextFallbackToastOrdinal,
): ToastIdFactory {
  return () => `toast-${nextOrdinal().toString(36)}`;
}

export function enqueueToast(
  queue: readonly Toast[],
  toast: Toast,
  maxVisible: number = MAX_VISIBLE_TOASTS,
): Toast[] {
  const next = [...queue, toast];
  return next.length > maxVisible ? next.slice(next.length - maxVisible) : next;
}

export function dismissToastFromQueue(queue: readonly Toast[], id: string): readonly Toast[] {
  return queue.some((toast) => toast.id === id)
    ? queue.filter((toast) => toast.id !== id)
    : queue;
}

export function formatToastErrorDetail(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
