/**
 * McpServerTabV2 - Servers Tab with Modern UI
 * Redesigned with elegant filters, search, and server card grid
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message, Select, Spin, Input, Tooltip } from 'antd';
import { Plus, RefreshCw, Search, Filter, Server, AlertCircle } from 'lucide-react';

import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';

import { mcpAPI } from '@/services/mcpService';

import { McpServerCardV2 } from './McpServerCardV2';
import { McpServerDrawer } from './McpServerDrawer';
import { McpToolsDrawer } from './McpToolsDrawer';
import { CARD_STYLES, BUTTON_STYLES } from './styles';
import { getRuntimeStatus } from './types';
import { useMcpProjectScope } from './useMcpProjectScope';

import type { MCPServerResponse } from '@/types/agent';

import type { ServerFilters } from './types';

const { Search: AntSearch } = Input;

export const McpServerTabV2: React.FC = () => {
  const { t } = useTranslation();
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

  const { projectId } = useMcpProjectScope();

  useEffect(() => {
    void listServers(projectId ? { project_id: projectId } : {});
    void fetchApps(projectId);
  }, [listServers, fetchApps, projectId]);

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
    void listServers(projectId ? { project_id: projectId } : {});
  }, [listServers, projectId]);

  const handleToggle = useCallback(
    async (server: MCPServerResponse, enabled: boolean) => {
      try {
        await toggleEnabled(server.id, enabled);
        message.success(enabled ? t('mcp.servers.enableSuccess') : t('mcp.servers.disableSuccess'));
      } catch {
        /* store handles error */
      }
    },
    [toggleEnabled, t]
  );

  const handleSync = useCallback(
    async (server: MCPServerResponse) => {
      try {
        await syncServer(server.id);
        message.success(t('mcp.servers.syncSuccess'));
      } catch {
        /* store handles error */
      }
    },
    [syncServer, t]
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
              ? t('mcp.servers.connectSuccessDetail', {
                  latency: Math.round(latencyMs),
                  count: toolsCount,
                })
              : t('mcp.servers.connectSuccess')
          );
        } else {
          message.error(t('mcp.servers.connectFailed', { message: result.message }));
        }
      } catch {
        /* store handles error */
      }
    },
    [testServer, t]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteServer(id);
        message.success(t('mcp.servers.deleteSuccess'));
      } catch {
        /* store handles error */
      }
    },
    [deleteServer, t]
  );

  const handleRefresh = useCallback(() => {
    void listServers(projectId ? { project_id: projectId } : {});
    void fetchApps(projectId);
  }, [listServers, fetchApps, projectId]);

  const handleReconcile = useCallback(async () => {
    if (!projectId) {
      message.warning(t('mcp.servers.selectProjectFirst'));
      return;
    }

    setIsReconciling(true);
    try {
      const result = await mcpAPI.reconcileProject(projectId);
      await Promise.all([listServers({ project_id: projectId }), fetchApps(projectId)]);
      message.success(
        t('mcp.servers.reconcileSuccess', {
          restored: result.restored,
          running: result.already_running,
          failed: result.failed,
        })
      );
    } catch {
      message.error(t('mcp.servers.reconcileFailed'));
    } finally {
      setIsReconciling(false);
    }
  }, [projectId, listServers, fetchApps, t]);

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
              placeholder={t('mcp.servers.searchPlaceholder')}
              value={filters.search}
              onChange={(e) => {
                setFilters({ ...filters, search: e.target.value });
              }}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
              enterButton={
                <>
                  <span className="sr-only">{t('common.search', 'Search')}</span>
                  <Search size={16} aria-hidden="true" />
                </>
              }
              className="w-full"
            />
          </div>

          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-2">
              <Filter size={16} className="text-slate-400 flex-shrink-0" />
              <Select
                aria-label={t('mcp.servers.enabledFilterLabel')}
                value={filters.enabled}
                onChange={(value) => {
                  setFilters({ ...filters, enabled: value });
                }}
                className="w-32"
                size="middle"
                options={[
                  { label: t('mcp.servers.statusAll'), value: 'all' },
                  { label: t('mcp.servers.statusEnabled'), value: 'enabled' },
                  { label: t('mcp.servers.statusDisabled'), value: 'disabled' },
                ]}
              />
            </div>
            <Select
              aria-label={t('mcp.servers.typeFilterLabel')}
              value={filters.type}
              onChange={(value) => {
                setFilters({ ...filters, type: value });
              }}
              className="w-36"
              size="middle"
              placeholder={t('mcp.servers.typePlaceholder')}
              options={[
                { label: t('mcp.servers.typeAll'), value: 'all' },
                { label: 'STDIO', value: 'stdio' },
                { label: 'SSE', value: 'sse' },
                { label: 'HTTP', value: 'http' },
                { label: 'WebSocket', value: 'websocket' },
              ]}
            />
            <Select
              aria-label={t('mcp.servers.runtimeFilterLabel')}
              value={filters.runtime}
              onChange={(value) => {
                setFilters({ ...filters, runtime: value });
              }}
              className="w-40"
              size="middle"
              options={[
                { label: t('mcp.servers.runtimeAll'), value: 'all' },
                { label: t('mcp.servers.runtimeRunning'), value: 'running' },
                { label: t('mcp.servers.runtimeStarting'), value: 'starting' },
                { label: t('mcp.servers.runtimeError'), value: 'error' },
                { label: t('mcp.servers.runtimeDisabled'), value: 'disabled' },
                { label: t('mcp.servers.runtimeUnknown'), value: 'unknown' },
              ]}
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <Tooltip title={t('mcp.servers.refreshTooltip')}>
              <button
                type="button"
                onClick={handleRefresh}
                disabled={isLoading}
                className={`inline-flex items-center justify-center px-3 py-2 border border-slate-200 dark:border-slate-600 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200`}
                aria-label={t('mcp.servers.refreshTooltip')}
              >
                <RefreshCw
                  size={18}
                  className={isLoading ? 'animate-spin motion-reduce:animate-none' : ''}
                />
              </button>
            </Tooltip>
            <Tooltip title={t('mcp.servers.reconcileTooltip')}>
              <button
                type="button"
                onClick={() => {
                  void handleReconcile();
                }}
                disabled={isReconciling || !projectId}
                className={`inline-flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-200 dark:border-slate-600 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200`}
              >
                <RefreshCw
                  size={16}
                  className={isReconciling ? 'animate-spin motion-reduce:animate-none' : ''}
                />
                <span className="text-xs font-medium">{t('mcp.servers.reconcileButton')}</span>
              </button>
            </Tooltip>
            <button type="button" onClick={handleCreate} className={BUTTON_STYLES.primary}>
              <Plus size={18} />
              <span>{t('mcp.servers.createButton')}</span>
            </button>
          </div>
        </div>

        {/* Filter summary */}
        {hasActiveFilters && (
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t('mcp.servers.filterSummary', {
                shown: filteredServers.length,
                total: servers.length,
              })}
            </span>
            <button
              type="button"
              onClick={clearFilters}
              className="text-xs text-primary-600 hover:text-primary-700 dark:text-primary-400 font-medium"
            >
              {t('mcp.servers.clearFilters')}
            </button>
          </div>
        )}
      </div>

      {/* Error Banner */}
      {errorCount > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl">
          <AlertCircle size={18} className="text-amber-500 flex-shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {t('mcp.servers.errorBanner', { count: errorCount })}
          </p>
        </div>
      )}

      {/* Content */}
      {isLoading && servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Spin size="large" />
          <p className="text-sm text-slate-400 mt-4">{t('mcp.servers.loadingServers')}</p>
        </div>
      ) : servers.length === 0 ? (
        <div
          className={`flex flex-col items-center justify-center py-16 text-center ${CARD_STYLES.base} border-dashed`}
        >
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <Server size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            {t('mcp.servers.emptyTitle')}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 max-w-sm">
            {t('mcp.servers.emptyHint')}
          </p>
          <button type="button" onClick={handleCreate} className={BUTTON_STYLES.primary}>
            <Plus size={18} />
            {t('mcp.servers.emptyCreateButton')}
          </button>
        </div>
      ) : filteredServers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-12 h-12 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-3">
            <Search size={20} className="text-slate-300 dark:text-slate-500" />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t('mcp.servers.noMatch')}</p>
          <button
            type="button"
            onClick={clearFilters}
            className="mt-2 text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 font-medium"
          >
            {t('mcp.servers.clearAllFilters')}
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
              onToggle={(targetServer, enabled) => {
                void handleToggle(targetServer, enabled);
              }}
              onSync={(targetServer) => {
                void handleSync(targetServer);
              }}
              onTest={(targetServer) => {
                void handleTest(targetServer);
              }}
              onEdit={handleEdit}
              onDelete={(id) => {
                void handleDelete(id);
              }}
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
        onClose={() => {
          setToolsServer(null);
        }}
      />
    </div>
  );
};
