/**
 * Layout Mode Store
 *
 * Manages the workspace layout mode for the agent chat page.
 * Four modes optimize for different workflows:
 * - chat: Full chat view, optional plan panel
 * - code: Split view with terminal (50/50)
 * - desktop: Split view with remote desktop (30/70)
 * - focus: Fullscreen desktop with floating chat bubble
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

export type LayoutMode = 'chat' | 'code' | 'desktop' | 'focus';

interface LayoutModeState {
  /** Current layout mode */
  mode: LayoutMode;
  /** Split ratio for code/desktop modes (0-1, represents left panel proportion) */
  splitRatio: number;
  /** Whether the right panel is visible in chat mode */
  chatPanelVisible: boolean;
  /** Active tab in right panel: plan, terminal, or desktop */
  rightPanelTab: 'plan' | 'terminal' | 'desktop';
  /** Whether floating chat is expanded in focus mode */
  focusChatExpanded: boolean;

  /** Set layout mode */
  setMode: (mode: LayoutMode) => void;
  /** Set split ratio */
  setSplitRatio: (ratio: number) => void;
  /** Toggle chat panel in chat mode */
  toggleChatPanel: () => void;
  /** Set right panel tab */
  setRightPanelTab: (tab: 'plan' | 'terminal' | 'desktop') => void;
  /** Toggle floating chat in focus mode */
  toggleFocusChat: () => void;
}

const MODE_DEFAULTS: Record<LayoutMode, { splitRatio: number; rightPanelTab: 'plan' | 'terminal' | 'desktop' }> = {
  chat: { splitRatio: 1, rightPanelTab: 'plan' },
  code: { splitRatio: 0.5, rightPanelTab: 'terminal' },
  desktop: { splitRatio: 0.3, rightPanelTab: 'desktop' },
  focus: { splitRatio: 0, rightPanelTab: 'desktop' },
};

export const useLayoutModeStore = create<LayoutModeState>()(
  devtools(
    persist(
      (set) => ({
        mode: 'chat',
        splitRatio: 1,
        chatPanelVisible: true,
        rightPanelTab: 'plan',
        focusChatExpanded: false,

        setMode: (mode) =>
          set({
            mode,
            splitRatio: MODE_DEFAULTS[mode].splitRatio,
            rightPanelTab: MODE_DEFAULTS[mode].rightPanelTab,
            focusChatExpanded: false,
          }),

        setSplitRatio: (ratio) =>
          set({ splitRatio: Math.max(0.15, Math.min(0.85, ratio)) }),

        toggleChatPanel: () =>
          set((state) => ({ chatPanelVisible: !state.chatPanelVisible })),

        setRightPanelTab: (tab) => set({ rightPanelTab: tab }),

        toggleFocusChat: () =>
          set((state) => ({ focusChatExpanded: !state.focusChatExpanded })),
      }),
      { name: 'layout-mode-store' }
    ),
    { name: 'layout-mode' }
  )
);
