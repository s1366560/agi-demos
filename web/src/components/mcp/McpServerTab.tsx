/**
 * McpServerTab - Servers tab content with search, filters, and server card grid.
 * Self-contained: manages filter state, server actions, and drawer state.
 */

import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';

import { message, Select, Spin, Input, Tooltip } from 'antd';
import { Plus, RefreshCw, Search, Filter, Server, AlertCircle } from 'lucide-react';


import { useMCPStore } from '@/stores/mcp';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAPI } from '@/services/mcpService';

import { McpServerCard } from './McpServerCard';
import { McpServerDrawer } from './McpServerDrawer';
import { McpToolsDrawer } from './McpToolsDrawer';

import type { MCPServerResponse, MCPServerType } from '@/types/agent';

const { Search: AntSearch } = Input;

function getServerRuntimeStatus(server: MCPServerResponse): string {
  if (server.runtime_status) return server.runtime_status;
  if (!server.enabled) return 'disabled';
  if (server.sync_error) return 'error';
  if (server.last_sync_at) return 'running';
  return 'unknown';
}

export const McpServerTab: React.FC = () => {
  const [search, setSearch] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | MCPServerType>('all');
  const [runtimeFilter, setRuntimeFilter] = useState<
    'all' | 'running' | 'starting' | 'error' | 'disabled' | 'unknown'
  >('all');
  const [isReconciling, setIsReconciling] = useState(false);

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
      if (search) {
        const q = search.toLowerCase();
        if (
          !server.name.toLowerCase().includes(q) &&
          !server.description?.toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      if (enabledFilter === 'enabled' && !server.enabled) return false;
      if (enabledFilter === 'disabled' && server.enabled) return false;
      if (typeFilter !== 'all' && server.server_type !== typeFilter) return false;
      if (runtimeFilter !== 'all' && getServerRuntimeStatus(server) !== runtimeFilter) return false;
      return true;
    });
  }, [servers, search, enabledFilter, typeFilter, runtimeFilter]);

  const appStatsByServer = useMemo(() => {
    const byId: Record<string, { total: number; ready: number; error: number }> = {};
    const byName: Record<string, { total: number; ready: number; error: number }> = {};

    for (const app of Object.values(apps)) {
      const base = { total: 1, ready: app.status === 'ready' ? 1 : 0, error: app.status === 'error' ? 1 : 0 };
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
        message.success(enabled ? 'Server enabled' : 'Server disabled');
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
        message.success('Server synced successfully');
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
              ? `Connection successful (${Math.round(latencyMs)}ms, ${toolsCount} tools)`
              : 'Connection successful'
          );
        } else {
          message.error(`Connection failed: ${result.message}`);
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
        message.success('Server deleted');
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
      message.warning('Please select a project first');
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
        `Reconciled runtime: restored ${result.restored}, already running ${result.already_running}, failed ${result.failed}`
      );
    } catch {
      message.error('Failed to reconcile MCP runtime');
    } finally {
      setIsReconciling(false);
    }
  }, [currentProject?.id, listServers, fetchApps]);

  // Error count for badge
  const errorCount = useMemo(() => 
    servers.filter((s) => s.sync_error || getServerRuntimeStatus(s) === 'error').length,
    [servers]
  );

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="bg-white dark:bg-slate-800 rounded-xl p-4 border border-slate-200 dark:border-slate-700 shadow-sm">
        <div className="flex flex-col lg:flex-row gap-4">
          {/* Search */}
          <div className="flex-1 min-w-0">
            <AntSearch
              placeholder="Search servers by name or description..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
              prefix={<Search size={16} className="text-slate-400" />}
              className="w-full"
            />
          </div>
          
          {/* Filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="flex items-center gap-2">
              <Filter size={16} className="text-slate-400 flex-shrink-0" />
              <Select
                value={enabledFilter}
                onChange={setEnabledFilter}
                className="w-32"
                size="middle"
                options={[
                  { label: 'All Status', value: 'all' },
                  { label: 'Enabled', value: 'enabled' },
                  { label: 'Disabled', value: 'disabled' },
                ]}
              />
            </div>
            <Select
              value={typeFilter}
              onChange={setTypeFilter}
              className="w-36"
              size="middle"
              placeholder="Type"
              options={[
                { label: 'All Types', value: 'all' },
                { label: 'STDIO', value: 'stdio' },
                { label: 'SSE', value: 'sse' },
                { label: 'HTTP', value: 'http' },
                { label: 'WebSocket', value: 'websocket' },
              ]}
            />
            <Select
              value={runtimeFilter}
              onChange={setRuntimeFilter}
              className="w-40"
              size="middle"
              options={[
                { label: 'All Runtime', value: 'all' },
                { label: 'Running', value: 'running' },
                { label: 'Starting', value: 'starting' },
                { label: 'Error', value: 'error' },
                { label: 'Disabled', value: 'disabled' },
                { label: 'Unknown', value: 'unknown' },
              ]}
            />
          </div>
          
          {/* Actions */}
          <div className="flex gap-2">
            <Tooltip title="Refresh list">
              <button
                onClick={handleRefresh}
                disabled={isLoading}
                className="inline-flex items-center justify-center px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-colors"
                aria-label="refresh"
                >
                  <RefreshCw size={18} className={isLoading ? 'animate-spin' : ''} />
                </button>
              </Tooltip>
            <Tooltip title="Reconcile runtime with sandbox">
              <button
                onClick={handleReconcile}
                disabled={isReconciling || !currentProject?.id}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400 disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={16} className={isReconciling ? 'animate-spin' : ''} />
                <span className="text-xs font-medium">Reconcile</span>
              </button>
            </Tooltip>
            <button
              onClick={handleCreate}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors shadow-sm hover:shadow font-medium"
            >
              <Plus size={18} />
              <span>Create Server</span>
            </button>
          </div>
        </div>
        
        {/* Filter summary */}
        {(search || enabledFilter !== 'all' || typeFilter !== 'all' || runtimeFilter !== 'all') && (
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Showing {filteredServers.length} of {servers.length} servers
            </span>
            {(search || enabledFilter !== 'all' || typeFilter !== 'all' || runtimeFilter !== 'all') && (
              <button
                onClick={() => {
                  setSearch('');
                  setEnabledFilter('all');
                  setTypeFilter('all');
                  setRuntimeFilter('all');
                }}
                className="text-xs text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
              >
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Error Banner */}
      {errorCount > 0 && (
        <div className="flex items-center gap-3 px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl">
          <AlertCircle size={18} className="text-amber-500 flex-shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {errorCount} server{errorCount > 1 ? 's have' : ' has'} sync errors. Check the server cards for details.
          </p>
        </div>
      )}

      {/* Content */}
      {isLoading && servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <Spin size="large" />
          <p className="text-sm text-slate-400 mt-4">Loading servers...</p>
        </div>
      ) : servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 border-dashed">
          <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-4">
            <Server size={28} className="text-slate-300 dark:text-slate-500" />
          </div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-1">
            No MCP servers configured
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 max-w-sm">
            Create your first MCP server to enable powerful tools and capabilities
          </p>
          <button
            onClick={handleCreate}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors shadow-sm"
          >
            <Plus size={18} />
            Create Server
          </button>
        </div>
      ) : filteredServers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-12 h-12 rounded-full bg-slate-50 dark:bg-slate-700/50 flex items-center justify-center mb-3">
            <Search size={20} className="text-slate-300 dark:text-slate-500" />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No servers match your search criteria.
          </p>
          <button
            onClick={() => {
              setSearch('');
              setEnabledFilter('all');
              setTypeFilter('all');
            }}
            className="mt-2 text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400"
          >
            Clear all filters
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {filteredServers.map((server) => (
            <McpServerCard
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
        onClose={() => setToolsServer(null)}
      />
    </div>
  );
};
