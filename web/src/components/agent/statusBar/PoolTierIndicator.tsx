import type { FC } from 'react';

import { Layers, Flame, Cloud, Snowflake, Heart, Loader2 } from 'lucide-react';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { PoolInstance, ProjectTier } from '../../../services/poolService';
import type { TFunction } from 'i18next';
import type { LucideIcon } from 'lucide-react';

/**
 * Tier configuration for pool-based management
 */
const tierConfig: Record<
  ProjectTier,
  {
    label: string;
    icon: LucideIcon;
    color: string;
    bgColor: string;
  }
> = {
  hot: {
    label: 'HOT',
    icon: Flame,
    color: 'text-caution',
    bgColor: 'bg-caution-bg dark:bg-caution-bg-dark',
  },
  warm: {
    label: 'WARM',
    icon: Cloud,
    color: 'text-info',
    bgColor: 'bg-info-bg dark:bg-info-bg-dark',
  },
  cold: {
    label: 'COLD',
    icon: Snowflake,
    color: 'text-text-muted',
    bgColor: 'bg-surface-alt dark:bg-surface-dark-alt',
  },
};

export interface PoolTierIndicatorProps {
  poolEnabled: boolean;
  poolInstance: PoolInstance | null;
  poolLoading: boolean;
  t: TFunction;
}

export const PoolTierIndicator: FC<PoolTierIndicatorProps> = ({
  poolEnabled,
  poolInstance,
  poolLoading,
  t,
}) => {
  if (!poolEnabled) return null;

  const poolTierConfig = poolInstance?.tier ? tierConfig[poolInstance.tier] : null;
  const TierIcon = poolTierConfig?.icon ?? Layers;

  return (
    <>
      <LazyTooltip
        title={
          <div className="space-y-2 max-w-xs">
            <div className="font-medium flex items-center gap-2">
              <Layers size={14} />
              <span>{t('agent.lifecycle.pool.title')}</span>
            </div>
            {poolInstance ? (
              <>
                <div className="text-xs">
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.tier')}:</span>
                    <span className={poolTierConfig?.color}>{poolTierConfig?.label}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.status')}:</span>
                    <span>{poolInstance.status}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.health')}:</span>
                    <span
                      className={
                        poolInstance.health_status === 'healthy'
                          ? 'text-status-text-success-dark'
                          : 'text-status-text-warning-dark'
                      }
                    >
                      {poolInstance.health_status}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.activeRequests')}:</span>
                    <span>{poolInstance.active_requests}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.totalRequests')}:</span>
                    <span>{poolInstance.total_requests}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="opacity-70">{t('agent.lifecycle.pool.memory')}:</span>
                    <span>{poolInstance.memory_used_mb} MB</span>
                  </div>
                </div>
                <div className="text-xs opacity-70 pt-1 border-t border-border-dark mt-1">
                  {poolInstance?.tier ? t(`agent.lifecycle.pool.tiers.${poolInstance.tier}`) : ''}
                </div>
              </>
            ) : (
              <div className="text-xs opacity-70">{t('agent.lifecycle.pool.noInstance')}</div>
            )}
          </div>
        }
      >
        <div
          className={`
            flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
            ${poolTierConfig?.bgColor ?? 'bg-surface-alt dark:bg-surface-dark-alt'}
            ${poolTierConfig?.color ?? 'text-text-muted'}
            transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 cursor-help
          `}
        >
          {poolLoading ? (
            <Loader2 size={12} className="animate-spin motion-reduce:animate-none" />
          ) : (
            <TierIcon size={12} />
          )}
          <span className="hidden sm:inline">
            {poolInstance ? (poolTierConfig?.label ?? 'POOL') : t('agent.lifecycle.pool.pending')}
          </span>
          {poolInstance?.health_status === 'healthy' && (
            <Heart size={10} className="text-success fill-success" />
          )}
        </div>
      </LazyTooltip>
      {/* Separator */}
      <div className="w-px h-3 bg-border-separator dark:bg-border-separator-dark hidden sm:block" />
    </>
  );
};
