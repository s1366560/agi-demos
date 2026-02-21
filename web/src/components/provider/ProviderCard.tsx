import React from 'react';

import { ProviderConfig, CircuitBreakerState } from '../../types/memory';
import { ProviderIcon } from './ProviderIcon';

export interface ProviderCardProps {
  provider: ProviderConfig;
  onEdit: (provider: ProviderConfig) => void;
  onAssign: (provider: ProviderConfig) => void;
  onDelete: (providerId: string) => void;
  onCheckHealth: (providerId: string) => void;
  onResetCircuitBreaker: (providerType: string) => void;
  isCheckingHealth?: boolean;
  isResettingCircuitBreaker?: boolean;
}

const getStatusConfig = (healthStatus?: string) => {
  switch (healthStatus) {
    case 'healthy':
      return {
        bg: 'bg-green-500',
        text: 'text-green-700',
        bgSoft: 'bg-green-50 dark:bg-green-900/20',
        border: 'border-green-200 dark:border-green-800',
        icon: 'check_circle',
        label: 'Healthy',
      };
    case 'degraded':
      return {
        bg: 'bg-yellow-500',
        text: 'text-yellow-700',
        bgSoft: 'bg-yellow-50 dark:bg-yellow-900/20',
        border: 'border-yellow-200 dark:border-yellow-800',
        icon: 'warning',
        label: 'Degraded',
      };
    case 'unhealthy':
      return {
        bg: 'bg-red-500',
        text: 'text-red-700',
        bgSoft: 'bg-red-50 dark:bg-red-900/20',
        border: 'border-red-200 dark:border-red-800',
        icon: 'error',
        label: 'Unhealthy',
      };
    default:
      return {
        bg: 'bg-slate-400',
        text: 'text-slate-500',
        bgSoft: 'bg-slate-50 dark:bg-slate-800/20',
        border: 'border-slate-200 dark:border-slate-700',
        icon: 'help',
        label: 'Unknown',
      };
  }
};

const getCircuitBreakerConfig = (state?: CircuitBreakerState) => {
  switch (state) {
    case 'closed':
      return {
        color: 'text-green-700 bg-green-100 dark:bg-green-900/30 dark:text-green-400',
        icon: 'shield',
        label: 'Closed',
      };
    case 'open':
      return {
        color: 'text-red-700 bg-red-100 dark:bg-red-900/30 dark:text-red-400',
        icon: 'electric_bolt',
        label: 'Open',
      };
    case 'half_open':
      return {
        color: 'text-yellow-700 bg-yellow-100 dark:bg-yellow-900/30 dark:text-yellow-400',
        icon: 'halfway_full',
        label: 'Half Open',
      };
    default:
      return {
        color: 'text-slate-600 bg-slate-100 dark:bg-slate-700 dark:text-slate-400',
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
  isCheckingHealth = false,
  isResettingCircuitBreaker = false,
}) => {
  const statusConfig = getStatusConfig(provider.health_status);
  const cbConfig = getCircuitBreakerConfig(provider.resilience?.circuit_breaker_state);

  return (
    <div className="group relative bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm hover:shadow-xl hover:border-primary/30 transition-all duration-300 overflow-hidden">
      {/* Top gradient bar based on health status */}
      <div className={`h-1.5 w-full ${statusConfig.bg}`} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3 flex-1">
            <ProviderIcon providerType={provider.provider_type} size="lg" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold text-slate-900 dark:text-white truncate">
                  {provider.name}
                </h3>
                {provider.is_default && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-sm">
                    <span className="material-symbols-outlined text-[12px] mr-0.5">star</span>
                    Default
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {provider.provider_type}
              </p>
            </div>
          </div>

          {/* Active Toggle */}
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={provider.is_active}
              onChange={(e) => {
                e.stopPropagation();
                // Handle toggle in parent component
              }}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/20 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-gradient-to-r peer-checked:from-green-400 peer-checked:to-green-500"></div>
          </label>
        </div>

        {/* Models Info */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-400 dark:text-slate-500 w-16 shrink-0">LLM:</span>
            <code className="flex-1 px-2.5 py-1 bg-slate-100 dark:bg-slate-700/50 rounded-lg text-slate-700 dark:text-slate-300 font-mono text-xs truncate">
              {provider.llm_model}
            </code>
          </div>
          {provider.llm_small_model && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400 dark:text-slate-500 w-16 shrink-0">Small:</span>
              <code className="flex-1 px-2.5 py-1 bg-slate-100 dark:bg-slate-700/50 rounded-lg text-slate-700 dark:text-slate-300 font-mono text-xs truncate">
                {provider.llm_small_model}
              </code>
            </div>
          )}
          {provider.embedding_model && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400 dark:text-slate-500 w-16 shrink-0">Embed:</span>
              <code className="flex-1 px-2.5 py-1 bg-slate-100 dark:bg-slate-700/50 rounded-lg text-slate-700 dark:text-slate-300 font-mono text-xs truncate">
                {provider.embedding_model}
              </code>
              {provider.embedding_config?.dimensions && (
                <span className="text-xs text-slate-400 shrink-0">
                  {provider.embedding_config.dimensions}d
                </span>
              )}
            </div>
          )}
          {provider.reranker_model && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400 dark:text-slate-500 w-16 shrink-0">Rerank:</span>
              <code className="flex-1 px-2.5 py-1 bg-slate-100 dark:bg-slate-700/50 rounded-lg text-slate-700 dark:text-slate-300 font-mono text-xs truncate">
                {provider.reranker_model}
              </code>
            </div>
          )}
        </div>

        {/* Status Bar */}
        <div
          className={`flex items-center justify-between p-3 rounded-xl border ${statusConfig.bgSoft} ${statusConfig.border} mb-3`}
        >
          {/* Health Status */}
          <div className="flex items-center gap-2">
            <span
              className={`material-symbols-outlined text-lg ${statusConfig.text}`}
            >
              {statusConfig.icon}
            </span>
            <div>
              <p className={`text-xs font-medium ${statusConfig.text}`}>{statusConfig.label}</p>
              {provider.response_time_ms && (
                <p className="text-xs text-slate-500">{provider.response_time_ms}ms</p>
              )}
            </div>
          </div>

          {/* Divider */}
          <div className="h-8 w-px bg-slate-200 dark:bg-slate-600" />

          {/* Circuit Breaker */}
          <div className="flex items-center gap-2">
            <span
              className={`material-symbols-outlined text-lg ${cbConfig.color.split(' ')[0]}`}
            >
              {cbConfig.icon}
            </span>
            <div>
              <p className={`text-xs font-medium ${cbConfig.color.split(' ')[0]}`}>
                {cbConfig.label}
              </p>
              {provider.resilience?.failure_count ? (
                <p className="text-xs text-red-500">{provider.resilience.failure_count} fails</p>
              ) : null}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-3 border-t border-slate-100 dark:border-slate-700">
          <button
            onClick={() => onCheckHealth(provider.id)}
            disabled={isCheckingHealth}
            className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-primary/10 hover:text-primary rounded-lg transition-all disabled:opacity-50"
            title="Check Health"
          >
            <span
              className={`material-symbols-outlined text-[18px] ${isCheckingHealth ? 'animate-spin' : ''}`}
            >
              {isCheckingHealth ? 'progress_activity' : 'monitor_heart'}
            </span>
            Health
          </button>

          {provider.resilience?.circuit_breaker_state &&
            provider.resilience.circuit_breaker_state !== 'closed' && (
              <button
                onClick={() => onResetCircuitBreaker(provider.provider_type)}
                disabled={isResettingCircuitBreaker}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-yellow-600 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 rounded-lg transition-all disabled:opacity-50"
                title="Reset Circuit Breaker"
              >
                <span
                  className={`material-symbols-outlined text-[18px] ${isResettingCircuitBreaker ? 'animate-spin' : ''}`}
                >
                  {isResettingCircuitBreaker ? 'progress_activity' : 'refresh'}
                </span>
                Reset
              </button>
            )}

          <div className="flex-1" />

          <button
            onClick={() => onAssign(provider)}
            className="p-2 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-all"
            title="Assign to Tenant"
          >
            <span className="material-symbols-outlined text-[18px]">assignment_ind</span>
          </button>

          <button
            onClick={() => onEdit(provider)}
            className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-all"
            title="Edit"
          >
            <span className="material-symbols-outlined text-[18px]">edit</span>
          </button>

          <button
            onClick={() => onDelete(provider.id)}
            className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all"
            title="Delete"
          >
            <span className="material-symbols-outlined text-[18px]">delete</span>
          </button>
        </div>
      </div>
    </div>
  );
};
