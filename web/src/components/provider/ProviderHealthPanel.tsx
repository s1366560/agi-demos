import React from 'react';

import { Activity, Bot, CheckCircle, Gauge, SlidersHorizontal ,
  Square,
  StopCircle,
  Terminal,
  Cloud,
  Zap,
  Ban,
  Search,
  Sparkles,
  AlertTriangle,
  FlaskConical,
  RefreshCcw,
  Settings,
  Brain,
  Info,
  Loader2,
  AlertCircle,
  Globe,
  User
} from 'lucide-react';

import { ProviderConfig, SystemResilienceStatus } from '../../types/memory';

const renderDynamicIcon = (name: string, size: number, className: string = '') => {
  switch (name) {
    case 'check_circle': return <CheckCircle size={size} className={className} />;
    case 'progress_activity': return <Loader2 size={size} className={`animate-spin ${className}`} />;
    case 'stop': return <Square size={size} className={className} />;
    case 'stop_circle': return <StopCircle size={size} className={className} />;
    case 'error': return <AlertCircle size={size} className={className} />;
    case 'warning': return <AlertTriangle size={size} className={className} />;
    case 'terminal': return <Terminal size={size} className={className} />;
    case 'http': return <Globe size={size} className={className} />;
    case 'cloud': return <Cloud size={size} className={className} />;
    case 'globe': return <Globe size={size} className={className} />;
    case 'zap': return <Zap size={size} className={className} />;
    case 'block': return <Ban size={size} className={className} />;
    case 'search': return <Search size={size} className={className} />;
    case 'person': return <User size={size} className={className} />;
    case 'auto_awesome': return <Sparkles size={size} className={className} />;
    case 'monitor_heart': return <Activity size={size} className={className} />;
    case 'refresh': return <RefreshCcw size={size} className={className} />;
    case 'sync': return <RefreshCcw size={size} className={className} />;
    case 'science': return <FlaskConical size={size} className={className} />;
    case 'settings': return <Settings size={size} className={className} />;
    case 'psychology': return <Brain size={size} className={className} />;
    case 'info': return <Info size={size} className={className} />;
    default: return <AlertCircle size={size} className={className} />;
  }
};

interface ProviderHealthPanelProps {
  providers: ProviderConfig[];
  systemStatus: SystemResilienceStatus | null;
  isLoading?: boolean | undefined;
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

  const getHealthColor = () => {
    if (healthPercentage >= 80) return 'text-emerald-600 dark:text-emerald-400';
    if (healthPercentage >= 50) return 'text-amber-600 dark:text-amber-400';
    return 'text-red-600 dark:text-red-400';
  };

  const getHealthIcon = () => {
    if (healthPercentage >= 80) return 'check_circle';
    if (healthPercentage >= 50) return 'warning';
    return 'error';
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="animate-pulse motion-reduce:animate-none space-y-4">
          <div className="h-6 bg-slate-100 dark:bg-slate-800 rounded w-1/4"></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-20 bg-slate-100 dark:bg-slate-800 rounded-lg"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Activity size={20} className="text-primary" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">System Health</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Real-time provider status overview
            </p>
          </div>
        </div>

        {/* Overall Health Indicator */}
        <div
          className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border ${
            healthPercentage >= 80
              ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
              : healthPercentage >= 50
                ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'
                : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
          }`}
        >
          {renderDynamicIcon(getHealthIcon(), 18, getHealthColor())}
          <span className={`text-sm font-semibold ${getHealthColor()}`}>
            {healthPercentage}% Healthy
          </span>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="p-5 grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Total Providers */}
        <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">
              Total Providers
            </span>
            <Bot size={18} className="text-slate-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 dark:text-white">
              {totalProviders}
            </span>
            <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
              {activeProviders} active
            </span>
          </div>
        </div>

        {/* Healthy */}
        <div className="p-4 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/20">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-emerald-700 dark:text-emerald-400 font-medium">
              Healthy
            </span>
            <CheckCircle size={18} className="text-emerald-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-emerald-700 dark:text-emerald-400">
              {healthyProviders}
            </span>
            <span className="text-xs text-emerald-600 dark:text-emerald-500">providers</span>
          </div>
        </div>

        {/* Issues */}
        <div
          className={`p-4 rounded-lg border ${
            unhealthyProviders > 0
              ? 'border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-900/20'
              : degradedProviders > 0
                ? 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/20'
                : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className={`text-xs font-medium ${
                unhealthyProviders > 0
                  ? 'text-red-700 dark:text-red-400'
                  : degradedProviders > 0
                    ? 'text-amber-700 dark:text-amber-400'
                    : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Issues
            </span>
            {renderDynamicIcon(unhealthyProviders > 0 ? 'error' : degradedProviders > 0 ? 'warning' : 'verified', 18, unhealthyProviders > 0 ? 'text-red-500' : degradedProviders > 0 ? 'text-amber-500' : 'text-emerald-500')}
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-2xl font-bold ${
                unhealthyProviders > 0
                  ? 'text-red-700 dark:text-red-400'
                  : degradedProviders > 0
                    ? 'text-amber-700 dark:text-amber-400'
                    : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {unhealthyProviders + degradedProviders}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
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
          className={`p-4 rounded-lg border ${
            openCircuitBreakers > 0
              ? 'border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/20'
              : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className={`text-xs font-medium ${
                openCircuitBreakers > 0
                  ? 'text-amber-700 dark:text-amber-400'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              Circuit Breakers
            </span>
            {renderDynamicIcon('zap', 18, openCircuitBreakers > 0 ? 'text-amber-500' : 'text-slate-400')}
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-2xl font-bold ${
                openCircuitBreakers > 0
                  ? 'text-amber-700 dark:text-amber-400'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {openCircuitBreakers}
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {openCircuitBreakers > 0 ? 'open' : 'all closed'}
            </span>
          </div>
        </div>
      </div>

      {/* Response Time & Additional Stats */}
      <div className="px-5 pb-5">
        <div className="flex items-center justify-between p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-gradient-to-r from-slate-50 to-slate-100/50 dark:from-slate-800/50 dark:to-slate-800/30">
          <div className="flex items-center gap-4">
            <div className="p-2 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800">
              <Gauge size={20} className="text-primary" />
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400 font-medium">
                Avg Response Time
              </p>
              <p className="text-lg font-bold text-slate-900 dark:text-white">
                {avgResponseTime > 0 ? `${avgResponseTime}ms` : 'N/A'}
              </p>
            </div>
          </div>

          {systemStatus?.providers && (
            <div className="flex items-center gap-4">
              <div className="text-right">
                <p className="text-xs text-slate-500 dark:text-slate-400 font-medium">
                  Active Providers
                </p>
                <p className="text-lg font-bold text-slate-900 dark:text-white">
                  {Object.keys(systemStatus.providers).length}
                </p>
              </div>
              <div className="p-2 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800">
                <SlidersHorizontal size={20} className="text-primary" />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
