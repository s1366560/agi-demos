import React from 'react';

import { ProviderConfig, CircuitBreakerState } from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { ProviderIcon } from './ProviderIcon';

export interface ProviderCardProps {
  provider: ProviderConfig;
  onEdit: (provider: ProviderConfig) => void;
  onAssign: (provider: ProviderConfig) => void;
  onDelete: (providerId: string) => void;
  onCheckHealth: (providerId: string) => void;
  onResetCircuitBreaker: (providerType: string) => void;
  onViewStats?: (provider: ProviderConfig) => void;
  isCheckingHealth?: boolean;
  isResettingCircuitBreaker?: boolean;
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
        label: 'Healthy',
      };
    case 'degraded':
      return {
        color: 'text-amber-600 dark:text-amber-400',
        bgColor: 'bg-amber-50 dark:bg-amber-900/20',
        borderColor: 'border-amber-200 dark:border-amber-800',
        dotColor: 'bg-amber-500',
        icon: 'warning',
        label: 'Degraded',
      };
    case 'unhealthy':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-50 dark:bg-red-900/20',
        borderColor: 'border-red-200 dark:border-red-800',
        dotColor: 'bg-red-500',
        icon: 'error',
        label: 'Unhealthy',
      };
    default:
      return {
        color: 'text-slate-500 dark:text-slate-400',
        bgColor: 'bg-slate-50 dark:bg-slate-800/50',
        borderColor: 'border-slate-200 dark:border-slate-700',
        dotColor: 'bg-slate-400',
        icon: 'help',
        label: 'Unknown',
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
  const statusConfig = getStatusConfig(provider.health_status);
  const cbConfig = getCircuitBreakerConfig(provider.resilience?.circuit_breaker_state);

  return (
    <div className="group relative bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-all duration-200 overflow-hidden">
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
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-primary/10 text-primary border border-primary/20">
                    <MaterialIcon name="star" size={10} filled />
                    <span className="ml-0.5">Default</span>
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
            {provider.is_active ? 'Active' : 'Inactive'}
          </div>
        </div>
      </div>

      {/* Card Body */}
      <div className="p-4 space-y-3">
        {/* Models */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">LLM</span>
            <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
              {provider.llm_model}
            </code>
          </div>
          {provider.llm_small_model && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
                Small
              </span>
              <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
                {provider.llm_small_model}
              </code>
            </div>
          )}
          {provider.embedding_model && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 w-14 shrink-0">
                Embed
              </span>
              <code className="flex-1 px-2 py-1 bg-slate-50 dark:bg-slate-800 rounded text-xs text-slate-700 dark:text-slate-300 font-mono truncate">
                {provider.embedding_model}
              </code>
              {provider.embedding_config?.dimensions && (
                <span className="text-[10px] text-slate-400 shrink-0">
                  {provider.embedding_config.dimensions}d
                </span>
              )}
            </div>
          )}
        </div>

        {/* Status Bar */}
        <div
          className={`flex items-center justify-between p-2.5 rounded-lg border ${statusConfig.bgColor} ${statusConfig.borderColor}`}
        >
          {/* Health Status */}
          <div className="flex items-center gap-2">
            <MaterialIcon
              name={statusConfig.icon}
              size={16}
              className={statusConfig.color}
            />
            <div className="flex flex-col">
              <span className={`text-xs font-medium ${statusConfig.color}`}>
                {statusConfig.label}
              </span>
              {provider.response_time_ms && (
                <span className="text-[10px] text-slate-500">{provider.response_time_ms}ms</span>
              )}
            </div>
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />

          {/* Circuit Breaker */}
          <div className="flex items-center gap-2">
            <MaterialIcon
              name={cbConfig.icon}
              size={16}
              className={cbConfig.color}
            />
            <div className="flex flex-col">
              <span className={`text-xs font-medium ${cbConfig.color}`}>
                {cbConfig.label}
              </span>
              {provider.resilience?.failure_count ? (
                <span className="text-[10px] text-red-500">
                  {provider.resilience.failure_count} fails
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Card Footer - Actions */}
      <div className="flex items-center gap-1 p-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
        <button
          onClick={() => onCheckHealth(provider.id)}
          disabled={isCheckingHealth}
          className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-slate-200 dark:hover:border-slate-600"
          title="Check Health"
        >
          <MaterialIcon
            name={isCheckingHealth ? 'progress_activity' : 'monitor_heart'}
            size={16}
            className={isCheckingHealth ? 'animate-spin' : ''}
          />
          Health
        </button>

        {provider.resilience?.circuit_breaker_state &&
          provider.resilience.circuit_breaker_state !== 'closed' && (
            <button
              onClick={() => onResetCircuitBreaker(provider.provider_type)}
              disabled={isResettingCircuitBreaker}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium text-amber-600 dark:text-amber-400 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50 border border-transparent hover:border-amber-200 dark:hover:border-amber-800"
              title="Reset Circuit Breaker"
            >
              <MaterialIcon
                name={isResettingCircuitBreaker ? 'progress_activity' : 'refresh'}
                size={16}
                className={isResettingCircuitBreaker ? 'animate-spin' : ''}
              />
              Reset
            </button>
          )}

        {onViewStats && (
          <button
            onClick={() => onViewStats(provider)}
            className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
            title="View Statistics"
          >
            <MaterialIcon name="bar_chart" size={18} />
          </button>
        )}

        <button
          onClick={() => onAssign(provider)}
          className="p-2 text-slate-400 hover:text-blue-500 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title="Assign to Tenant"
        >
          <MaterialIcon name="assignment_ind" size={18} />
        </button>

        <button
          onClick={() => onEdit(provider)}
          className="p-2 text-slate-400 hover:text-primary hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title="Edit"
        >
          <MaterialIcon name="edit" size={18} />
        </button>

        <button
          onClick={() => onDelete(provider.id)}
          className="p-2 text-slate-400 hover:text-red-500 hover:bg-white dark:hover:bg-slate-700 rounded-lg transition-colors"
          title="Delete"
        >
          <MaterialIcon name="delete" size={18} />
        </button>
      </div>
    </div>
  );
};
