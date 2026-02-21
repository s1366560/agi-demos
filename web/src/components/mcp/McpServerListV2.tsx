/**
 * McpServerListV2 - Modern MCP Server Management Page
 * Redesigned with elegant UI/UX, better visual hierarchy, and smooth animations
 */

import React, { useEffect, useMemo, useState } from 'react';

import { useShallow } from 'zustand/react/shallow';

import { message, Badge } from 'antd';
import { 
  RefreshCw, 
  Server, 
  AlertCircle,
  Activity,
  Layers
} from 'lucide-react';

import { McpServerTabV2 } from './McpServerTabV2';
import { McpToolsTabV2 } from './McpToolsTabV2';
import { McpAppsTabV2 } from './McpAppsTabV2';

import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import type { MCPServerType, McpTabKey, ServerStats, AppStats, ToolStats } from './types';
import { getRuntimeStatus } from './types';
import { ANIMATION_CLASSES } from './styles';

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
  <div className="relative overflow-hidden bg-white dark:bg-slate-800 rounded-2xl p-5 border border-slate-200 dark:border-slate-700/60 shadow-sm hover:shadow-lg transition-all duration-300 group">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-1">{title}</p>
        <p className={`text-3xl font-bold ${textColor}`}>{value}</p>
        {subtitle && (
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-2 flex items-center gap-1">
            {subtitle}
          </p>
        )}
      </div>
      <div className={`w-14 h-14 rounded-2xl ${iconBg} flex items-center justify-center flex-shrink-0 group-hover:scale-110 transition-transform duration-300`}>
        {icon}
      </div>
    </div>
    {/* Decorative gradient */}
    <div className={`absolute -right-6 -bottom-6 w-24 h-24 rounded-full opacity-5 ${bgColor}`} />
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
    const serverStats: ServerStats = {
      total: servers.length,
      running: 0,
      starting: 0,
      error: 0,
      disabled: 0,
      unknown: 0,
    };

    const byType: Record<MCPServerType, number> = { stdio: 0, sse: 0, http: 0, websocket: 0 };

    for (const server of servers) {
      const status = getRuntimeStatus(server);
      if (status in serverStats) {
        serverStats[status as keyof ServerStats]++;
      } else {
        serverStats.unknown++;
      }
      byType[server.server_type]++;
    }

    const appStats: AppStats = {
      total: Object.keys(apps).length,
      ready: 0,
      loading: 0,
      error: 0,
      disabled: 0,
      discovered: 0,
    };

    for (const app of Object.values(apps)) {
      if (app.status in appStats) {
        appStats[app.status as keyof AppStats]++;
      }
    }

    const toolStats: ToolStats = {
      total: servers.reduce((sum, s) => sum + (s.discovered_tools?.length || 0), 0),
      serversWithTools: servers.filter(s => s.discovered_tools?.length).length,
    };

    return {
      servers: serverStats,
      apps: appStats,
      tools: toolStats,
      byType,
    };
  }, [servers, apps]);

  const tabs = [
    { 
      key: 'servers' as McpTabKey, 
      label: '服务器', 
      icon: 'dns', 
      count: stats.servers.total,
      color: 'text-blue-600 dark:text-blue-400'
    },
    { 
      key: 'tools' as McpTabKey, 
      label: '工具', 
      icon: 'build', 
      count: stats.tools.total,
      color: 'text-violet-600 dark:text-violet-400'
    },
    { 
      key: 'apps' as McpTabKey, 
      label: '应用', 
      icon: 'widgets', 
      count: stats.apps.total,
      color: 'text-emerald-600 dark:text-emerald-400'
    },
  ];

  const handleReconcile = async () => {
    const currentProject = useProjectStore.getState().currentProject;
    if (!currentProject?.id) {
      message.warning('请先选择项目');
      return;
    }

    setIsReconciling(true);
    try {
      const result = await mcpAPI.reconcileProject(currentProject.id);
      message.success(
        `运行时已协调：恢复 ${result.restored} 个，已运行 ${result.already_running} 个，失败 ${result.failed} 个`
      );
    } catch {
      message.error('协调 MCP 运行时失败');
    } finally {
      setIsReconciling(false);
    }
  };

  return (
    <div className="max-w-[1600px] mx-auto w-full flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-3">
            <span className="material-symbols-outlined text-primary-500">dns</span>
            MCP 运行时
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            统一管理 MCP 服务器、工具和应用的运行时面板
          </p>
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleReconcile}
            disabled={isReconciling}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-600 transition-colors disabled:opacity-50 text-sm font-medium"
          >
            <RefreshCw size={16} className={isReconciling ? ANIMATION_CLASSES.spin : ''} />
            协调运行时
          </button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="服务器总数"
          value={stats.servers.total}
          icon={<Server size={24} className="text-slate-600 dark:text-slate-400" />}
          bgColor="bg-slate-500"
          textColor="text-slate-900 dark:text-white"
          iconBg="bg-slate-100 dark:bg-slate-700/50"
          subtitle={`${stats.servers.disabled} 个已禁用`}
        />
        <StatsCard
          title="运行中"
          value={stats.servers.running}
          icon={<Activity size={24} className="text-green-600 dark:text-green-400" />}
          bgColor="bg-green-500"
          textColor="text-green-600 dark:text-green-400"
          iconBg="bg-green-50 dark:bg-green-900/20"
          subtitle={`${stats.servers.starting} 个启动中`}
        />
        <StatsCard
          title="错误"
          value={stats.servers.error}
          icon={<AlertCircle size={24} className="text-red-600 dark:text-red-400" />}
          bgColor="bg-red-500"
          textColor="text-red-600 dark:text-red-400"
          iconBg="bg-red-50 dark:bg-red-900/20"
          subtitle={`${stats.servers.disabled} 个已禁用`}
        />
        <StatsCard
          title="应用就绪"
          value={stats.apps.ready}
          icon={<Layers size={24} className="text-blue-600 dark:text-blue-400" />}
          bgColor="bg-blue-500"
          textColor="text-blue-600 dark:text-blue-400"
          iconBg="bg-blue-50 dark:bg-blue-900/20"
          subtitle={`${stats.apps.error} 个错误`}
        />
      </div>

      {/* Error Banner */}
      {stats.servers.error > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-xl">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0" />
          <p className="text-sm text-red-700 dark:text-red-300">
            检测到 {stats.servers.error} 个运行时错误服务器，请在服务器标签页中进行协调、同步或测试
          </p>
        </div>
      )}

      {/* Tab Bar */}
      <div className="bg-white dark:bg-slate-800 rounded-2xl p-2 border border-slate-200 dark:border-slate-700/60 shadow-sm">
        <div className="flex gap-2">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl transition-all duration-200 ${
                  isActive
                    ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700/50'
                }`}
              >
                <span className={`material-symbols-outlined text-base ${isActive ? 'filled' : ''}`}>
                  {tab.icon}
                </span>
                {tab.label}
                <Badge 
                  count={tab.count} 
                  className={`text-xs min-w-[1.25rem] h-5 px-1.5 rounded-full flex items-center justify-center ${
                    isActive
                      ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                      : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                  }`}
                />
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1">
        {activeTab === 'servers' && <McpServerTabV2 />}
        {activeTab === 'tools' && <McpToolsTabV2 />}
        {activeTab === 'apps' && <McpAppsTabV2 />}
      </div>
    </div>
  );
};

McpServerListV2.displayName = 'McpServerListV2';

export default McpServerListV2;
