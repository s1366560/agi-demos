/**
 * MCP App Store - State management for MCP Apps
 *
 * Manages registered MCP Apps, their resources, and active app instances.
 * Integrates with the Canvas store for rendering apps in the right panel.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { mcpAppAPI } from '@/services/mcpAppService';

import { getErrorMessage } from '@/types/common';
import type { MCPApp, MCPAppResource, MCPAppToolCallResponse } from '@/types/mcpApp';

const RESOURCE_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const HTML_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const MAX_HTML_CACHE_ENTRIES = 200;

interface MCPAppState {
  /** Registered MCP Apps indexed by ID */
  apps: Record<string, MCPApp>;
  /** Cached HTML resources indexed by app ID */
  resources: Record<string, MCPAppResource>;
  /** Timestamps when resources were cached (for TTL expiry) */
  resourceCachedAt: Record<string, number>;
  /** Cached HTML content by resource URI (for timeline "Open App" lookup) */
  htmlByUri: Record<string, { html: string; cachedAt: number }>;
  /** Loading state */
  loading: boolean;
  /** Error message */
  error: string | null;

  // Actions
  fetchApps: (projectId?: string) => Promise<void>;
  addApp: (app: MCPApp) => void;
  removeApp: (appId: string) => void;
  loadResource: (appId: string, bustCache?: boolean) => Promise<MCPAppResource | null>;
  invalidateResource: (appId: string) => void;
  /** Cache HTML content by resource URI for later lookup */
  cacheHtmlByUri: (uri: string, html: string) => void;
  /** Get cached HTML content by resource URI */
  getHtmlByUri: (uri: string) => string | null;
  proxyToolCall: (
    appId: string,
    toolName: string,
    args: Record<string, unknown>
  ) => Promise<MCPAppToolCallResponse>;
  reset: () => void;
}

export const useMCPAppStore = create<MCPAppState>()(
  devtools(
    (set, get) => ({
      apps: {},
      resources: {},
      resourceCachedAt: {},
      htmlByUri: {},
      loading: false,
      error: null,

      fetchApps: async (projectId?: string) => {
        set({ loading: true, error: null });
        try {
          const appsList = await mcpAppAPI.list(projectId);
          const apps: Record<string, MCPApp> = {};
          for (const app of appsList) {
            apps[app.id] = app;
          }
          // Prune stale resources/cache entries for apps no longer in backend
          const prev = get();
          const resources = { ...prev.resources };
          const resourceCachedAt = { ...prev.resourceCachedAt };
          for (const id of Object.keys(resources)) {
            if (!apps[id]) {
              delete resources[id];
              delete resourceCachedAt[id];
            }
          }
          set({ apps, resources, resourceCachedAt, loading: false });
        } catch (err) {
          set({ error: getErrorMessage(err), loading: false });
        }
      },

      addApp: (app: MCPApp) => {
        set((state) => {
          // Clear cached resource so re-registration picks up new HTML
          const { [app.id]: _, ...restResources } = state.resources;
          const { [app.id]: __, ...restCachedAt } = state.resourceCachedAt;
          return {
            apps: { ...state.apps, [app.id]: app },
            resources: restResources,
            resourceCachedAt: restCachedAt,
          };
        });
      },

      removeApp: (appId: string) => {
        set((state) => {
          const { [appId]: _, ...rest } = state.apps;
          const { [appId]: __, ...restResources } = state.resources;
          const { [appId]: ___, ...restCachedAt } = state.resourceCachedAt;
          return { apps: rest, resources: restResources, resourceCachedAt: restCachedAt };
        });
      },

      loadResource: async (appId: string, bustCache = false) => {
        // Check cache first (unless bust requested or TTL expired)
        if (!bustCache) {
          const cached = get().resources[appId];
          const cachedAt = get().resourceCachedAt[appId];
          if (cached && cachedAt && Date.now() - cachedAt < RESOURCE_CACHE_TTL_MS) {
            return cached;
          }
        }

        try {
          const resource = await mcpAppAPI.getResource(appId);
          set((state) => ({
            resources: { ...state.resources, [appId]: resource },
            resourceCachedAt: { ...state.resourceCachedAt, [appId]: Date.now() },
            error: null,
          }));
          return resource;
        } catch (err) {
          set({ error: getErrorMessage(err) });
          return null;
        }
      },

      invalidateResource: (appId: string) => {
        set((state) => {
          const { [appId]: _, ...rest } = state.resources;
          const { [appId]: __, ...restCachedAt } = state.resourceCachedAt;
          return { resources: rest, resourceCachedAt: restCachedAt };
        });
      },

      cacheHtmlByUri: (uri: string, html: string) => {
        if (!uri || !html) return;
        const now = Date.now();
        set((state) => {
          const nextHtmlByUri = { ...state.htmlByUri };
          for (const [key, value] of Object.entries(nextHtmlByUri)) {
            if (now - value.cachedAt >= HTML_CACHE_TTL_MS) {
              delete nextHtmlByUri[key];
            }
          }

          nextHtmlByUri[uri] = { html, cachedAt: now };

          const keys = Object.keys(nextHtmlByUri);
          if (keys.length > MAX_HTML_CACHE_ENTRIES) {
            keys
              .sort((a, b) => (nextHtmlByUri[a]?.cachedAt ?? 0) - (nextHtmlByUri[b]?.cachedAt ?? 0))
              .slice(0, keys.length - MAX_HTML_CACHE_ENTRIES)
              .forEach((key) => {
                delete nextHtmlByUri[key];
              });
          }

          return { htmlByUri: nextHtmlByUri };
        });
      },

      getHtmlByUri: (uri: string) => {
        if (!uri) return null;
        const entry = get().htmlByUri[uri];
        const now = Date.now();
        if (entry && now - entry.cachedAt < HTML_CACHE_TTL_MS) {
          return entry.html;
        }
        if (entry && now - entry.cachedAt >= HTML_CACHE_TTL_MS) {
          set((state) => {
            const { [uri]: _, ...rest } = state.htmlByUri;
            return { htmlByUri: rest };
          });
        }
        return null;
      },

      proxyToolCall: async (appId: string, toolName: string, args: Record<string, unknown>) => {
        return await mcpAppAPI.proxyToolCall(appId, {
          tool_name: toolName,
          arguments: args,
        });
      },

      reset: () =>
        set({
          apps: {},
          resources: {},
          resourceCachedAt: {},
          htmlByUri: {},
          loading: false,
          error: null,
        }),
    }),
    { name: 'mcp-app-store' }
  )
);

// Selectors
export const useMCPApps = () => useMCPAppStore((s) => s.apps);
export const useMCPAppLoading = () => useMCPAppStore((s) => s.loading);
export const useMCPAppActions = () =>
  useMCPAppStore(
    useShallow((s) => ({
      fetchApps: s.fetchApps,
      addApp: s.addApp,
      removeApp: s.removeApp,
      loadResource: s.loadResource,
      cacheHtmlByUri: s.cacheHtmlByUri,
      getHtmlByUri: s.getHtmlByUri,
      proxyToolCall: s.proxyToolCall,
      reset: s.reset,
    }))
  );
