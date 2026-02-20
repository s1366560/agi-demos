import React from 'react';

import {
  ProviderConfig,
  ProviderStatus,
  CircuitBreakerState,
  ProviderType,
} from '../../types/memory';

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

const PROVIDER_ICONS: Record<ProviderType, string> = {
  openai: '🤖',
  anthropic: '🧠',
  gemini: '✨',
  dashscope: '🌐',
  kimi: '🌙',
  groq: '⚡',
  azure_openai: '☁️',
  cohere: '🔮',
  mistral: '🌪️',
  bedrock: '🏔️',
  vertex: '📊',
  deepseek: '🔍',
  zai: '🐲',
  ollama: '🦙',
  lmstudio: '🖥️',
};

const PROVIDER_TYPE_LABELS: Record<ProviderType, string> = {
  openai: 'OpenAI',
  dashscope: 'Dashscope',
  kimi: 'Moonshot Kimi',
  gemini: 'Google Gemini',
  anthropic: 'Anthropic',
  groq: 'Groq',
  azure_openai: 'Azure OpenAI',
  cohere: 'Cohere',
  mistral: 'Mistral',
  bedrock: 'AWS Bedrock',
  vertex: 'Google Vertex AI',
  deepseek: 'Deepseek',
  zai: 'ZhipuAI',
  ollama: 'Ollama',
  lmstudio: 'LM Studio',
};

const getStatusColor = (status?: ProviderStatus) => {
  switch (status) {
    case 'healthy':
      return 'bg-green-500';
    case 'degraded':
      return 'bg-yellow-500';
    case 'unhealthy':
      return 'bg-red-500';
    default:
      return 'bg-slate-400';
  }
};

const getCircuitBreakerColor = (state?: CircuitBreakerState) => {
  switch (state) {
    case 'closed':
      return 'text-green-600 bg-green-100 dark:bg-green-900/30 dark:text-green-400';
    case 'open':
      return 'text-red-600 bg-red-100 dark:bg-red-900/30 dark:text-red-400';
    case 'half_open':
      return 'text-yellow-600 bg-yellow-100 dark:bg-yellow-900/30 dark:text-yellow-400';
    default:
      return 'text-slate-600 bg-slate-100 dark:bg-slate-700 dark:text-slate-400';
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
  const circuitBreakerState = provider.resilience?.circuit_breaker_state;

  return (
    <div className="group relative bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden">
      {/* Status Indicator Bar */}
      <div
        className={`absolute top-0 left-0 right-0 h-1 ${getStatusColor(provider.health_status)}`}
      />

      {/* Card Content */}
      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="text-3xl">{PROVIDER_ICONS[provider.provider_type] || '🤖'}</div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-slate-900 dark:text-white">{provider.name}</h3>
                {provider.is_default && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
                    Default
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {PROVIDER_TYPE_LABELS[provider.provider_type]}
              </p>
            </div>
          </div>

          {/* Active Toggle */}
          <div
            className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${
              provider.is_active
                ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${provider.is_active ? 'bg-green-500' : 'bg-slate-400'}`}
            />
            {provider.is_active ? 'Active' : 'Inactive'}
          </div>
        </div>

        {/* Models Info */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-500 dark:text-slate-400 w-20">LLM:</span>
            <code className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-slate-700 dark:text-slate-300 font-mono text-xs">
              {provider.llm_model}
            </code>
          </div>
          {provider.embedding_model && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500 dark:text-slate-400 w-20">Embed:</span>
              <code className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-slate-700 dark:text-slate-300 font-mono text-xs">
                {provider.embedding_model}
              </code>
              {provider.embedding_config?.dimensions && (
                <span className="text-xs text-slate-500">
                  {provider.embedding_config.dimensions}d
                </span>
              )}
            </div>
          )}
        </div>

        {/* Health & Circuit Breaker */}
        <div className="flex items-center gap-3 mb-4">
          {/* Health Status */}
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${getStatusColor(provider.health_status)}`} />
            <span className="text-sm text-slate-600 dark:text-slate-300 capitalize">
              {provider.health_status || 'Unknown'}
            </span>
            {provider.response_time_ms && (
              <span className="text-xs text-slate-400">{provider.response_time_ms}ms</span>
            )}
          </div>

          {/* Divider */}
          <div className="h-4 w-px bg-slate-200 dark:bg-slate-600" />

          {/* Circuit Breaker */}
          <div className="flex items-center gap-2">
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${getCircuitBreakerColor(circuitBreakerState)}`}
            >
              CB: {circuitBreakerState || 'Unknown'}
            </span>
            {provider.resilience?.failure_count ? (
              <span className="text-xs text-red-500">
                {provider.resilience.failure_count} failures
              </span>
            ) : null}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-3 border-t border-slate-100 dark:border-slate-700">
          <button
            onClick={() => onCheckHealth(provider.id)}
            disabled={isCheckingHealth}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
            title="Check Health"
          >
            <span
              className={`material-symbols-outlined text-[16px] ${isCheckingHealth ? 'animate-spin' : ''}`}
            >
              {isCheckingHealth ? 'progress_activity' : 'monitor_heart'}
            </span>
            Health
          </button>

          {circuitBreakerState && circuitBreakerState !== 'closed' && (
            <button
              onClick={() => onResetCircuitBreaker(provider.provider_type)}
              disabled={isResettingCircuitBreaker}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-yellow-600 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 rounded-lg transition-colors disabled:opacity-50"
              title="Reset Circuit Breaker"
            >
              <span
                className={`material-symbols-outlined text-[16px] ${isResettingCircuitBreaker ? 'animate-spin' : ''}`}
              >
                {isResettingCircuitBreaker ? 'progress_activity' : 'refresh'}
              </span>
              Reset CB
            </button>
          )}

          <div className="flex-1" />

          <button
            onClick={() => onAssign(provider)}
            className="p-1.5 text-slate-400 hover:text-blue-500 transition-colors"
            title="Assign to Tenant"
          >
            <span className="material-symbols-outlined text-[18px]">assignment_ind</span>
          </button>

          <button
            onClick={() => onEdit(provider)}
            className="p-1.5 text-slate-400 hover:text-primary transition-colors"
            title="Edit"
          >
            <span className="material-symbols-outlined text-[18px]">edit</span>
          </button>

          <button
            onClick={() => onDelete(provider.id)}
            className="p-1.5 text-slate-400 hover:text-red-500 transition-colors"
            title="Delete"
          >
            <span className="material-symbols-outlined text-[18px]">delete</span>
          </button>
        </div>
      </div>
    </div>
  );
};
