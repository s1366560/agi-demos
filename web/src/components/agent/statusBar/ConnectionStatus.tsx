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

export const ConnectionStatus: FC<ConnectionStatusProps> = ({ isLoading, status, t }) => {
  return (
    <LazyTooltip
      title={
        <div className="space-y-1">
          <div>
            {isLoading
              ? t('agent.statusBar.connection.loading', 'Loading...')
              : status.connection.websocket
                ? t('agent.statusBar.connection.websocketConnected', 'WebSocket Connected')
                : t('agent.statusBar.connection.ready', 'Ready')}
          </div>
          {status.resources.activeCalls > 0 && (
            <div>
              {t('agent.statusBar.connection.activeToolCalls', {
                count: status.resources.activeCalls,
                defaultValue: 'Active tool calls: {{count}}',
              })}
            </div>
          )}
        </div>
      }
    >
      <div className="flex items-center gap-1.5 text-text-muted">
        {isLoading ? (
          <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
        ) : status.resources.activeCalls > 0 ? (
          <>
            <Activity size={12} className="text-info animate-pulse motion-reduce:animate-none" />
            <span className="hidden sm:inline text-info">
              {t('agent.statusBar.connection.activeCount', {
                count: status.resources.activeCalls,
                defaultValue: '{{count}} active',
              })}
            </span>
          </>
        ) : status.connection.websocket ? (
          <>
            <Wifi size={12} className="text-success" />
            <span className="hidden sm:inline text-success">
              {t('agent.statusBar.connection.online', 'Online')}
            </span>
          </>
        ) : (
          <>
            <Wifi size={12} />
            <span className="hidden sm:inline">
              {t('agent.statusBar.connection.ready', 'Ready')}
            </span>
          </>
        )}
      </div>
    </LazyTooltip>
  );
};
