/**
 * ProjectAgentStatusBar - Project ReAct Agent Lifecycle Status Bar
 *
 * Displays the complete lifecycle state of the ProjectReActAgent:
 * - Lifecycle state (uninitialized, initializing, ready, executing, paused, error, shutting_down)
 * - Resource counts (tools, skills, subagents)
 * - Execution metrics (total/failed chats, active chats)
 * - Health status (uptime, last error)
 *
 * @module components/agent/ProjectAgentStatusBar
 */

import React, { useMemo } from 'react';
import { Tooltip, Badge } from 'antd';
import {
  Zap,
  MessageSquare,
  Terminal,
  Wifi,
  Loader2,
  CheckCircle2,
  AlertCircle,
  PauseCircle,
  Power,
  Cpu,
  Wrench,
  BrainCircuit,
  Bot,
  Activity,
  Clock,
  AlertTriangle,
} from 'lucide-react';
import type {
  AgentSessionStatus,
  ProjectAgentLifecycleState,
} from '../../services/agentStatusService';

interface ProjectAgentStatusBarProps {
  /** Project ID */
  projectId: string;
  /** Agent session status from API */
  sessionStatus: AgentSessionStatus | null;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Error message if any */
  error?: string | null;
  /** Whether conversation is streaming */
  isStreaming?: boolean;
  /** Number of messages */
  messageCount?: number;
  /** Whether sandbox is connected */
  sandboxConnected?: boolean;
  /** Whether plan mode is active */
  isPlanMode?: boolean;
}

/**
 * Lifecycle state configuration
 */
const lifecycleConfig: Record<
  ProjectAgentLifecycleState,
  {
    label: string;
    icon: React.ElementType;
    color: string;
    bgColor: string;
    description: string;
    animate?: boolean;
  }
> = {
  uninitialized: {
    label: '未启动',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'Agent 尚未初始化，将在首次请求时自动启动',
  },
  initializing: {
    label: '初始化中',
    icon: Loader2,
    color: 'text-blue-500',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: '正在加载工具、技能和配置',
    animate: true,
  },
  ready: {
    label: '就绪',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
    description: 'Agent 已就绪，可以接收请求',
  },
  executing: {
    label: '执行中',
    icon: Cpu,
    color: 'text-amber-500',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: '正在处理聊天请求',
    animate: true,
  },
  paused: {
    label: '已暂停',
    icon: PauseCircle,
    color: 'text-orange-500',
    bgColor: 'bg-orange-100 dark:bg-orange-900/30',
    description: 'Agent 已暂停，不接收新请求',
  },
  error: {
    label: '错误',
    icon: AlertCircle,
    color: 'text-red-500',
    bgColor: 'bg-red-100 dark:bg-red-900/30',
    description: 'Agent 遇到错误',
  },
  shutting_down: {
    label: '关闭中',
    icon: Power,
    color: 'text-slate-500',
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    description: 'Agent 正在关闭',
    animate: true,
  },
};

/**
 * Format uptime to human readable string
 */
function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

/**
 * Format timestamp to relative time
 */
function formatLastActivity(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);

  if (diffSecs < 60) return '刚刚';
  if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)} 分钟前`;
  if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)} 小时前`;
  return `${Math.floor(diffSecs / 86400)} 天前`;
}

/**
 * Get lifecycle state from session status
 */
function getLifecycleState(status: AgentSessionStatus | null): ProjectAgentLifecycleState {
  if (!status) return 'uninitialized';
  if (status.last_error && !status.is_active) return 'error';
  if (status.is_executing) return 'executing';
  if (status.is_active && status.is_initialized) return 'ready';
  if (status.is_active && !status.is_initialized) return 'initializing';
  if (!status.is_active && status.is_initialized) return 'paused';
  return 'uninitialized';
}

export const ProjectAgentStatusBar: React.FC<ProjectAgentStatusBarProps> = ({
  sessionStatus,
  isLoading = false,
  isStreaming = false,
  messageCount = 0,
  sandboxConnected = false,
  isPlanMode = false,
}) => {
  const lifecycleState = useMemo(() => getLifecycleState(sessionStatus), [sessionStatus]);
  const config = lifecycleConfig[lifecycleState];

  const StatusIcon = config.icon;
  const isError = lifecycleState === 'error';
  const hasDetails = !!sessionStatus;

  return (
    <div className="px-4 py-1.5 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
      {/* Left: Lifecycle Status & Resources */}
      <div className="flex items-center gap-3">
        {/* Main Lifecycle Status */}
        <Tooltip
          title={
            <div className="space-y-2 max-w-xs">
              <div className="font-medium">{config.label}</div>
              <div className="text-xs opacity-80">{config.description}</div>
              {sessionStatus?.last_error && (
                <div className="text-xs text-red-400 pt-1 border-t border-gray-600 mt-1">
                  错误: {sessionStatus.last_error}
                </div>
              )}
              {sessionStatus?.created_at && (
                <div className="text-xs opacity-60 pt-1 border-t border-gray-600 mt-1">
                  创建于: {new Date(sessionStatus.created_at).toLocaleString('zh-CN')}
                </div>
              )}
            </div>
          }
        >
          <div
            className={`
              flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
              ${config.bgColor} ${config.color}
              transition-all duration-300 cursor-help
            `}
          >
            <StatusIcon
              size={12}
              className={config.animate ? 'animate-spin' : ''}
            />
            <span>{config.label}</span>
            {sessionStatus?.active_chats ? (
              <span className="ml-0.5">({sessionStatus.active_chats})</span>
            ) : null}
          </div>
        </Tooltip>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Resources: Tools */}
        {hasDetails && (
          <Tooltip title={`可用工具: ${sessionStatus?.tool_count || 0}`}>
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Wrench size={11} />
              <span>{sessionStatus?.tool_count || 0}</span>
            </div>
          </Tooltip>
        )}

        {/* Resources: Skills */}
        {sessionStatus?.skill_count ? (
          <Tooltip title={`已加载技能: ${sessionStatus.skill_count}`}>
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <BrainCircuit size={11} />
              <span>{sessionStatus.skill_count}</span>
            </div>
          </Tooltip>
        ) : null}

        {/* Resources: Subagents */}
        {sessionStatus?.subagent_count ? (
          <Tooltip title={`可用子代理: ${sessionStatus.subagent_count}`}>
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Bot size={11} />
              <span>{sessionStatus.subagent_count}</span>
            </div>
          </Tooltip>
        ) : null}

        {/* Uptime */}
        {sessionStatus?.uptime_seconds ? (
          <Tooltip title="运行时间">
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Clock size={11} />
              <span>{formatUptime(sessionStatus.uptime_seconds)}</span>
            </div>
          </Tooltip>
        ) : null}

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Message Count */}
        <Tooltip title="对话消息数">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <MessageSquare size={11} />
            <span>{messageCount}</span>
          </div>
        </Tooltip>

        {/* Sandbox Status */}
        {sandboxConnected && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title="沙盒环境已连接">
              <div className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <Terminal size={11} />
                <span>沙盒</span>
              </div>
            </Tooltip>
          </>
        )}

        {/* Plan Mode */}
        {isPlanMode && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title="计划模式 - Agent 正在创建详细计划">
              <div className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
                <Zap size={11} />
                <span>计划模式</span>
              </div>
            </Tooltip>
          </>
        )}

        {/* Streaming Indicator */}
        {isStreaming && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <div className="flex items-center gap-1 text-xs text-amber-600">
              <Activity size={11} className="animate-pulse" />
              <span>流式响应中</span>
            </div>
          </>
        )}

        {/* Error Indicator */}
        {isError && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title={sessionStatus?.last_error || 'Agent 错误'}>
              <div className="flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle size={11} />
                <span>错误</span>
              </div>
            </Tooltip>
          </>
        )}
      </div>

      {/* Right: Connection & Metrics */}
      <div className="flex items-center gap-3 text-xs">
        {/* Chats Stats */}
        {sessionStatus?.total_chats ? (
          <Tooltip
            title={`总对话: ${sessionStatus.total_chats}, 失败: ${sessionStatus.failed_chats || 0}`}
          >
            <div className="flex items-center gap-1.5 text-slate-400">
              <Badge
                count={sessionStatus.total_chats}
                style={{ fontSize: '10px', height: '14px', lineHeight: '14px', minWidth: '14px' }}
                color={sessionStatus.failed_chats ? 'warning' : 'success'}
              />
              <span>对话</span>
            </div>
          </Tooltip>
        ) : null}

        {/* Last Activity */}
        {sessionStatus?.last_activity_at && (
          <Tooltip title={`最后活动: ${new Date(sessionStatus.last_activity_at).toLocaleString('zh-CN')}`}>
            <span className="text-slate-400">
              {formatLastActivity(sessionStatus.last_activity_at)}
            </span>
          </Tooltip>
        )}

        {/* Connection Status */}
        <Tooltip title={isLoading ? '加载中...' : '已连接'}>
          <div className="flex items-center gap-1 text-slate-400">
            {isLoading ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Wifi size={12} />
            )}
            <span>{isLoading ? '加载中' : '已连接'}</span>
          </div>
        </Tooltip>
      </div>
    </div>
  );
};

export default ProjectAgentStatusBar;
