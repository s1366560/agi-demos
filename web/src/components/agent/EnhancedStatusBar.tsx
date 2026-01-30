/**
 * EnhancedStatusBar - Bottom status bar with Agent state integration via WebSocket
 */

import React from 'react';
import { Tooltip } from 'antd';
import { 
  Zap, 
  MessageSquare, 
  Terminal,
  Wifi,
  WifiOff,
  Brain,
  Wrench,
  Eye,
  Pause,
  Loader2,
  CheckCircle2,
  Sparkles,
  Workflow,
} from 'lucide-react';
import { useAgentStatusWebSocket } from '../../hooks/useAgentStatusWebSocket';

interface EnhancedStatusBarProps {
  projectId: string;
  isStreaming: boolean;
  agentState: string;
  isPlanMode: boolean;
  messageCount: number;
  sandboxConnected: boolean;
  activeToolCallsCount: number;
}

const iconMap: Record<string, React.ElementType> = {
  zap: Zap,
  brain: Brain,
  tool: Wrench,
  eye: Eye,
  pause: Pause,
  loader: Loader2,
  'check-circle': CheckCircle2,
  sparkles: Sparkles,
  wifi: Wifi,
  workflow: Workflow,
};

const colorMap: Record<string, { bg: string; text: string; dot: string }> = {
  emerald: { 
    bg: 'bg-emerald-500', 
    text: 'text-emerald-600 dark:text-emerald-400',
    dot: 'bg-emerald-500'
  },
  blue: { 
    bg: 'bg-blue-500', 
    text: 'text-blue-600 dark:text-blue-400',
    dot: 'bg-blue-500'
  },
  purple: { 
    bg: 'bg-purple-500', 
    text: 'text-purple-600 dark:text-purple-400',
    dot: 'bg-purple-500'
  },
  amber: { 
    bg: 'bg-amber-500', 
    text: 'text-amber-600 dark:text-amber-400',
    dot: 'bg-amber-500'
  },
  orange: { 
    bg: 'bg-orange-500', 
    text: 'text-orange-600 dark:text-orange-400',
    dot: 'bg-orange-500'
  },
  slate: { 
    bg: 'bg-slate-500', 
    text: 'text-slate-600 dark:text-slate-400',
    dot: 'bg-slate-500'
  },
};

export const EnhancedStatusBar: React.FC<EnhancedStatusBarProps> = ({
  projectId,
  isStreaming,
  agentState,
  isPlanMode,
  messageCount,
  sandboxConnected,
  activeToolCallsCount,
}) => {
  const { 
    sessionStatus, 
    isConnected,
    detailedStatus,
  } = useAgentStatusWebSocket({
    projectId,
    isStreaming,
    agentState,
    activeToolCallsCount,
    enabled: !!projectId,
  });

  const StatusIcon = iconMap[detailedStatus.icon] || Wifi;
  const colors = colorMap[detailedStatus.color] || colorMap.slate;
  const isPulsing = detailedStatus.color === 'amber' || detailedStatus.color === 'blue';

  return (
    <div className="px-4 py-1.5 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
      {/* Left: Status indicators */}
      <div className="flex items-center gap-4">
        {/* Agent Status with Enhanced Info */}
        <Tooltip 
          title={
            <div className="space-y-1 max-w-xs">
              <div className="font-medium">{detailedStatus.label}</div>
              <div className="text-xs opacity-80">{detailedStatus.description}</div>
              {sessionStatus && sessionStatus.is_initialized && (
                <div className="text-xs opacity-60 pt-1 border-t border-gray-600 mt-1">
                  Session: {sessionStatus.total_chats} chats | {sessionStatus.tool_count} tools
                  {sessionStatus.cached_since && (
                    <div className="mt-0.5">
                      Cached: {new Date(sessionStatus.cached_since).toLocaleTimeString()}
                    </div>
                  )}
                </div>
              )}
              {!isConnected && (
                <div className="text-xs text-amber-400 mt-1">
                  Reconnecting...
                </div>
              )}
            </div>
          }
        >
          <div className="flex items-center gap-2 cursor-help">
            <div className={`
              w-2 h-2 rounded-full transition-colors duration-300
              ${isPulsing ? 'animate-pulse' : ''}
              ${colors.dot}
            `} />
            <span className="text-xs text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
              {!isConnected && <WifiOff size={10} className="text-slate-400" />}
              <StatusIcon size={12} className={colors.text} />
              {detailedStatus.label}
            </span>
          </div>
        </Tooltip>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />

        {/* Message Count */}
        <Tooltip title="Messages in conversation">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 cursor-help">
            <MessageSquare size={12} />
            <span>{messageCount} messages</span>
          </div>
        </Tooltip>

        {/* Sandbox Status */}
        {sandboxConnected && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title="Sandbox environment active">
              <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 cursor-help">
                <Terminal size={12} />
                <span>Sandbox</span>
              </div>
            </Tooltip>
          </>
        )}

        {/* Plan Mode */}
        {isPlanMode && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-600" />
            <Tooltip title="Plan Mode - Agent is creating a detailed plan">
              <div className="flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400 cursor-help">
                <Zap size={12} />
                <span>Plan Mode</span>
              </div>
            </Tooltip>
          </>
        )}
      </div>

      {/* Right: Connection & Session info */}
      <div className="flex items-center gap-3 text-xs text-slate-400">
        {sessionStatus?.cached_since && (
          <Tooltip title={`Session cached since ${new Date(sessionStatus.cached_since).toLocaleTimeString()}`}>
            <div className="flex items-center gap-1 cursor-help">
              <CheckCircle2 size={12} />
              <span>Cached</span>
            </div>
          </Tooltip>
        )}
        <Tooltip title={isConnected ? "Connected to agent service" : "Disconnected - reconnecting..."}>
          <div className={`flex items-center gap-1 cursor-help ${isConnected ? '' : 'text-amber-500'}`}>
            {isConnected ? <Wifi size={12} /> : <WifiOff size={12} />}
            <span>{isConnected ? 'Connected' : 'Reconnecting'}</span>
          </div>
        </Tooltip>
      </div>
    </div>
  );
};
