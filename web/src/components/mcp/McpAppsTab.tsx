/**
 * McpAppsTab - MCP Apps management tab.
 * Upgraded from MCPAppList with retry button for errors and loading timeout hints.
 */

import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';

import { message, Popconfirm, Tag, Tooltip, Input, Spin } from 'antd';
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
  RotateCcw,
} from 'lucide-react';

import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { mcpAppAPI } from '@/services/mcpAppService';

import type { MCPApp, MCPAppStatus } from '@/types/mcpApp';

const LOADING_TIMEOUT_MS = 30_000;

const STATUS_CONFIG: Record<MCPAppStatus, { color: string; icon: React.ReactNode; label: string }> =
  {
    discovered: { color: 'blue', icon: <Search size={12} />, label: 'Discovered' },
    loading: {
      color: 'processing',
      icon: <Loader2 size={12} className="animate-spin" />,
      label: 'Loading',
    },
    ready: { color: 'success', icon: <CheckCircle2 size={12} />, label: 'Ready' },
    error: { color: 'error', icon: <AlertCircle size={12} />, label: 'Error' },
    disabled: { color: 'default', icon: <Ban size={12} />, label: 'Disabled' },
  };

// ============================================================================
// App Card
// ============================================================================

interface McpAppCardProps {
  app: MCPApp;
  onDelete: (appId: string) => void;
  onRetry: (appId: string) => void;
  onOpenInCanvas: (app: MCPApp) => void;
  deleting: Set<string>;
  retrying: Set<string>;
}

const McpAppCard: React.FC<McpAppCardProps> = ({
  app,
  onDelete,
  onRetry,
  onOpenInCanvas,
  deleting,
  retrying,
}) => {
  const statusCfg = STATUS_CONFIG[app.status];
  const isAgentDeveloped = app.source === 'agent_developed';
  const title = app.ui_metadata?.title || app.tool_name;

  const [loadingTimeout, setLoadingTimeout] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (app.status === 'loading') {
      timeoutRef.current = setTimeout(() => setLoadingTimeout(true), LOADING_TIMEOUT_MS);
    } else {
      setLoadingTimeout(false);
    }
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [app.status]);
  /* eslint-enable react-hooks/set-state-in-effect */

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
        <Tag color={statusCfg.color} className="flex items-center gap-1 text-xs flex-shrink-0">
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

      {/* Error message with retry */}
      {app.error_message && (
        <div className="mb-3 p-2 bg-red-50 dark:bg-red-950/20 rounded-md border border-red-200/60 dark:border-red-800/30">
          <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2">{app.error_message}</p>
          <button
            type="button"
            onClick={() => onRetry(app.id)}
            disabled={retrying.has(app.id)}
            className="mt-1.5 flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50 transition-colors"
          >
            {retrying.has(app.id) ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <RotateCcw size={10} />
            )}
            Retry
          </button>
        </div>
      )}

      {/* Loading timeout hint */}
      {app.status === 'loading' && loadingTimeout && (
        <div className="mb-3 p-2 bg-yellow-50 dark:bg-yellow-950/20 rounded-md border border-yellow-200/60 dark:border-yellow-800/30">
          <p className="text-xs text-yellow-700 dark:text-yellow-300">
            Taking longer than expected. Try refreshing the list.
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

// ============================================================================
// Apps Tab
// ============================================================================

export const McpAppsTab: React.FC = () => {
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
    [removeApp]
  );

  const handleRetry = useCallback(
    async (appId: string) => {
      setRetrying((prev) => new Set(prev).add(appId));
      try {
        await mcpAppAPI.refresh(appId);
        await fetchApps(currentProject?.id);
        message.success('App refreshed');
      } catch {
        message.error('Failed to retry');
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

  if (loading && Object.keys(apps).length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin tip="Loading MCP Apps..." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppWindow size={18} className="text-violet-500" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {appList.length} app{appList.length !== 1 ? 's' : ''}
          </span>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Search (when many apps) */}
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
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <span className="material-symbols-outlined text-5xl text-slate-300 dark:text-slate-600 mb-4">
            widgets
          </span>
          <p className="text-slate-500 dark:text-slate-400">
            {Object.keys(apps).length === 0
              ? 'No MCP Apps discovered yet. Apps are auto-detected when MCP tools declare UI resources.'
              : 'No apps match your search.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {appList.map((app) => (
            <McpAppCard
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
