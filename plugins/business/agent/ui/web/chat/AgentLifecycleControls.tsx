import { Loader2, PauseCircle, Play, RefreshCw, Square } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { LazyPopconfirm, LazyTooltip } from '@/components/ui/lazyAntd';

export type ActorAction = 'pause' | 'resume' | 'stop' | 'restart';

export function AgentLifecycleControls({
  allowed,
  isActionPending,
  poolManaged,
  onAction,
}: {
  allowed: readonly ActorAction[];
  isActionPending: boolean;
  poolManaged: boolean;
  onAction: (action: ActorAction) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-1.5">
      {/* Pause Button - pool mode only, shown when agent is ready */}
      {allowed.includes('pause') && (
        <LazyTooltip title={t('agent.lifecycle.controls.pause')}>
          <button
            type="button"
            aria-label={t('agent.lifecycle.controls.pause')}
            onClick={() => {
              void onAction('pause');
            }}
            disabled={isActionPending}
            className={`
                  rounded-md p-1 transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50
                  disabled:cursor-not-allowed disabled:opacity-40
                  ${
                    isActionPending
                      ? 'text-slate-400'
                      : 'text-orange-500 hover:bg-orange-100 dark:hover:bg-orange-900/30'
                  }
                `}
          >
            {isActionPending ? (
              <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
            ) : (
              <PauseCircle size={14} />
            )}
          </button>
        </LazyTooltip>
      )}

      {/* Resume Button - pool mode only, shown when agent is paused */}
      {allowed.includes('resume') && (
        <LazyTooltip title={t('agent.lifecycle.controls.resume')}>
          <button
            type="button"
            aria-label={t('agent.lifecycle.controls.resume')}
            onClick={() => {
              void onAction('resume');
            }}
            disabled={isActionPending}
            className={`
                  rounded-md p-1 transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50
                  disabled:cursor-not-allowed disabled:opacity-40
                  ${
                    isActionPending
                      ? 'text-slate-400'
                      : 'text-emerald-500 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                  }
                `}
          >
            {isActionPending ? (
              <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
            ) : (
              <Play size={14} />
            )}
          </button>
        </LazyTooltip>
      )}

      {/* Stop Button - shown when agent is running */}
      {allowed.includes('stop') && (
        <LazyPopconfirm
          title={t('agent.lifecycle.controls.stopAgent')}
          description={
            poolManaged
              ? t('agent.lifecycle.controls.confirmTerminate')
              : t('agent.lifecycle.controls.confirmStop')
          }
          onConfirm={() => onAction('stop')}
          okText={t('agent.lifecycle.controls.stop')}
          cancelText={t('agent.lifecycle.controls.cancel')}
          okButtonProps={{ danger: true }}
        >
          <LazyTooltip
            title={
              poolManaged
                ? t('agent.lifecycle.controls.terminateInstance')
                : t('agent.lifecycle.controls.stopAgent')
            }
          >
            <button
              type="button"
              aria-label={
                poolManaged
                  ? t('agent.lifecycle.controls.terminateInstance')
                  : t('agent.lifecycle.controls.stopAgent')
              }
              disabled={isActionPending}
              className={`
                    rounded-md p-1 transition-colors duration-150
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50
                    disabled:cursor-not-allowed disabled:opacity-40
                    ${
                      isActionPending
                        ? 'text-slate-400'
                        : 'text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30'
                    }
                  `}
            >
              {isActionPending ? (
                <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
              ) : (
                <Square size={14} />
              )}
            </button>
          </LazyTooltip>
        </LazyPopconfirm>
      )}

      {/* Restart Button - shown when agent exists */}
      {allowed.includes('restart') && (
        <LazyPopconfirm
          title={t('agent.lifecycle.controls.restart')}
          description={t('agent.lifecycle.controls.confirmRestart')}
          onConfirm={() => onAction('restart')}
          okText={t('agent.lifecycle.controls.restart')}
          cancelText={t('agent.lifecycle.controls.cancel')}
        >
          <LazyTooltip title={t('agent.lifecycle.controls.restartAgent')}>
            <button
              type="button"
              aria-label={t('agent.lifecycle.controls.restartAgent')}
              disabled={isActionPending}
              className={`
                    rounded-md p-1 transition-colors duration-150
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50
                    disabled:cursor-not-allowed disabled:opacity-40
                    ${
                      isActionPending
                        ? 'text-slate-400'
                        : 'text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30'
                    }
                  `}
            >
              {isActionPending ? (
                <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
              ) : (
                <RefreshCw size={14} />
              )}
            </button>
          </LazyTooltip>
        </LazyPopconfirm>
      )}
    </div>
  );
}
