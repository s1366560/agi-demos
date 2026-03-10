/**
 * MCP Types and Status Utilities
 * Aligned with agent workspace design system
 */

import type { MCPServerResponse } from '@/types/agent';

// ============================================================================
// Type Definitions
// ============================================================================

export type McpTabKey = 'servers' | 'tools' | 'apps';

export type RuntimeStatus = 'running' | 'starting' | 'stopping' | 'stopped' | 'error';

export interface ServerStats {
  total: number;
  running: number;
  starting: number;
  error: number;
  disabled: number;
}

export interface AppStats {
  total: number;
  ready: number;
  error: number;
  disabled: number;
}

export interface ToolStats {
  total: number;
  available: number;
  error: number;
}

// ============================================================================
// Status Utilities
// ============================================================================

export function getRuntimeStatus(server: MCPServerResponse): RuntimeStatus {
  if (!server.enabled) return 'stopped';

  // Primary signal: top-level runtime_status from backend
  const topLevelStatus = server.runtime_status;
  if (topLevelStatus === 'running') return 'running';
  if (topLevelStatus === 'starting') return 'starting';
  if (topLevelStatus === 'stopping') return 'stopping';
  if (topLevelStatus === 'error') return 'error';
  if (topLevelStatus === 'stopped') return 'stopped';

  // Fallback: check runtime_metadata for granular state
  const runtimeState = server.runtime_metadata?.runtime_state as string;
  const isReady = server.runtime_metadata?.is_ready as boolean;

  if (runtimeState === 'running' && isReady) return 'running';
  if (runtimeState === 'starting' || runtimeState === 'pending') return 'starting';
  if (runtimeState === 'stopping') return 'stopping';
  if (runtimeState === 'stopped' || runtimeState === 'not_started') return 'stopped';

  // For newly registered servers, both are undefined.
  // Treat undefined/unknown states as 'stopped' rather than 'error'.
  if (!runtimeState || runtimeState === 'unknown') return 'stopped';

  return 'error';
}

export function getStatusColor(status: RuntimeStatus): string {
  const colors: Record<RuntimeStatus, string> = {
    running: 'text-emerald-600 dark:text-emerald-400',
    starting: 'text-blue-600 dark:text-blue-400',
    stopping: 'text-amber-600 dark:text-amber-400',
    stopped: 'text-slate-500 dark:text-slate-400',
    error: 'text-red-600 dark:text-red-400',
  };
  return colors[status];
}

export function getStatusBg(status: RuntimeStatus): string {
  const bgs: Record<RuntimeStatus, string> = {
    running: 'bg-emerald-50 dark:bg-emerald-900/20',
    starting: 'bg-blue-50 dark:bg-blue-900/20',
    stopping: 'bg-amber-50 dark:bg-amber-900/20',
    stopped: 'bg-slate-50 dark:bg-slate-800/50',
    error: 'bg-red-50 dark:bg-red-900/20',
  };
  return bgs[status];
}

export interface ServerFilters {
  search: string;
  enabled: 'all' | 'enabled' | 'disabled';
  type: 'all' | 'stdio' | 'sse' | 'remote' | 'http';
  runtime: 'all' | 'running' | 'starting' | 'stopping' | 'stopped' | 'error';
}
