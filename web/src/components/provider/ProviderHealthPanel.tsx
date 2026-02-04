import React from 'react'
import { ProviderConfig, SystemResilienceStatus } from '../../types/memory'

interface ProviderHealthPanelProps {
    providers: ProviderConfig[]
    systemStatus: SystemResilienceStatus | null
    isLoading?: boolean
}

export const ProviderHealthPanel: React.FC<ProviderHealthPanelProps> = ({
    providers,
    systemStatus,
    isLoading = false,
}) => {
    const totalProviders = providers.length
    const activeProviders = providers.filter(p => p.is_active).length
    const healthyProviders = providers.filter(p => p.health_status === 'healthy').length
    const degradedProviders = providers.filter(p => p.health_status === 'degraded').length
    const unhealthyProviders = providers.filter(p => p.health_status === 'unhealthy').length
    
    const openCircuitBreakers = systemStatus?.providers
        ? Object.values(systemStatus.providers).filter(p => p.circuit_breaker?.state === 'open').length
        : 0
    
    const healthPercentage = totalProviders > 0 
        ? Math.round((healthyProviders / totalProviders) * 100) 
        : 0

    // Calculate average response time from providers
    const avgResponseTime = providers.length > 0
        ? Math.round(
            providers
                .filter(p => p.response_time_ms)
                .reduce((sum, p) => sum + (p.response_time_ms || 0), 0) / 
            (providers.filter(p => p.response_time_ms).length || 1)
        )
        : 0

    if (isLoading) {
        return (
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
                <div className="animate-pulse space-y-4">
                    <div className="h-6 bg-slate-200 dark:bg-slate-700 rounded w-1/4"></div>
                    <div className="grid grid-cols-4 gap-4">
                        {[1, 2, 3, 4].map(i => (
                            <div key={i} className="h-20 bg-slate-200 dark:bg-slate-700 rounded"></div>
                        ))}
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            {/* Header */}
            <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-primary/10 rounded-lg">
                        <span className="material-symbols-outlined text-primary">monitoring</span>
                    </div>
                    <div>
                        <h2 className="font-semibold text-slate-900 dark:text-white">System Health</h2>
                        <p className="text-sm text-slate-500">Real-time provider status overview</p>
                    </div>
                </div>
                
                {/* Overall Health Indicator */}
                <div className="flex items-center gap-3">
                    <div className={`flex items-center gap-2 px-4 py-2 rounded-full ${
                        healthPercentage >= 80 
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                            : healthPercentage >= 50
                            ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                            : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                        <span className="material-symbols-outlined text-lg">
                            {healthPercentage >= 80 ? 'check_circle' : healthPercentage >= 50 ? 'warning' : 'error'}
                        </span>
                        <span className="font-semibold">{healthPercentage}% Healthy</span>
                    </div>
                </div>
            </div>

            {/* Stats Grid */}
            <div className="p-6 grid grid-cols-2 md:grid-cols-4 gap-4">
                {/* Total Providers */}
                <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-slate-500 dark:text-slate-400 text-sm">Total Providers</span>
                        <span className="material-symbols-outlined text-slate-400 text-lg">smart_toy</span>
                    </div>
                    <div className="flex items-baseline gap-2">
                        <span className="text-3xl font-bold text-slate-900 dark:text-white">{totalProviders}</span>
                        <span className="text-sm text-slate-500">{activeProviders} active</span>
                    </div>
                </div>

                {/* Healthy */}
                <div className="bg-green-50 dark:bg-green-900/20 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-green-700 dark:text-green-400 text-sm">Healthy</span>
                        <span className="material-symbols-outlined text-green-500 text-lg">check_circle</span>
                    </div>
                    <div className="flex items-baseline gap-2">
                        <span className="text-3xl font-bold text-green-700 dark:text-green-400">{healthyProviders}</span>
                        <span className="text-sm text-green-600 dark:text-green-500">providers</span>
                    </div>
                </div>

                {/* Degraded/Unhealthy */}
                <div className={`rounded-xl p-4 ${
                    unhealthyProviders > 0 
                        ? 'bg-red-50 dark:bg-red-900/20' 
                        : degradedProviders > 0 
                        ? 'bg-yellow-50 dark:bg-yellow-900/20'
                        : 'bg-slate-50 dark:bg-slate-700/50'
                }`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className={`text-sm ${
                            unhealthyProviders > 0 
                                ? 'text-red-700 dark:text-red-400'
                                : degradedProviders > 0
                                ? 'text-yellow-700 dark:text-yellow-400'
                                : 'text-slate-500 dark:text-slate-400'
                        }`}>Issues</span>
                        <span className={`material-symbols-outlined text-lg ${
                            unhealthyProviders > 0 
                                ? 'text-red-500'
                                : degradedProviders > 0
                                ? 'text-yellow-500'
                                : 'text-slate-400'
                        }`}>
                            {unhealthyProviders > 0 ? 'error' : degradedProviders > 0 ? 'warning' : 'verified'}
                        </span>
                    </div>
                    <div className="flex items-baseline gap-2">
                        <span className={`text-3xl font-bold ${
                            unhealthyProviders > 0 
                                ? 'text-red-700 dark:text-red-400'
                                : degradedProviders > 0
                                ? 'text-yellow-700 dark:text-yellow-400'
                                : 'text-slate-500 dark:text-slate-400'
                        }`}>
                            {unhealthyProviders + degradedProviders}
                        </span>
                        <span className="text-sm text-slate-500">
                            {unhealthyProviders > 0 ? `${unhealthyProviders} down` : degradedProviders > 0 ? 'degraded' : 'all clear'}
                        </span>
                    </div>
                </div>

                {/* Circuit Breakers */}
                <div className={`rounded-xl p-4 ${
                    openCircuitBreakers > 0 
                        ? 'bg-orange-50 dark:bg-orange-900/20'
                        : 'bg-slate-50 dark:bg-slate-700/50'
                }`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className={`text-sm ${
                            openCircuitBreakers > 0 
                                ? 'text-orange-700 dark:text-orange-400'
                                : 'text-slate-500 dark:text-slate-400'
                        }`}>Circuit Breakers</span>
                        <span className={`material-symbols-outlined text-lg ${
                            openCircuitBreakers > 0 ? 'text-orange-500' : 'text-slate-400'
                        }`}>electric_bolt</span>
                    </div>
                    <div className="flex items-baseline gap-2">
                        <span className={`text-3xl font-bold ${
                            openCircuitBreakers > 0 
                                ? 'text-orange-700 dark:text-orange-400'
                                : 'text-slate-500 dark:text-slate-400'
                        }`}>
                            {openCircuitBreakers}
                        </span>
                        <span className="text-sm text-slate-500">
                            {openCircuitBreakers > 0 ? 'open' : 'all closed'}
                        </span>
                    </div>
                </div>
            </div>

            {/* Response Time & Additional Stats */}
            <div className="px-6 pb-6">
                <div className="bg-gradient-to-r from-slate-50 to-slate-100 dark:from-slate-700/50 dark:to-slate-700/30 rounded-xl p-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="p-2 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                            <span className="material-symbols-outlined text-primary">speed</span>
                        </div>
                        <div>
                            <p className="text-sm text-slate-500 dark:text-slate-400">Avg Response Time</p>
                            <p className="text-xl font-bold text-slate-900 dark:text-white">
                                {avgResponseTime > 0 ? `${avgResponseTime}ms` : 'N/A'}
                            </p>
                        </div>
                    </div>
                    
                    {systemStatus?.providers && (
                        <div className="flex items-center gap-4">
                            <div className="text-right">
                                <p className="text-sm text-slate-500 dark:text-slate-400">Active Rate Limits</p>
                                <p className="text-xl font-bold text-slate-900 dark:text-white">
                                    {Object.keys(systemStatus.providers).length}
                                </p>
                            </div>
                            <div className="p-2 bg-white dark:bg-slate-800 rounded-lg shadow-sm">
                                <span className="material-symbols-outlined text-primary">tune</span>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
