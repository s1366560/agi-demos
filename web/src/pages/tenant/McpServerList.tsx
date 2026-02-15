/**
 * McpServerList Page
 *
 * MCP management page with three tabs: Servers, Tools, and Apps.
 * Each tab is self-contained with its own state and actions.
 */

import React, { useEffect, useMemo, useState } from 'react';

import { useShallow } from 'zustand/react/shallow';

import { McpAppsTab } from '../../components/mcp/McpAppsTab';
import { McpServerTab } from '../../components/mcp/McpServerTab';
import { McpToolsTab } from '../../components/mcp/McpToolsTab';
import { useMCPStore } from '../../stores/mcp';
import { useMCPAppStore } from '../../stores/mcpAppStore';

import type { McpTabKey, McpTab, McpServerListProps, StatsCardProps } from './McpServerList/types';
import type { MCPServerType } from '../../types/agent';

// ============================================================================
// Stats Card
// ============================================================================

const StatsCard: React.FC<StatsCardProps> = ({
  title,
  value,
  icon,
  iconBgColor = 'bg-primary-50 dark:bg-primary-900/20',
  iconColor = 'text-primary-500',
  valueColor = 'text-slate-900 dark:text-white',
  subtitle,
}) => (
  <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700/60">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className={`w-8 h-8 rounded-md ${iconBgColor} flex items-center justify-center flex-shrink-0`}>
          <span className={`material-symbols-outlined text-lg ${iconColor}`}>{icon}</span>
        </div>
        <div>
          <p className={`text-lg font-semibold leading-none ${valueColor}`}>{value}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{title}</p>
        </div>
      </div>
    </div>
    {subtitle && (
      <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-700/50">
        <p className="text-xs text-slate-400 dark:text-slate-500">{subtitle}</p>
      </div>
    )}
  </div>
);

// ============================================================================
// Type Badge
// ============================================================================

const TypeBadge: React.FC<{ type: string; count: number }> = ({ type, count }) => {
  const typeStyles: Record<string, string> = {
    stdio: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 border-blue-100 dark:border-blue-800',
    sse: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400 border-green-100 dark:border-green-800',
    http: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400 border-purple-100 dark:border-purple-800',
    websocket: 'bg-orange-50 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400 border-orange-100 dark:border-orange-800',
  };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${typeStyles[type] || typeStyles.stdio}`}>
      {type.toUpperCase()}
      <span className="ml-1 opacity-60">{count}</span>
    </span>
  );
};

// ============================================================================
// Main Component
// ============================================================================

export const McpServerList: React.FC<McpServerListProps> = ({ className = '' }) => {
  const [activeTab, setActiveTab] = useState<McpTabKey>('servers');

  const { servers, clearError } = useMCPStore(
    useShallow((s) => ({ servers: s.servers, clearError: s.clearError }))
  );
  const apps = useMCPAppStore((s) => s.apps);

  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Computed stats
  const enabledCount = useMemo(() => servers.filter((s) => s.enabled).length, [servers]);
  const disabledCount = useMemo(() => servers.filter((s) => !s.enabled).length, [servers]);
  const totalToolsCount = useMemo(
    () => servers.reduce((sum, s) => sum + (s.discovered_tools?.length || 0), 0),
    [servers]
  );
  const serversByType = useMemo(() => {
    const result: Record<MCPServerType, number> = { stdio: 0, sse: 0, http: 0, websocket: 0 };
    servers.forEach((s) => {
      result[s.server_type]++;
    });
    return result;
  }, [servers]);

  const activeTypeFilters = useMemo(() => {
    return Object.entries(serversByType)
      .filter(([, count]) => count > 0)
      .sort(([, a], [, b]) => b - a);
  }, [serversByType]);

  const tabs: McpTab[] = [
    { key: 'servers', label: 'Servers', icon: 'dns', count: servers.length },
    { key: 'tools', label: 'Tools', icon: 'build', count: totalToolsCount },
    { key: 'apps', label: 'Apps', icon: 'widgets', count: Object.keys(apps).length },
  ];

  return (
    <div className={`max-w-full mx-auto w-full flex flex-col gap-5 p-2 ${className}`}>
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white">MCP Servers</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Manage Model Context Protocol servers, tools, and applications
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatsCard 
          title="Total" 
          value={servers.length} 
          icon="dns"
          iconBgColor="bg-slate-100 dark:bg-slate-700/50"
          iconColor="text-slate-600 dark:text-slate-400"
          subtitle={`${disabledCount} disabled`}
        />
        <StatsCard
          title="Active"
          value={enabledCount}
          icon="check_circle"
          iconBgColor="bg-green-50 dark:bg-green-900/20"
          iconColor="text-green-500"
          valueColor="text-green-600 dark:text-green-400"
          subtitle={`${servers.length > 0 ? Math.round((enabledCount / servers.length) * 100) : 0}% enabled`}
        />
        <StatsCard
          title="Tool Count"
          value={totalToolsCount}
          icon="build"
          iconBgColor="bg-blue-50 dark:bg-blue-900/20"
          iconColor="text-blue-500"
          valueColor="text-blue-600 dark:text-blue-400"
          subtitle={`${servers.length > 0 ? (totalToolsCount / servers.length).toFixed(1) : 0} avg`}
        />
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700/60">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center flex-shrink-0">
              <span className="material-symbols-outlined text-lg text-violet-500">category</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-slate-500 dark:text-slate-400">By Type</p>
              <div className="flex flex-wrap gap-1 mt-1">
                {activeTypeFilters.length > 0 ? (
                  activeTypeFilters.map(([type, count]) => (
                    <TypeBadge key={type} type={type} count={count} />
                  ))
                ) : (
                  <span className="text-xs text-slate-400 dark:text-slate-500">No servers</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="border-b border-slate-200 dark:border-slate-700">
        <div className="flex gap-6">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`relative flex items-center gap-2 py-3 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'text-primary-600 dark:text-primary-400 border-primary-500'
                    : 'text-slate-500 dark:text-slate-400 border-transparent hover:text-slate-700 dark:hover:text-slate-300'
                }`}
              >
                <span className={`material-symbols-outlined text-base ${isActive ? 'filled' : ''}`}>
                  {tab.icon}
                </span>
                {tab.label}
                <span
                  className={`text-xs min-w-[1.25rem] h-5 px-1.5 rounded flex items-center justify-center ${
                    isActive
                      ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                      : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content */}
      <div>
        {activeTab === 'servers' && <McpServerTab />}
        {activeTab === 'tools' && <McpToolsTab />}
        {activeTab === 'apps' && <McpAppsTab />}
      </div>
    </div>
  );
}

McpServerList.displayName = 'McpServerList';

export default McpServerList;
