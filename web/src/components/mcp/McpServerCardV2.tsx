/**
 * McpServerCardV2 - Modern MCP Server Card
 * Aligned with agent workspace design system
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import { Popconfirm, Switch, Tooltip } from 'antd';
import {
  Clock,
  Info,
  Pencil,
  Trash2,
  Wrench,
  CheckCircle,
  Square,
  StopCircle,
  Terminal,
  Cloud,
  Zap,
  Ban,
  Search,
  Sparkles,
  AlertTriangle,
  Activity,
  FlaskConical,
  RefreshCcw,
  Settings,
  Brain,
  Loader2,
  AlertCircle,
  Globe,
  User,
} from 'lucide-react';

import { RUNTIME_STATUS_STYLES, SERVER_TYPE_STYLES, CARD_STYLES } from './styles';
import { getRuntimeStatus } from './types';

import type { MCPServerResponse } from '@/types/agent';

import type { TFunction } from 'i18next';

const renderDynamicIcon = (name: string, size: number, className: string = '') => {
  switch (name) {
    case 'check_circle':
      return <CheckCircle size={size} className={className} />;
    case 'progress_activity':
      return <Loader2 size={size} className={`animate-spin ${className}`} />;
    case 'stop':
      return <Square size={size} className={className} />;
    case 'stop_circle':
      return <StopCircle size={size} className={className} />;
    case 'error':
      return <AlertCircle size={size} className={className} />;
    case 'warning':
      return <AlertTriangle size={size} className={className} />;
    case 'terminal':
      return <Terminal size={size} className={className} />;
    case 'http':
      return <Globe size={size} className={className} />;
    case 'cloud':
      return <Cloud size={size} className={className} />;
    case 'globe':
      return <Globe size={size} className={className} />;
    case 'zap':
      return <Zap size={size} className={className} />;
    case 'block':
      return <Ban size={size} className={className} />;
    case 'search':
      return <Search size={size} className={className} />;
    case 'person':
      return <User size={size} className={className} />;
    case 'auto_awesome':
      return <Sparkles size={size} className={className} />;
    case 'monitor_heart':
      return <Activity size={size} className={className} />;
    case 'refresh':
      return <RefreshCcw size={size} className={className} />;
    case 'sync':
      return <RefreshCcw size={size} className={className} />;
    case 'science':
      return <FlaskConical size={size} className={className} />;
    case 'settings':
      return <Settings size={size} className={className} />;
    case 'psychology':
      return <Brain size={size} className={className} />;
    case 'info':
      return <Info size={size} className={className} />;
    default:
      return <AlertCircle size={size} className={className} />;
  }
};

const DEFAULT_RUNTIME_STATUS_STYLE = {
  color: 'text-slate-500 dark:text-slate-400',
  bgColor: 'bg-slate-50 dark:bg-slate-800/50',
  borderColor: 'border-slate-200 dark:border-slate-700',
  dotColor: 'bg-slate-400',
  icon: 'stop_circle',
  label: 'Stopped',
} satisfies NonNullable<(typeof RUNTIME_STATUS_STYLES)[string]>;

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

function formatLastSync(dateStr: string | undefined, t: TFunction): string {
  if (!dateStr) return t('mcp.serverCard.sync.never');
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (mins < 1) return t('mcp.serverCard.sync.justNow');
  if (mins < 60) return t('mcp.serverCard.sync.minutesAgo', { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t('mcp.serverCard.sync.hoursAgo', { count: hrs });
  return t('mcp.serverCard.sync.daysAgo', { count: Math.floor(hrs / 24) });
}

function formatConfigPreview(server: MCPServerResponse, t: TFunction): string {
  const config = server.transport_config;
  if (server.server_type === 'stdio') {
    const cmd = config.command;
    if (Array.isArray(cmd)) return cmd.join(' ') || t('mcp.serverCard.notAvailable');
    return (cmd as string) || t('mcp.serverCard.notAvailable');
  }
  return (config.url as string) || t('mcp.serverCard.notAvailable');
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
    const { t } = useTranslation();
    const status = getRuntimeStatus(server);
    const runtimeStyle = RUNTIME_STATUS_STYLES[status] ?? DEFAULT_RUNTIME_STATUS_STYLE;
    const typeStyle = SERVER_TYPE_STYLES[server.server_type];
    const toolCount = server.discovered_tools.length;

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
        } transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 overflow-hidden`}
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
                {renderDynamicIcon(typeStyle.icon, 20, typeStyle.textColor)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                    {server.name}
                  </h3>
                  {!server.enabled && (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-500">
                      {t('common.status.disabled')}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                  {formatConfigPreview(server, t)}
                </p>
              </div>
            </div>

            {/* Toggle Switch */}
            <Tooltip
              title={
                server.enabled
                  ? t('mcp.serverCard.disableTooltip')
                  : t('mcp.serverCard.enableTooltip')
              }
            >
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
            {renderDynamicIcon(
              runtimeStyle.icon,
              16,
              `${runtimeStyle.color} ${status === 'starting' ? 'animate-spin motion-reduce:animate-none' : ''}`
            )}
            <span className={`text-xs font-medium ${runtimeStyle.color}`}>
              {t(`mcp.serverCard.runtimeStatus.${status}`, runtimeStyle.label)}
            </span>
            {status === 'error' && runtimeError && (
              <Tooltip title={runtimeError}>
                <Info size={14} className="text-red-500" />
              </Tooltip>
            )}
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">{toolCount}</p>
              <p className="text-2xs text-slate-500 dark:text-slate-400">
                {t('mcp.serverCard.stats.tools')}
              </p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">{appCount || 0}</p>
              <p className="text-2xs text-slate-500 dark:text-slate-400">
                {t('mcp.serverCard.stats.apps')}
              </p>
            </div>
            <div className="text-center p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <p className="text-lg font-bold text-slate-900 dark:text-white">
                {readyAppCount || 0}
              </p>
              <p className="text-2xs text-slate-500 dark:text-slate-400">
                {t('mcp.serverCard.stats.ready')}
              </p>
            </div>
          </div>

          {/* Last Sync */}
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mb-3">
            <Clock size={14} />
            <span>
              {t('mcp.serverCard.sync.label', { value: formatLastSync(server.last_sync_at, t) })}
            </span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Tooltip title={t('mcp.serverCard.actions.syncTooltip')}>
              <button
                onClick={() => {
                  onSync(server);
                }}
                disabled={isSyncing}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-700"
              >
                {renderDynamicIcon(
                  isSyncing ? 'progress_activity' : 'sync',
                  16,
                  isSyncing ? 'animate-spin motion-reduce:animate-none' : ''
                )}
                {t('mcp.serverCard.actions.sync')}
              </button>
            </Tooltip>

            <Tooltip title={t('mcp.serverCard.actions.testTooltip')}>
              <button
                onClick={() => {
                  onTest(server);
                }}
                disabled={isTesting}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-700"
              >
                {renderDynamicIcon(
                  isTesting ? 'progress_activity' : 'science',
                  16,
                  isTesting ? 'animate-spin motion-reduce:animate-none' : ''
                )}
                {t('mcp.serverCard.actions.test')}
              </button>
            </Tooltip>

            <Tooltip title={t('mcp.serverCard.actions.viewToolsTooltip')}>
              <button
                onClick={() => {
                  onShowTools(server);
                }}
                className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors"
              >
                <Wrench size={18} />
              </button>
            </Tooltip>

            <button
              onClick={() => {
                onEdit(server);
              }}
              className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors"
            >
              <Pencil size={18} />
            </button>

            <Popconfirm
              title={t('mcp.serverCard.delete.title')}
              description={t('mcp.serverCard.delete.description')}
              onConfirm={() => {
                onDelete(server.id);
              }}
              okText={t('common.delete')}
              cancelText={t('common.cancel')}
              okButtonProps={{ danger: true }}
            >
              <button className="p-2 text-slate-400 hover:text-red-500 hover:bg-white dark:hover:bg-slate-800 rounded-lg transition-colors">
                <Trash2 size={18} />
              </button>
            </Popconfirm>
          </div>
        </div>
      </div>
    );
  }
);

McpServerCardV2.displayName = 'McpServerCardV2';
