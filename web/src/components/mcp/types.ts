/**
 * MCP UI Type Definitions
 */

import type { MCPServerResponse, MCPServerType as ServerType } from '@/types/agent';
import type { MCPApp } from '@/types/mcpApp';

export type MCPServerType = ServerType;

// ============================================================================
// Tab Types
// ============================================================================

export type McpTabKey = 'servers' | 'tools' | 'apps';

export interface McpTab {
  key: McpTabKey;
  label: string;
  icon: string;
  count: number;
}

// ============================================================================
// Runtime Status
// ============================================================================

export type RuntimeStatus = 'running' | 'starting' | 'error' | 'disabled' | 'unknown';

export interface RuntimeStatusConfig {
  dot: string;
  label: string;
  chip: string;
  icon: string;
}

export const RUNTIME_STATUS_STYLES: Record<RuntimeStatus, RuntimeStatusConfig> = {
  running: {
    dot: 'bg-emerald-500',
    label: '运行中',
    icon: 'play_circle',
    chip: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800',
  },
  starting: {
    dot: 'bg-blue-500',
    label: '启动中',
    icon: 'progress_activity',
    chip: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800',
  },
  error: {
    dot: 'bg-red-500',
    label: '错误',
    icon: 'error',
    chip: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800',
  },
  disabled: {
    dot: 'bg-slate-400',
    label: '已禁用',
    icon: 'block',
    chip: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600',
  },
  unknown: {
    dot: 'bg-amber-500',
    label: '未知',
    icon: 'help',
    chip: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800',
  },
};

// ============================================================================
// Server Type Config
// ============================================================================

export interface ServerTypeConfig {
  bg: string;
  text: string;
  border: string;
  icon: string;
  gradient: string;
}

export const SERVER_TYPE_STYLES: Record<string, ServerTypeConfig> = {
  stdio: {
    bg: 'bg-blue-50 dark:bg-blue-900/20',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-100 dark:border-blue-800',
    icon: 'terminal',
    gradient: 'from-blue-500 to-cyan-500',
  },
  sse: {
    bg: 'bg-emerald-50 dark:bg-emerald-900/20',
    text: 'text-emerald-700 dark:text-emerald-300',
    border: 'border-emerald-100 dark:border-emerald-800',
    icon: 'stream',
    gradient: 'from-emerald-500 to-teal-500',
  },
  http: {
    bg: 'bg-violet-50 dark:bg-violet-900/20',
    text: 'text-violet-700 dark:text-violet-300',
    border: 'border-violet-100 dark:border-violet-800',
    icon: 'http',
    gradient: 'from-violet-500 to-purple-500',
  },
  websocket: {
    bg: 'bg-orange-50 dark:bg-orange-900/20',
    text: 'text-orange-700 dark:text-orange-300',
    border: 'border-orange-100 dark:border-orange-800',
    icon: 'hub',
    gradient: 'from-orange-500 to-amber-500',
  },
};

// ============================================================================
// Stats
// ============================================================================

export interface ServerStats {
  total: number;
  running: number;
  starting: number;
  error: number;
  disabled: number;
  unknown: number;
}

export interface AppStats {
  total: number;
  ready: number;
  loading: number;
  error: number;
  disabled: number;
  discovered: number;
}

export interface ToolStats {
  total: number;
  serversWithTools: number;
}

export interface McpStats {
  servers: ServerStats;
  apps: AppStats;
  tools: ToolStats;
  byType: Record<MCPServerType, number>;
}

// ============================================================================
// View Modes
// ============================================================================

export type ServerViewMode = 'grid' | 'list';
export type AppViewMode = 'grid' | 'list';

// ============================================================================
// Filter State
// ============================================================================

export interface ServerFilters {
  search: string;
  enabled: 'all' | 'enabled' | 'disabled';
  type: 'all' | MCPServerType;
  runtime: 'all' | RuntimeStatus;
}

export interface AppFilters {
  search: string;
  status: 'all' | MCPApp['status'];
  source: 'all' | 'user_added' | 'agent_developed';
}

export interface ToolFilters {
  search: string;
  server: string;
}

// ============================================================================
// Helper Functions
// ============================================================================

export function getRuntimeStatus(server: MCPServerResponse): RuntimeStatus {
  if (server.runtime_status) return server.runtime_status as RuntimeStatus;
  if (!server.enabled) return 'disabled';
  if (server.sync_error) return 'error';
  if (server.last_sync_at) return 'running';
  return 'unknown';
}
