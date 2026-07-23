/**
 * Shared formatting helpers.
 */

/**
 * Format a byte count as a human-readable file size (B/KB/MB/GB).
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

/**
 * Format a millisecond duration as a compact human-readable string
 * (e.g. 420ms / 1.5s / 2.3m). Used for tool execution durations.
 */
export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${String(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

/**
 * Format a second-based duration badge (e.g. 45s / 2m 5s).
 */
export function formatDurationSeconds(seconds: number): string {
  if (seconds < 60) return `${String(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${String(mins)}m ${String(secs)}s`;
}

/**
 * Format a second-based duration as a MM:SS clock timer (voice call elapsed time).
 */
export function formatCallDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}
