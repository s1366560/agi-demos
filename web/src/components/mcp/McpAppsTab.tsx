/**
 * McpAppsTab - MCP Apps management tab.
 * Upgraded from MCPAppList with retry button for errors and loading timeout hints.
 */

import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';

import { message, Popconfirm, Tag, Tooltip, Input, Spin, Badge } from 'antd';
import {
  LayoutGrid,
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
  Sparkles,
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
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:shadow-md transition-shadow">
      <div className="p-4">
        {/* App Info - Compact */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
              isAgentDeveloped 
                ? 'bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400' 
                : 'bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400'
            }`}>
              {isAgentDeveloped ? <Sparkles size={16} /> : <LayoutGrid size={16} />}
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-slate-900 dark:text-white truncate">
                {title}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                {app.server_name}
              </p>
            </div>
          </div>
          <Tag 
            color={statusCfg.color} 
            className="text-xs flex-shrink-0 m-0"
            style={{ margin: 0 }}
          >
            {statusCfg.label}
          </Tag>
        </div>

        {/* Resource URI - Compact */}
        <div className="mb-3 p-2 bg-slate-50 dark:bg-slate-900/50 rounded border border-slate-100 dark:border-slate-800">
          <code className="text-xs text-slate-600 dark:text-slate-400 break-all font-mono">
            {app.ui_metadata?.resourceUri || 'No resource URI'}
          </code>
        </div>

        {/* Error message */}
        {app.error_message && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-950/20 rounded border border-red-100 dark:border-red-800/30">
            <p className="text-xs text-red-600 dark:text-red-400 line-clamp-2">{app.error_message}</p>
            <button
              type="button"
              onClick={() => onRetry(app.id)}
              disabled={retrying.has(app.id)}
              className="mt-1.5 flex items-center gap-1 px-2 py-1 text-xs rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 hover:bg-red-200 disabled:opacity-50 transition-colors"
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
          <div className="mb-3 p-2 bg-amber-50 dark:bg-amber-950/20 rounded border border-amber-100 dark:border-amber-800/30">
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Taking longer than expected. Try refreshing.
            </p>
          </div>
        )}

        {/* Actions - Compact */}
        <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-700/50">
          <div className="flex items-center gap-2">
            <Tooltip title={isAgentDeveloped ? 'Created by Agent' : 'Added by user'}>
              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${
                isAgentDeveloped 
                  ? 'text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20' 
                  : 'text-cyan-600 dark:text-cyan-400 bg-cyan-50 dark:bg-cyan-900/20'
              }`}>
                {isAgentDeveloped ? <Bot size={10} /> : <User size={10} />}
                {isAgentDeveloped ? 'Agent' : 'User'}
              </span>
            </Tooltip>
            {app.has_resource && app.resource_size_bytes && (
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {(app.resource_size_bytes / 1024).toFixed(1)} KB
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {app.status === 'ready' && (
              <button
                type="button"
                onClick={() => onOpenInCanvas(app)}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors"
              >
                <ExternalLink size={12} />
                Open
              </button>
            )}
            <Popconfirm
              title="Delete this MCP App?"
              onConfirm={() => onDelete(app.id)}
              okText="Delete"
              cancelText="Cancel"
            >
              <button
                type="button"
                disabled={deleting.has(app.id)}
                className="p-1.5 rounded text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-50"
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

  // Status counts
  const statusCounts = useMemo(() => {
    const counts: Record<MCPAppStatus, number> = {
      discovered: 0, loading: 0, ready: 0, error: 0, disabled: 0
    };
    Object.values(apps).forEach(app => {
      counts[app.status]++;
    });
    return counts;
  }, [apps]);

  return (
    <div className="space-y-5">
      {/* Header Stats */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
            <div className="w-8 h-8 rounded-lg bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center">
              <LayoutGrid size={16} className="text-violet-500" />
            </div>
            <span>
              <span className="font-semibold text-slate-900 dark:text-white">{appList.length}</span> apps
            </span>
          </div>
          {statusCounts.ready > 0 && (
            <Badge count={statusCounts.ready} color="green">
              <span className="text-xs text-slate-500 dark:text-slate-400 px-2 py-1 bg-green-50 dark:bg-green-900/20 rounded-full">Ready</span>
            </Badge>
          )}
          {statusCounts.error > 0 && (
            <Badge count={statusCounts.error} color="red">
              <span className="text-xs text-slate-500 dark:text-slate-400 px-2 py-1 bg-red-50 dark:bg-red-900/20 rounded-full">Errors</span>
            </Badge>
          )}
        </div>
        
        <div className="flex items-center gap-3">
          {Object.keys(apps).length > 5 && (
            <Input
              placeholder="Search apps..."
              prefix={<Search size={14} className="text-slate-400" />}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-48"
              allowClear
            />
          )}
          <button
            type="button"
            onClick={handleRefresh}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 hover:border-slate-400 transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </div>

      {/* Grid */}
      {appList.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 border-dashed">
          <LayoutGrid size={32} className="text-slate-300 dark:text-slate-500 mb-3" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No MCP Apps discovered yet
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
