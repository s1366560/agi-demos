import React from 'react';

import { ProviderConfig } from '../../types/memory';

interface ProviderUsageStatsProps {
  provider: ProviderConfig;
  onClose: () => void;
}

export const ProviderUsageStats: React.FC<ProviderUsageStatsProps> = ({ provider, onClose }) => {
  // Mock data - replace with actual API call
  const stats = {
    totalRequests: 12453,
    totalTokens: 2847392,
    totalCost: 23.45,
    avgResponseTime: 245,
    successRate: 99.2,
    requestsByDay: [1200, 1800, 1500, 2200, 1900, 2400, 2100],
    tokensByModel: {
      [provider.llm_model]: 1847392,
      [provider.llm_small_model || 'N/A']: 1000000,
    },
  };

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
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          {/* Content */}
          <div className="p-6 space-y-6">
            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div className="bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-900/10 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-blue-500">analytics</span>
                  <span className="text-sm text-blue-700 dark:text-blue-400">Total Requests</span>
                </div>
                <p className="text-2xl font-bold text-blue-900 dark:text-blue-100">
                  {stats.totalRequests.toLocaleString()}
                </p>
              </div>

              <div className="bg-gradient-to-br from-purple-50 to-purple-100 dark:from-purple-900/20 dark:to-purple-900/10 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-purple-500">data_usage</span>
                  <span className="text-sm text-purple-700 dark:text-purple-400">Total Tokens</span>
                </div>
                <p className="text-2xl font-bold text-purple-900 dark:text-purple-100">
                  {(stats.totalTokens / 1000000).toFixed(2)}M
                </p>
              </div>

              <div className="bg-gradient-to-br from-green-50 to-green-100 dark:from-green-900/20 dark:to-green-900/10 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-green-500">attach_money</span>
                  <span className="text-sm text-green-700 dark:text-green-400">Total Cost</span>
                </div>
                <p className="text-2xl font-bold text-green-900 dark:text-green-100">
                  ${stats.totalCost.toFixed(2)}
                </p>
              </div>

              <div className="bg-gradient-to-br from-orange-50 to-orange-100 dark:from-orange-900/20 dark:to-orange-900/10 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-orange-500">speed</span>
                  <span className="text-sm text-orange-700 dark:text-orange-400">Avg Response</span>
                </div>
                <p className="text-2xl font-bold text-orange-900 dark:text-orange-100">
                  {stats.avgResponseTime}ms
                </p>
              </div>

              <div className="bg-gradient-to-br from-teal-50 to-teal-100 dark:from-teal-900/20 dark:to-teal-900/10 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-teal-500">check_circle</span>
                  <span className="text-sm text-teal-700 dark:text-teal-400">Success Rate</span>
                </div>
                <p className="text-2xl font-bold text-teal-900 dark:text-teal-100">
                  {stats.successRate}%
                </p>
              </div>
            </div>

            {/* Chart Placeholder */}
            <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-6">
              <h3 className="font-semibold text-slate-900 dark:text-white mb-4">
                Requests (Last 7 Days)
              </h3>
              <div className="h-48 flex items-end justify-between gap-2">
                {stats.requestsByDay.map((value, index) => {
                  const maxValue = Math.max(...stats.requestsByDay);
                  const height = (value / maxValue) * 100;
                  return (
                    <div key={index} className="flex-1 flex flex-col items-center gap-2">
                      <div
                        className="w-full bg-gradient-to-t from-primary/80 to-primary rounded-t-lg transition-all hover:from-primary hover:to-primary-dark"
                        style={{ height: `${height}%` }}
                      />
                      <span className="text-xs text-slate-500">
                        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][index]}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Token Distribution */}
            <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-6">
              <h3 className="font-semibold text-slate-900 dark:text-white mb-4">
                Token Distribution by Model
              </h3>
              <div className="space-y-3">
                {Object.entries(stats.tokensByModel).map(([model, tokens]) => {
                  const percentage = (tokens / stats.totalTokens) * 100;
                  return (
                    <div key={model}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-600 dark:text-slate-400 font-mono">
                          {model}
                        </span>
                        <span className="text-slate-900 dark:text-white font-medium">
                          {percentage.toFixed(1)}%
                        </span>
                      </div>
                      <div className="h-2 bg-slate-200 dark:bg-slate-600 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-primary to-primary-dark rounded-full"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
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
