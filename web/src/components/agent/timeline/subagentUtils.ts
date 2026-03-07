/**
 * Shared utilities for SubAgent timeline components.
 *
 * Extracted from SubAgentTimeline.tsx and SubAgentDetailPanel.tsx to
 * eliminate code duplication.
 */

export const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

export const formatTokens = (count: number): string => {
  if (count < 1000) return `${count}`;
  return `${(count / 1000).toFixed(1)}k`;
};

/**
 * Maps a SubAgent status to a human-readable i18n key suffix.
 */
export const STATUS_LABEL_KEYS: Record<string, string> = {
  running: 'agent.subagent.status.running',
  success: 'agent.subagent.status.success',
  error: 'agent.subagent.status.error',
  background: 'agent.subagent.status.background',
  queued: 'agent.subagent.status.queued',
  killed: 'agent.subagent.status.killed',
  steered: 'agent.subagent.status.steered',
  depth_limited: 'agent.subagent.status.depth_limited',
};

/**
 * Fallback labels when i18n is not available.
 */
export const STATUS_LABEL_FALLBACKS: Record<string, string> = {
  running: 'Running',
  success: 'Completed',
  error: 'Failed',
  background: 'Background',
  queued: 'Waiting',
  killed: 'Stopped',
  steered: 'Redirected',
  depth_limited: 'Depth limit',
};

/**
 * Status pill color classes (text + background).
 */
export const STATUS_PILL_CLASSES: Record<string, string> = {
  running: 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/40',
  success: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40',
  error: 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/40',
  background: 'text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/40',
  queued: 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800/40',
  killed: 'text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40',
  steered: 'text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40',
  depth_limited: 'text-orange-600 dark:text-orange-400 bg-orange-100 dark:bg-orange-900/40',
};

/**
 * Card left-border color classes keyed by status.
 */
export const STATUS_BORDER_CLASSES: Record<string, string> = {
  running: 'border-l-blue-500',
  success: 'border-l-emerald-500',
  error: 'border-l-red-500',
  background: 'border-l-purple-500',
  queued: 'border-l-gray-400',
  killed: 'border-l-amber-500',
  steered: 'border-l-amber-500',
  depth_limited: 'border-l-orange-500',
};

/**
 * Maps raw error strings from the backend to user-friendly i18n keys.
 * Returns the original error string if no mapping is found.
 */
export const ERROR_PATTERNS: Array<{ pattern: RegExp; key: string; fallback: string }> = [
  {
    pattern: /cancelled by steer restart/i,
    key: 'agent.subagent.error.steer_restart',
    fallback: 'Stopped: agent was redirected to a new task',
  },
  {
    pattern: /max.*depth.*exceeded/i,
    key: 'agent.subagent.error.depth_exceeded',
    fallback: 'Stopped: maximum delegation depth reached',
  },
  {
    pattern: /timeout|timed?\s*out/i,
    key: 'agent.subagent.error.timeout',
    fallback: 'Stopped: execution timed out',
  },
  {
    pattern: /killed|terminated/i,
    key: 'agent.subagent.error.killed',
    fallback: 'Stopped: execution was terminated',
  },
  {
    pattern: /rate.?limit/i,
    key: 'agent.subagent.error.rate_limit',
    fallback: 'Paused: rate limit reached, will retry',
  },
  {
    pattern: /context.?length|token.?limit/i,
    key: 'agent.subagent.error.context_length',
    fallback: 'Failed: context window exceeded',
  },
  {
    pattern: /permission.?denied|unauthorized|forbidden/i,
    key: 'agent.subagent.error.permission',
    fallback: 'Failed: insufficient permissions',
  },
  {
    pattern: /connection|network|ECONNREFUSED/i,
    key: 'agent.subagent.error.connection',
    fallback: 'Failed: connection error',
  },
];

/**
 * Resolves a SubAgent display name with proper fallbacks.
 */
export const resolveSubAgentName = (
  subagentName: string | undefined | null,
  subagentId: string | undefined | null,
  fallbackLabel: string
): string => {
  if (subagentName && subagentName.trim().length > 0) return subagentName;
  if (subagentId && subagentId.length > 0) return subagentId.slice(0, 8);
  return fallbackLabel;
};
