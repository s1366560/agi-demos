/**
 * StatusBar - Bottom status bar
 */

import React from 'react';
import { Tooltip } from 'antd';
import { 
  Zap, 
  MessageSquare, 
  Terminal,
  Wifi
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
    <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
      {/* Left: Status indicators */}
      <div className="flex items-center gap-4">
        {/* Agent Status */}
        <Tooltip title={isStreaming ? 'Agent is thinking...' : 'Agent ready'}>
          <div className="flex items-center gap-2">
            <div className={`
              w-2 h-2 rounded-full
              ${isStreaming ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'}
            `} />
            <span className="text-xs text-slate-500">
              {isStreaming ? 'Processing...' : 'Ready'}
            </span>
          </div>
        </Tooltip>

        {/* Separator */}
        <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />

        {/* Message Count */}
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <MessageSquare size={12} />
          <span>{messageCount} messages</span>
        </div>

        {/* Sandbox Status */}
        {sandboxConnected && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />
            <div className="flex items-center gap-1.5 text-xs text-emerald-600">
              <Terminal size={12} />
              <span>Sandbox</span>
            </div>
          </>
        )}

        {/* Plan Mode */}
        {isPlanMode && (
          <>
            <div className="w-px h-3 bg-slate-300 dark:bg-slate-700" />
            <div className="flex items-center gap-1.5 text-xs text-blue-600">
              <Zap size={12} />
              <span>Plan Mode</span>
            </div>
          </>
        )}
      </div>

      {/* Right: System info */}
      <div className="flex items-center gap-3 text-xs text-slate-400">
        <div className="flex items-center gap-1">
          <Wifi size={12} />
          <span>Connected</span>
        </div>
      </div>
    </div>
  );
};
