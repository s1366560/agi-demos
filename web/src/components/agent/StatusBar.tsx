/**
 * StatusBar - Bottom status bar
 * Aligned with sidebar user profile section
 */

import React from 'react';
import { Tooltip } from 'antd';
import { 
  Zap, 
  MessageSquare, 
  Terminal,
  Wifi,
  Bot
} from 'lucide-react';

interface StatusBarProps {
  isStreaming: boolean;
  isPlanMode: boolean;
  messageCount: number;
  sandboxConnected: boolean;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  isStreaming,
  isPlanMode,
  messageCount,
  sandboxConnected,
}) => {
  return (
    <div className="p-3 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
      <div className="flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 h-[52px]">
        {/* Agent Avatar - aligned with sidebar user avatar */}
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
          <Bot size={16} />
        </div>

        {/* Status Info */}
        <div className="flex-1 flex items-center justify-between min-w-0">
          {/* Left: Status indicators */}
          <div className="flex items-center gap-3">
            {/* Agent Status */}
            <Tooltip title={isStreaming ? 'Agent is thinking...' : 'Agent ready'}>
              <div className="flex items-center gap-1.5">
                <div className={`
                  w-2 h-2 rounded-full
                  ${isStreaming ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'}
                `} />
                <span className="text-xs text-slate-600 dark:text-slate-300 font-medium leading-4">
                  {isStreaming ? 'Processing...' : 'Ready'}
                </span>
              </div>
            </Tooltip>

            {/* Separator */}
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />

            {/* Message Count */}
            <div className="flex items-center gap-1 text-xs text-slate-500 leading-4">
              <MessageSquare size={12} />
              <span>{messageCount}</span>
            </div>

            {/* Sandbox Status */}
            {sandboxConnected && (
              <>
                <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />
                <div className="flex items-center gap-1 text-xs text-emerald-600 leading-4">
                  <Terminal size={12} />
                  <span>Sandbox</span>
                </div>
              </>
            )}

            {/* Plan Mode */}
            {isPlanMode && (
              <>
                <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />
                <div className="flex items-center gap-1 text-xs text-blue-600 leading-4">
                  <Zap size={12} />
                  <span>Plan</span>
                </div>
              </>
            )}
          </div>

          {/* Right: Connection status */}
          <div className="flex items-center gap-1 text-xs text-slate-400 leading-4">
            <Wifi size={12} />
            <span>Connected</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default StatusBar;
