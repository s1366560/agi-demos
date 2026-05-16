/**
 * McpAppCardV2 - Modern MCP App Card
 * Redesigned with elegant UI/UX, better visual hierarchy, and smooth animations
 */

import React, { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Popconfirm, Tag, Tooltip } from 'antd';
import {
  LayoutGrid,
  Trash2,
  ExternalLink,
  Bot,
  User,
  AlertCircle,
  Loader2,
  RotateCcw,
  Globe,
  Clock,
  FileText,
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
  Info,
} from 'lucide-react';

import { formatDistanceToNow } from '@/utils/date';

import { ANIMATION_CLASSES, APP_STATUS_STYLES, CARD_STYLES, SOURCE_STYLES } from './styles';

import type { MCPApp } from '@/types/mcpApp';

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

const LOADING_TIMEOUT_MS = 30_000;

const DEFAULT_APP_STATUS_STYLE = {
  color: 'text-slate-500 dark:text-slate-400',
  bgColor: 'bg-slate-50 dark:bg-slate-800/50',
  borderColor: 'border-slate-200 dark:border-slate-700',
  icon: 'block',
  label: 'Disabled',
} satisfies NonNullable<(typeof APP_STATUS_STYLES)[string]>;

const DEFAULT_SOURCE_STYLE = {
  bgColor: 'bg-cyan-50 dark:bg-cyan-900/20',
  textColor: 'text-cyan-700 dark:text-cyan-400',
  icon: 'person',
  label: 'User Added',
} satisfies NonNullable<(typeof SOURCE_STYLES)[string]>;

function getLifecycleText(app: MCPApp, key: string): string | undefined {
  const value = app.lifecycle_metadata?.[key];
  return typeof value === 'string' ? value : undefined;
}

function formatRelativeTime(dateStr?: string): string {
  if (!dateStr) return '';
  return formatDistanceToNow(dateStr);
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return '';
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export interface McpAppCardV2Props {
  app: MCPApp;
  serverRuntime?: string | undefined;
  onDelete: (appId: string) => void;
  onRetry: (appId: string) => void;
  onOpenInCanvas: (app: MCPApp) => void;
  deleting: Set<string>;
  retrying: Set<string>;
}

export const McpAppCardV2: React.FC<McpAppCardV2Props> = ({
  app,
  serverRuntime,
  onDelete,
  onRetry,
  onOpenInCanvas,
  deleting,
  retrying,
}) => {
  const { t } = useTranslation();
  const statusCfg = APP_STATUS_STYLES[app.status] ?? DEFAULT_APP_STATUS_STYLE;
  const sourceCfg = SOURCE_STYLES[app.source] ?? DEFAULT_SOURCE_STYLE;
  const statusLabel = t(`mcp.appCard.status.${app.status}`, statusCfg.label);
  const sourceLabel = t(`mcp.appCard.source.${app.source}`, sourceCfg.label);
  const isAgentDeveloped = app.source === 'agent_developed';
  const title = app.ui_metadata.title || app.tool_name;
  const refreshStatus = getLifecycleText(app, 'last_resource_refresh_status');
  const refreshAt = getLifecycleText(app, 'last_resource_refresh_at');

  const [loadingTimeout, setLoadingTimeout] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (app.status === 'loading') {
      timeoutRef.current = setTimeout(() => {
        setLoadingTimeout(true);
      }, LOADING_TIMEOUT_MS);
    } else {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoadingTimeout(false);
    }
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [app.status]);

  return (
    <div
      className={`group relative ${CARD_STYLES.base} ${CARD_STYLES.hover} transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 overflow-hidden`}
    >
      {/* Source Indicator */}
      <div
        className={`absolute top-0 left-0 right-0 h-0.5 ${
          isAgentDeveloped
            ? 'bg-gradient-to-r from-violet-500 to-purple-500'
            : 'bg-gradient-to-r from-cyan-500 to-blue-500'
        }`}
      />

      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            {/* App Icon */}
            <div
              className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
                isAgentDeveloped
                  ? 'bg-gradient-to-br from-violet-50 to-purple-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400'
                  : 'bg-gradient-to-br from-cyan-50 to-blue-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400'
              }`}
            >
              {isAgentDeveloped ? <Bot size={18} /> : <LayoutGrid size={18} />}
            </div>

            {/* App Info */}
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                {title}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                {app.server_name}
              </p>
            </div>
          </div>

          {/* Status Badges */}
          <div className="flex flex-col gap-1.5 items-end">
            <Tag
              color={statusCfg.color}
              className="text-xs flex-shrink-0 m-0 px-2 py-0.5 rounded-full"
            >
              <span className="flex items-center gap-1">
                {renderDynamicIcon(statusCfg.icon, 12, '')}
                {statusLabel}
              </span>
            </Tag>
            {serverRuntime && (
              <Tag
                color={
                  serverRuntime === 'running'
                    ? 'green'
                    : serverRuntime === 'starting'
                      ? 'blue'
                      : serverRuntime === 'error'
                        ? 'red'
                        : 'default'
                }
                className="text-2xs flex-shrink-0 m-0 px-1.5 py-0.5 rounded-full"
              >
                {t('mcp.appCard.runtimePrefix', { value: serverRuntime })}
              </Tag>
            )}
          </div>
        </div>

        {/* Resource URI */}
        <div className="mb-3 p-2.5 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <Globe size={10} className="text-slate-400" />
            <span className="text-2xs text-slate-500 dark:text-slate-400 font-medium">
              {t('mcp.appCard.resourceUri')}
            </span>
          </div>
          <code className="text-xs text-slate-600 dark:text-slate-400 break-all font-mono block">
            {app.ui_metadata.resourceUri || t('mcp.appCard.noResourceUri')}
          </code>
          {refreshStatus && (
            <div className="flex items-center gap-1 mt-1.5 text-2xs text-slate-500 dark:text-slate-400">
              <Clock size={10} />
              <span>
                {t('mcp.appCard.refreshWithStatus', { status: refreshStatus })}
                {refreshAt ? ` · ${formatRelativeTime(refreshAt)}` : ''}
              </span>
            </div>
          )}
        </div>

        {/* Error Message */}
        {app.error_message && (
          <div className="mb-3 p-2.5 bg-red-50 dark:bg-red-950/20 rounded-xl border border-red-100 dark:border-red-800/30">
            <div className="flex items-start gap-2">
              <AlertCircle size={12} className="text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2 flex-1">
                {app.error_message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                onRetry(app.id);
              }}
              disabled={retrying.has(app.id)}
              className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-200 disabled:opacity-50 transition-colors"
            >
              {retrying.has(app.id) ? (
                <Loader2 size={10} className={ANIMATION_CLASSES.spin} />
              ) : (
                <RotateCcw size={10} />
              )}
              {t('mcp.appCard.retry')}
            </button>
          </div>
        )}

        {/* Loading Timeout Hint */}
        {app.status === 'loading' && loadingTimeout && (
          <div className="mb-3 p-2.5 bg-amber-50 dark:bg-amber-950/20 rounded-xl border border-amber-100 dark:border-amber-800/30">
            <div className="flex items-center gap-2">
              <AlertCircle size={12} className="text-amber-500" />
              <p className="text-xs text-amber-700 dark:text-amber-300">
                {t('mcp.appCard.slowLoadHint')}
              </p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-3 border-t border-slate-100 dark:border-slate-700/50">
          {/* Meta Info */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Source Badge */}
            <Tooltip title={sourceLabel}>
              <span
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs ${sourceCfg.bgColor} ${sourceCfg.textColor}`}
              >
                {isAgentDeveloped ? <Bot size={10} /> : <User size={10} />}
                {isAgentDeveloped ? t('mcp.appCard.developerAI') : t('mcp.appCard.developerUser')}
              </span>
            </Tooltip>

            {/* File Size */}
            {app.has_resource && app.resource_size_bytes && (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
                <FileText size={10} />
                {formatFileSize(app.resource_size_bytes)}
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5">
            {/* Open Button */}
            {app.status === 'ready' && (
              <button
                type="button"
                onClick={() => {
                  onOpenInCanvas(app);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20 hover:bg-violet-100 dark:hover:bg-violet-900/30 transition-colors font-medium"
              >
                <ExternalLink size={12} />
                {t('mcp.appCard.open')}
              </button>
            )}

            {/* Delete Button */}
            <Popconfirm
              title={t('mcp.appCard.deleteConfirm')}
              onConfirm={() => {
                onDelete(app.id);
              }}
              okText={t('mcp.appCard.deleteOk')}
              cancelText={t('mcp.appCard.deleteCancel')}
            >
              <button
                type="button"
                disabled={deleting.has(app.id)}
                className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50"
              >
                {deleting.has(app.id) ? (
                  <Loader2 size={14} className={ANIMATION_CLASSES.spin} />
                ) : (
                  <Trash2 size={14} />
                )}
              </button>
            </Popconfirm>
          </div>
        </div>
      </div>
    </div>
  );
};
