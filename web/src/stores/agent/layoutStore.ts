/**
 * Agent Layout Store - Extracted from agentV3.ts (Wave 1)
 *
 * Manages UI layout preferences for the agent workspace:
 * - showPlanPanel: Toggle plan panel visibility
 * - showHistorySidebar: Toggle conversation history sidebar
 * - leftSidebarWidth: Width of left sidebar in pixels
 * - rightPanelWidth: Width of right panel in pixels
 *
 * Persists to localStorage under key 'agent-layout-storage'.
 * Previously these fields lived in agentV3.ts under 'agent-v3-storage'.
 *
 * @module stores/agent/layoutStore
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

// -- State --

interface AgentLayoutState {
  showPlanPanel: boolean;
  showHistorySidebar: boolean;
  leftSidebarWidth: number;
  rightPanelWidth: number;

  togglePlanPanel: () => void;
  toggleHistorySidebar: () => void;
  setLeftSidebarWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
}

// -- Store --

export const useAgentLayoutStore = create<AgentLayoutState>()(
  devtools(
    persist(
      (set) => ({
        showPlanPanel: false,
        showHistorySidebar: false,
        leftSidebarWidth: 280,
        rightPanelWidth: 400,

        togglePlanPanel: () => set((state) => ({ showPlanPanel: !state.showPlanPanel })),
        toggleHistorySidebar: () =>
          set((state) => ({ showHistorySidebar: !state.showHistorySidebar })),

        setLeftSidebarWidth: (width: number) => set({ leftSidebarWidth: width }),
        setRightPanelWidth: (width: number) => set({ rightPanelWidth: width }),
      }),
      {
        name: 'agent-layout-storage',
        partialize: (state) => ({
          showHistorySidebar: state.showHistorySidebar,
          leftSidebarWidth: state.leftSidebarWidth,
          rightPanelWidth: state.rightPanelWidth,
        }),
      }
    ),
    { name: 'agent-layout-store' }
  )
);

// -- Selectors (single-value, no useShallow needed) --

export const useShowPlanPanel = () => useAgentLayoutStore((state) => state.showPlanPanel);
export const useShowHistorySidebar = () => useAgentLayoutStore((state) => state.showHistorySidebar);
export const useLeftSidebarWidth = () => useAgentLayoutStore((state) => state.leftSidebarWidth);
export const useRightPanelWidth = () => useAgentLayoutStore((state) => state.rightPanelWidth);
