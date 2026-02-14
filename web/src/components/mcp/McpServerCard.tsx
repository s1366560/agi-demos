/**
 * McpServerCard - Individual MCP server card with connection status indicator.
 */

import React from 'react';

import { Popconfirm, Switch, Spin, Tooltip, Tag } from 'antd';

import type { MCPServerResponse, MCPServerType, MCPToolInfo } from '@/types/agent';

const TYPE_COLORS: Record<MCPServerType, { bg: string; text: string }> = {
  stdio: { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-800 dark:text-blue-300' },
  sse: { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-800 dark:text-green-300' },
  http: { bg: 'bg-purple-100 dark:bg-purple-900/30', text: 'text-purple-800 dark:text-purple-300' },
  websocket: {
    bg: 'bg-orange-100 dark:bg-orange-900/30',
    text: 'text-orange-800 dark:text-orange-300',
  },
};

type ConnectionStatus = 'connected' | 'not_synced' | 'error' | 'disabled';

const STATUS_DOT: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: 'bg-green-500', label: 'Connected' },
  not_synced: { color: 'bg-yellow-500', label: 'Not synced' },
  error: { color: 'bg-red-500', label: 'Error' },
  disabled: { color: 'bg-slate-400', label: 'Disabled' },
};

function getConnectionStatus(server: MCPServerResponse): ConnectionStatus {
  if (!server.enabled) return 'disabled';
  if (server.sync_error) return 'error';
  if (!server.last_sync_at) return 'not_synced';
  return 'connected';
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
}

export const McpServerCard: React.FC<McpServerCardProps> = React.memo(
  ({ server, isSyncing, isTesting, onToggle, onSync, onTest, onEdit, onDelete, onShowTools }) => {
    const status = getConnectionStatus(server);
    const dot = STATUS_DOT[status];
    const typeColor = TYPE_COLORS[server.server_type];

    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow">
        {/* Header with status dot */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Tooltip title={dot.label}>
                <span className={`inline-block w-2 h-2 rounded-full ${dot.color} flex-shrink-0`} />
              </Tooltip>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white truncate">
                {server.name}
              </h3>
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${typeColor.bg} ${typeColor.text} flex-shrink-0`}
              >
                {server.server_type.toUpperCase()}
              </span>
            </div>
          </div>
          <Switch
            checked={server.enabled}
            onChange={(checked) => onToggle(server, checked)}
            size="small"
          />
        </div>

        {/* Description */}
        {server.description && (
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4 line-clamp-2">
            {server.description}
          </p>
        )}

        {/* Sync error */}
        {server.sync_error && (
          <div className="mb-4 p-2 bg-red-50 dark:bg-red-950/20 rounded-md border border-red-200/60 dark:border-red-800/30">
            <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2">
              {server.sync_error}
            </p>
          </div>
        )}

        {/* Config preview */}
        <div className="mb-4">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">Config:</p>
          <code className="text-xs text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 px-2 py-1 rounded block truncate">
            {server.server_type === 'stdio'
              ? (server.transport_config as { command?: string })?.command || 'N/A'
              : (server.transport_config as { url?: string })?.url || 'N/A'}
          </code>
        </div>

        {/* Tools preview */}
        <div className="mb-4">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
            Tools ({server.discovered_tools?.length || 0})
          </p>
          <div className="flex flex-wrap gap-1">
            {server.discovered_tools?.slice(0, 3).map((tool: MCPToolInfo, idx: number) => (
              <Tooltip key={idx} title={tool.description}>
                <Tag className="text-xs m-0">{tool.name}</Tag>
              </Tooltip>
            ))}
            {(server.discovered_tools?.length || 0) > 3 && (
              <button
                onClick={() => onShowTools(server)}
                className="inline-flex px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30 text-xs text-primary-700 dark:text-primary-300 rounded hover:bg-primary-200 dark:hover:bg-primary-900/50"
              >
                +{server.discovered_tools.length - 3} more
              </button>
            )}
          </div>
        </div>

        {/* Last sync */}
        <div className="mb-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Last Sync: {formatLastSync(server.last_sync_at)}
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Tooltip title="Sync tools">
              <button
                onClick={() => onSync(server)}
                disabled={isSyncing}
                className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
                aria-label="sync"
              >
                {isSyncing ? (
                  <Spin size="small" />
                ) : (
                  <span className="material-symbols-outlined text-sm">sync</span>
                )}
                <span className="ml-1">Sync</span>
              </button>
            </Tooltip>
            <Tooltip title="Test connection">
              <button
                onClick={() => onTest(server)}
                disabled={isTesting}
                className="inline-flex items-center justify-center px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
                aria-label="test"
              >
                {isTesting ? (
                  <Spin size="small" />
                ) : (
                  <span className="material-symbols-outlined text-sm">speed</span>
                )}
              </button>
            </Tooltip>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onEdit(server)}
              className="p-2 text-slate-600 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
              aria-label="edit"
            >
              <span className="material-symbols-outlined text-lg">edit</span>
            </button>
            <Popconfirm
              title="Are you sure you want to delete this server?"
              onConfirm={() => onDelete(server.id)}
              okText="Confirm"
              cancelText="Cancel"
            >
              <button
                className="p-2 text-slate-600 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
                aria-label="delete"
              >
                <span className="material-symbols-outlined text-lg">delete</span>
              </button>
            </Popconfirm>
          </div>
        </div>
      </div>
    );
  }
);
McpServerCard.displayName = 'McpServerCard';
