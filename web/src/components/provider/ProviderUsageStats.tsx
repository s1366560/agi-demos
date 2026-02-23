import React, { useEffect, useState } from 'react';

import { providerAPI } from '../../services/api';
import { ProviderConfig, ProviderUsageStats as ProviderUsageStatsType } from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

interface ProviderUsageStatsProps {
  provider: ProviderConfig;
  onClose: () => void;
}

export const ProviderUsageStats: React.FC<ProviderUsageStatsProps> = ({ provider, onClose }) => {
  const [stats, setStats] = useState<ProviderUsageStatsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        setLoading(true);
        const data = await providerAPI.getUsage(provider.id);
        setStats(data);
      } catch (err) {
        console.error('Failed to fetch usage stats:', err);
        setError('Failed to load usage statistics');
      } finally {
        setLoading(false);
      }
    };

    if (provider.id) {
      fetchStats();
    }
  }, [provider.id]);

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-4xl bg-white dark:bg-slate-800 rounded-2xl shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
                Usage Statistics
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">{provider.name}</p>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <MaterialIcon name="close" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            {loading ? (
              <div className="flex justify-center items-center py-12">
                <MaterialIcon
                  name="progress_activity"
                  className="animate-spin text-primary text-4xl"
                />
              </div>
            ) : error ? (
              <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg flex items-center gap-2">
                <MaterialIcon name="error" />
                {error}
              </div>
            ) : stats ? (
              <>
                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-900/10 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MaterialIcon name="analytics" className="text-blue-500" />
                      <span className="text-sm text-blue-700 dark:text-blue-400">
                        Total Requests
                      </span>
                    </div>
                    <p className="text-2xl font-bold text-blue-900 dark:text-blue-100">
                      {stats.total_requests.toLocaleString()}
                    </p>
                  </div>

                  <div className="bg-gradient-to-br from-purple-50 to-purple-100 dark:from-purple-900/20 dark:to-purple-900/10 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MaterialIcon name="data_usage" className="text-purple-500" />
                      <span className="text-sm text-purple-700 dark:text-purple-400">
                        Total Tokens
                      </span>
                    </div>
                    <p className="text-2xl font-bold text-purple-900 dark:text-purple-100">
                      {(stats.total_tokens / 1000).toFixed(1)}k
                    </p>
                    <div className="text-xs text-purple-600/80 dark:text-purple-400/80 mt-1">
                      {stats.total_prompt_tokens.toLocaleString()} in /{' '}
                      {stats.total_completion_tokens.toLocaleString()} out
                    </div>
                  </div>

                  <div className="bg-gradient-to-br from-green-50 to-green-100 dark:from-green-900/20 dark:to-green-900/10 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MaterialIcon name="attach_money" className="text-green-500" />
                      <span className="text-sm text-green-700 dark:text-green-400">Total Cost</span>
                    </div>
                    <p className="text-2xl font-bold text-green-900 dark:text-green-100">
                      ${(stats.total_cost_usd || 0).toFixed(4)}
                    </p>
                  </div>

                  <div className="bg-gradient-to-br from-orange-50 to-orange-100 dark:from-orange-900/20 dark:to-orange-900/10 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <MaterialIcon name="speed" className="text-orange-500" />
                      <span className="text-sm text-orange-700 dark:text-orange-400">
                        Avg Response
                      </span>
                    </div>
                    <p className="text-2xl font-bold text-orange-900 dark:text-orange-100">
                      {(stats.avg_response_time_ms || 0).toFixed(0)}ms
                    </p>
                  </div>
                </div>

                {/* Additional Info */}
                <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-6">
                  <h3 className="font-semibold text-slate-900 dark:text-white mb-4">Details</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                      <span className="text-slate-500">First Request</span>
                      <span className="font-mono text-slate-900 dark:text-white">
                        {stats.first_request_at
                          ? new Date(stats.first_request_at).toLocaleString()
                          : 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                      <span className="text-slate-500">Last Request</span>
                      <span className="font-mono text-slate-900 dark:text-white">
                        {stats.last_request_at
                          ? new Date(stats.last_request_at).toLocaleString()
                          : 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-slate-200 dark:border-slate-600">
                      <span className="text-slate-500">Provider ID</span>
                      <span
                        className="font-mono text-slate-900 dark:text-white truncate max-w-[200px]"
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
                No usage data available for this provider.
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
