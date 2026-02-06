/**
 * Agent Chat Hooks
 *
 * Custom hooks extracted from AgentChatContent for better separation of concerns.
 *
 * Features:
 * - useAgentChatPanelState: Manages panel and input resize state
 * - useAgentChatData: Handles data fetching and synchronization
 * - useAgentChatHandlers: Provides event handlers for user interactions
 */

import { useState, useEffect, useMemo, useCallback } from 'react';

// Constants for resize constraints
export const PANEL_MIN_WIDTH = 280;
export const PANEL_DEFAULT_WIDTH = 360;
export const PANEL_MAX_PERCENT = 0.9; // 90% of viewport width

export const INPUT_MIN_HEIGHT = 120;
export const INPUT_MAX_HEIGHT = 400;
export const INPUT_DEFAULT_HEIGHT = 160;

/**
 * Hook for managing panel and input resize state
 *
 * @returns Panel and input state with setters
 */
export function useAgentChatPanelState(initialShowPlanPanel = false) {
  const [panelCollapsed, setPanelCollapsed] = useState(!initialShowPlanPanel);
  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_WIDTH);
  const [inputHeight, setInputHeight] = useState(INPUT_DEFAULT_HEIGHT);

  // Calculate max width based on viewport (90%)
  const [maxPanelWidth, setMaxPanelWidth] = useState(
    typeof window !== 'undefined' ? window.innerWidth * PANEL_MAX_PERCENT : 1200
  );

  // Update max width on window resize
  useEffect(() => {
    const updateMaxWidth = () => {
      setMaxPanelWidth(window.innerWidth * PANEL_MAX_PERCENT);
    };

    updateMaxWidth();
    window.addEventListener('resize', updateMaxWidth);
    return () => window.removeEventListener('resize', updateMaxWidth);
  }, []);

  // Clamp panel width when max changes - use useMemo for derived state
  const clampedPanelWidth = useMemo(() => {
    return panelWidth > maxPanelWidth ? maxPanelWidth : panelWidth;
  }, [panelWidth, maxPanelWidth]);

  return {
    // State
    panelCollapsed,
    panelWidth,
    inputHeight,
    maxPanelWidth,
    clampedPanelWidth,
    // Setters
    setPanelCollapsed,
    setPanelWidth,
    setInputHeight,
    // Toggle helpers
    togglePanel: () => setPanelCollapsed((prev) => !prev),
  };
}

/**
 * Hook for handling chat event handlers
 *
 * @param options - Configuration options
 * @returns Event handlers for chat interactions
 */
export function useAgentChatHandlers(options: {
  projectId: string | undefined;
  conversationId: string | undefined;
  basePath: string;
  customBasePath: string | undefined;
  queryProjectId: string | null;
  navigate: (path: string) => void;
  togglePlanPanel: () => void;
  activeConversationId: string | null;
  planModeStatus: { current_plan_id?: string } | null;
  exitPlanMode: (conversationId: string, planId: string, approve: boolean) => Promise<void>;
  togglePlanMode: () => void;
  createNewConversation: (projectId: string) => Promise<string | undefined>;
  sendMessage: (
    content: string,
    projectId: string,
    handlers: { onAct: unknown; onObserve: unknown }
  ) => Promise<string | undefined>;
  onAct: unknown;
  onObserve: unknown;
  loadEarlierMessages?: (conversationId: string, projectId: string) => void;
}) {
  const {
    projectId,
    conversationId,
    basePath,
    customBasePath,
    queryProjectId,
    navigate,
    togglePlanPanel,
    activeConversationId,
    createNewConversation,
    sendMessage,
    onAct,
    onObserve,
    loadEarlierMessages,
  } = options;

  const handleNewConversation = useCallback(async () => {
    if (!projectId) return;
    const newId = await createNewConversation(projectId);
    if (newId) {
      const queryString = queryProjectId ? `?projectId=${queryProjectId}` : '';
      navigate(`${basePath}/${newId}${queryString}`);
    }
  }, [projectId, createNewConversation, navigate, basePath, customBasePath, queryProjectId]);

  const handleSend = useCallback(
    async (content: string) => {
      if (!projectId) return;
      // Note: Sandbox auto-creation removed - backend should handle sandbox provisioning
      const newId = await sendMessage(content, projectId, { onAct, onObserve });
      if (!conversationId && newId) {
        const queryString = queryProjectId ? `?projectId=${queryProjectId}` : '';
        navigate(`${basePath}/${newId}${queryString}`);
      }
    },
    [
      projectId,
      conversationId,
      sendMessage,
      onAct,
      onObserve,
      navigate,
      basePath,
      customBasePath,
      queryProjectId,
    ]
  );

  const handleViewPlan = useCallback(() => {
    togglePlanPanel();
  }, [togglePlanPanel]);

  const handleLoadEarlier = useCallback(() => {
    if (activeConversationId && projectId && loadEarlierMessages) {
      loadEarlierMessages(activeConversationId, projectId);
    }
  }, [activeConversationId, projectId, loadEarlierMessages]);

  const handlePanelClose = useCallback(
    (setPanelCollapsed: (value: boolean | ((prev: boolean) => boolean)) => void) => {
      setPanelCollapsed(true);
      togglePlanPanel();
    },
    [togglePlanPanel]
  );

  return {
    handleNewConversation,
    handleSend,
    handleViewPlan,
    handleLoadEarlier,
    handlePanelClose,
  };
}
