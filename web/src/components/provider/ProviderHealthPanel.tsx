import React from 'react';

import { ProviderConfig, SystemResilienceStatus } from '../../types/memory';

interface ProviderHealthPanelProps {
  providers: ProviderConfig[];
  systemStatus: SystemResilienceStatus | null;
  isLoading?: boolean;
}

export const ProviderHealthPanel: React.FC<ProviderHealthPanelProps> = ({
  providers,
  systemStatus,
  isLoading = false,
}) => {
  const totalProviders = providers.length;
  const activeProviders = providers.filter((p) => p.is_active).length;
  const healthyProviders = providers.filter((p) => p.health_status === 'healthy').length;
  const degradedProviders = providers.filter((p) => p.health_status === 'degraded').length;
  const unhealthyProviders = providers.filter((p) => p.health_status === 'unhealthy').length;

  const openCircuitBreakers = systemStatus?.providers
    ? Object.values(systemStatus.providers).filter((p) => p.circuit_breaker?.state === 'open')
        .length
    : 0;

  const healthPercentage =
    totalProviders > 0 ? Math.round((healthyProviders / totalProviders) * 100) : 0;

  const avgResponseTime =
    providers.length > 0
      ? Math.round(
          providers
            .filter((p) => p.response_time_ms)
            .reduce((sum, p) => sum + (p.response_time_ms || 0), 0) /
            (providers.filter((p) => p.response_time_ms).length || 1)
        )
      : 0;

  const getHealthGradient = () => {
    if (healthPercentage >= 80) return 'from-green-500 to-emerald-500';
    if (healthPercentage >= 50) return 'from-yellow-500 to-orange-500';
    return 'from-red-500 to-rose-500';
  };

  const getHealthIcon = () => {
    if (healthPercentage >= 80) return 'check_circle';
    if (healthPercentage >= 50) return 'warning';
    return 'error';
  };

  if (isLoading) {
    return (
      <div className="bg-gradient-to-br from-slate-50 to-white dark:from-slate-800 dark:to-slate-900 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-slate-200 dark:bg-slate-700 rounded w-1/3"></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-24 bg-slate-200 dark:bg-slate-700 rounded-xl"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-br from-slate-50 to-white dark:from-slate-800 dark:to-slate-900 rounded-2xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-6 py-5 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-white/50 dark:bg-slate-800/50 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-gradient-to-br from-primary/20 to-primary/10 rounded-xl">
            <span className="material-symbols-outlined text-primary">monitoring</span>
          </div>
          <div>
            <h2 className="font-semibold text-slate-900 dark:text-white">System Health Dashboard</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Real-time monitoring of all LLM providers
            </p>
          </div>
        </div>

        {/* Overall Health Indicator */}
        <div
          className={`flex items-center gap-2.5 px-4 py-2 rounded-full bg-gradient-to-r ${getHealthGradient()} text-white shadow-lg`}
        >
          <span className="material-symbols-outlined text-xl">{getHealthIcon()}</span>
          <span className="font-semibold">{healthPercentage}% Operational</span>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="p-6 grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Providers */}
        <div className="group bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700 hover:border-primary/30 hover:shadow-md transition-all">
          <div className="flex items-center justify-between mb-3">
            <span className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              Total Providers
            </span>
            <div className="p-2 bg-gradient-to-br from-blue-100 to-blue-50 dark:from-blue-900/30 dark:to-blue-900/10 rounded-lg">
              <span className="material-symbols-outlined text-blue-500 text-lg">smart_toy</span>
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-slate-900 dark:text-white">
              {totalProviders}
            </span>
            <span className="text-sm text-green-600 dark:text-green-400 font-medium">
              {activeProviders} active
            </span>
          </div>
        </div>

        {/* Healthy */}
        <div className="group bg-white dark:bg-slate-800 rounded-xl p-4 border border-green-200 dark:border-green-800 hover:border-green-400 hover:shadow-md transition-all">
          <div className="flex items-center justify-between mb-3">
            <span className="text-green-700 dark:text-green-400 text-sm font-medium">Healthy</span>
            <div className="p-2 bg-gradient-to-br from-green-100 to-green-50 dark:from-green-900/30 dark:to-green-900/10 rounded-lg">
              <span className="material-symbols-outlined text-green-500 text-lg">check_circle</span>
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-green-600 dark:text-green-400">
              {healthyProviders}
            </span>
            <span className="text-sm text-green-600 dark:text-green-500">providers</span>
          </div>
        </div>

        {/* Issues */}
        <div
          className={`group bg-white dark:bg-slate-800 rounded-xl p-4 border transition-all ${
            unhealthyProviders > 0
              ? 'border-red-200 dark:border-red-800 hover:border-red-400'
              : degradedProviders > 0
                ? 'border-yellow-200 dark:border-yellow-800 hover:border-yellow-400'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-400'
          }`}
        >
          <div className="flex items-center justify-between mb-3">
            <span
              className={`text-sm font-medium ${
                unhealthyProviders > 0
                  ? 'text-red-700 dark:text-red-400'
                  : degradedProviders > 0
                    ? 'text-yellow-700 dark:text-yellow-400'
                    : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Issues Detected
            </span>
            <div
              className={`p-2 rounded-lg ${
                unhealthyProviders > 0
                  ? 'bg-gradient-to-br from-red-100 to-red-50 dark:from-red-900/30 dark:to-red-900/10'
                  : degradedProviders > 0
                    ? 'bg-gradient-to-br from-yellow-100 to-yellow-50 dark:from-yellow-900/30 dark:to-yellow-900/10'
                    : 'bg-gradient-to-br from-slate-100 to-slate-50 dark:from-slate-700/30 dark:to-slate-700/10'
              }`}
            >
              <span
                className={`material-symbols-outlined text-lg ${
                  unhealthyProviders > 0
                    ? 'text-red-500'
                    : degradedProviders > 0
                      ? 'text-yellow-500'
                      : 'text-slate-400'
                }`}
              >
                {unhealthyProviders > 0 ? 'error' : degradedProviders > 0 ? 'warning' : 'verified'}
              </span>
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-3xl font-bold ${
                unhealthyProviders > 0
                  ? 'text-red-600 dark:text-red-400'
                  : degradedProviders > 0
                    ? 'text-yellow-600 dark:text-yellow-400'
                    : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {unhealthyProviders + degradedProviders}
            </span>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {unhealthyProviders > 0
                ? `${unhealthyProviders} down`
                : degradedProviders > 0
                  ? 'degraded'
                  : 'all clear'}
            </span>
          </div>
        </div>

        {/* Circuit Breakers */}
        <div
          className={`group bg-white dark:bg-slate-800 rounded-xl p-4 border transition-all ${
            openCircuitBreakers > 0
              ? 'border-orange-200 dark:border-orange-800 hover:border-orange-400'
              : 'border-slate-200 dark:border-slate-700 hover:border-slate-400'
          }`}
        >
          <div className="flex items-center justify-between mb-3">
            <span
              className={`text-sm font-medium ${
                openCircuitBreakers > 0
                  ? 'text-orange-700 dark:text-orange-400'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Circuit Breakers
            </span>
            <div
              className={`p-2 rounded-lg ${
                openCircuitBreakers > 0
                  ? 'bg-gradient-to-br from-orange-100 to-orange-50 dark:from-orange-900/30 dark:to-orange-900/10'
                  : 'bg-gradient-to-br from-slate-100 to-slate-50 dark:from-slate-700/30 dark:to-slate-700/10'
              }`}
            >
              <span
                className={`material-symbols-outlined text-lg ${
                  openCircuitBreakers > 0 ? 'text-orange-500' : 'text-slate-400'
                }`}
              >
                electric_bolt
              </span>
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-3xl font-bold ${
                openCircuitBreakers > 0
                  ? 'text-orange-600 dark:text-orange-400'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {openCircuitBreakers}
            </span>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {openCircuitBreakers > 0 ? 'tripped' : 'normal'}
            </span>
          </div>
        </div>
      </div>

      {/* Response Time & Additional Stats */}
      <div className="px-6 pb-6">
        <div className="bg-gradient-to-r from-primary/5 via-primary/5 to-transparent dark:from-primary/10 dark:via-primary/5 dark:to-transparent rounded-xl p-5 border border-primary/10 dark:border-primary/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
                <span className="material-symbols-outlined text-primary">speed</span>
              </div>
              <div>
                <p className="text-sm text-slate-500 dark:text-slate-400 font-medium">
                  Average Response Time
                </p>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {avgResponseTime > 0 ? `${avgResponseTime}ms` : 'N/A'}
                </p>
              </div>
            </div>

            {systemStatus?.providers && (
              <>
                <div className="h-12 w-px bg-slate-200 dark:bg-slate-700" />
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <p className="text-sm text-slate-500 dark:text-slate-400 font-medium">
                      Active Providers
                    </p>
                    <p className="text-2xl font-bold text-slate-900 dark:text-white">
                      {Object.keys(systemStatus.providers).length}
                    </p>
                  </div>
                  <div className="p-3 bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700">
                    <span className="material-symbols-outlined text-primary">tune</span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
