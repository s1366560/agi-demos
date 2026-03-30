import type { FC } from 'react';

import { Loader2, Wifi, Activity } from 'lucide-react';

import type { UnifiedAgentStatus as AgentStatus } from '@/hooks/useUnifiedAgentStatus';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { TFunction } from 'i18next';

export interface ConnectionStatusProps {
  isLoading: boolean;
  status: AgentStatus;
  t: TFunction;
}

export const ConnectionStatus: FC<ConnectionStatusProps> = ({ isLoading, status }) => {
  return (
    <LazyTooltip
      title={
        <div className="space-y-1">
          <div>
            {isLoading
              ? 'Loading...'
              : status.connection.websocket
                ? 'WebSocket Connected'
                : 'Ready'}
          </div>
          {status.resources.activeCalls > 0 && (
            <div>Active tool calls: {status.resources.activeCalls}</div>
          )}
        </div>
      }
    >
      <div className="flex items-center gap-1.5 text-text-muted">
        {isLoading ? (
          <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
        ) : status.resources.activeCalls > 0 ? (
          <>
            <Activity
              size={12}
              className="text-info animate-pulse motion-reduce:animate-none"
            />
            <span className="hidden sm:inline text-info">
              {status.resources.activeCalls} active
            </span>
          </>
        ) : status.connection.websocket ? (
          <>
            <Wifi size={12} className="text-success" />
            <span className="hidden sm:inline text-success">Online</span>
          </>
        ) : (
          <>
            <Wifi size={12} />
            <span className="hidden sm:inline">Ready</span>
          </>
        )}
      </div>
    </LazyTooltip>
  );
};
