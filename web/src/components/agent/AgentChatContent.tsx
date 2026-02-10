/**
 * AgentChatContent - Agent Chat content with multi-mode layout
 *
 * Supports four layout modes:
 * - chat: Full chat view with optional right panel (Plan/Terminal/Desktop tabs)
 * - code: Split view — chat (left) + terminal (right), resizable
 * - desktop: Split view — chat (left, compact) + remote desktop (right, wide)
 * - focus: Fullscreen desktop with floating chat bubble
 *
 * Features:
 * - Cmd+1/2/3/4 to switch modes
 * - Draggable split ratio in code/desktop modes
 * - Flat right panel tabs (Plan | Terminal | Desktop)
 */

import * as React from 'react';
import { useEffect, useCallback, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';

import { GripHorizontal } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { usePlanModeStore } from '@/stores/agent/planModeStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useProjectStore } from '@/stores/project';
import { useSandboxStore } from '@/stores/sandbox';

import type { FileMetadata } from '@/services/sandboxUploadService';

import { useSandboxAgentHandlers } from '@/hooks/useSandboxDetection';


import { useLazyNotification } from '@/components/ui/lazyAntd';

// Import design components
import { EmptyState } from './EmptyState';
import { FocusDesktopOverlay } from './layout/FocusDesktopOverlay';
import { LayoutModeSelector } from './layout/LayoutModeSelector';
import { Resizer } from './Resizer';
import { SandboxSection } from './SandboxSection';

import { MessageArea, InputBar, RightPanel, ProjectAgentStatusBar } from './index';

interface AgentChatContentProps {
  /** Optional className for styling */
  className?: string;
  /** External project ID (overrides URL param) */
  externalProjectId?: string;
  /** Base path for navigation (default: /project/{projectId}/agent) */
  basePath?: string;
  /** Extra content to show in header area */
  headerExtra?: React.ReactNode;
}

// Constants for resize constraints
const INPUT_MIN_HEIGHT = 140;
const INPUT_MAX_HEIGHT = 400;
const INPUT_DEFAULT_HEIGHT = 180;

// Right panel width constraints (chat mode only)
const PANEL_MIN_WIDTH = 280;
const PANEL_DEFAULT_WIDTH = 360;
const PANEL_MAX_WIDTH = 600;

export const AgentChatContent: React.FC<AgentChatContentProps> = ({
  className = '',
  externalProjectId,
  basePath: customBasePath,
  headerExtra,
}) => {
  const { t } = useTranslation();
  const notification = useLazyNotification();
  const { projectId: urlProjectId, conversation: conversationId } = useParams<{
    projectId: string;
    conversation?: string;
  }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // Use external project ID if provided, otherwise fall back to URL param
  const queryProjectId = searchParams.get('projectId');
  const projectId = externalProjectId || queryProjectId || urlProjectId;

  // Determine base path for navigation
  const basePath = useMemo(() => {
    if (customBasePath) return customBasePath;
    if (urlProjectId) return `/project/${urlProjectId}/agent`;
    return `/project/${projectId}/agent`;
  }, [customBasePath, urlProjectId, projectId]);

  // Store state - single useShallow selector to avoid infinite re-renders
  const {
    activeConversationId,
    timeline,
    isLoadingHistory,
    isLoadingEarlier,
    isStreaming,
    workPlan,
    executionPlan,
    isPlanMode,
    // HITL state now rendered inline in timeline via InlineHITLCard
    // pendingClarification, pendingDecision, pendingEnvVarRequest removed
    doomLoopDetected,
    hasEarlier,
    loadConversations,
    loadMessages,
    loadEarlierMessages,
    setActiveConversation,
    createNewConversation,
    sendMessage,
    abortStream,
    togglePlanMode,
    togglePlanPanel,
    // HITL response methods still available but not used directly
    // respondToClarification, respondToDecision, respondToEnvVar
    loadPendingHITL,
    clearError,
    error,
    streamingAssistantContent,
    streamingThought,
    isThinkingStreaming,
  } = useAgentV3Store(
    useShallow((state) => ({
      activeConversationId: state.activeConversationId,
      timeline: state.timeline,
      isLoadingHistory: state.isLoadingHistory,
      isLoadingEarlier: state.isLoadingEarlier,
      isStreaming: state.isStreaming,
      workPlan: state.workPlan,
      executionPlan: state.executionPlan,
      isPlanMode: state.isPlanMode,
      doomLoopDetected: state.doomLoopDetected,
      hasEarlier: state.hasEarlier,
      loadConversations: state.loadConversations,
      loadMessages: state.loadMessages,
      loadEarlierMessages: state.loadEarlierMessages,
      setActiveConversation: state.setActiveConversation,
      createNewConversation: state.createNewConversation,
      sendMessage: state.sendMessage,
      abortStream: state.abortStream,
      togglePlanMode: state.togglePlanMode,
      togglePlanPanel: state.togglePlanPanel,
      loadPendingHITL: state.loadPendingHITL,
      clearError: state.clearError,
      error: state.error,
      streamingAssistantContent: state.streamingAssistantContent,
      streamingThought: state.streamingThought,
      isThinkingStreaming: state.isThinkingStreaming,
    }))
  );

  // Derive streaming content - only show when actively streaming
  const streamingContent = isStreaming ? streamingAssistantContent : '';

  const { planModeStatus, exitPlanMode } = usePlanModeStore();
  const {
    activeSandboxId,
    toolExecutions,
    currentTool,
    setProjectId,
    subscribeSSE,
    unsubscribeSSE,
    ensureSandbox,
    setSandboxId,
  } = useSandboxStore();
  const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

  // Set projectId to sandbox store and subscribe to SSE events
  useEffect(() => {
    if (projectId) {
      setProjectId(projectId);
      subscribeSSE(projectId);
      // Try to ensure sandbox exists and get sandboxId
      // Pass projectId directly to avoid race condition with setProjectId
      ensureSandbox(projectId).then((sandboxId) => {
        if (sandboxId) {
          setSandboxId(sandboxId);
        }
      });
    }
    return () => {
      unsubscribeSSE();
    };
  }, [projectId, setProjectId, subscribeSSE, unsubscribeSSE, ensureSandbox, setSandboxId]);

  // Get tenant ID from current project
  const currentProject = useProjectStore((state) => state.currentProject);
  const tenantId = currentProject?.tenant_id || 'default-tenant';

  // Note: HITL is now rendered inline in the message timeline via InlineHITLCard.
  // The useUnifiedHITL hook and modal rendering have been removed.

  // Layout mode state
  const { mode: layoutMode, splitRatio, setSplitRatio, chatPanelVisible } = useLayoutModeStore(
    useShallow((state) => ({
      mode: state.mode,
      splitRatio: state.splitRatio,
      setSplitRatio: state.setSplitRatio,
      chatPanelVisible: state.chatPanelVisible,
    }))
  );

  // Local UI state
  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_WIDTH);
  const [inputHeight, setInputHeight] = useState(INPUT_DEFAULT_HEIGHT);

  // In chat mode, right panel visibility is controlled by chatPanelVisible
  const panelCollapsed = layoutMode === 'chat' ? !chatPanelVisible : true;

  // Clamp panel width (chat mode only)
  const clampedPanelWidth = useMemo(() => {
    return Math.min(panelWidth, PANEL_MAX_WIDTH);
  }, [panelWidth]);

  // Load conversations
  useEffect(() => {
    if (projectId) loadConversations(projectId);
  }, [projectId, loadConversations]);

  // Handle URL changes
  useEffect(() => {
    if (projectId && conversationId) {
      setActiveConversation(conversationId);
      // Read fresh state directly from the store to avoid stale closure values.
      // When sendMessage creates a new conversation and navigates here, the store
      // has already been updated synchronously, but the component hasn't re-rendered
      // yet so closure-captured activeConversationId/isStreaming may be stale.
      const freshState = useAgentV3Store.getState();
      const alreadyStreaming =
        freshState.activeConversationId === conversationId && freshState.isStreaming;
      if (!alreadyStreaming) {
        loadMessages(conversationId, projectId);
      }
      // Load any pending HITL requests to restore dialog state after refresh
      loadPendingHITL(conversationId);
    } else if (projectId && !conversationId) {
      setActiveConversation(null);
    }
  }, [conversationId, projectId, setActiveConversation, loadMessages, loadPendingHITL]);

  // Handle errors
  useEffect(() => {
    if (error) {
      notification?.error({
        message: t('agent.chat.errors.title'),
        description: error,
        onClose: clearError,
      });
    }
  }, [error, clearError, t]);

  // Handle doom loop
  useEffect(() => {
    if (doomLoopDetected) {
      notification?.warning({
        message: t('agent.chat.doomLoop.title'),
        description: t('agent.chat.doomLoop.description', {
          tool: doomLoopDetected.tool_name,
          count: doomLoopDetected.call_count,
        }),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doomLoopDetected, t]);

  const handleNewConversation = useCallback(async () => {
    if (!projectId) return;
    const newId = await createNewConversation(projectId);
    if (newId) {
      if (customBasePath) {
        navigate(`${basePath}/${newId}${queryProjectId ? `?projectId=${queryProjectId}` : ''}`);
      } else {
        navigate(`${basePath}/${newId}`);
      }
    }
  }, [projectId, createNewConversation, navigate, basePath, customBasePath, queryProjectId]);

  const handleSend = useCallback(
    async (content: string, fileMetadata?: FileMetadata[], forcedSkillName?: string) => {
      if (!projectId) return;
      const newId = await sendMessage(content, projectId, {
        onAct,
        onObserve,
        fileMetadata,
        forcedSkillName,
      });
      if (!conversationId && newId) {
        if (customBasePath) {
          navigate(`${basePath}/${newId}${queryProjectId ? `?projectId=${queryProjectId}` : ''}`);
        } else {
          navigate(`${basePath}/${newId}`);
        }
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
    if (layoutMode === 'chat') {
      const store = useLayoutModeStore.getState();
      if (!store.chatPanelVisible) store.toggleChatPanel();
      store.setRightPanelTab('plan');
    }
    togglePlanPanel();
  }, [togglePlanPanel, layoutMode]);

  const handleExitPlanMode = useCallback(async () => {
    if (!activeConversationId || !planModeStatus?.current_plan_id) return;
    try {
      await exitPlanMode(activeConversationId, planModeStatus.current_plan_id, false);
      togglePlanMode();
    } catch (error) {
      notification?.error({
        message: t('agent.notifications.planModeExitFailed.title'),
        description: t('agent.notifications.planModeExitFailed.description'),
      });
    }
  }, [activeConversationId, planModeStatus, exitPlanMode, togglePlanMode, t, notification]);

  // Memoized components
  const messageArea = useMemo(
    () =>
      timeline.length === 0 && !activeConversationId ? (
        <EmptyState onNewConversation={handleNewConversation} />
      ) : (
        <MessageArea
          timeline={timeline}
          streamingContent={streamingContent}
          streamingThought={streamingThought}
          isStreaming={isStreaming}
          isThinkingStreaming={isThinkingStreaming}
          isLoading={isLoadingHistory}
          planModeStatus={planModeStatus}
          onViewPlan={handleViewPlan}
          onExitPlanMode={handleExitPlanMode}
          hasEarlierMessages={hasEarlier}
          onLoadEarlier={() => {
            if (activeConversationId && projectId) {
              loadEarlierMessages(activeConversationId, projectId);
            }
          }}
          isLoadingEarlier={isLoadingEarlier}
          conversationId={activeConversationId}
        />
      ),
    [
      timeline,
      streamingContent,
      streamingThought,
      isStreaming,
      isThinkingStreaming,
      isLoadingHistory,
      isLoadingEarlier,
      activeConversationId,
      planModeStatus,
      handleViewPlan,
      handleExitPlanMode,
      handleNewConversation,
      hasEarlier,
      loadEarlierMessages,
      projectId,
      conversationId,
    ]
  );

  const rightPanel = useMemo(
    () => (
      <RightPanel
        workPlan={workPlan}
        executionPlan={executionPlan}
        sandboxId={activeSandboxId}
        toolExecutions={toolExecutions}
        currentTool={currentTool}
        onClose={() => {
          useLayoutModeStore.getState().toggleChatPanel();
          togglePlanPanel();
        }}
        collapsed={panelCollapsed}
        width={clampedPanelWidth}
        onWidthChange={setPanelWidth}
        minWidth={PANEL_MIN_WIDTH}
        maxWidth={PANEL_MAX_WIDTH}
      />
    ),
    [
      workPlan,
      executionPlan,
      activeSandboxId,
      toolExecutions,
      currentTool,
      panelCollapsed,
      clampedPanelWidth,
      togglePlanPanel,
    ]
  );

  // Sandbox content for code/desktop/focus split modes
  const sandboxContent = useMemo(
    () => (
      <SandboxSection
        sandboxId={activeSandboxId || null}
        toolExecutions={toolExecutions}
        currentTool={currentTool || null}
      />
    ),
    [activeSandboxId, toolExecutions, currentTool]
  );

  const statusBar = useMemo(
    () => (
      <ProjectAgentStatusBar
        projectId={projectId || ''}
        tenantId={tenantId}
        messageCount={timeline.length}
        enablePoolManagement
      />
    ),
    [projectId, tenantId, timeline.length]
  );

  // Split mode drag handler
  const handleSplitDrag = useCallback(
    (e: React.MouseEvent) => {
      if (layoutMode !== 'code' && layoutMode !== 'desktop') return;
      e.preventDefault();
      const startX = e.clientX;
      const startRatio = splitRatio;
      const containerWidth = (e.currentTarget as HTMLElement).parentElement?.offsetWidth || window.innerWidth;

      const onMove = (ev: MouseEvent) => {
        const delta = ev.clientX - startX;
        const newRatio = startRatio + delta / containerWidth;
        setSplitRatio(newRatio);
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [layoutMode, splitRatio, setSplitRatio]
  );

  // Chat column content (reused across modes)
  const chatColumn = (
    <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
      {headerExtra && (
        <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm px-4 py-2">
          {headerExtra}
        </div>
      )}
      <div className="flex-1 overflow-hidden relative min-h-0">{messageArea}</div>
      <div
        className="flex-shrink-0 border-t border-slate-200/60 dark:border-slate-700/50 bg-white/90 dark:bg-slate-900/90 backdrop-blur-md relative flex flex-col shadow-[0_-4px_20px_rgba(0,0,0,0.03)]"
        style={{ height: inputHeight }}
      >
        <div className="absolute -top-2 left-0 right-0 z-40 flex justify-center">
          <Resizer
            direction="vertical"
            currentSize={inputHeight}
            minSize={INPUT_MIN_HEIGHT}
            maxSize={INPUT_MAX_HEIGHT}
            onResize={setInputHeight}
            position="top"
          />
          <div className="pointer-events-none absolute top-1 flex items-center gap-1 text-slate-400">
            <GripHorizontal size={12} />
          </div>
        </div>
        <InputBar
          onSend={handleSend}
          onAbort={abortStream}
          isStreaming={isStreaming}
          isPlanMode={isPlanMode}
          onTogglePlanMode={togglePlanMode}
          disabled={isLoadingHistory}
          projectId={projectId || undefined}
        />
      </div>
    </div>
  );

  // Status bar with layout mode selector
  const statusBarWithLayout = (
    <div className="flex-shrink-0 flex items-center border-t border-slate-200/60 dark:border-slate-700/50 bg-slate-50/80 dark:bg-slate-800/50 backdrop-blur-sm">
      <div className="flex-1">{statusBar}</div>
      <div className="flex items-center gap-2 pr-3">
        <LayoutModeSelector />
      </div>
    </div>
  );

  // Focus mode: fullscreen desktop with floating chat
  if (layoutMode === 'focus') {
    return (
      <div className={`flex flex-col h-full w-full overflow-hidden ${className}`}>
        <FocusDesktopOverlay
          desktopContent={sandboxContent}
          chatContent={messageArea}
          onSend={(content) => handleSend(content)}
          isStreaming={isStreaming}
        />
        {statusBarWithLayout}
      </div>
    );
  }

  // Code/Desktop split modes
  if (layoutMode === 'code' || layoutMode === 'desktop') {
    const leftPercent = `${splitRatio * 100}%`;
    const rightPercent = `${(1 - splitRatio) * 100}%`;

    return (
      <div
        className={`flex flex-col h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
      >
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left: Chat */}
          <div className="h-full overflow-hidden flex flex-col" style={{ width: leftPercent }}>
            {chatColumn}
          </div>

          {/* Drag handle */}
          <div
            className="flex-shrink-0 w-1.5 h-full cursor-col-resize relative group
              hover:bg-blue-500/20 active:bg-blue-500/30 transition-colors z-10"
            onMouseDown={handleSplitDrag}
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-slate-400/50 group-hover:bg-blue-500/70 transition-colors" />
          </div>

          {/* Right: Sandbox (Terminal or Desktop depending on mode) */}
          <div
            className="h-full overflow-hidden border-l border-slate-200/60 dark:border-slate-700/50 bg-slate-900"
            style={{ width: rightPercent }}
          >
            {sandboxContent}
          </div>
        </div>

        {statusBarWithLayout}
      </div>
    );
  }

  // Chat mode (default): classic layout with optional right panel
  return (
    <div
      className={`flex h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
    >
      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
        {chatColumn}
        {statusBarWithLayout}
      </main>

      {/* Right Panel with built-in resize handle (Plan / Sandbox tabs) */}
      <aside
        className={`
          flex-shrink-0 h-full
          border-l border-slate-200/60 dark:border-slate-700/50
          bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm
          transition-all duration-300 ease-out overflow-hidden
          ${panelCollapsed ? 'w-0 opacity-0' : 'opacity-100'}
        `}
        style={{ width: panelCollapsed ? 0 : clampedPanelWidth }}
      >
        {!panelCollapsed && rightPanel}
      </aside>
    </div>
  );
};

export default AgentChatContent;
