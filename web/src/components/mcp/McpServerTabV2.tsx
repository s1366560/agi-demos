/**
 * McpServerTabV2 - Servers Tab with Modern UI
 * Redesigned with elegant filters, search, and server card grid
 */

import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';

import { message, Select, Spin, Input, Tooltip } from 'antd';
import { Plus, RefreshCw, Search, Filter, Server, AlertCircle } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import { McpServerCardV2 } from './McpServerCardV2';
import { McpServerDrawer } from './McpServerDrawer';
import { McpToolsDrawer } from './McpToolsDrawer';
import { CARD_STYLES, BUTTON_STYLES } from './styles';
import { getRuntimeStatus } from './types';

import type { MCPServerResponse } from '@/types/agent';

import type { ServerFilters } from './types';

const { Search: AntSearch } = Input;

export const McpServerTabV2: React.FC = () => {
  const [isReconciling, setIsReconciling] = useState(false);

  // Filters
  const [filters, setFilters] = useState<ServerFilters>({
    search: '',
    enabled: 'all',
    type: 'all',
    runtime: 'all',
  });

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServerResponse | null>(null);
  const [toolsServer, setToolsServer] = useState<MCPServerResponse | null>(null);

  // Store
  const servers = useMCPStore((s) => s.servers);
  const syncingServers = useMCPStore((s) => s.syncingServers);
  const testingServers = useMCPStore((s) => s.testingServers);
  const isLoading = useMCPStore((s) => s.isLoading);
  const listServers = useMCPStore((s) => s.listServers);
  const deleteServer = useMCPStore((s) => s.deleteServer);
  const toggleEnabled = useMCPStore((s) => s.toggleEnabled);
  const syncServer = useMCPStore((s) => s.syncServer);
  const testServer = useMCPStore((s) => s.testServer);
  const apps = useMCPAppStore((s) => s.apps);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);

  const currentProject = useProjectStore((s) => s.currentProject);
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    if (currentProject?.id) {
      listServers({ project_id: currentProject.id });
      fetchApps(currentProject.id);
    } else if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      listServers();
      fetchApps();
    }
  }, [listServers, fetchApps, currentProject?.id]);

  const filteredServers = useMemo(() => {
    return servers.filter((server) => {
      if (filters.search) {
        const q = filters.search.toLowerCase();
        if (
          !server.name.toLowerCase().includes(q) &&
          !server.description?.toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      if (filters.enabled === 'enabled' && !server.enabled) return false;
      if (filters.enabled === 'disabled' && server.enabled) return false;
      if (filters.type !== 'all' && server.server_type !== filters.type) return false;
      if (filters.runtime !== 'all' && getRuntimeStatus(server) !== filters.runtime) return false;
      return true;
    });
  }, [servers, filters]);

  const appStatsByServer = useMemo(() => {
    const byId: Record<string, { total: number; ready: number; error: number }> = {};
    const byName: Record<string, { total: number; ready: number; error: number }> = {};

    for (const app of Object.values(apps)) {
      const base = {
        total: 1,
        ready: app.status === 'ready' ? 1 : 0,
        error: app.status === 'error' ? 1 : 0,
      };
      if (app.server_id) {
        byId[app.server_id] = {
          total: (byId[app.server_id]?.total || 0) + base.total,
          ready: (byId[app.server_id]?.ready || 0) + base.ready,
          error: (byId[app.server_id]?.error || 0) + base.error,
        };
      }
      byName[app.server_name] = {
        total: (byName[app.server_name]?.total || 0) + base.total,
        ready: (byName[app.server_name]?.ready || 0) + base.ready,
        error: (byName[app.server_name]?.error || 0) + base.error,
      };
    }

    return { byId, byName };
  }, [apps]);

  const handleCreate = useCallback(() => {
    setEditingServer(null);
    setDrawerOpen(true);
  }, []);

  const handleEdit = useCallback((server: MCPServerResponse) => {
    setEditingServer(server);
    setDrawerOpen(true);
  }, []);

  const handleDrawerClose = useCallback(() => {
    setDrawerOpen(false);
    setEditingServer(null);
  }, []);

  const handleDrawerSuccess = useCallback(() => {
    setDrawerOpen(false);
    setEditingServer(null);
    const projectId = currentProject?.id;
    listServers(projectId ? { project_id: projectId } : {});
  }, [listServers, currentProject]);

  const handleToggle = useCallback(
    async (server: MCPServerResponse, enabled: boolean) => {
      try {
        await toggleEnabled(server.id, enabled);
        message.success(enabled ? '服务器已启用' : '服务器已禁用');
      } catch {
        /* store handles error */
      }
    },
    [toggleEnabled]
  );

  const handleSync = useCallback(
    async (server: MCPServerResponse) => {
      try {
        await syncServer(server.id);
        message.success('服务器同步成功');
      } catch {
        /* store handles error */
      }
    },
    [syncServer]
  );

  const handleTest = useCallback(
    async (server: MCPServerResponse) => {
      try {
        const result = await testServer(server.id);
        if (result.success) {
          const latencyMs = result.connection_time_ms ?? result.latency_ms;
          const toolsCount = result.tools_discovered ?? 0;
          message.success(
            latencyMs != null
              ? `连接成功 (${Math.round(latencyMs)}ms, ${toolsCount} 个工具)`
              : '连接成功'
          );
        } else {
          message.error(`连接失败：${result.message}`);
        }
      } catch {
        /* store handles error */
      }
    },
    [testServer]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteServer(id);
        message.success('服务器已删除');
      } catch {
        /* store handles error */
      }
    },
    [deleteServer]
  );

  const handleRefresh = useCallback(() => {
    const projectId = currentProject?.id;
    listServers(projectId ? { project_id: projectId } : {});
    fetchApps(projectId);
  }, [listServers, fetchApps, currentProject]);

  const handleReconcile = useCallback(async () => {
    if (!currentProject?.id) {
      message.warning('请先选择项目');
      return;
    }

    setIsReconciling(true);
    try {
      const result = await mcpAPI.reconcileProject(currentProject.id);
      await Promise.all([
        listServers({ project_id: currentProject.id }),
        fetchApps(currentProject.id),
      ]);
      message.success(
        `运行时已协调：恢复 ${result.restored} 个，已运行 ${result.already_running} 个，失败 ${result.failed} 个`
      );
    } catch {
      message.error('协调 MCP 运行时失败');
    } finally {
      setIsReconciling(false);
    }
  }, [currentProject?.id, listServers, fetchApps]);

  // Error count
  const errorCount = useMemo(
    () => servers.filter((s) => s.sync_error || getRuntimeStatus(s) === 'error').length,
    [servers]
  );

  const hasActiveFilters =
    filters.search ||
    filters.enabled !== 'all' ||
    filters.type !== 'all' ||
    filters.runtime !== 'all';

  const clearFilters = () => {
    setFilters({
      search: '',
      enabled: 'all',
      type: 'all',
      runtime: 'all',
    });
  };

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className={`${CARD_STYLES.base} p-4 shadow-sm`}>
        <div className="flex flex-col lg:flex-row gap-4">
          {/* Search */}
          <div className="flex-1 min-w-0">
            <AntSearch
              placeholder="搜索服务器名称或描述..."
              value={filters.search}
              onChange={(e) => { setFilters({ ...filters, search: e.target.value }); }}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
              className="w-full"
            />
          </div>

          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-2">
              <Filter size={16} className="text-slate-400 flex-shrink-0" />
              <Select
                value={filters.enabled}
                onChange={(value) => { setFilters({ ...filters, enabled: value }); }}
                className="w-32"
                size="middle"
                options={[
                  { label: '全部状态', value: 'all' },
                  { label: '已启用', value: 'enabled' },
                  { label: '已禁用', value: 'disabled' },
                ]}
              />
            </div>
            <Select
              value={filters.type}
              onChange={(value) => { setFilters({ ...filters, type: value }); }}
              className="w-36"
              size="middle"
              placeholder="类型"
              options={[
                { label: '全部类型', value: 'all' },
                { label: 'STDIO', value: 'stdio' },
                { label: 'SSE', value: 'sse' },
                { label: 'HTTP', value: 'http' },
                { label: 'WebSocket', value: 'websocket' },
              ]}
            />
            <Select
              value={filters.runtime}
              onChange={(value) => { setFilters({ ...filters, runtime: value }); }}
              className="w-40"
              size="middle"
              options={[
                { label: '全部运行状态', value: 'all' },
                { label: '运行中', value: 'running' },
                { label: '启动中', value: 'starting' },
                { label: '错误', value: 'error' },
                { label: '已禁用', value: 'disabled' },
                { label: '未知', value: 'unknown' },
              ]}
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <Tooltip title="刷新列表">
              <button
                onClick={handleRefresh}
                disabled={isLoading}
                className={`inline-flex items-center justify-center px-3 py-2 border border-slate-200 dark:border-slate-600 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-all duration-200`}
                aria-label="refresh"
              >
                <RefreshCw size={18} className={isLoading ? 'animate-spin' : ''} />
              </button>
            </Tooltip>
            <Tooltip title="与沙盒协调运行时">
              <button
                onClick={handleReconcile}
                disabled={isReconciling || !currentProject?.id}
                className={`inline-flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-200 dark:border-slate-600 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-all duration-200`}
              >
                <RefreshCw size={16} className={isReconciling ? 'animate-spin' : ''} />
                <span className="text-xs font-medium">协调</span>
              </button>
            </Tooltip>
            <button onClick={handleCreate} className={BUTTON_STYLES.primary}>
              <Plus size={18} />
              <span>创建服务器</span>
            </button>
          </div>
        </div>

        {/* Filter summary */}
        {hasActiveFilters && (
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-500 dark:text-slate-400">
              显示 {filteredServers.length} / {servers.length} 个服务器
            </span>
            <button
              onClick={clearFilters}
              className="text-xs text-primary-600 hover:text-primary-700 dark:text-primary-400 font-medium"
            >
              清除筛选
            </button>
          </div>
        )}
      </div>

      {/* Error Banner */}
      {errorCount > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl">
          <AlertCircle size={18} className="text-amber-500 flex-shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {errorCount} 个服务器存在同步错误，请检查服务器卡片详情
          </p>
        </div>
      )}

      {/* Content */}
      {isLoading && servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Spin size="large" />
          <p className="text-sm text-slate-400 mt-4">加载服务器中...</p>
        </div>
      ) : servers.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-16 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <Server size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            暂无 MCP 服务器
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 max-w-sm">
            创建第一个 MCP 服务器，启用强大的工具和功能
          </p>
          <button onClick={handleCreate} className={BUTTON_STYLES.primary}>
            <Plus size={18} />
            创建服务器
          </button>
        </div>
      ) : filteredServers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-12 h-12 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-3">
            <Search size={20} className="text-slate-300 dark:text-slate-500" />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">没有符合筛选条件的服务器</p>
          <button
            onClick={clearFilters}
            className="mt-2 text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 font-medium"
          >
            清除所有筛选
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {filteredServers.map((server) => (
            <McpServerCardV2
              key={server.id}
              server={server}
              isSyncing={syncingServers.has(server.id)}
              isTesting={testingServers.has(server.id)}
              onToggle={handleToggle}
              onSync={handleSync}
              onTest={handleTest}
              onEdit={handleEdit}
              onDelete={handleDelete}
              onShowTools={setToolsServer}
              appCount={
                appStatsByServer.byId[server.id]?.total ??
                appStatsByServer.byName[server.name]?.total ??
                0
              }
              readyAppCount={
                appStatsByServer.byId[server.id]?.ready ??
                appStatsByServer.byName[server.name]?.ready ??
                0
              }
              errorAppCount={
                appStatsByServer.byId[server.id]?.error ??
                appStatsByServer.byName[server.name]?.error ??
                0
              }
            />
          ))}
        </div>
      )}

      {/* Drawers */}
      <McpServerDrawer
        open={drawerOpen}
        server={editingServer}
        onClose={handleDrawerClose}
        onSuccess={handleDrawerSuccess}
      />
      <McpToolsDrawer
        open={!!toolsServer}
        server={toolsServer}
        onClose={() => { setToolsServer(null); }}
      />
    </div>
  );
};
