/**
 * MCPAppList - MCP Apps listing section for the MCP management page.
 *
 * Shows all registered MCP Apps (both user-added and agent-developed)
 * with status badges, source indicators, and actions.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { message, Empty, Spin, Popconfirm, Tag, Tooltip, Input } from 'antd';
import {
  AppWindow,
  Trash2,
  RefreshCw,
  ExternalLink,
  Bot,
  User,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Ban,
  Search,
} from 'lucide-react';

import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';
import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { mcpAppAPI } from '@/services/mcpAppService';

import type { MCPApp, MCPAppStatus } from '@/types/mcpApp';

// Status configuration
const STATUS_CONFIG: Record<
  MCPAppStatus,
  { color: string; icon: React.ReactNode; label: string }
> = {
  discovered: {
    color: 'blue',
    icon: <Search size={12} />,
    label: 'Discovered',
  },
  loading: {
    color: 'processing',
    icon: <Loader2 size={12} className="animate-spin" />,
    label: 'Loading',
  },
  ready: {
    color: 'success',
    icon: <CheckCircle2 size={12} />,
    label: 'Ready',
  },
  error: {
    color: 'error',
    icon: <AlertCircle size={12} />,
    label: 'Error',
  },
  disabled: {
    color: 'default',
    icon: <Ban size={12} />,
    label: 'Disabled',
  },
};

interface MCPAppCardProps {
  app: MCPApp;
  onDelete: (appId: string) => void;
  onOpenInCanvas: (app: MCPApp) => void;
  deleting: Set<string>;
}

const MCPAppCard: React.FC<MCPAppCardProps> = ({ app, onDelete, onOpenInCanvas, deleting }) => {
  const statusCfg = STATUS_CONFIG[app.status];
  const isAgentDeveloped = app.source === 'agent_developed';
  const title = app.ui_metadata?.title || app.tool_name;

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center flex-shrink-0">
            <AppWindow size={16} className="text-violet-600 dark:text-violet-400" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
              {title}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
              {app.server_name} / {app.tool_name}
            </p>
          </div>
        </div>
        <Tag
          color={statusCfg.color}
          className="flex items-center gap-1 text-xs flex-shrink-0"
        >
          {statusCfg.icon}
          {statusCfg.label}
        </Tag>
      </div>

      {/* Source badge */}
      <div className="flex items-center gap-2 mb-3">
        <Tooltip title={isAgentDeveloped ? 'Created by Agent in sandbox' : 'Added by user'}>
          <Tag
            className="flex items-center gap-1 text-xs"
            color={isAgentDeveloped ? 'purple' : 'cyan'}
          >
            {isAgentDeveloped ? <Bot size={10} /> : <User size={10} />}
            {isAgentDeveloped ? 'Agent Developed' : 'User Added'}
          </Tag>
        </Tooltip>
        {app.has_resource && app.resource_size_bytes && (
          <span className="text-xs text-slate-400">
            {(app.resource_size_bytes / 1024).toFixed(1)} KB
          </span>
        )}
      </div>

      {/* Resource URI */}
      <div className="mb-3 p-2 bg-slate-50 dark:bg-slate-900/50 rounded-md">
        <code className="text-xs text-slate-600 dark:text-slate-400 break-all">
          {app.ui_metadata?.resourceUri || 'No resource URI'}
        </code>
      </div>

      {/* Error message */}
      {app.error_message && (
        <div className="mb-3 p-2 bg-red-50 dark:bg-red-950/20 rounded-md border border-red-200/60 dark:border-red-800/30">
          <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2">
            {app.error_message}
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-2 border-t border-slate-100 dark:border-slate-700">
        {app.status === 'ready' && (
          <button
            type="button"
            onClick={() => onOpenInCanvas(app)}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-violet-50 dark:bg-violet-950/30 text-violet-600 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-900/40 transition-colors"
          >
            <ExternalLink size={12} />
            Open in Canvas
          </button>
        )}
        <div className="flex-1" />
        <Popconfirm
          title="Delete this MCP App?"
          onConfirm={() => onDelete(app.id)}
          okText="Delete"
          cancelText="Cancel"
        >
          <button
            type="button"
            disabled={deleting.has(app.id)}
            className="p-1.5 rounded-md text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 transition-colors disabled:opacity-50"
          >
            {deleting.has(app.id) ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Trash2 size={14} />
            )}
          </button>
        </Popconfirm>
      </div>
    </div>
  );
};

export const MCPAppList: React.FC = () => {
  const apps = useMCPAppStore((s) => s.apps);
  const loading = useMCPAppStore((s) => s.loading);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);
  const removeApp = useMCPAppStore((s) => s.removeApp);
  const currentProject = useProjectStore((s) => s.currentProject);

  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<Set<string>>(new Set());

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
        (app.ui_metadata?.title || '').toLowerCase().includes(q),
    );
  }, [apps, search]);

  const handleDelete = useCallback(
    async (appId: string) => {
      setDeleting((prev) => new Set(prev).add(appId));
      try {
        await mcpAppAPI.delete(appId);
        removeApp(appId);
        message.success('MCP App deleted');
      } catch {
        message.error('Failed to delete MCP App');
      } finally {
        setDeleting((prev) => {
          const next = new Set(prev);
          next.delete(appId);
          return next;
        });
      }
    },
    [removeApp],
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
    if (currentProject?.id) {
      fetchApps(currentProject.id);
    }
  }, [currentProject?.id, fetchApps]);

  if (loading && Object.keys(apps).length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin tip="Loading MCP Apps..." />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppWindow size={18} className="text-violet-500" />
          <h3 className="text-base font-medium text-slate-800 dark:text-slate-200">
            MCP Apps
          </h3>
          <Tag className="text-xs">{appList.length}</Tag>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded-md text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Search */}
      {Object.keys(apps).length > 3 && (
        <Input
          placeholder="Search apps..."
          prefix={<Search size={14} className="text-slate-400" />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          allowClear
        />
      )}

      {/* Grid */}
      {appList.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span className="text-slate-400 text-sm">
              {Object.keys(apps).length === 0
                ? 'No MCP Apps discovered yet. Apps are auto-detected when MCP tools declare UI resources.'
                : 'No apps match your search.'}
            </span>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {appList.map((app) => (
            <MCPAppCard
              key={app.id}
              app={app}
              onDelete={handleDelete}
              onOpenInCanvas={handleOpenInCanvas}
              deleting={deleting}
            />
          ))}
        </div>
      )}
    </div>
  );
};
