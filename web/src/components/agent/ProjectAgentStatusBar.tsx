/**
 * ProjectAgentStatusBar - Project ReAct Agent Lifecycle Status Bar
 *
 * Displays the complete lifecycle state of the ProjectReActAgent:
 * - Sandbox status (with click-to-start and metrics popover)
 * - Lifecycle state (uninitialized, initializing, ready, executing, paused, error, shutting_down)
 * - Resource counts (tools, skills, subagents)
 * - Execution metrics (total/failed chats, active chats)
 * - Health status (uptime, last error)
 *
 * This component now uses the unified agent status hook for consolidated state management.
 *
 * @module components/agent/ProjectAgentStatusBar
 */

import type { FC } from 'react';
import { Tooltip, Badge } from 'antd';
import {
  Zap,
  MessageSquare,
  Wifi,
  Loader2,
  CheckCircle2,
  AlertCircle,
  PauseCircle,
  Power,
  Cpu,
  Wrench,
  BrainCircuit,
  Activity,
  AlertTriangle,
} from 'lucide-react';
import { useUnifiedAgentStatus, type ProjectAgentLifecycleState } from '../../hooks/useUnifiedAgentStatus';
import { SandboxStatusIndicator } from './sandbox/SandboxStatusIndicator';

interface ProjectAgentStatusBarProps {
  /** Project ID */
  projectId: string;
  /** Tenant ID */
  tenantId: string;
  /** Number of messages */
  messageCount?: number;
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
 * ProjectAgentStatusBar - Refactored to use unified status hook
 *
 * This component now uses the useUnifiedAgentStatus hook which consolidates:
 * - Lifecycle state (from useAgentLifecycleState via WebSocket)
 * - Execution state (from agentV3 store)
 * - Plan mode state (from planModeStore)
 * - Streaming state (from streamingStore)
 * - Sandbox connection (from sandboxStore)
 */
export const ProjectAgentStatusBar: FC<ProjectAgentStatusBarProps> = ({
  projectId,
  tenantId,
  messageCount = 0,
}) => {
  // Use the unified status hook for consolidated state (WebSocket-based)
  const { status, isLoading, error, isStreaming } = useUnifiedAgentStatus({
    projectId,
    tenantId,
    enabled: !!projectId,
  });

  const lifecycleState = status.lifecycle;
  const config = lifecycleConfig[lifecycleState];

  const StatusIcon = config.icon;
  const isError = lifecycleState === 'error';

  return (
    <div className="px-4 py-1.5 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
      {/* Left: Sandbox Status, Lifecycle Status & Resources */}
      <div className="flex items-center gap-3">
        {/* Sandbox Status Indicator (First Column) */}
        <SandboxStatusIndicator
          projectId={projectId}
          tenantId={tenantId}
        />

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Agent Lifecycle Status */}
        <Tooltip
          title={
            <div className="space-y-2 max-w-xs">
              <div className="font-medium">{config.label}</div>
              <div className="text-xs opacity-80">{config.description}</div>
              {error && (
                <div className="text-xs text-red-400 pt-1 border-t border-gray-600 mt-1">
                  错误: {error}
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
            {status.resources.activeCalls > 0 ? (
              <span className="ml-0.5">({status.resources.activeCalls})</span>
            ) : null}
          </div>
        </Tooltip>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Resources: Tools - always show if we have data */}
        {status.resources.tools > 0 && (
          <Tooltip title={`可用工具: ${status.resources.tools}`}>
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Wrench size={11} />
              <span>{status.resources.tools}</span>
            </div>
          </Tooltip>
        )}

        {/* Resources: Skills - always show if we have data */}
        {status.resources.skills > 0 && (
          <Tooltip title={`已加载技能: ${status.resources.skills}`}>
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <BrainCircuit size={11} />
              <span>{status.resources.skills}</span>
            </div>
          </Tooltip>
        )}

        {/* Message Count */}
        <Tooltip title="对话消息数">
          <div className="flex items-center gap-1 text-xs text-slate-500">
            <MessageSquare size={11} />
            <span>{messageCount}</span>
          </div>
        </Tooltip>

        {/* Plan Mode */}
        {status.planMode.isActive && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title={`${status.planMode.currentMode?.toUpperCase() || 'PLAN'} 模式 - Agent 正在创建详细计划`}>
              <div className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
                <Zap size={11} />
                <span>{status.planMode.currentMode === 'plan' ? '计划' : status.planMode.currentMode}</span>
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
            <Tooltip title={error || 'Agent 错误'}>
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
        {/* Active Calls */}
        {status.resources.activeCalls > 0 && (
          <Tooltip title={`活跃工具调用: ${status.resources.activeCalls}`}>
            <div className="flex items-center gap-1.5 text-slate-400">
              <Badge
                count={status.resources.activeCalls}
                style={{ fontSize: '10px', height: '14px', lineHeight: '14px', minWidth: '14px' }}
                color="blue"
              />
              <span>调用</span>
            </div>
          </Tooltip>
        )}

        {/* Connection Status */}
        <Tooltip title={isLoading ? '加载中...' : status.connection.websocket ? 'WebSocket 已连接' : '就绪'}>
          <div className="flex items-center gap-1 text-slate-400">
            {isLoading ? (
              <Loader2 size={12} className="animate-spin" />
            ) : status.connection.websocket ? (
              <Wifi size={12} />
            ) : (
              <Wifi size={12} />
            )}
            <span>{isLoading ? '加载中' : status.connection.websocket ? '已连接' : '就绪'}</span>
          </div>
        </Tooltip>
      </div>
    </div>
  );
};

export default ProjectAgentStatusBar;
