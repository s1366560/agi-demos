/**
 * McpServerCardV2 - Modern MCP Server Card
 * Aligned with agent workspace design system
 */

import React from 'react';

import { Popconfirm, Switch, Tooltip } from 'antd';

import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { RUNTIME_STATUS_STYLES, SERVER_TYPE_STYLES, CARD_STYLES } from './styles';
import { getRuntimeStatus } from './types';

import type { MCPServerResponse } from '@/types/agent';

export interface McpServerCardV2Props {
  server: MCPServerResponse;
  isSyncing: boolean;
  isTesting: boolean;
  onToggle: (server: MCPServerResponse, enabled: boolean) => void;
  onSync: (server: MCPServerResponse) => void;
  onTest: (server: MCPServerResponse) => void;
  onEdit: (server: MCPServerResponse) => void;
  onDelete: (id: string) => void;
  onShowTools: (server: MCPServerResponse) => void;
  appCount?: number | undefined;
  readyAppCount?: number | undefined;
  errorAppCount?: number | undefined;
}

function formatLastSync(dateStr?: string): string {
  if (!dateStr) return 'Never synced';
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatConfigPreview(server: MCPServerResponse): string {
  const config = server.transport_config;
  if (server.server_type === 'stdio') {
    return (config.command as string) || 'N/A';
  }
  return (config.url as string) || 'N/A';
}

export const McpServerCardV2: React.FC<McpServerCardV2Props> = React.memo(
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
  }) => {
    const status = getRuntimeStatus(server);
    const runtimeStyle = RUNTIME_STATUS_STYLES[status] ?? RUNTIME_STATUS_STYLES.stopped!;
    const typeStyle = SERVER_TYPE_STYLES[server.server_type] ?? SERVER_TYPE_STYLES.stdio;
    const toolCount = server.discovered_tools?.length || 0;

    const hasError = status === 'error' || server.sync_error;
    const runtimeError = hasError
      ? (server.runtime_metadata?.last_error_message as string) ||
        (server.runtime_metadata?.last_error as string) ||
        server.sync_error
      : undefined;

    return (
      <div
        className={`group relative ${CARD_STYLES.base} ${CARD_STYLES.hover} ${
          hasError ? CARD_STYLES.error : ''
        } transition-all duration-200 overflow-hidden`}
      >
        {/* Status Bar */}
        <div
          className={`h-1 w-full ${status === 'error' ? 'bg-red-500' : status === 'running' ? 'bg-emerald-500' : 'bg-slate-200 dark:bg-slate-700'}`}
        />

        {/* Card Content */}
        <div className="p-4">
          {/* Header */}
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-3 flex-1">
              <div
                className={`w-10 h-10 rounded-lg flex items-center justify-center ${typeStyle.bgColor}`}
              >
                <MaterialIcon name={typeStyle.icon} size={20} className={typeStyle.textColor} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                    {server.name}
                  </h3>
                  {!server.enabled && (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-500">
                      Disabled
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                  {formatConfigPreview(server)}
                </p>
              </div>
            </div>

            {/* Toggle Switch */}
            <Tooltip title={server.enabled ? 'Disable server' : 'Enable server'}>
              <Switch
                size="small"
                checked={server.enabled}
                onChange={(checked) => {
                  onToggle(server, checked);
                }}
                checkedChildren=""
                unCheckedChildren=""
                className="ml-2"
              />
            </Tooltip>
          </div>

          {/* Status Badge */}
          <div
            className={`inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg border mb-3 ${runtimeStyle.bgColor} ${runtimeStyle.borderColor}`}
          >
            <MaterialIcon
              name={runtimeStyle.icon}
              size={16}
              className={`${runtimeStyle.color} ${status === 'starting' ? 'animate-spin' : ''}`}
            />
            <span className={`text-xs font-medium ${runtimeStyle.color}`}>
              {runtimeStyle.label}
            </span>
            {status === 'error' && runtimeError && (
              <Tooltip title={runtimeError}>
                <MaterialIcon name="info" size={14} className="text-red-500" />
              </Tooltip>
            )}
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">{toolCount}</p>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">Tools</p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">{appCount || 0}</p>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">Apps</p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">
                {readyAppCount || 0}
              </p>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">Ready</p>
            </div>
          </div>

          {/* Last Sync */}
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mb-3">
            <MaterialIcon name="schedule" size={14} />
            <span>Synced {formatLastSync(server.last_sync_at)}</span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Tooltip title="Sync tools">
              <button
                onClick={() => {
                  onSync(server);
                }}
                disabled={isSyncing}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-700"
              >
                <MaterialIcon
                  name={isSyncing ? 'progress_activity' : 'sync'}
                  size={16}
                  className={isSyncing ? 'animate-spin' : ''}
                />
                Sync
              </button>
            </Tooltip>

            <Tooltip title="Test connection">
              <button
                onClick={() => {
                  onTest(server);
                }}
                disabled={isTesting}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-700"
              >
                <MaterialIcon
                  name={isTesting ? 'progress_activity' : 'science'}
                  size={16}
                  className={isTesting ? 'animate-spin' : ''}
                />
                Test
              </button>
            </Tooltip>

            <Tooltip title="View tools">
              <button
                onClick={() => {
                  onShowTools(server);
                }}
                className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors"
              >
                <MaterialIcon name="build" size={18} />
              </button>
            </Tooltip>

            <button
              onClick={() => {
                onEdit(server);
              }}
              className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors"
            >
              <MaterialIcon name="edit" size={18} />
            </button>

            <Popconfirm
              title="Delete Server"
              description="Are you sure you want to delete this server?"
              onConfirm={() => {
                onDelete(server.id);
              }}
              okText="Delete"
              cancelText="Cancel"
              okButtonProps={{ danger: true }}
            >
              <button className="p-2 text-slate-400 hover:text-red-500 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors">
                <MaterialIcon name="delete" size={18} />
              </button>
            </Popconfirm>
          </div>
        </div>
      </div>
    );
  }
);

McpServerCardV2.displayName = 'McpServerCardV2';
