/**
 * McpAppCardV2 - Modern MCP App Card
 * Redesigned with elegant UI/UX, better visual hierarchy, and smooth animations
 */

import React, { useEffect, useRef, useState } from 'react';

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
  Sparkles,
  Globe,
  Clock,
  FileText,
} from 'lucide-react';

import { SOURCE_STYLES, CARD_STYLES, ANIMATION_CLASSES, APP_STATUS_STYLES } from './styles';

import type { MCPApp } from '@/types/mcpApp';

const LOADING_TIMEOUT_MS = 30_000;

function getLifecycleText(app: MCPApp, key: string): string | undefined {
  const value = app.lifecycle_metadata?.[key];
  return typeof value === 'string' ? value : undefined;
}

function formatRelativeTime(dateStr?: string): string {
  if (!dateStr) return '';
  const minutes = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
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
  const statusCfg = APP_STATUS_STYLES[app.status] ?? APP_STATUS_STYLES.disabled!;
  const sourceCfg = SOURCE_STYLES[app.source] ?? SOURCE_STYLES.user_added!;
  const isAgentDeveloped = app.source === 'agent_developed';
  const title = app.ui_metadata?.title || app.tool_name;
  const refreshStatus = getLifecycleText(app, 'last_resource_refresh_status');
  const refreshAt = getLifecycleText(app, 'last_resource_refresh_at');

  const [loadingTimeout, setLoadingTimeout] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (app.status === 'loading') {
      timeoutRef.current = setTimeout(() => { setLoadingTimeout(true); }, LOADING_TIMEOUT_MS);
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
      className={`group relative ${CARD_STYLES.base} ${CARD_STYLES.hover} transition-all duration-300 overflow-hidden`}
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
              {isAgentDeveloped ? <Sparkles size={18} /> : <LayoutGrid size={18} />}
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
                <span className="material-symbols-outlined text-xs">{statusCfg.icon}</span>
                {statusCfg.label}
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
                className="text-[10px] flex-shrink-0 m-0 px-1.5 py-0.5 rounded-full"
              >
                运行：{serverRuntime}
              </Tag>
            )}
          </div>
        </div>

        {/* Resource URI */}
        <div className="mb-3 p-2.5 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <Globe size={10} className="text-slate-400" />
            <span className="text-[10px] text-slate-500 dark:text-slate-400 font-medium">
              资源地址
            </span>
          </div>
          <code className="text-xs text-slate-600 dark:text-slate-400 break-all font-mono block">
            {app.ui_metadata?.resourceUri || '无资源地址'}
          </code>
          {refreshStatus && (
            <div className="flex items-center gap-1 mt-1.5 text-[10px] text-slate-500 dark:text-slate-400">
              <Clock size={10} />
              <span>
                刷新 {refreshStatus}
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
              onClick={() => { onRetry(app.id); }}
              disabled={retrying.has(app.id)}
              className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-200 disabled:opacity-50 transition-colors"
            >
              {retrying.has(app.id) ? (
                <Loader2 size={10} className={ANIMATION_CLASSES.spin} />
              ) : (
                <RotateCcw size={10} />
              )}
              重试
            </button>
          </div>
        )}

        {/* Loading Timeout Hint */}
        {app.status === 'loading' && loadingTimeout && (
          <div className="mb-3 p-2.5 bg-amber-50 dark:bg-amber-950/20 rounded-xl border border-amber-100 dark:border-amber-800/30">
            <div className="flex items-center gap-2">
              <AlertCircle size={12} className="text-amber-500" />
              <p className="text-xs text-amber-700 dark:text-amber-300">加载时间较长，请尝试刷新</p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-3 border-t border-slate-100 dark:border-slate-700/50">
          {/* Meta Info */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Source Badge */}
            <Tooltip title={sourceCfg.label}>
              <span
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs ${sourceCfg.bgColor} ${sourceCfg.textColor}`}
              >
                {isAgentDeveloped ? <Bot size={10} /> : <User size={10} />}
                {isAgentDeveloped ? 'AI' : '用户'}
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
                onClick={() => { onOpenInCanvas(app); }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20 hover:bg-violet-100 dark:hover:bg-violet-900/30 transition-colors font-medium"
              >
                <ExternalLink size={12} />
                打开
              </button>
            )}

            {/* Delete Button */}
            <Popconfirm
              title="确定要删除此应用吗？"
              onConfirm={() => { onDelete(app.id); }}
              okText="删除"
              cancelText="取消"
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
