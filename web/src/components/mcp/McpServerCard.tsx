/**
 * McpServerCard - Individual MCP server card with connection status indicator.
 */

import React from 'react';

import { Popconfirm, Switch, Spin, Tooltip, Tag } from 'antd';
import { Trash2, Edit3, RefreshCw, Zap, ChevronRight } from 'lucide-react';


import type { MCPServerResponse, MCPServerType, MCPToolInfo } from '@/types/agent';

const TYPE_COLORS: Record<MCPServerType, { bg: string; text: string; border: string; icon: string }> = {
  stdio: { 
    bg: 'bg-blue-50 dark:bg-blue-900/20', 
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-100 dark:border-blue-800',
    icon: 'terminal'
  },
  sse: { 
    bg: 'bg-green-50 dark:bg-green-900/20', 
    text: 'text-green-700 dark:text-green-300',
    border: 'border-green-100 dark:border-green-800',
    icon: 'stream'
  },
  http: { 
    bg: 'bg-purple-50 dark:bg-purple-900/20', 
    text: 'text-purple-700 dark:text-purple-300',
    border: 'border-purple-100 dark:border-purple-800',
    icon: 'http'
  },
  websocket: {
    bg: 'bg-orange-50 dark:bg-orange-900/20',
    text: 'text-orange-700 dark:text-orange-300',
    border: 'border-orange-100 dark:border-orange-800',
    icon: 'hub'
  },
};

type RuntimeStatus = 'running' | 'starting' | 'error' | 'disabled' | 'unknown';

const RUNTIME_STATUS_STYLES: Record<
  RuntimeStatus,
  { dot: string; label: string; chip: string }
> = {
  running: {
    dot: 'bg-green-500',
    label: 'Running',
    chip: 'bg-green-50 text-green-700 border-green-200 dark:bg-green-900/20 dark:text-green-300 dark:border-green-800',
  },
  starting: {
    dot: 'bg-blue-500',
    label: 'Starting',
    chip: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800',
  },
  error: {
    dot: 'bg-red-500',
    label: 'Error',
    chip: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800',
  },
  disabled: {
    dot: 'bg-slate-400',
    label: 'Disabled',
    chip: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600',
  },
  unknown: {
    dot: 'bg-amber-500',
    label: 'Unknown',
    chip: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800',
  },
};

function getRuntimeStatus(server: MCPServerResponse): RuntimeStatus {
  const status = server.runtime_status;
  if (status === 'running' || status === 'starting' || status === 'error' || status === 'disabled') {
    return status;
  }
  if (!server.enabled) return 'disabled';
  if (server.sync_error) return 'error';
  if (server.last_sync_at) return 'running';
  return 'unknown';
}

function getRuntimeText(server: MCPServerResponse, key: string): string | undefined {
  const value = server.runtime_metadata?.[key];
  return typeof value === 'string' ? value : undefined;
}

function formatStatusText(value?: string): string {
  if (!value) return '';
  return value.replace(/_/g, ' ');
}

function formatLastSync(dateStr?: string): string {
  if (!dateStr) return 'Never';
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export interface McpServerCardProps {
  server: MCPServerResponse;
  isSyncing: boolean;
  isTesting: boolean;
  onToggle: (server: MCPServerResponse, enabled: boolean) => void;
  onSync: (server: MCPServerResponse) => void;
  onTest: (server: MCPServerResponse) => void;
  onEdit: (server: MCPServerResponse) => void;
  onDelete: (id: string) => void;
  onShowTools: (server: MCPServerResponse) => void;
  appCount?: number;
  readyAppCount?: number;
  errorAppCount?: number;
}

export const McpServerCard: React.FC<McpServerCardProps> = React.memo(
  ({
    server,
    isSyncing,
    isTesting,
    onToggle,
    onSync,
    onTest,
    onEdit,
    onDelete,
    onShowTools,
    appCount = 0,
    readyAppCount = 0,
    errorAppCount = 0,
  }) => {
    const status = getRuntimeStatus(server);
    const runtimeStyle = RUNTIME_STATUS_STYLES[status];
    const typeColor = TYPE_COLORS[server.server_type];
    const toolCount = server.discovered_tools?.length || 0;
    const runtimeError =
      status === 'error'
        ? getRuntimeText(server, 'last_error_message') ||
          getRuntimeText(server, 'last_error') ||
          server.sync_error
        : undefined;
    const lastTestStatus = getRuntimeText(server, 'last_test_status');
    const lastReconcileStatus = getRuntimeText(server, 'last_reconcile_status');

    return (
      <div className={`bg-white dark:bg-slate-800 rounded-xl border hover:shadow-lg transition-all duration-200 overflow-hidden ${
        status === 'error' 
          ? 'border-red-200 dark:border-red-800/50 ring-1 ring-red-50 dark:ring-red-900/20' 
          : status === 'disabled'
          ? 'border-slate-200 dark:border-slate-700 opacity-75'
          : 'border-slate-200 dark:border-slate-700'
      }`}>
        {/* Card Header */}
        <div className="p-5">
          {/* Top Row: Status, Name, Type Badge, Toggle */}
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <Tooltip title={runtimeStyle.label}>
                <span className={`inline-block w-2.5 h-2.5 rounded-full ${runtimeStyle.dot} flex-shrink-0 ${
                  status === 'running' ? 'animate-pulse' : ''
                }`} />
              </Tooltip>
              <h3 className="text-base font-semibold text-slate-900 dark:text-white truncate">
                {server.name}
              </h3>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border ${typeColor.bg} ${typeColor.text} ${typeColor.border}`}>
                <span className="material-symbols-outlined text-xs mr-1">{typeColor.icon}</span>
                {server.server_type.toUpperCase()}
              </span>
              <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border ${runtimeStyle.chip}`}>
                {runtimeStyle.label}
              </span>
              <Switch
                checked={server.enabled}
                onChange={(checked) => onToggle(server, checked)}
                size="small"
                className="ml-1"
              />
            </div>
          </div>

          {/* Description */}
          {server.description ? (
            <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2 mb-3">
              {server.description}
            </p>
          ) : (
            <p className="text-sm text-slate-400 dark:text-slate-500 italic mb-3">
              No description provided
            </p>
          )}

          {/* Config preview */}
          <div className="mb-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400 dark:text-slate-500">Config:</span>
              <code className="text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-700/50 px-2 py-0.5 rounded truncate flex-1">
                {server.server_type === 'stdio'
                  ? (server.transport_config as { command?: string })?.command || 'N/A'
                  : (server.transport_config as { url?: string })?.url || 'N/A'}
              </code>
            </div>
          </div>

          {/* Tools preview */}
          <div className="flex items-center justify-between">
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              <span className="text-xs text-slate-400 dark:text-slate-500 flex-shrink-0">
                {toolCount} tool{toolCount !== 1 ? 's' : ''}
              </span>
              {appCount > 0 && (
                <span className="text-xs text-slate-400 dark:text-slate-500 flex-shrink-0">
                  {readyAppCount}/{appCount} app{appCount !== 1 ? 's' : ''} ready
                  {errorAppCount > 0 ? `, ${errorAppCount} error` : ''}
                </span>
              )}
              <div className="flex flex-wrap gap-1 min-w-0">
                {server.discovered_tools?.slice(0, 4).map((tool: MCPToolInfo, idx: number) => (
                  <Tooltip key={idx} title={tool.description}>
                    <Tag className="text-xs m-0 truncate max-w-[100px]" style={{ fontSize: '11px', lineHeight: '18px', padding: '0 6px' }}>
                      {tool.name}
                    </Tag>
                  </Tooltip>
                ))}
                {toolCount > 4 && (
                  <button
                    onClick={() => onShowTools(server)}
                    className="inline-flex items-center px-1.5 py-0.5 bg-primary-50 dark:bg-primary-900/20 text-xs text-primary-600 dark:text-primary-400 rounded hover:bg-primary-100 dark:hover:bg-primary-900/30 transition-colors"
                  >
                    +{toolCount - 4}
                    <ChevronRight size={12} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Sync error banner */}
        {runtimeError && (
          <div className="px-5 py-2.5 bg-red-50 dark:bg-red-950/20 border-y border-red-100 dark:border-red-800/30">
            <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2 flex items-center gap-1.5">
              <span className="material-symbols-outlined text-xs">error</span>
              {runtimeError}
            </p>
          </div>
        )}

        {/* Card Footer: Actions */}
        <div className="px-5 py-3 bg-slate-50 dark:bg-slate-700/30 border-t border-slate-100 dark:border-slate-700/50 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Tooltip title="Sync tools">
              <button
                onClick={() => onSync(server)}
                disabled={isSyncing || !server.enabled}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSyncing ? (
                  <Spin size="small" />
                ) : (
                  <RefreshCw size={12} />
                )}
                Sync
              </button>
            </Tooltip>
            <Tooltip title="Test connection">
              <button
                onClick={() => onTest(server)}
                disabled={isTesting || !server.enabled}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isTesting ? (
                  <Spin size="small" />
                ) : (
                  <Zap size={12} />
                )}
                Test
              </button>
            </Tooltip>
          </div>
          
          <div className="flex items-center gap-1">
            <Tooltip title="Edit server">
              <button
                onClick={() => onEdit(server)}
                className="p-2 text-slate-500 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 hover:bg-white dark:hover:bg-slate-600 rounded-lg transition-colors"
                aria-label="edit"
              >
                <Edit3 size={14} />
              </button>
            </Tooltip>
            <Popconfirm
              title="Delete this server?"
              description="This action cannot be undone."
              onConfirm={() => onDelete(server.id)}
              okText="Delete"
              cancelText="Cancel"
              okButtonProps={{ danger: true }}
            >
              <Tooltip title="Delete server">
                <button
                  className="p-2 text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-white dark:hover:bg-slate-600 rounded-lg transition-colors"
                  aria-label="delete"
                >
                  <Trash2 size={14} />
                </button>
              </Tooltip>
            </Popconfirm>
          </div>
        </div>

        {/* Last sync timestamp */}
        <div className="px-5 py-1.5 bg-slate-50/50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-700/50">
          <p className="text-[10px] text-slate-400 dark:text-slate-500 flex items-center gap-1">
            <span className="material-symbols-outlined text-xs">schedule</span>
            Last sync: {formatLastSync(server.last_sync_at)}
          </p>
          {(lastTestStatus || lastReconcileStatus) && (
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
              {lastTestStatus ? `Test: ${formatStatusText(lastTestStatus)}` : ''}
              {lastTestStatus && lastReconcileStatus ? ' · ' : ''}
              {lastReconcileStatus ? `Reconcile: ${formatStatusText(lastReconcileStatus)}` : ''}
            </p>
          )}
        </div>
      </div>
    );
  }
);
McpServerCard.displayName = 'McpServerCard';
