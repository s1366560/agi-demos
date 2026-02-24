/**
 * McpAppsTabV2 - Apps Tab with Modern UI
 * Redesigned with elegant app cards and better visual hierarchy
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { message, Spin, Input, Badge } from 'antd';
import { LayoutGrid, RefreshCw, Search } from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAppAPI } from '@/services/mcpAppService';

import { McpAppCardV2 } from './McpAppCardV2';
import { CARD_STYLES, BUTTON_STYLES } from './styles';

import type { MCPApp, MCPAppStatus } from '@/types/mcpApp';

export const McpAppsTabV2: React.FC = () => {
  const apps = useMCPAppStore((s) => s.apps);
  const loading = useMCPAppStore((s) => s.loading);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);
  const removeApp = useMCPAppStore((s) => s.removeApp);
  const currentProject = useProjectStore((s) => s.currentProject);

  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [retrying, setRetrying] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchApps(currentProject?.id);
  }, [currentProject?.id, fetchApps]);

  const appList = useMemo(() => {
    const list = Object.values(apps);
    if (!search) return list;
    const q = search.toLowerCase();
    return list.filter(
      (app) =>
        app.tool_name.toLowerCase().includes(q) ||
        app.server_name.toLowerCase().includes(q) ||
        (app.ui_metadata?.title || '').toLowerCase().includes(q)
    );
  }, [apps, search]);

  const handleDelete = useCallback(
    async (appId: string) => {
      setDeleting((prev) => new Set(prev).add(appId));
      try {
        await mcpAppAPI.delete(appId);
        removeApp(appId);
        message.success('MCP 应用已删除');
      } catch {
        message.error('删除 MCP 应用失败');
      } finally {
        setDeleting((prev) => {
          const next = new Set(prev);
          next.delete(appId);
          return next;
        });
      }
    },
    [removeApp]
  );

  const handleRetry = useCallback(
    async (appId: string) => {
      setRetrying((prev) => new Set(prev).add(appId));
      try {
        await mcpAppAPI.refresh(appId);
        await fetchApps(currentProject?.id);
        message.success('应用已刷新');
      } catch {
        message.error('重试失败');
      } finally {
        setRetrying((prev) => {
          const next = new Set(prev);
          next.delete(appId);
          return next;
        });
      }
    },
    [fetchApps, currentProject?.id]
  );

  const handleOpenInCanvas = useCallback((app: MCPApp) => {
    const tabId = `mcp-app-${app.id}`;
    useCanvasStore.getState().openTab({
      id: tabId,
      title: app.ui_metadata?.title || app.tool_name,
      type: 'mcp-app' as const,
      content: '',
      mcpAppId: app.id,
    });
    useLayoutModeStore.getState().setMode('canvas');
  }, []);

  const handleRefresh = useCallback(() => {
    fetchApps(currentProject?.id);
  }, [currentProject?.id, fetchApps]);

  // Status counts
  const statusCounts = useMemo(() => {
    const counts: Record<MCPAppStatus, number> = {
      discovered: 0,
      loading: 0,
      ready: 0,
      error: 0,
      disabled: 0,
    };
    Object.values(apps).forEach((app) => {
      counts[app.status]++;
    });
    return counts;
  }, [apps]);

  if (loading && Object.keys(apps).length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin tip="加载 MCP 应用中..." />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header Stats */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-50 to-green-50 dark:from-emerald-900/20 dark:to-green-900/20 flex items-center justify-center">
                <LayoutGrid size={20} className="text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">
                  {appList.length}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">应用总数</p>
              </div>
            </div>

            {/* Status Badges */}
            <div className="flex items-center gap-2 flex-wrap">
              {statusCounts.ready > 0 && (
                <Badge count={statusCounts.ready} color="green" offset={[-10, 0]}>
                  <span className="text-xs px-2.5 py-1 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 rounded-full font-medium">
                    就绪
                  </span>
                </Badge>
              )}
              {statusCounts.loading > 0 && (
                <Badge count={statusCounts.loading} color="blue" offset={[-10, 0]}>
                  <span className="text-xs px-2.5 py-1 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 rounded-full font-medium">
                    加载中
                  </span>
                </Badge>
              )}
              {statusCounts.error > 0 && (
                <Badge count={statusCounts.error} color="red" offset={[-10, 0]}>
                  <span className="text-xs px-2.5 py-1 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-full font-medium">
                    错误
                  </span>
                </Badge>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {Object.keys(apps).length > 5 && (
              <Input
                placeholder="搜索应用..."
                prefix={<Search size={14} className="text-slate-400" />}
                value={search}
                onChange={(e) => { setSearch(e.target.value); }}
                className="w-48"
                allowClear
              />
            )}
            <button type="button" onClick={handleRefresh} className={BUTTON_STYLES.secondary}>
              <RefreshCw size={14} />
              刷新
            </button>
          </div>
        </div>
      </div>

      {/* App Grid */}
      {appList.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-12 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <LayoutGrid size={32} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            暂无 MCP 应用
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            发现 MCP 服务器后，应用将自动显示在此处
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {appList.map((app) => (
            <McpAppCardV2
              key={app.id}
              app={app}
              onDelete={handleDelete}
              onRetry={handleRetry}
              onOpenInCanvas={handleOpenInCanvas}
              deleting={deleting}
              retrying={retrying}
            />
          ))}
        </div>
      )}
    </div>
  );
};
