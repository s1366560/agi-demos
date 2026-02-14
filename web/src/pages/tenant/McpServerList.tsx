/**
 * McpServerList Page
 *
 * MCP management page with three tabs: Servers, Tools, and Apps.
 * Each tab is self-contained with its own state and actions.
 */

import React, { useEffect, useMemo, useState } from 'react';

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
  iconColor = 'text-primary-500',
  valueColor = 'text-slate-900 dark:text-white',
}) => (
  <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-slate-600 dark:text-slate-400">{title}</p>
        <p className={`text-2xl font-bold ${valueColor} mt-1`}>{value}</p>
      </div>
      <span className={`material-symbols-outlined text-4xl ${iconColor}`}>{icon}</span>
    </div>
  </div>
);

// ============================================================================
// Main Component
// ============================================================================

export const McpServerList: React.FC<McpServerListProps> = ({ className = '' }) => {
  const [activeTab, setActiveTab] = useState<McpTabKey>('servers');

  const servers = useMCPStore((s) => s.servers);
  const apps = useMCPAppStore((s) => s.apps);
  const clearError = useMCPStore((s) => s.clearError);

  useEffect(() => {
    return () => clearError();
  }, [clearError]);

  // Computed stats
  const enabledCount = useMemo(() => servers.filter((s) => s.enabled).length, [servers]);
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

  const tabs: McpTab[] = [
    { key: 'servers', label: 'Servers', icon: 'dns', count: servers.length },
    { key: 'tools', label: 'Tools', icon: 'build', count: totalToolsCount },
    { key: 'apps', label: 'Apps', icon: 'widgets', count: Object.keys(apps).length },
  ];

  return (
    <div className={`max-w-full mx-auto w-full flex flex-col gap-8 ${className}`}>
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">MCP Servers</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage your Model Context Protocol servers, tools, and apps
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard title="Total Servers" value={servers.length} icon="dns" />
        <StatsCard
          title="Enabled"
          value={enabledCount}
          icon="check_circle"
          iconColor="text-green-500"
          valueColor="text-green-600 dark:text-green-400"
        />
        <StatsCard
          title="Total Tools"
          value={totalToolsCount}
          icon="build"
          iconColor="text-blue-500"
          valueColor="text-blue-600 dark:text-blue-400"
        />
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">By Type</p>
              <div className="flex gap-2 mt-1">
                {Object.entries(serversByType).map(
                  ([type, count]) =>
                    count > 0 && (
                      <span key={type} className="text-xs text-slate-600 dark:text-slate-400">
                        {type}: {count}
                      </span>
                    )
                )}
              </div>
            </div>
            <span className="material-symbols-outlined text-4xl text-purple-500">category</span>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="border-b border-slate-200 dark:border-slate-800">
        <div className="flex gap-8 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`relative flex items-center gap-2 pb-4 text-sm font-semibold tracking-wide transition-colors ${
                activeTab === tab.key
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              <span className="material-symbols-outlined text-base">{tab.icon}</span>
              {tab.label}
              <span
                className={`text-xs px-1.5 py-0.5 rounded-full ${
                  activeTab === tab.key
                    ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                }`}
              >
                {tab.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'servers' && <McpServerTab />}
      {activeTab === 'tools' && <McpToolsTab />}
      {activeTab === 'apps' && <McpAppsTab />}
    </div>
  );
};

McpServerList.displayName = 'McpServerList';

export default McpServerList;
