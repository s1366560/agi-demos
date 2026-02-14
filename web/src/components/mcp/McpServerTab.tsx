/**
 * McpServerTab - Servers tab content with search, filters, and server card grid.
 * Self-contained: manages filter state, server actions, and drawer state.
 */

import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';

import { message, Select, Empty, Spin, Input } from 'antd';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import { McpServerCard } from './McpServerCard';
import { McpServerDrawer } from './McpServerDrawer';
import { McpToolsDrawer } from './McpToolsDrawer';

import type { MCPServerResponse, MCPServerType } from '@/types/agent';

const { Search } = Input;

export const McpServerTab: React.FC = () => {
  const [search, setSearch] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | MCPServerType>('all');

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

  const currentProject = useProjectStore((s) => s.currentProject);
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    if (currentProject?.id) {
      listServers({ project_id: currentProject.id });
    } else if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      listServers();
    }
  }, [listServers, currentProject?.id]);

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
      return true;
    });
  }, [servers, search, enabledFilter, typeFilter]);

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
          message.success(`Connection successful (${result.latency_ms}ms)`);
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
  }, [listServers, currentProject]);

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Search
              placeholder="Search servers..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              allowClear
            />
          </div>
          <Select
            value={enabledFilter}
            onChange={setEnabledFilter}
            className="w-full sm:w-36"
            options={[
              { label: 'All', value: 'all' },
              { label: 'Enabled', value: 'enabled' },
              { label: 'Disabled', value: 'disabled' },
            ]}
          />
          <Select
            value={typeFilter}
            onChange={setTypeFilter}
            className="w-full sm:w-36"
            options={[
              { label: 'All Types', value: 'all' },
              { label: 'STDIO', value: 'stdio' },
              { label: 'SSE', value: 'sse' },
              { label: 'HTTP', value: 'http' },
              { label: 'WebSocket', value: 'websocket' },
            ]}
          />
          <div className="flex gap-2">
            <button
              onClick={handleRefresh}
              className="inline-flex items-center justify-center px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700"
              aria-label="refresh"
            >
              <span className="material-symbols-outlined">refresh</span>
            </button>
            <button
              onClick={handleCreate}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
            >
              <span className="material-symbols-outlined text-lg">add</span>
              Create
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin size="large" />
        </div>
      ) : servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <span className="material-symbols-outlined text-5xl text-slate-300 dark:text-slate-600 mb-4">
            dns
          </span>
          <p className="text-slate-500 dark:text-slate-400 mb-4">
            No MCP servers configured. Create your first server to get started.
          </p>
          <button
            onClick={handleCreate}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            Create Server
          </button>
        </div>
      ) : filteredServers.length === 0 ? (
        <Empty description="No servers match your filters." className="py-12" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
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
