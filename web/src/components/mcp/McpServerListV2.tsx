/**
 * McpServerListV2 - Modern MCP Server Management Page
 * Aligned with agent workspace design system
 */

import React, { useEffect, useMemo, useState } from 'react';


import { message } from 'antd';
import { RefreshCw, Server, AlertCircle, Activity, Layers } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';



import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { McpAppsTabV2 } from './McpAppsTabV2';
import { McpServerTabV2 } from './McpServerTabV2';
import { McpToolsTabV2 } from './McpToolsTabV2';
import { ANIMATION_CLASSES } from './styles';
import { getRuntimeStatus } from './types';

import type { MCPServerType, McpTabKey, ServerStats, AppStats, ToolStats } from './types';

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
  subtitle?: string;
}

const StatsCard: React.FC<StatsCardProps> = ({
  title,
  value,
  icon,
  bgColor,
  textColor,
  iconBg,
  subtitle,
}) => (
  <div className="relative overflow-hidden bg-white dark:bg-slate-900 rounded-xl p-4 border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md transition-all duration-200 group">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mb-1">{title}</p>
        <p className={`text-2xl font-bold ${textColor}`}>{value}</p>
        {subtitle && (
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
            {subtitle}
          </p>
        )}
      </div>
      <div className={`w-12 h-12 rounded-lg ${iconBg} flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform duration-200`}>
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
    return () => clearError();
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
      else if (s.enabled === false) serverStats.disabled++;
    });

    const appStats: AppStats = {
      total: appsArray.length,
      ready: appsArray.filter((a) => a.status === 'Ready').length,
      error: appsArray.filter((a) => a.status === 'Error').length,
      disabled: appsArray.filter((a) => a.enabled === false).length,
    };

    const toolStats: ToolStats = {
      total: servers.reduce((acc, s) => acc + (s.discovered_tools?.length || 0), 0),
      available: servers.reduce(
        (acc, s) => acc + (s.discovered_tools?.filter((t) => !(t as MCPToolInfo).is_error)?.length || 0),
        0
      ),
      error: servers.reduce(
        (acc, s) => acc + (s.discovered_tools?.filter((t) => (t as MCPToolInfo).is_error)?.length || 0),
        0
      ),
    };

    return { serverStats, appStats, toolStats };
  }, [servers, apps]);

  // Reconcile
  const handleReconcile = async () => {
    setIsReconciling(true);
    try {
      await mcpAPI.reconcile();
      message.success('Servers reconciled');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || 'Reconciliation failed');
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
          onClick={handleReconcile}
          disabled={isReconciling}
          className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
        >
          <MaterialIcon
            name={isReconciling ? 'progress_activity' : 'sync'}
            size={20}
            className={isReconciling ? 'animate-spin' : ''}
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
          subtitle={`${stats.serverStats.running} running`}
        />
        <StatsCard
          title="Tools"
          value={stats.toolStats.total}
          icon={<MaterialIcon name="build" size={24} className="text-purple-600 dark:text-purple-400" />}
          bgColor="bg-purple-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-purple-100 dark:bg-purple-900/30"
          subtitle={`${stats.toolStats.available} available`}
        />
        <StatsCard
          title="Applications"
          value={stats.appStats.total}
          icon={<MaterialIcon name="apps" size={24} className="text-emerald-600 dark:text-emerald-400" />}
          bgColor="bg-emerald-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-emerald-100 dark:bg-emerald-900/30"
          subtitle={`${stats.appStats.ready} ready`}
        />
        <StatsCard
          title="Health"
          value={stats.serverStats.error > 0 ? stats.serverStats.error : stats.serverStats.running}
          icon={
            stats.serverStats.error > 0 ? (
              <MaterialIcon name="warning" size={24} className="text-amber-600 dark:text-amber-400" />
            ) : (
              <MaterialIcon name="check_circle" size={24} className="text-emerald-600 dark:text-emerald-400" />
            )
          }
          bgColor="bg-emerald-500"
          textColor={stats.serverStats.error > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}
          iconBg={stats.serverStats.error > 0 ? 'bg-amber-100 dark:bg-amber-900/30' : 'bg-emerald-100 dark:bg-emerald-900/30'}
          subtitle={stats.serverStats.error > 0 ? 'errors' : 'healthy'}
        />
      </div>

      {/* Tabs */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
        {/* Tab Navigation */}
        <div className="border-b border-slate-200 dark:border-slate-800">
          <nav className="flex items-center gap-2 px-4" aria-label="Tabs">
            <button
              onClick={() => setActiveTab('servers')}
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
              onClick={() => setActiveTab('tools')}
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
              onClick={() => setActiveTab('apps')}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'apps'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <MaterialIcon name="apps" size={18} />
              Applications
            </button>
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-4">
          {activeTab === 'servers' && <McpServerTabV2 />}
          {activeTab === 'tools' && <McpToolsTabV2 />}
          {activeTab === 'apps' && <McpAppsTabV2 />}
        </div>
      </div>
    </div>
  );
};
