/**
 * McpServerListV2 - Modern MCP Server Management Page
 * Aligned with agent workspace design system
 */

import React, { useEffect, useMemo, useState } from 'react';

import { message } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';

import { mcpAPI } from '@/services/mcpService';

import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { McpAppsTabV2 } from './McpAppsTabV2';
import { McpLogsTabV2 } from './McpLogsTabV2';
import { McpPromptsTabV2 } from './McpPromptsTabV2';
import { McpServerTabV2 } from './McpServerTabV2';
import { McpToolsTabV2 } from './McpToolsTabV2';
import { getRuntimeStatus } from './types';

import type { McpTabKey, ServerStats, AppStats, ToolStats } from './types';

// ============================================================================
// Stats Card Component
// ============================================================================

interface StatsCardProps {
  title: string;
  value: number;
  icon: React.ReactNode;
  bgColor: string;
  textColor: string;
  iconBg: string;
  subtitle?: string | undefined;
}

const StatsCard: React.FC<StatsCardProps> = ({
  title,
  value,
  icon,
  textColor,
  iconBg,
  subtitle,
}) => (
  <div className="relative overflow-hidden bg-white dark:bg-slate-900 rounded-xl p-4 border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 group">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mb-1">{title}</p>
        <p className={`text-2xl font-bold ${textColor}`}>{value}</p>
        {subtitle && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{subtitle}</p>}
      </div>
      <div
        className={`w-12 h-12 rounded-lg ${iconBg} flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform duration-200`}
      >
        {icon}
      </div>
    </div>
  </div>
);

// ============================================================================
// Main Component
// ============================================================================

export const McpServerListV2: React.FC = () => {
  const [activeTab, setActiveTab] = useState<McpTabKey>('servers');
  const [isReconciling, setIsReconciling] = useState(false);

  const { servers, clearError } = useMCPStore(
    useShallow((s) => ({ servers: s.servers, clearError: s.clearError }))
  );
  const apps = useMCPAppStore((s) => s.apps);

  useEffect(() => {
    return () => {
      clearError();
    };
  }, [clearError]);

  // Computed stats
  const stats = useMemo(() => {
    // Convert apps record to array for filtering
    const appsArray = Object.values(apps);

    const serverStats: ServerStats = {
      total: servers.length,
      running: 0,
      starting: 0,
      error: 0,
      disabled: 0,
    };

    servers.forEach((s) => {
      const status = getRuntimeStatus(s);
      if (status === 'running') serverStats.running++;
      else if (status === 'starting') serverStats.starting++;
      else if (status === 'error') serverStats.error++;
      else if (!s.enabled) serverStats.disabled++;
    });

    const appStats: AppStats = {
      total: appsArray.length,
      ready: appsArray.filter((a) => a.status === 'ready').length,
      error: appsArray.filter((a) => a.status === 'error').length,
      disabled: appsArray.filter((a) => a.status === 'disabled').length,
    };

    const toolStats: ToolStats = {
      total: servers.reduce((acc, s) => acc + s.discovered_tools.length, 0),
      available: servers.reduce(
        (acc, s) => acc + s.discovered_tools.filter((t) => !t.is_error).length,
        0
      ),
      error: servers.reduce(
        (acc, s) => acc + s.discovered_tools.filter((t) => t.is_error).length,
        0
      ),
    };

    return { serverStats, appStats, toolStats };
  }, [servers, apps]);

  // Reconcile
  const handleReconcile = async () => {
    setIsReconciling(true);
    try {
      await mcpAPI.reconcileProject(servers[0]?.project_id || 'default');
      message.success('Servers reconciled');
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string };
      message.error(error.response?.data?.detail ?? error.message ?? 'Reconciliation failed');
    } finally {
      setIsReconciling(false);
    }
  };

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            MCP Servers
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Manage MCP servers, tools, and applications
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleReconcile()}
          disabled={isReconciling}
          className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
        >
          <MaterialIcon
            name={isReconciling ? 'progress_activity' : 'sync'}
            size={20}
            className={isReconciling ? 'animate-spin motion-reduce:animate-none' : ''}
          />
          Reconcile
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Total Servers"
          value={stats.serverStats.total}
          icon={<MaterialIcon name="dns" size={24} className="text-blue-600 dark:text-blue-400" />}
          bgColor="bg-blue-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-blue-100 dark:bg-blue-900/30"
          subtitle={`${String(stats.serverStats.running)} running`}
        />
        <StatsCard
          title="Tools"
          value={stats.toolStats.total}
          icon={
            <MaterialIcon name="build" size={24} className="text-purple-600 dark:text-purple-400" />
          }
          bgColor="bg-purple-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-purple-100 dark:bg-purple-900/30"
          subtitle={`${String(stats.toolStats.available)} available`}
        />
        <StatsCard
          title="Applications"
          value={stats.appStats.total}
          icon={
            <MaterialIcon
              name="apps"
              size={24}
              className="text-emerald-600 dark:text-emerald-400"
            />
          }
          bgColor="bg-emerald-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-emerald-100 dark:bg-emerald-900/30"
          subtitle={`${String(stats.appStats.ready)} ready`}
        />
        <StatsCard
          title="Health"
          value={stats.serverStats.error > 0 ? stats.serverStats.error : stats.serverStats.running}
          icon={
            stats.serverStats.error > 0 ? (
              <MaterialIcon
                name="warning"
                size={24}
                className="text-amber-600 dark:text-amber-400"
              />
            ) : (
              <MaterialIcon
                name="check_circle"
                size={24}
                className="text-emerald-600 dark:text-emerald-400"
              />
            )
          }
          bgColor="bg-emerald-500"
          textColor={
            stats.serverStats.error > 0
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-emerald-600 dark:text-emerald-400'
          }
          iconBg={
            stats.serverStats.error > 0
              ? 'bg-amber-100 dark:bg-amber-900/30'
              : 'bg-emerald-100 dark:bg-emerald-900/30'
          }
          subtitle={stats.serverStats.error > 0 ? 'errors' : 'healthy'}
        />
      </div>

      {/* Tabs */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
        {/* Tab Navigation */}
        <div className="border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 px-4" aria-label="Tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'servers'}
              aria-controls="tabpanel-servers"
              onClick={() => {
                setActiveTab('servers');
              }}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'servers'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="dns" size={18} />
              Servers
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'tools'}
              aria-controls="tabpanel-tools"
              onClick={() => {
                setActiveTab('tools');
              }}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'tools'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="build" size={18} />
              Tools
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'apps'}
              aria-controls="tabpanel-apps"
              onClick={() => {
                setActiveTab('apps');
              }}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'apps'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="apps" size={18} />
              Applications
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'prompts'}
              aria-controls="tabpanel-prompts"
              onClick={() => {
                setActiveTab('prompts');
              }}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'prompts'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="chat" size={18} />
              Prompts
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'logs'}
              aria-controls="tabpanel-logs"
              onClick={() => {
                setActiveTab('logs');
              }}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'logs'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="terminal" size={18} />
              Logs
            </button>
          </div>
        </div>

        {/* Tab Content */}
        <div className="p-4">
          {activeTab === 'servers' && <div id="tabpanel-servers" role="tabpanel"><McpServerTabV2 /></div>}
          {activeTab === 'tools' && <div id="tabpanel-tools" role="tabpanel"><McpToolsTabV2 /></div>}
          {activeTab === 'apps' && <div id="tabpanel-apps" role="tabpanel"><McpAppsTabV2 /></div>}
          {activeTab === 'prompts' && <div id="tabpanel-prompts" role="tabpanel"><McpPromptsTabV2 /></div>}
          {activeTab === 'logs' && <div id="tabpanel-logs" role="tabpanel"><McpLogsTabV2 /></div>}
        </div>
      </div>
    </div>
  );
};
