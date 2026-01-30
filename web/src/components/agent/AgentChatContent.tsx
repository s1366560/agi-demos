/**
 * AgentChatContent - Agent Chat content for use in layouts
 * 
 * This version is designed to work inside layouts that already have
 * a conversation sidebar as the primary navigation.
 * 
 * Features:
 * - Draggable resize for right panel (horizontal)
 * - Draggable resize for input area (vertical)
 */

import * as React from 'react';
import { useEffect, useCallback, useMemo, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Modal, notification } from 'antd';
import { useTranslation } from 'react-i18next';
import { PanelRight, GripHorizontal } from 'lucide-react';
import { useAgentV3Store } from '@/stores/agentV3';
import { usePlanModeStore } from '@/stores/agent/planModeStore';
import { useSandboxStore } from '@/stores/sandbox';
import { useProjectStore } from '@/stores/project';
import { useSandboxAgentHandlers } from '@/hooks/useSandboxDetection';
import { sandboxService } from '@/services/sandboxService';
import { Resizer } from './Resizer';

// Import design components
import {
  MessageArea,
  InputBar,
  RightPanel,
  ProjectAgentStatusBar,
} from './index';
import { EmptyState } from './EmptyState';

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
const PANEL_MIN_WIDTH = 280;
const PANEL_DEFAULT_WIDTH = 360;
const PANEL_MAX_PERCENT = 0.9; // 90% of viewport width

const INPUT_MIN_HEIGHT = 120;
const INPUT_MAX_HEIGHT = 400;
const INPUT_DEFAULT_HEIGHT = 160;

export const AgentChatContent: React.FC<AgentChatContentProps> = ({
  className = '',
  externalProjectId,
  basePath: customBasePath,
  headerExtra
}) => {
  const { t } = useTranslation();
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

  // Store state
  const {
    activeConversationId,
    timeline,
    messages,
    isLoadingHistory,
    isLoadingEarlier,
    isStreaming,
    workPlan,
    executionPlan,
    isPlanMode,
    showPlanPanel,
    pendingDecision,
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
    respondToDecision,
    clearError,
    error,
  } = useAgentV3Store();

  // Get streaming content from the last assistant message
  const streamingContent = React.useMemo(() => {
    if (!isStreaming || messages.length === 0) return '';
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === 'assistant') {
      return lastMessage.content || '';
    }
    return '';
  }, [messages, isStreaming]);

  // Get streaming thought from store
  const { streamingThought, isThinkingStreaming } = useAgentV3Store();

  const { planModeStatus, exitPlanMode } = usePlanModeStore();
  const {
    activeSandboxId,
    toolExecutions,
    currentTool,
    setSandboxId
  } = useSandboxStore();
  const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

  // Get tenant ID from current project
  const currentProject = useProjectStore((state) => state.currentProject);
  const tenantId = currentProject?.tenant_id || 'default-tenant';

  // Local UI state
  const [panelCollapsed, setPanelCollapsed] = useState(!showPlanPanel);
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

  // Clamp panel width when max changes
  useEffect(() => {
    if (panelWidth > maxPanelWidth) {
      setPanelWidth(maxPanelWidth);
    }
  }, [maxPanelWidth, panelWidth]);

  // Ensure sandbox exists
  const ensureSandbox = useCallback(async () => {
    if (activeSandboxId) return activeSandboxId;
    if (!projectId) return null;

    try {
      const { sandboxes } = await sandboxService.listSandboxes(projectId);
      if (sandboxes.length > 0 && sandboxes[0].status === 'running') {
        setSandboxId(sandboxes[0].id);
        return sandboxes[0].id;
      }
      const { sandbox } = await sandboxService.createSandbox({ project_id: projectId });
      setSandboxId(sandbox.id);
      return sandbox.id;
    } catch (error) {
      console.error('[AgentChatContent] Failed to ensure sandbox:', error);
      return null;
    }
  }, [activeSandboxId, projectId, setSandboxId]);

  // Load conversations
  useEffect(() => {
    if (projectId) loadConversations(projectId);
  }, [projectId, loadConversations]);

  // Handle URL changes
  useEffect(() => {
    if (projectId && conversationId) {
      setActiveConversation(conversationId);
      loadMessages(conversationId, projectId);
    } else if (projectId && !conversationId) {
      setActiveConversation(null);
    }
  }, [conversationId, projectId, setActiveConversation, loadMessages]);

  // Handle errors
  useEffect(() => {
    if (error) {
      notification.error({ 
        message: t('agent.chat.errors.title'), 
        description: error, 
        onClose: clearError 
      });
    }
  }, [error, clearError, t]);

  // Handle pending decisions
  useEffect(() => {
    if (pendingDecision) {
      Modal.confirm({
        title: t('agent.chat.decision.title'),
        content: pendingDecision.question,
        okText: t('agent.chat.decision.confirm'),
        cancelText: t('agent.chat.decision.cancel'),
        onOk: () => respondToDecision(pendingDecision.request_id, 'approved'),
        onCancel: () => respondToDecision(pendingDecision.request_id, 'rejected'),
      });
    }
  }, [pendingDecision, respondToDecision, t]);

  // Handle doom loop
  useEffect(() => {
    if (doomLoopDetected) {
      notification.warning({
        message: t('agent.chat.doomLoop.title'),
        description: t('agent.chat.doomLoop.description', { 
          tool: doomLoopDetected.tool_name, 
          count: doomLoopDetected.call_count 
        }),
      });
    }
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

  const handleSend = useCallback(async (content: string) => {
    if (!projectId) return;
    await ensureSandbox();
    const newId = await sendMessage(content, projectId, { onAct, onObserve });
    if (!conversationId && newId) {
      if (customBasePath) {
        navigate(`${basePath}/${newId}${queryProjectId ? `?projectId=${queryProjectId}` : ''}`);
      } else {
        navigate(`${basePath}/${newId}`);
      }
    }
  }, [projectId, conversationId, sendMessage, onAct, onObserve, navigate, ensureSandbox, basePath, customBasePath, queryProjectId]);

  const handleViewPlan = useCallback(() => {
    setPanelCollapsed(false);
    togglePlanPanel();
  }, [togglePlanPanel]);

  const handleExitPlanMode = useCallback(async () => {
    if (!activeConversationId || !planModeStatus?.current_plan_id) return;
    try {
      await exitPlanMode(activeConversationId, planModeStatus.current_plan_id, false);
      togglePlanMode();
    } catch (error) {
      notification.error({ 
        message: t('agent.notifications.planModeExitFailed.title'), 
        description: t('agent.notifications.planModeExitFailed.description') 
      });
    }
  }, [activeConversationId, planModeStatus, exitPlanMode, togglePlanMode, t]);

  // Memoized components
  // DEBUG: Log timeline events before rendering
  useEffect(() => {
    const events = timeline.filter((e: any) => e.type === 'assistant_message');
    console.log('[AgentChatContent] Rendering - assistant_message events in timeline:', events.length);
    events.forEach((e: any, i: number) => {
      console.log(`  [${i}] id=${e.id}, seq=${e.sequenceNumber}, content="${((e as any).content || '').slice(0, 50)}..."`);
    });
  }, [timeline]);

  const messageArea = useMemo(() => (
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
      />
    )
  ), [timeline, streamingContent, streamingThought, isStreaming, isThinkingStreaming, isLoadingHistory, isLoadingEarlier, activeConversationId, planModeStatus, handleViewPlan, handleExitPlanMode, handleNewConversation, hasEarlier, loadEarlierMessages, projectId]);



  const rightPanel = useMemo(() => (
    <RightPanel
      workPlan={workPlan}
      executionPlan={executionPlan}
      sandboxId={activeSandboxId}
      toolExecutions={toolExecutions}
      currentTool={currentTool}
      onClose={() => {
        setPanelCollapsed(true);
        togglePlanPanel();
      }}
      collapsed={panelCollapsed}
      width={panelWidth}
      onWidthChange={setPanelWidth}
      minWidth={PANEL_MIN_WIDTH}
      maxWidth={maxPanelWidth}
    />
  ), [workPlan, executionPlan, activeSandboxId, toolExecutions, currentTool, panelCollapsed, panelWidth, togglePlanPanel, maxPanelWidth]);

  const statusBar = useMemo(() => (
    <ProjectAgentStatusBar
      projectId={projectId || ''}
      tenantId={tenantId}
      messageCount={timeline.length}
    />
  ), [projectId, tenantId, timeline.length]);

  return (
    <div className={`flex h-full w-full overflow-hidden bg-slate-50 dark:bg-slate-950 ${className}`}>
      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
        {/* Header Extra Content (if provided) */}
        {headerExtra && (
          <div className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-2">
            {headerExtra}
          </div>
        )}



        {/* Message Area - Takes remaining space */}
        <div className="flex-1 overflow-hidden relative">
          {messageArea}
        </div>

        {/* Resizable Input Area */}
        <div 
          className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 relative flex flex-col"
          style={{ height: inputHeight }}
        >
          {/* Resize handle for input area (at top) */}
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
          />
        </div>

        {/* Status Bar with Panel Toggle */}
        <div className="flex-shrink-0 flex items-center border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          <div className="flex-1">
            {statusBar}
          </div>
          <button
            type="button"
            title={panelCollapsed ? t('agent.chat.panel.show') : t('agent.chat.panel.hide')}
            onClick={() => {
              setPanelCollapsed(!panelCollapsed);
              togglePlanPanel();
            }}
            className="h-7 px-2 mr-2 flex items-center justify-center rounded-md text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            aria-label={panelCollapsed ? t('agent.chat.panel.show') : t('agent.chat.panel.hide')}
          >
            {panelCollapsed ? <PanelRight size={14} /> : <PanelRight size={14} className="rotate-180" />}
          </button>
        </div>
      </main>

      {/* Right Panel with built-in resize handle */}
      <aside
        className={`
          flex-shrink-0 h-full
          border-l border-slate-200 dark:border-slate-800
          transition-opacity duration-300 ease-out overflow-hidden
          ${panelCollapsed ? 'w-0 opacity-0' : 'opacity-100'}
        `}
        style={{ width: panelCollapsed ? 0 : panelWidth }}
      >
        {!panelCollapsed && rightPanel}
      </aside>
    </div>
  );
};

export default AgentChatContent;
