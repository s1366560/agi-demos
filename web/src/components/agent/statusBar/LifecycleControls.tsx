import type { FC } from 'react';

import { PauseCircle, Play, Square, RefreshCw, Loader2 } from 'lucide-react';

import { LazyTooltip, LazyPopconfirm } from '@/components/ui/lazyAntd';

import type { TFunction } from 'i18next';

export interface LifecycleControlsProps {
  canPause: boolean;
  canResume: boolean;
  canStop: boolean;
  canRestart: boolean;
  isActionPending: boolean;
  enablePoolManagement: boolean;
  poolEnabled: boolean;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onRestart: () => void;
  t: TFunction;
}

export const LifecycleControls: FC<LifecycleControlsProps> = ({
  canPause,
  canResume,
  canStop,
  canRestart,
  isActionPending,
  enablePoolManagement,
  poolEnabled,
  onPause,
  onResume,
  onStop,
  onRestart,
  t,
}) => {
  return (
    <div className="flex items-center gap-1.5">
      {/* Pause Button - pool mode only, shown when agent is ready */}
      {canPause && (
        <LazyTooltip title={t('agent.lifecycle.controls.pause')}>
          <button
            type="button"
            onClick={onPause}
            disabled={isActionPending}
            className={`
              p-1 rounded transition-colors
              ${
                isActionPending
                  ? 'text-text-muted cursor-not-allowed'
                  : 'text-caution hover:bg-caution-bg dark:hover:bg-caution-bg-dark'
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
      {canResume && (
        <LazyTooltip title={t('agent.lifecycle.controls.resume')}>
          <button
            type="button"
            onClick={onResume}
            disabled={isActionPending}
            className={`
              p-1 rounded transition-colors
              ${
                isActionPending
                  ? 'text-text-muted cursor-not-allowed'
                  : 'text-success hover:bg-success-bg dark:hover:bg-success-bg-dark'
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
      {canStop && (
        <LazyPopconfirm
          title={t('agent.lifecycle.controls.stopAgent')}
          description={
            enablePoolManagement && poolEnabled
              ? t('agent.lifecycle.controls.confirmTerminate')
              : t('agent.lifecycle.controls.confirmStop')
          }
          onConfirm={onStop}
          okText={t('agent.lifecycle.controls.stop')}
          cancelText={t('agent.lifecycle.controls.cancel')}
          okButtonProps={{ danger: true }}
        >
          <LazyTooltip title={enablePoolManagement && poolEnabled ? t('agent.lifecycle.controls.terminateInstance') : t('agent.lifecycle.controls.stopAgent')}>
            <button
              type="button"
              disabled={isActionPending}
              className={`
                p-1 rounded transition-colors
                ${
                  isActionPending
                    ? 'text-text-muted cursor-not-allowed'
                    : 'text-error hover:bg-error-bg dark:hover:bg-error-bg-dark'
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
      {canRestart && (
        <LazyPopconfirm
          title={t('agent.lifecycle.controls.restart')}
          description={t('agent.lifecycle.controls.confirmRestart')}
          onConfirm={onRestart}
          okText={t('agent.lifecycle.controls.restart')}
          cancelText={t('agent.lifecycle.controls.cancel')}
        >
          <LazyTooltip title={t('agent.lifecycle.controls.restartAgent')}>
            <button
              type="button"
              disabled={isActionPending}
              className={`
                p-1 rounded transition-colors
                ${
                  isActionPending
                    ? 'text-text-muted cursor-not-allowed'
                    : 'text-info hover:bg-info-bg dark:hover:bg-info-bg-dark'
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
};
