/**
 * AgentChatContent - Agent Chat content with multi-mode layout
 *
 * Supports four layout modes:
 * - chat: Full chat view with optional right panel (Plan/Terminal/Desktop tabs)
 * - task: Split view — chat (left) + task panel (right, 50/50)
 * - code: Split view — chat (left) + terminal (right), resizable
 * - canvas: Split view — chat (left) + artifact canvas (right, 35/65)
 *
 * Features:
 * - Cmd+1/2/3/4 to switch modes
 * - Draggable split ratio in task/code/canvas modes
 * - Flat right panel tabs (Plan | Terminal | Desktop)
 */

import * as React from 'react';
import { useEffect, useCallback, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';

import { GripHorizontal, Download, ChevronDown, GitCompareArrows } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useAgentV3Store } from '@/stores/agentV3';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useProjectStore } from '@/stores/project';
import { useSandboxStore } from '@/stores/sandbox';

import type { FileMetadata } from '@/services/sandboxUploadService';

import { useSandboxAgentHandlers } from '@/hooks/useSandboxDetection';


import { useLazyNotification } from '@/components/ui/lazyAntd';

// Import design components
import {
  downloadConversationMarkdown,
  downloadConversationPdf,
} from '../../utils/exportConversation';

import { CanvasPanel } from './canvas/CanvasPanel';
import { ChatSearch } from './chat/ChatSearch';
import { OnboardingTour } from './chat/OnboardingTour';
import { ShortcutOverlay } from './chat/ShortcutOverlay';
import { ConversationCompareView } from './comparison/ConversationCompareView';
import { ConversationPickerModal } from './comparison/ConversationPickerModal';
import { EmptyState } from './EmptyState';
import { LayoutModeSelector } from './layout/LayoutModeSelector';
import { Resizer } from './Resizer';
import { RightPanel } from './RightPanel';
import { SandboxSection } from './SandboxSection';

import { MessageArea, InputBar, ProjectAgentStatusBar } from './index';

import type { AgentTask } from '../../types/agent';


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
const INPUT_MAX_HEIGHT = 560;
const INPUT_DEFAULT_HEIGHT = 180;



export const AgentChatContent: React.FC<AgentChatContentProps> = React.memo(({
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
  // NOTE: streamingAssistantContent, streamingThought, isThinkingStreaming are
  // subscribed directly inside MessageArea to avoid re-rendering this entire
  // component on every streaming token.
  const {
    activeConversationId,
    timeline,
    isLoadingHistory,
    isLoadingEarlier,
    isStreaming,
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
    // HITL response methods still available but not used directly
    // respondToClarification, respondToDecision, respondToEnvVar
    loadPendingHITL,
    clearError,
    error,
    suggestions,
    conversations,
  } = useAgentV3Store(
    useShallow((state) => ({
      activeConversationId: state.activeConversationId,
      timeline: state.timeline,
      isLoadingHistory: state.isLoadingHistory,
      isLoadingEarlier: state.isLoadingEarlier,
      isStreaming: state.isStreaming,
      doomLoopDetected: state.doomLoopDetected,
      hasEarlier: state.hasEarlier,
      loadConversations: state.loadConversations,
      loadMessages: state.loadMessages,
      loadEarlierMessages: state.loadEarlierMessages,
      setActiveConversation: state.setActiveConversation,
      createNewConversation: state.createNewConversation,
      sendMessage: state.sendMessage,
      abortStream: state.abortStream,
      loadPendingHITL: state.loadPendingHITL,
      clearError: state.clearError,
      error: state.error,
      suggestions: state.suggestions,
      conversations: state.conversations,
    }))
  );

  // Derive last conversation for resume card
  const lastConversation = useMemo(() => {
    if (conversations.length > 0 && !activeConversationId) {
      const conv = conversations[0];
      return { id: conv.id, title: conv.title, updated_at: conv.updated_at };
    }
    return undefined;
  }, [conversations, activeConversationId]);

  const handleResumeConversation = useCallback(
    (id: string) => {
      if (customBasePath) {
        navigate(`${basePath}/${id}${queryProjectId ? `?projectId=${queryProjectId}` : ''}`);
      } else {
        navigate(`${basePath}/${id}`);
      }
    },
    [navigate, basePath, customBasePath, queryProjectId]
  );

  const {
    activeSandboxId,
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
  const { mode: layoutMode, splitRatio, setSplitRatio } = useLayoutModeStore(
    useShallow((state) => ({
      mode: state.mode,
      splitRatio: state.splitRatio,
      setSplitRatio: state.setSplitRatio,
    }))
  );

  // Tasks from active conversation state (separate selector to avoid re-renders)
  const EMPTY_TASKS: AgentTask[] = useMemo(() => [], []);
  const rawTasks = useAgentV3Store((state) => {
    const convId = state.activeConversationId;
    if (!convId) return undefined;
    return state.conversationStates.get(convId)?.tasks;
  });
  const tasks = rawTasks ?? EMPTY_TASKS;

  // Local UI state
  const [inputHeight, setInputHeight] = useState(INPUT_DEFAULT_HEIGHT);
  const [chatSearchVisible, setChatSearchVisible] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(
    () => !localStorage.getItem('memstack_onboarding_complete'),
  );

  // Auto-switch to task mode when tasks appear
  useEffect(() => {
    if (tasks.length > 0 && layoutMode === 'chat') {
      // Don't auto-switch, just let the user know via the layout selector
    }
  }, [tasks.length, layoutMode]);

  // Cmd+F to open chat search, / to focus input, Shift+Tab to toggle plan mode
  useEffect(() => {
    const handleKeyShortcut = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault();
        setChatSearchVisible((v) => !v);
        return;
      }

      // Shift+Tab to toggle Plan Mode
      if (e.shiftKey && e.key === 'Tab') {
        e.preventDefault();
        // Use dynamic import to avoid stale closure
        const store = useAgentV3Store.getState();
        const convId = store.activeConversationId;
        if (!convId) return;
        const newMode = store.isPlanMode ? 'build' : 'plan';
        import('@/services/planService').then(({ planService }) => {
          planService.switchMode(convId, newMode as 'plan' | 'build').then(() => {
            useAgentV3Store.getState().updateConversationState(convId, {
              isPlanMode: newMode === 'plan',
            });
            useAgentV3Store.setState({ isPlanMode: newMode === 'plan' });
          }).catch(console.error);
        });
        return;
      }

      // / to focus input (when not already in an input)
      if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const target = e.target as HTMLElement;
        const isInput =
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable;
        if (!isInput) {
          e.preventDefault();
          const textarea = document.querySelector<HTMLTextAreaElement>(
            '[data-testid="chat-input"], textarea[placeholder]'
          );
          textarea?.focus();
        }
      }
    };
    window.addEventListener('keydown', handleKeyShortcut);
    return () => window.removeEventListener('keydown', handleKeyShortcut);
  }, []);

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

  // Auto-focus input when conversation finishes loading
  useEffect(() => {
    if (!isLoadingHistory && activeConversationId) {
      const timer = setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>('textarea[data-testid="chat-input"]');
        textarea?.focus();
      }, 100);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [isLoadingHistory, activeConversationId]);

  // Return focus to input when agent finishes responding
  useEffect(() => {
    if (!isStreaming && activeConversationId) {
      const timer = setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>('textarea[data-testid="chat-input"]');
        textarea?.focus();
      }, 200);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [isStreaming, activeConversationId]);

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

  // Memoized components
  const messageArea = useMemo(
    () =>
      timeline.length === 0 && !activeConversationId ? (
        <EmptyState
          onNewConversation={handleNewConversation}
          onSendPrompt={handleSend}
          lastConversation={lastConversation}
          onResumeConversation={handleResumeConversation}
          projectId={projectId}
        />
      ) : (
        <MessageArea
          timeline={timeline}
          isStreaming={isStreaming}
          isLoading={isLoadingHistory}
          hasEarlierMessages={hasEarlier}
          onLoadEarlier={() => {
            if (activeConversationId && projectId) {
              loadEarlierMessages(activeConversationId, projectId);
            }
          }}
          isLoadingEarlier={isLoadingEarlier}
          conversationId={activeConversationId}
          suggestions={suggestions}
          onSuggestionSelect={handleSend}
        />
      ),
    [
      timeline,
      isStreaming,
      isLoadingHistory,
      isLoadingEarlier,
      activeConversationId,
      handleNewConversation,
      handleSend,
      handleResumeConversation,
      lastConversation,
      hasEarlier,
      suggestions,
      loadEarlierMessages,
      projectId,
      conversationId,
    ]
  );

  // Sandbox content for code/desktop/focus split modes
  const sandboxContent = useMemo(
    () => (
      <SandboxSection
        sandboxId={activeSandboxId || null}
      />
    ),
    [activeSandboxId]
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
      if (layoutMode !== 'task' && layoutMode !== 'code' && layoutMode !== 'canvas') return;
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

  // Plan Mode toggle
  const isPlanMode = useAgentV3Store((s) => s.isPlanMode);

  const handleTogglePlanMode = useCallback(async () => {
    if (!activeConversationId) return;
    const newMode = isPlanMode ? 'build' : 'plan';
    try {
      const { planService } = await import('@/services/planService');
      await planService.switchMode(activeConversationId, newMode);
      useAgentV3Store.getState().updateConversationState(activeConversationId, {
        isPlanMode: newMode === 'plan',
      });
      useAgentV3Store.setState({ isPlanMode: newMode === 'plan' });
    } catch (err) {
      console.error('Failed to switch plan mode:', err);
    }
  }, [activeConversationId, isPlanMode]);

  const chatColumn = (
    <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
      {headerExtra && (
        <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm px-4 py-2">
          {headerExtra}
        </div>
      )}
      <div className="flex-1 overflow-hidden relative min-h-0">
        {messageArea}
        <ChatSearch
          timeline={timeline}
          visible={chatSearchVisible}
          onClose={() => setChatSearchVisible(false)}
        />
      </div>
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
          disabled={isLoadingHistory}
          projectId={projectId || undefined}
          onTogglePlanMode={handleTogglePlanMode}
          isPlanMode={isPlanMode}
        />
      </div>
    </div>
  );

  // Export conversation as Markdown
  const handleExportMarkdown = useCallback(() => {
    if (timeline.length === 0) return;
    downloadConversationMarkdown(timeline, undefined, `conversation-${activeConversationId || 'export'}.md`);
  }, [timeline, activeConversationId]);

  // Export conversation as PDF
  const handleExportPdf = useCallback(() => {
    if (timeline.length === 0) return;
    downloadConversationPdf(timeline, undefined, `conversation-${activeConversationId || 'export'}.pdf`);
  }, [timeline, activeConversationId]);

  const [showExportMenu, setShowExportMenu] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [compareConversationId, setCompareConversationId] = useState<string | null>(null);
  const [showComparePicker, setShowComparePicker] = useState(false);

  const handleOnboardingComplete = useCallback(() => {
    localStorage.setItem('memstack_onboarding_complete', 'true');
    setShowOnboarding(false);
  }, []);

  // Status bar with layout mode selector
  const statusBarWithLayout = (
    <div className="flex-shrink-0 flex items-center border-t border-slate-200/60 dark:border-slate-700/50 bg-slate-50/80 dark:bg-slate-800/50 backdrop-blur-sm min-w-0">
      <div className="flex-1 min-w-0 overflow-hidden">{statusBar}</div>
      <div className="flex items-center gap-1 sm:gap-2 pr-2 sm:pr-3 flex-shrink-0">
        {activeConversationId && timeline.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setCompareMode(true);
              setShowComparePicker(true);
            }}
            className="flex items-center gap-1 p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={t('comparison.compare', 'Compare')}
            aria-label={t('comparison.compare', 'Compare')}
          >
            <GitCompareArrows size={14} />
          </button>
        )}
        {timeline.length > 0 && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowExportMenu((v) => !v)}
              onBlur={() => setTimeout(() => setShowExportMenu(false), 150)}
              className="flex items-center gap-0.5 p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              title={t('agent.actions.export', 'Export')}
              aria-label={t('agent.actions.export', 'Export')}
            >
              <Download size={14} />
              <ChevronDown size={10} />
            </button>
            {showExportMenu && (
              <div className="absolute bottom-full right-0 mb-1 w-48 rounded-md border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 shadow-lg z-50 py-1">
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); handleExportMarkdown(); setShowExportMenu(false); }}
                  className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                >
                  {t('agent.actions.exportMarkdown', 'Export as Markdown')}
                </button>
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); handleExportPdf(); setShowExportMenu(false); }}
                  className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                >
                  {t('agent.actions.exportPdf', 'Export as PDF')}
                </button>
              </div>
            )}
          </div>
        )}
        <LayoutModeSelector />
      </div>
    </div>
  );

  // Comparison mode: side-by-side conversation view
  if (compareMode && activeConversationId) {
    return (
      <div className={`flex flex-col h-full w-full overflow-hidden ${className}`}>
        <ConversationCompareView
          projectId={projectId || ''}
          leftConversationId={activeConversationId}
          rightConversationId={compareConversationId}
          conversations={conversations}
          onClose={() => {
            setCompareMode(false);
            setCompareConversationId(null);
          }}
          onSelectRight={() => setShowComparePicker(true)}
        />
        <ConversationPickerModal
          visible={showComparePicker}
          currentConversationId={activeConversationId}
          conversations={conversations}
          onSelect={(id) => setCompareConversationId(id)}
          onClose={() => setShowComparePicker(false)}
        />
        {statusBarWithLayout}
      </div>
    );
  }

  // Task mode: chat + task panel split
  if (layoutMode === 'task') {
    const leftPercent = `${splitRatio * 100}%`;
    const rightPercent = `${(1 - splitRatio) * 100}%`;

    return (
      <div
        className={`flex flex-col h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
      >
        <div className="flex-1 flex min-h-0 overflow-hidden mobile-stack">
          {/* Left: Chat */}
          <div className="h-full overflow-hidden flex flex-col mobile-full" style={{ width: leftPercent }}>
            {chatColumn}
          </div>

          {/* Drag handle */}
          <div
            className="flex-shrink-0 w-1.5 h-full cursor-col-resize relative group
              hover:bg-purple-500/20 active:bg-purple-500/30 transition-colors z-10 mobile-hidden"
            onMouseDown={handleSplitDrag}
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-slate-400/50 group-hover:bg-purple-500/70 transition-colors" />
          </div>

          {/* Right: Task Panel */}
          <div
            className="h-full overflow-hidden border-l border-slate-200/60 dark:border-slate-700/50 mobile-full"
            style={{ width: rightPercent }}
          >
            <RightPanel
              tasks={tasks}
              sandboxId={activeSandboxId}
              collapsed={false}
            />
          </div>
        </div>

        {statusBarWithLayout}
      </div>
    );
  }

  // Code split mode
  if (layoutMode === 'code') {
    const leftPercent = `${splitRatio * 100}%`;
    const rightPercent = `${(1 - splitRatio) * 100}%`;

    return (
      <div
        className={`flex flex-col h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
      >
        <div className="flex-1 flex min-h-0 overflow-hidden mobile-stack">
          {/* Left: Chat */}
          <div className="h-full overflow-hidden flex flex-col mobile-full" style={{ width: leftPercent }}>
            {chatColumn}
          </div>

          {/* Drag handle */}
          <div
            className="flex-shrink-0 w-1.5 h-full cursor-col-resize relative group
              hover:bg-blue-500/20 active:bg-blue-500/30 transition-colors z-10 mobile-hidden"
            onMouseDown={handleSplitDrag}
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-slate-400/50 group-hover:bg-blue-500/70 transition-colors" />
          </div>

          {/* Right: Sandbox Terminal */}
          <div
            className="h-full overflow-hidden border-l border-slate-200/60 dark:border-slate-700/50 bg-slate-900 mobile-full"
            style={{ width: rightPercent }}
          >
            {sandboxContent}
          </div>
        </div>

        {statusBarWithLayout}
      </div>
    );
  }

  // Canvas mode: chat + artifact canvas split
  if (layoutMode === 'canvas') {
    const leftPercent = `${splitRatio * 100}%`;
    const rightPercent = `${(1 - splitRatio) * 100}%`;

    return (
      <div
        className={`flex flex-col h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
      >
        <div className="flex-1 flex min-h-0 overflow-hidden mobile-stack">
          {/* Left: Chat */}
          <div
            className="h-full overflow-hidden flex flex-col transition-[width] duration-200 ease-out mobile-full"
            style={{ width: leftPercent, minWidth: '280px' }}
          >
            {chatColumn}
          </div>

          {/* Drag handle */}
          <div
            className="flex-shrink-0 w-1.5 h-full cursor-col-resize relative group
              hover:bg-violet-500/20 active:bg-violet-500/30 transition-colors z-10 mobile-hidden"
            onMouseDown={handleSplitDrag}
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-0.5 h-8 rounded-full bg-slate-400/50 group-hover:bg-violet-500/70 transition-colors" />
          </div>

          {/* Right: Canvas Panel */}
          <div
            className="h-full overflow-hidden border-l border-slate-200/60 dark:border-slate-700/50 transition-[width] duration-200 ease-out mobile-full"
            style={{ width: rightPercent, minWidth: '320px' }}
          >
            <CanvasPanel
              onSendPrompt={(prompt) => handleSend(prompt)}
              onUpdateModelContext={(ctx) => {
                const convId = useAgentV3Store.getState().activeConversationId;
                if (convId) {
                  useAgentV3Store.getState().updateConversationState(convId, {
                    appModelContext: ctx,
                  });
                }
              }}
            />
          </div>
        </div>

        {statusBarWithLayout}
      </div>
    );
  }

  // Chat mode (default): classic layout
  return (
    <div
      className={`flex h-full w-full overflow-hidden bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-950 dark:to-slate-900/50 ${className}`}
    >
      {/* Keyboard shortcut overlay (Cmd+/) */}
      <ShortcutOverlay />

      {/* First-time user onboarding tour */}
      {showOnboarding && !activeConversationId && (
        <OnboardingTour onComplete={handleOnboardingComplete} />
      )}

      {/* Main Content Area */}
      <main
        className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative"
        aria-label="Chat"
      >
        {chatColumn}
        {statusBarWithLayout}
      </main>
    </div>
  );
});

AgentChatContent.displayName = 'AgentChatContent';

export default AgentChatContent;
