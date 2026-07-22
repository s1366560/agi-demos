import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Activity, AlertCircle, BarChart3, DollarSign, Gauge, Loader2 } from 'lucide-react';

import { AppModal } from '@/components/common';

import { providerAPI } from '../../services/api';
import { ProviderConfig, ProviderUsageStats as ProviderUsageStatsType } from '../../types/memory';

interface ProviderUsageStatsProps {
  provider: ProviderConfig;
  onClose: () => void;
}

export const ProviderUsageStats: React.FC<ProviderUsageStatsProps> = ({ provider, onClose }) => {
  const { t, i18n } = useTranslation();
  const [stats, setStats] = useState<ProviderUsageStatsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const compactNumber = useMemo(
    () => new Intl.NumberFormat(i18n.language, { notation: 'compact' }),
    [i18n.language]
  );

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await providerAPI.getUsage(provider.id);
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch usage stats:', err);
      setError(t('components.provider.usage.loadError'));
    } finally {
      setLoading(false);
    }
  }, [provider.id, t]);

  useEffect(() => {
    if (provider.id) {
      void fetchStats();
    }
  }, [provider.id, fetchStats]);

  return (
    <AppModal
      open
      onClose={onClose}
      title={t('components.provider.usage.title')}
      description={provider.name}
      size="xl"
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text)] hover:bg-[var(--color-panel-2)]"
        >
          {t('common.close')}
        </button>
      }
    >
      <div className="space-y-6" aria-live="polite">
        {loading ? (
          <div className="flex justify-center items-center py-12">
            <Loader2
              size={16}
              className="animate-spin motion-reduce:animate-none text-primary text-4xl"
            />
          </div>
        ) : error ? (
          <div
            role="alert"
            className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg flex items-center gap-2"
          >
            <AlertCircle aria-hidden="true" size={16} />
            <span className="flex-1">{error}</span>
            <button
              type="button"
              onClick={() => {
                void fetchStats();
              }}
              className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:bg-red-900/40"
            >
              {t('common.retry', 'Retry')}
            </button>
          </div>
        ) : stats ? (
          <>
            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="rounded-lg border border-blue-100 bg-blue-50 dark:border-blue-900/30 dark:bg-blue-900/10 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <BarChart3 size={16} className="text-blue-500" />
                  <span className="text-sm text-blue-700 dark:text-blue-400">
                    {t('components.provider.usage.totalRequests')}
                  </span>
                </div>
                <p className="text-2xl font-bold text-blue-900 dark:text-blue-100">
                  {stats.total_requests.toLocaleString()}
                </p>
              </div>

              <div className="rounded-lg border border-purple-100 bg-purple-50 dark:border-purple-900/30 dark:bg-purple-900/10 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Activity size={16} className="text-purple-500" />
                  <span className="text-sm text-purple-700 dark:text-purple-400">
                    {t('components.provider.usage.totalTokens')}
                  </span>
                </div>
                <p className="text-2xl font-bold text-purple-900 dark:text-purple-100">
                  {compactNumber.format(stats.total_tokens)}
                </p>
                <div className="text-xs text-purple-600/80 dark:text-purple-400/80 mt-1">
                  {t('components.provider.usage.tokenBreakdown', {
                    inCount: stats.total_prompt_tokens.toLocaleString(),
                    outCount: stats.total_completion_tokens.toLocaleString(),
                  })}
                </div>
              </div>

              <div className="rounded-lg border border-green-100 bg-green-50 dark:border-green-900/30 dark:bg-green-900/10 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <DollarSign size={16} className="text-green-500" />
                  <span className="text-sm text-green-700 dark:text-green-400">
                    {t('components.provider.usage.totalCost')}
                  </span>
                </div>
                <p className="text-2xl font-bold text-green-900 dark:text-green-100">
                  ${(stats.total_cost_usd || 0).toFixed(4)}
                </p>
              </div>

              <div className="rounded-lg border border-orange-100 bg-orange-50 dark:border-orange-900/30 dark:bg-orange-900/10 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Gauge size={16} className="text-orange-500" />
                  <span className="text-sm text-orange-700 dark:text-orange-400">
                    {t('components.provider.usage.avgResponse')}
                  </span>
                </div>
                <p className="text-2xl font-bold text-orange-900 dark:text-orange-100">
                  {(stats.avg_response_time_ms || 0).toFixed(0)}ms
                </p>
              </div>
            </div>

            {/* Additional Info */}
            <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-700/50 p-6">
              <h3 className="font-semibold text-slate-900 dark:text-white mb-4">
                {t('components.provider.usage.details')}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                  <span className="text-slate-500">
                    {t('components.provider.usage.firstRequest')}
                  </span>
                  <span className="font-mono text-slate-900 dark:text-white">
                    {stats.first_request_at
                      ? new Date(stats.first_request_at).toLocaleString()
                      : t('components.provider.usage.notAvailable')}
                  </span>
                </div>
                <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                  <span className="text-slate-500">
                    {t('components.provider.usage.lastRequest')}
                  </span>
                  <span className="font-mono text-slate-900 dark:text-white">
                    {stats.last_request_at
                      ? new Date(stats.last_request_at).toLocaleString()
                      : t('components.provider.usage.notAvailable')}
                  </span>
                </div>
                <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                  <span className="text-slate-500">
                    {t('components.provider.usage.providerId')}
                  </span>
                  <span
                    className="font-mono text-slate-900 dark:text-white truncate max-w-50"
                    title={stats.provider_id}
                  >
                    {stats.provider_id}
                  </span>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-12 text-slate-500">
            {t('components.provider.usage.empty')}
          </div>
        )}
      </div>
    </AppModal>
  );
};
