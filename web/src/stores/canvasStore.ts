/**
 * Canvas Store - State management for canvas/artifact editing panel
 *
 * Manages open artifacts, active tab, content versions, and editor state.
 * Used alongside the canvas layout mode for side-by-side editing.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

export type CanvasContentType = 'code' | 'markdown' | 'preview' | 'data' | 'mcp-app';

export interface CanvasTab {
  id: string;
  title: string;
  type: CanvasContentType;
  content: string;
  language?: string;
  dirty: boolean;
  createdAt: number;
  history: string[];
  historyIndex: number;
  /** Links this canvas tab to a stored artifact for download/save */
  artifactId?: string;
  /** Presigned URL for downloading the original artifact */
  artifactUrl?: string;
  /** MCP App ID (when type is 'mcp-app') */
  mcpAppId?: string;
  /** MCP App HTML content (when type is 'mcp-app') */
  mcpAppHtml?: string;
  /** MCP App initial tool result (when type is 'mcp-app') */
  mcpAppToolResult?: unknown;
  /** MCP App tool input arguments (when type is 'mcp-app') */
  mcpAppToolInput?: Record<string, unknown>;
  /** MCP App UI metadata (when type is 'mcp-app') */
  mcpAppUiMetadata?: Record<string, unknown>;
  /** MCP resource URI (stable identifier for MCP Apps standard) */
  mcpResourceUri?: string;
  /** MCP tool name (for AppRenderer) */
  mcpToolName?: string;
  /** Project ID (for backend proxy calls) */
  mcpProjectId?: string;
  /** MCP server name (for proxy routing) */
  mcpServerName?: string;
}

const MAX_HISTORY = 50;

interface CanvasState {
  tabs: CanvasTab[];
  activeTabId: string | null;

  openTab: (tab: Omit<CanvasTab, 'dirty' | 'createdAt' | 'history' | 'historyIndex'>) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  updateTab: (id: string, updates: Partial<CanvasTab>) => void;
  updateContent: (id: string, content: string) => void;
  undo: (tabId: string) => void;
  redo: (tabId: string) => void;
  canUndo: (tabId: string) => boolean;
  canRedo: (tabId: string) => boolean;
  reset: () => void;
}

export const useCanvasStore = create<CanvasState>()(
  devtools(
    (set, get) => ({
      tabs: [],
      activeTabId: null,

      openTab: (tab) =>
        set((state) => {
          const existing = state.tabs.find((t) => t.id === tab.id);
          if (existing) {
            // Merge new data into existing tab (preserves history/dirty state)
            return {
              tabs: state.tabs.map((t) => (t.id === tab.id ? { ...t, ...tab, dirty: t.dirty } : t)),
              activeTabId: tab.id,
            };
          }
          const newTab: CanvasTab = {
            ...tab,
            dirty: false,
            createdAt: Date.now(),
            history: [],
            historyIndex: -1,
          };
          return {
            tabs: [...state.tabs, newTab],
            activeTabId: newTab.id,
          };
        }),

      closeTab: (id) =>
        set((state) => {
          const filtered = state.tabs.filter((t) => t.id !== id);
          const nextActive =
            state.activeTabId === id
              ? filtered.length > 0
                ? (filtered[filtered.length - 1]?.id ?? null)
                : null
              : state.activeTabId;
          return { tabs: filtered, activeTabId: nextActive };
        }),

      setActiveTab: (id) => set({ activeTabId: id }),

      updateTab: (id, updates) =>
        set((state) => ({
          tabs: state.tabs.map((t) => (t.id === id ? { ...t, ...updates } : t)),
        })),

      updateContent: (id, content) =>
        set((state) => ({
          tabs: state.tabs.map((t) => {
            if (t.id !== id) return t;
            // Push previous content to history, truncate any forward history
            const newHistory = [...t.history.slice(0, t.historyIndex + 1), t.content].slice(
              -MAX_HISTORY
            );
            return {
              ...t,
              content,
              dirty: true,
              history: newHistory,
              historyIndex: newHistory.length - 1,
            };
          }),
        })),

      undo: (tabId) =>
        set((state) => ({
          tabs: state.tabs.map((t) => {
            if (t.id !== tabId || t.historyIndex < 0) return t;
            const restoredContent = t.history[t.historyIndex] ?? '';
            // Save current content at the end if we're at the latest position
            const newHistory =
              t.historyIndex === t.history.length - 1 ? [...t.history, t.content] : t.history;
            return {
              ...t,
              content: restoredContent,
              historyIndex: t.historyIndex - 1,
              history: newHistory,
            };
          }),
        })),

      redo: (tabId) =>
        set((state) => ({
          tabs: state.tabs.map((t) => {
            if (t.id !== tabId) return t;
            const nextIndex = t.historyIndex + 2;
            if (nextIndex >= t.history.length) return t;
            return {
              ...t,
              content: t.history[nextIndex] ?? '',
              historyIndex: t.historyIndex + 1,
            };
          }),
        })),

      canUndo: (tabId) => {
        const tab = get().tabs.find((t) => t.id === tabId);
        return tab ? tab.historyIndex >= 0 : false;
      },

      canRedo: (tabId) => {
        const tab = get().tabs.find((t) => t.id === tabId);
        return tab ? tab.historyIndex + 2 < tab.history.length : false;
      },

      reset: () => set({ tabs: [], activeTabId: null }),
    }),
    { name: 'canvas-store' }
  )
);

// Selectors
export const useCanvasTabs = () => useCanvasStore(useShallow((s) => s.tabs));
export const useActiveCanvasTab = () =>
  useCanvasStore(useShallow((s) => s.tabs.find((t) => t.id === s.activeTabId) ?? null));
export const useCanvasActions = () =>
  useCanvasStore(
    useShallow((s) => ({
      openTab: s.openTab,
      closeTab: s.closeTab,
      setActiveTab: s.setActiveTab,
      updateTab: s.updateTab,
      updateContent: s.updateContent,
      undo: s.undo,
      redo: s.redo,
      canUndo: s.canUndo,
      canRedo: s.canRedo,
      reset: s.reset,
    }))
  );
