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

interface MCPAppState {
  /** Registered MCP Apps indexed by ID */
  apps: Record<string, MCPApp>;
  /** Cached HTML resources indexed by app ID */
  resources: Record<string, MCPAppResource>;
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
  proxyToolCall: (
    appId: string,
    toolName: string,
    args: Record<string, unknown>,
  ) => Promise<MCPAppToolCallResponse>;
  reset: () => void;
}

export const useMCPAppStore = create<MCPAppState>()(
  devtools(
    (set, get) => ({
      apps: {},
      resources: {},
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
          set({ apps, loading: false });
        } catch (err) {
          set({ error: getErrorMessage(err), loading: false });
        }
      },

      addApp: (app: MCPApp) => {
        set((state) => {
          // Clear cached resource so re-registration picks up new HTML
          const { [app.id]: _, ...restResources } = state.resources;
          return {
            apps: { ...state.apps, [app.id]: app },
            resources: restResources,
          };
        });
      },

      removeApp: (appId: string) => {
        set((state) => {
          const { [appId]: _, ...rest } = state.apps;
          const { [appId]: __, ...restResources } = state.resources;
          return { apps: rest, resources: restResources };
        });
      },

      loadResource: async (appId: string, bustCache = false) => {
        // Check cache first (unless bust requested)
        if (!bustCache) {
          const cached = get().resources[appId];
          if (cached) return cached;
        }

        try {
          const resource = await mcpAppAPI.getResource(appId);
          set((state) => ({
            resources: { ...state.resources, [appId]: resource },
          }));
          return resource;
        } catch {
          return null;
        }
      },

      invalidateResource: (appId: string) => {
        set((state) => {
          const { [appId]: _, ...rest } = state.resources;
          return { resources: rest };
        });
      },

      proxyToolCall: async (
        appId: string,
        toolName: string,
        args: Record<string, unknown>,
      ) => {
        return await mcpAppAPI.proxyToolCall(appId, {
          tool_name: toolName,
          arguments: args,
        });
      },

      reset: () => set({ apps: {}, resources: {}, loading: false, error: null }),
    }),
    { name: 'mcp-app-store' },
  ),
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
      proxyToolCall: s.proxyToolCall,
      reset: s.reset,
    })),
  );
