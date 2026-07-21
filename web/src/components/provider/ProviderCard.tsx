import React from 'react';

import { useTranslation } from 'react-i18next';

import { BarChart, Pencil, Star, Trash2, UserCheck } from 'lucide-react';

import { renderDynamicIcon } from '@/components/shared/DynamicIcon';

import { ProviderIcon } from './ProviderIcon';

import type { CircuitBreakerState, ProviderConfig } from '../../types/memory';

export interface ProviderCardProps {
  provider: ProviderConfig;
  onEdit: (provider: ProviderConfig) => void;
  onAssign: (provider: ProviderConfig) => void;
  onDelete: (providerId: string) => void;
  onCheckHealth: (providerId: string) => void;
  onResetCircuitBreaker: (providerType: string) => void;
  onViewStats?: ((provider: ProviderConfig) => void) | undefined;
  isCheckingHealth?: boolean | undefined;
  isResettingCircuitBreaker?: boolean | undefined;
}

const getStatusConfig = (healthStatus?: string) => {
  switch (healthStatus) {
    case 'healthy':
      return {
        color: 'text-emerald-600 dark:text-emerald-400',
        bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
        borderColor: 'border-emerald-200 dark:border-emerald-800',
        dotColor: 'bg-emerald-500',
        icon: 'check_circle',
        labelDefault: 'Healthy',
        labelKey: 'common.status.healthy',
      };
    case 'configuration_valid':
      return {
        color: 'text-emerald-600 dark:text-emerald-400',
        bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
        borderColor: 'border-emerald-200 dark:border-emerald-800',
        dotColor: 'bg-emerald-500',
        icon: 'check_circle',
        labelDefault: 'Configuration validated',
        labelKey: 'common.status.configurationValid',
      };
    case 'degraded':
      return {
        color: 'text-amber-600 dark:text-amber-400',
        bgColor: 'bg-amber-50 dark:bg-amber-900/20',
        borderColor: 'border-amber-200 dark:border-amber-800',
        dotColor: 'bg-amber-500',
        icon: 'warning',
        labelDefault: 'Degraded',
        labelKey: 'common.status.degraded',
      };
    case 'unhealthy':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        borderColor: 'border-red-200 dark:border-red-800',
        dotColor: 'bg-red-500',
        icon: 'error',
        labelDefault: 'Unhealthy',
        labelKey: 'common.status.unhealthy',
      };
    default:
      return {
        color: 'text-slate-500 dark:text-slate-400',
        bgColor: 'bg-slate-50 dark:bg-slate-800/50',
        borderColor: 'border-slate-200 dark:border-slate-700',
        dotColor: 'bg-slate-400',
        icon: 'help',
        labelDefault: 'Unknown',
        labelKey: 'common.status.unknown',
      };
  }
};

const getCircuitBreakerConfig = (state?: CircuitBreakerState) => {
  switch (state) {
    case 'closed':
      return {
        color: 'text-emerald-600 dark:text-emerald-400',
        bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
        icon: 'shield',
        label: 'Closed',
      };
    case 'open':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        icon: 'electric_bolt',
        label: 'Open',
      };
    case 'half_open':
      return {
        color: 'text-amber-600 dark:text-amber-400',
        bgColor: 'bg-amber-50 dark:bg-amber-900/20',
        icon: 'halfway_full',
        label: 'Half Open',
      };
    default:
      return {
        color: 'text-slate-500 dark:text-slate-400',
        bgColor: 'bg-slate-50 dark:bg-slate-800/50',
        icon: 'help',
        label: 'Unknown',
      };
  }
};

export const ProviderCard: React.FC<ProviderCardProps> = ({
  provider,
  onEdit,
  onAssign,
  onDelete,
  onCheckHealth,
  onResetCircuitBreaker,
  onViewStats,
  isCheckingHealth = false,
  isResettingCircuitBreaker = false,
}) => {
  const { t } = useTranslation();
  const statusConfig = getStatusConfig(provider.health_status);
  const cbConfig = getCircuitBreakerConfig(provider.resilience?.circuit_breaker_state);

  return (
    <div className="group relative bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 overflow-hidden">
      {/* Card Header */}
      <div className="p-4 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <ProviderIcon providerType={provider.provider_type} size="md" />
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                  {provider.name}
                </h3>
                {provider.is_default && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-2xs font-medium bg-primary/10 text-primary border border-primary/20">
                    <Star size={10} className="fill-current" />
                    <span className="ml-0.5">
                      {t('tenant.providers.defaultBadge', { defaultValue: 'Default' })}
                    </span>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {provider.provider_type} • {provider.api_key_masked}
              </p>
            </div>
          </div>

          {/* Status Badge */}
          <div
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
              provider.is_active
                ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                : 'bg-slate-50 dark:bg-slate-800/50 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                provider.is_active ? 'bg-emerald-500' : 'bg-slate-400'
              }`}
            />
            {provider.is_active ? t('common.status.active') : t('common.status.inactive')}
          </div>
        </div>
      </div>

      {/* Card Body */}
      <div className="p-4 space-y-3">
        {/* Models */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
              {t('components.provider.card.labels.llm', { defaultValue: 'LLM' })}
            </span>
            <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
              {provider.llm_model}
            </code>
          </div>
          {provider.llm_small_model && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
                {t('components.provider.card.labels.small', { defaultValue: 'Small' })}
              </span>
              <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
                {provider.llm_small_model}
              </code>
            </div>
          )}
          {provider.embedding_model && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
                {t('components.provider.card.labels.embed', { defaultValue: 'Embed' })}
              </span>
              <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
                {provider.embedding_model}
              </code>
              {provider.embedding_config?.dimensions && (
                <span className="text-2xs text-slate-400 shrink-0">
                  {provider.embedding_config.dimensions}d
                </span>
              )}
            </div>
          )}
          {provider.reranker_model && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
                {t('components.provider.card.labels.rerank', { defaultValue: 'Rerank' })}
              </span>
              <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
                {provider.reranker_model}
              </code>
            </div>
          )}
        </div>

        {/* Status Bar */}
        <div
          className={`flex items-center justify-between p-2.5 rounded-lg border ${statusConfig.bgColor} ${statusConfig.borderColor}`}
        >
          {/* Health Status */}
          <div className="flex items-center gap-2">
            {renderDynamicIcon(statusConfig.icon, 16, statusConfig.color)}
            <div className="flex flex-col">
              <span className={`text-xs font-medium ${statusConfig.color}`}>
                {t(statusConfig.labelKey, { defaultValue: statusConfig.labelDefault })}
              </span>
              {provider.response_time_ms && (
                <span className="text-2xs text-slate-500">{provider.response_time_ms}ms</span>
              )}
            </div>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />

          {/* Circuit Breaker */}
          <div className="flex items-center gap-2">
            {renderDynamicIcon(cbConfig.icon, 16, cbConfig.color)}
            <div className="flex flex-col">
              <span className={`text-xs font-medium ${cbConfig.color}`}>{cbConfig.label}</span>
              {provider.resilience?.failure_count ? (
                <span className="text-2xs text-red-500">
                  {t('components.provider.card.failureCount', {
                    count: provider.resilience.failure_count,
                    defaultValue: '{{count}} fails',
                  })}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Card Footer - Actions */}
      <div className="flex items-center gap-1 p-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
        <button
          type="button"
          onClick={() => {
            onCheckHealth(provider.id);
          }}
          disabled={isCheckingHealth}
          className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-600"
          title={t('components.provider.card.actions.checkHealth', {
            defaultValue: 'Check Health',
          })}
        >
          {renderDynamicIcon(
            isCheckingHealth ? 'progress_activity' : 'monitor_heart',
            16,
            isCheckingHealth ? 'animate-spin motion-reduce:animate-none' : ''
          )}
          {t('components.provider.card.actions.health', { defaultValue: 'Health' })}
        </button>

        {provider.resilience?.circuit_breaker_state &&
          provider.resilience.circuit_breaker_state !== 'closed' && (
            <button
              type="button"
              onClick={() => {
                onResetCircuitBreaker(provider.provider_type);
              }}
              disabled={isResettingCircuitBreaker}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-amber-600 dark:text-amber-400 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-amber-200 dark:hover:border-amber-800"
              title={t('components.provider.card.actions.resetCircuitBreaker', {
                defaultValue: 'Reset Circuit Breaker',
              })}
            >
              {renderDynamicIcon(
                isResettingCircuitBreaker ? 'progress_activity' : 'refresh',
                16,
                isResettingCircuitBreaker ? 'animate-spin motion-reduce:animate-none' : ''
              )}
              {t('components.provider.card.actions.reset', { defaultValue: 'Reset' })}
            </button>
          )}

        {onViewStats && (
          <button
            type="button"
            onClick={() => {
              onViewStats(provider);
            }}
            aria-label={t('components.provider.card.actions.viewStatistics', {
              defaultValue: 'View Statistics',
            })}
            className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
            title={t('components.provider.card.actions.viewStatistics', {
              defaultValue: 'View Statistics',
            })}
          >
            <BarChart size={18} />
          </button>
        )}

        <button
          type="button"
          onClick={() => {
            onAssign(provider);
          }}
          aria-label={t('components.provider.card.actions.assignToTenant', {
            defaultValue: 'Assign to Tenant',
          })}
          className="p-2 text-slate-400 hover:text-blue-500 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title={t('components.provider.card.actions.assignToTenant', {
            defaultValue: 'Assign to Tenant',
          })}
        >
          <UserCheck size={18} />
        </button>

        <button
          type="button"
          onClick={() => {
            onEdit(provider);
          }}
          aria-label={t('common.edit')}
          className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title={t('common.edit')}
        >
          <Pencil size={18} />
        </button>

        <button
          type="button"
          onClick={() => {
            onDelete(provider.id);
          }}
          aria-label={t('common.delete')}
          className="p-2 text-slate-400 hover:text-red-500 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title={t('common.delete')}
        >
          <Trash2 size={18} />
        </button>
      </div>
    </div>
  );
};
