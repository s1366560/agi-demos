/**
 * Shared formatting helpers and status icon for multiAgent trace views
 * (TraceChainView, TraceTimeline).
 */

import { AlertCircle, CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react';

export function formatDuration(ms: number | null): string {
  if (ms === null) return '-';
  if (ms < 1000) return `${String(ms)}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${String(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes)}m ${String(remainingSeconds)}s`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return '-';
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

export function StatusIcon({ status, size = 16 }: { status: string; size?: number }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={size} className="text-green-600 dark:text-green-400" />;
    case 'failed':
      return <AlertCircle size={size} className="text-red-600 dark:text-red-400" />;
    case 'running':
      return (
        <Loader2
          size={size}
          className="text-blue-600 dark:text-blue-400 animate-spin motion-reduce:animate-none"
        />
      );
    case 'cancelled':
      return <XCircle size={size} className="text-amber-600 dark:text-amber-400" />;
    default:
      return <Clock size={size} className="text-slate-400 dark:text-slate-500" />;
  }
}
