/**
 * McpServerCardV2 - Modern MCP Server Card
 * Redesigned with elegant UI/UX, better visual hierarchy, and smooth animations
 */

import React from 'react';

import { Popconfirm, Switch, Tooltip, Tag } from 'antd';
import { 
  Trash2, 
  Edit3, 
  RefreshCw, 
  Zap, 
  ChevronRight, 
  Server,
  Activity,
  AlertCircle,
  Clock,
  Cpu,
  Layers
} from 'lucide-react';

import { 
  RUNTIME_STATUS_STYLES, 
  SERVER_TYPE_STYLES,
  CARD_STYLES,
  ANIMATION_CLASSES 
} from './styles';
import { getRuntimeStatus } from './types';

import type { MCPServerResponse, MCPToolInfo } from '@/types/agent';

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
  appCount?: number;
  readyAppCount?: number;
  errorAppCount?: number;
}

function formatLastSync(dateStr?: string): string {
  if (!dateStr) return '从未同步';
  const mins = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时前`;
  return `${Math.floor(hrs / 24)} 天前`;
}

function formatConfigPreview(server: MCPServerResponse): string {
  const config = server.transport_config as Record<string, unknown>;
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
    errorAppCount = 0,
  }) => {
    const status = getRuntimeStatus(server);
    const runtimeStyle = RUNTIME_STATUS_STYLES[status];
    const typeStyle = SERVER_TYPE_STYLES[server.server_type];
    const toolCount = server.discovered_tools?.length || 0;
    
    const hasError = status === 'error' || server.sync_error;
    const runtimeError = hasError
      ? (server.runtime_metadata?.last_error_message as string) ||
        (server.runtime_metadata?.last_error as string) ||
        server.sync_error
      : undefined;

    const lastTestStatus = server.runtime_metadata?.last_test_status as string;
    const lastReconcileStatus = server.runtime_metadata?.last_reconcile_status as string;

    return (
      <div className={`group relative ${CARD_STYLES.base} ${CARD_STYLES.hover} ${
        hasError ? CARD_STYLES.error : ''
      } transition-all duration-300 overflow-hidden`}>
        
        {/* Gradient Top Border */}
        <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${typeStyle.gradient}`} />

        {/* Card Content */}
        <div className="p-5">
          {/* Header Row */}
          <div className="flex items-start justify-between gap-3 mb-4">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              {/* Status Indicator */}
              <Tooltip title={runtimeStyle.label}>
                <div className="relative">
                  <div className={`w-3 h-3 rounded-full ${runtimeStyle.dot} ${
                    status === 'running' ? ANIMATION_CLASSES.pulse : ''
                  }`} />
                  {status === 'starting' && (
                    <div className="absolute inset-0 rounded-full bg-blue-400 animate-ping opacity-75" />
                  )}
                </div>
              </Tooltip>

              {/* Server Name */}
              <div className="min-w-0 flex-1">
                <h3 className="text-base font-semibold text-slate-900 dark:text-white truncate">
                  {server.name}
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  {formatConfigPreview(server)}
                </p>
              </div>
            </div>

            {/* Toggle Switch */}
            <Switch
              checked={server.enabled}
              onChange={(checked) => onToggle(server, checked)}
              size="small"
              className="ml-2"
            />
          </div>

          {/* Description */}
          <div className="mb-4">
            {server.description ? (
              <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2 leading-relaxed">
                {server.description}
              </p>
            ) : (
              <p className="text-sm text-slate-400 dark:text-slate-500 italic">
                暂无描述
              </p>
            )}
          </div>

          {/* Tags Row */}
          <div className="flex flex-wrap items-center gap-2 mb-4">
            {/* Type Badge */}
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border ${typeStyle.bg} ${typeStyle.text} ${typeStyle.border}`}>
              <span className="material-symbols-outlined text-xs">{typeStyle.icon}</span>
              {server.server_type.toUpperCase()}
            </span>

            {/* Runtime Status Badge */}
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border ${runtimeStyle.chip}`}>
              <span className="material-symbols-outlined text-xs">{runtimeStyle.icon}</span>
              {runtimeStyle.label}
            </span>

            {/* Tool Count */}
            {toolCount > 0 && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
                <Cpu size={10} />
                {toolCount} 工具
              </span>
            )}

            {/* App Count */}
            {appCount > 0 && (
              <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium ${
                errorAppCount > 0
                  ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                  : 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400'
              }`}>
                <Layers size={10} />
                {readyAppCount}/{appCount} 应用
                {errorAppCount > 0 && <span className="ml-0.5">({errorAppCount} 错误)</span>}
              </span>
            )}
          </div>

          {/* Tools Preview */}
          {toolCount > 0 && (
            <div className="mb-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-400 dark:text-slate-500">工具:</span>
                <div className="flex flex-wrap gap-1.5">
                  {server.discovered_tools?.slice(0, 5).map((tool: MCPToolInfo, idx: number) => (
                    <Tooltip key={idx} title={tool.description} color="blue">
                      <Tag 
                        className="text-xs m-0 truncate max-w-[120px] cursor-default" 
                        style={{ fontSize: '11px', lineHeight: '18px', padding: '0 8px' }}
                      >
                        {tool.name}
                      </Tag>
                    </Tooltip>
                  ))}
                  {toolCount > 5 && (
                    <button
                      onClick={() => onShowTools(server)}
                      className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 dark:bg-primary-900/20 text-xs text-primary-600 dark:text-primary-400 rounded-lg hover:bg-primary-100 dark:hover:bg-primary-900/30 transition-colors"
                    >
                      +{toolCount - 5}
                      <ChevronRight size={12} />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {runtimeError && (
            <div className="mb-4 p-3 bg-red-50 dark:bg-red-950/20 rounded-xl border border-red-100 dark:border-red-800/30">
              <div className="flex items-start gap-2">
                <AlertCircle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2">
                  {runtimeError}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className={`px-5 py-3 ${hasError ? 'bg-red-50/50 dark:bg-red-950/10' : 'bg-slate-50 dark:bg-slate-700/30'} border-t border-slate-100 dark:border-slate-700/50`}>
          <div className="flex items-center justify-between">
            {/* Action Buttons */}
            <div className="flex items-center gap-2">
              <Tooltip title={isSyncing ? '同步中...' : '同步工具'}>
                <button
                  onClick={() => onSync(server)}
                  disabled={isSyncing || !server.enabled}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                    isSyncing
                      ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                      : 'bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-600'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  <RefreshCw size={12} className={isSyncing ? ANIMATION_CLASSES.spin : ''} />
                  同步
                </button>
              </Tooltip>

              <Tooltip title={isTesting ? '测试中...' : '测试连接'}>
                <button
                  onClick={() => onTest(server)}
                  disabled={isTesting || !server.enabled}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                    isTesting
                      ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                      : 'bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-600'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  <Zap size={12} className={isTesting ? ANIMATION_CLASSES.pulse : ''} />
                  测试
                </button>
              </Tooltip>
            </div>

            {/* Edit & Delete */}
            <div className="flex items-center gap-1">
              <Tooltip title="编辑">
                <button
                  onClick={() => onEdit(server)}
                  className="p-2 text-slate-500 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 hover:bg-white dark:hover:bg-slate-600 rounded-lg transition-colors"
                  aria-label="edit"
                >
                  <Edit3 size={14} />
                </button>
              </Tooltip>

              <Popconfirm
                title="确定要删除此服务器吗？"
                description="此操作无法撤销"
                onConfirm={() => onDelete(server.id)}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Tooltip title="删除">
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
        </div>

        {/* Status Bar */}
        <div className="px-5 py-2 bg-slate-50/50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-700/50">
          <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500">
            <div className="flex items-center gap-1">
              <Clock size={10} />
              <span>最后同步：{formatLastSync(server.last_sync_at)}</span>
            </div>
            {(lastTestStatus || lastReconcileStatus) && (
              <div className="flex items-center gap-2">
                {lastTestStatus && (
                  <span className="flex items-center gap-1">
                    <Activity size={10} />
                    测试：{lastTestStatus.replace(/_/g, ' ')}
                  </span>
                )}
                {lastReconcileStatus && (
                  <span className="flex items-center gap-1">
                    <Server size={10} />
                    协调：{lastReconcileStatus.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
);

McpServerCardV2.displayName = 'McpServerCardV2';
