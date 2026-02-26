/**
 * AppLauncher - Quick access dropdown for registered MCP Apps
 *
 * Shows a popover with all registered MCP apps for the current project.
 * Allows users to quickly open any app in the canvas without navigating
 * to the MCP management tab.
 *
 * Pinned apps appear at the top of the list for quick access.
 */

import { useCallback, useEffect, useMemo, useState, type FC } from 'react';

import { Badge, Empty, Input, Popover, Spin } from 'antd';
import { AppWindow, ExternalLink, Pin, RefreshCw, Search } from 'lucide-react';

import { useCanvasStore, usePinnedCanvasTabs } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';
import { useProjectStore } from '@/stores/project';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { MCPApp } from '@/types/mcpApp';

export const AppLauncher: FC = () => {
  const apps = useMCPAppStore((s) => s.apps);
  const loading = useMCPAppStore((s) => s.loading);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);
  const currentProject = useProjectStore((s) => s.currentProject);
  const pinnedTabs = usePinnedCanvasTabs();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  // Fetch apps when popover opens (if not already loaded)
  useEffect(() => {
    if (open && currentProject?.id) {
      fetchApps(currentProject.id);
    }
  }, [open, currentProject?.id, fetchApps]);

  const appList = useMemo(() => {
    const list = Object.values(apps).filter((app) => app.status === 'ready');
    if (!search) return list;
    const q = search.toLowerCase();
    return list.filter(
      (app) =>
        app.tool_name.toLowerCase().includes(q) ||
        app.server_name.toLowerCase().includes(q) ||
        (app.ui_metadata?.title || '').toLowerCase().includes(q)
    );
  }, [apps, search]);

  // Separate pinned apps from the rest
  const pinnedAppIds = useMemo(
    () => new Set(pinnedTabs.filter((t) => t.mcpAppId).map((t) => t.mcpAppId)),
    [pinnedTabs]
  );

  const { pinnedApps, unpinnedApps } = useMemo(() => {
    const pinned: MCPApp[] = [];
    const unpinned: MCPApp[] = [];
    for (const app of appList) {
      if (pinnedAppIds.has(app.id)) {
        pinned.push(app);
      } else {
        unpinned.push(app);
      }
    }
    return { pinnedApps: pinned, unpinnedApps: unpinned };
  }, [appList, pinnedAppIds]);

  const handleOpenApp = useCallback(
    (app: MCPApp) => {
      const tabId = `mcp-app-${app.id}`;
      useCanvasStore.getState().openTab({
        id: tabId,
        title: app.ui_metadata?.title || app.tool_name,
        type: 'mcp-app' as const,
        content: '',
        mcpAppId: app.id,
        mcpResourceUri: app.ui_metadata?.resourceUri,
        mcpServerName: app.server_name,
        mcpProjectId: currentProject?.id,
        mcpToolName: app.tool_name,
        mcpAppUiMetadata: app.ui_metadata as unknown as Record<string, unknown>,
      });
      useLayoutModeStore.getState().setMode('canvas');
      setOpen(false);
    },
    [currentProject?.id]
  );

  const handleTogglePin = useCallback(
    (app: MCPApp) => {
      const tabId = `mcp-app-${app.id}`;
      const store = useCanvasStore.getState();
      const existing = store.tabs.find((t) => t.id === tabId);
      if (existing) {
        store.togglePin(tabId);
      } else {
        // Create the tab first (not activated), then pin it
        store.openTab({
          id: tabId,
          title: app.ui_metadata?.title || app.tool_name,
          type: 'mcp-app' as const,
          content: '',
          mcpAppId: app.id,
          mcpResourceUri: app.ui_metadata?.resourceUri,
          mcpServerName: app.server_name,
          mcpProjectId: currentProject?.id,
          mcpToolName: app.tool_name,
          mcpAppUiMetadata: app.ui_metadata as unknown as Record<string, unknown>,
        });
        store.togglePin(tabId);
      }
    },
    [currentProject?.id]
  );

  const handleRefresh = useCallback(() => {
    if (currentProject?.id) {
      void fetchApps(currentProject.id);
    }
  }, [currentProject, fetchApps]);

  const totalReady = Object.values(apps).filter((a) => a.status === 'ready').length;

  const content = (
    <div className="w-80 max-h-96 overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1">
        <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
          MCP Apps
        </span>
        <button
          type="button"
          onClick={handleRefresh}
          className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title="Refresh apps"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Search */}
      {totalReady > 5 && (
        <div className="px-3 pb-2">
          <Input
            placeholder="Search apps..."
            prefix={<Search size={12} className="text-slate-400" />}
            value={search}
            onChange={(e) => { setSearch(e.target.value); }}
            size="small"
            allowClear
          />
        </div>
      )}

      {/* App List */}
      <div className="overflow-y-auto flex-1 px-1 pb-2">
        {loading && appList.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Spin size="small" />
          </div>
        ) : appList.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span className="text-xs text-slate-400">
                {search ? 'No apps match your search' : 'No MCP apps available'}
              </span>
            }
          />
        ) : (
          <>
            {/* Pinned Section */}
            {pinnedApps.length > 0 && (
              <>
                <div className="px-2 py-1">
                  <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                    Pinned
                  </span>
                </div>
                {pinnedApps.map((app) => (
                  <AppLauncherItem
                    key={app.id}
                    app={app}
                    pinned
                    onOpen={handleOpenApp}
                    onTogglePin={handleTogglePin}
                  />
                ))}
                {unpinnedApps.length > 0 && (
                  <div className="border-t border-slate-100 dark:border-slate-700 my-1 mx-2" />
                )}
              </>
            )}

            {/* All Apps */}
            {unpinnedApps.map((app) => (
              <AppLauncherItem
                key={app.id}
                app={app}
                pinned={false}
                onOpen={handleOpenApp}
                onTogglePin={handleTogglePin}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
      overlayClassName="app-launcher-popover"
    >
      <LazyTooltip title="Open MCP Apps">
        <button
          type="button"
          className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400 relative"
        >
          <AppWindow className="w-5 h-5" />
          {totalReady > 0 && (
            <Badge
              count={totalReady}
              size="small"
              offset={[0, 0]}
              className="absolute -top-1 -right-1"
            />
          )}
        </button>
      </LazyTooltip>
    </Popover>
  );
};

/** Individual app item in the launcher dropdown */
const AppLauncherItem: FC<{
  app: MCPApp;
  pinned: boolean;
  onOpen: (app: MCPApp) => void;
  onTogglePin: (app: MCPApp) => void;
}> = ({ app, pinned, onOpen, onTogglePin }) => {
  const title = app.ui_metadata?.title || app.tool_name;

  return (
    <div className="group flex items-center gap-2 px-2 py-1.5 mx-1 rounded-md hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
      {/* App icon */}
      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-50 to-purple-50 dark:from-violet-900/20 dark:to-purple-900/20 flex items-center justify-center flex-shrink-0">
        <AppWindow size={14} className="text-violet-500 dark:text-violet-400" />
      </div>

      {/* App info - clickable to open */}
      <button
        type="button"
        onClick={() => { onOpen(app); }}
        className="flex-1 min-w-0 text-left"
      >
        <div className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
          {title}
        </div>
        <div className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
          {app.server_name}
        </div>
      </button>

      {/* Actions */}
      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onTogglePin(app); }}
          className={`p-1 rounded transition-colors ${
            pinned
              ? 'text-primary bg-primary/10'
              : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700'
          }`}
          title={pinned ? 'Unpin app' : 'Pin app'}
        >
          <Pin size={12} className={pinned ? 'fill-current' : ''} />
        </button>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onOpen(app); }}
          className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          title="Open in canvas"
        >
          <ExternalLink size={12} />
        </button>
      </div>
    </div>
  );
};

AppLauncher.displayName = 'AppLauncher';
