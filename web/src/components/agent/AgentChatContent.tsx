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
import { Suspense, lazy, useEffect, useCallback, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';

import { message } from 'antd';
import { GripHorizontal, Download, ChevronDown, GitCompareArrows, Bot, Folder } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useIsPlanMode, useExecutionStore } from '@/stores/agent/executionStore';
import { useDoomLoopDetected, useSuggestions } from '@/stores/agent/hitlStore';
import { useIsStreaming, useAgentError, useStreamingStore } from '@/stores/agent/streamingStore';
import {
  useTimeline,
  useIsLoadingHistory,
  useIsLoadingEarlier,
  useHasEarlier,
} from '@/stores/agent/timelineStore';
import { useAgentV3Store } from '@/stores/agentV3';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useProjectStore } from '@/stores/project';
import { useSandboxStore } from '@/stores/sandbox';
import { useTenantStore } from '@/stores/tenant';
import { useWorkspaceStore } from '@/stores/workspace';

import { agentService } from '@/services/agentService';
import type { FileMetadata } from '@/services/sandboxUploadService';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';
import { useSandboxAgentHandlers } from '@/hooks/useSandboxDetection';

import { useLazyNotification } from '@/components/ui/lazyAntd';

// Import design components
import {
  downloadConversationMarkdown,
  downloadConversationPdf,
} from '../../utils/exportConversation';
import { WorkspaceStatusBar } from '../workspace/WorkspaceStatusBar';

import { ChatSearch } from './chat/ChatSearch';
import { OnboardingTour } from './chat/OnboardingTour';
import { subscribeToAgentChatSearchRequests } from './chat/searchEvents';
import { ShortcutOverlay } from './chat/ShortcutOverlay';
import { ConversationAgentBadge } from './ConversationAgentBadge';
import { EmptyState } from './EmptyState';
import { EvidenceBundleDrawer } from './evidence/EvidenceBundleDrawer';
import { InputBar } from './InputBar';
import { LayoutModeSelector } from './layout/LayoutModeSelector';
import { groupTimelineEvents, getSubAgentSummaries } from './message/groupTimelineEvents';
import { MessageArea } from './MessageArea';
import { ProjectAgentStatusBar } from './ProjectAgentStatusBar';
import { Resizer } from './Resizer';
import { SplitPaneLayout } from './SplitPaneLayout';
import { LAYOUT_BG_CLASSES } from './styles';
import { deriveTaskProgress } from './tasks/taskProgressDerivation';
import { SubAgentMiniMap } from './timeline/SubAgentMiniMap';

import type {
  AgentTask,
  Conversation,
  ExecutionNarrativeEntry,
  ExecutionPathDecidedEventData,
  PolicyFilteredEventData,
  SelectionTraceEventData,
  ToolsetChangedEventData,
} from '../../types/agent';

interface AgentChatContentProps {
  /** Optional className for styling */
  className?: string | undefined;
  /** External project ID (overrides URL param) */
  externalProjectId?: string | undefined;
  /** Base path for navigation (default: /project/{projectId}/agent) */
  basePath?: string | undefined;
  /** Optional query string to preserve across conversation navigation */
  navigationQuery?: string | undefined;
  /** Extra content to show in header area */
  headerExtra?: React.ReactNode | undefined;
}

// Constants for resize constraints
const INPUT_MIN_HEIGHT = 140;
const INPUT_MAX_HEIGHT = 560;
const INPUT_DEFAULT_HEIGHT = 180;

function metadataString(metadata: Record<string, unknown> | undefined, key: string): string | null {
  const value = metadata?.[key];
  return typeof value === 'string' && value.trim().length > 0 ? value : null;
}

function workspaceNodeIdFromConversationId(
  conversationId: string | null | undefined
): string | null {
  if (!conversationId?.startsWith('workspace-')) {
    return null;
  }
  const [, , nodeId] = conversationId.split(':');
  return nodeId?.startsWith('node-') ? nodeId : null;
}

function resolveCurrentWorkspaceTaskId(
  conversation: Conversation | null,
  conversationId: string | null | undefined
): string | null {
  return (
    conversation?.linked_workspace_task_id ??
    metadataString(conversation?.metadata, 'workspace_task_id') ??
    metadataString(conversation?.metadata, 'linked_workspace_task_id') ??
    workspaceNodeIdFromConversationId(conversation?.id ?? conversationId) ??
    null
  );
}

const CanvasPanel = lazy(() =>
  import('./canvas/CanvasPanel').then((module) => ({ default: module.CanvasPanel }))
);
const RightPanel = lazy(() =>
  import('./RightPanel').then((module) => ({ default: module.RightPanel }))
);
const SandboxSection = lazy(() =>
  import('./SandboxSection').then((module) => ({ default: module.SandboxSection }))
);
const WorkspaceGroupChatPanel = lazy(() =>
  import('../workspace/chat/WorkspaceGroupChatPanel').then((module) => ({
    default: module.WorkspaceGroupChatPanel,
  }))
);
const ConversationCompareView = lazy(() =>
  import('./comparison/ConversationCompareView').then((module) => ({
    default: module.ConversationCompareView,
  }))
);
const ConversationPickerModal = lazy(() =>
  import('./comparison/ConversationPickerModal').then((module) => ({
    default: module.ConversationPickerModal,
  }))
);

function AgentPanelFallback() {
  const { t } = useTranslation();

  return (
    <div className="flex h-full w-full items-center justify-center bg-slate-50 text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
      {t('agent.workspace.loading')}
    </div>
  );
}

export const AgentChatContent: React.FC<AgentChatContentProps> = React.memo(
  ({
    className = '',
    externalProjectId,
    basePath: customBasePath,
    navigationQuery,
    headerExtra,
  }) => {
    const { t } = useTranslation();
    const notification = useLazyNotification();
    const { projectId: urlProjectId, conversation: conversationId } = useParams<{
      projectId: string;
      conversation?: string | undefined;
    }>();
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { projectBasePath: resolvedProjectBasePath } = useProjectBasePath();

    // Use external project ID if provided, otherwise fall back to URL param
    const queryProjectId = searchParams.get('projectId');
    const queryWorkspaceId = searchParams.get('workspaceId');
    // Also check navigationQuery prop for workspaceId (e.g. restored from localStorage)
    const navQueryWorkspaceId = useMemo(() => {
      if (!navigationQuery) return null;
      return new URLSearchParams(navigationQuery).get('workspaceId');
    }, [navigationQuery]);
    const storeWorkspaceId = useWorkspaceStore((s) => s.currentWorkspace?.id ?? null);
    // Local override: set by collab panel workspace picker (no URL change)
    const [collabWorkspaceOverride, setCollabWorkspaceOverride] = useState<string | null>(null);
    const effectiveWorkspaceId =
      collabWorkspaceOverride || queryWorkspaceId || navQueryWorkspaceId || storeWorkspaceId;
    const effectiveNavigationQuery =
      navigationQuery || (queryProjectId ? `projectId=${queryProjectId}` : undefined);
    const navigationSuffix = effectiveNavigationQuery ? `?${effectiveNavigationQuery}` : '';
    const projectId = externalProjectId || queryProjectId || urlProjectId;
    const newConversationNavigationSuffix = useMemo(() => {
      if (!projectId) return '';
      const params = new URLSearchParams();
      params.set('projectId', projectId);
      return `?${params.toString()}`;
    }, [projectId]);

    // Determine base path for navigation
    const basePath = useMemo(() => {
      if (customBasePath) return customBasePath;
      return `${resolvedProjectBasePath}/agent`;
    }, [customBasePath, resolvedProjectBasePath]);

    // Store state - single useShallow selector to avoid infinite re-renders
    // NOTE: streamingAssistantContent, streamingThought, isThinkingStreaming are
    // subscribed directly inside MessageArea to avoid re-rendering this entire
    // component on every streaming token.
    const {
      activeConversationId,
      isCreatingConversation,
      loadConversations,
      loadMessages,
      loadEarlierMessages,
      setActiveConversation,
      createNewConversation,
      sendMessage,
      abortStream,
      clearError,
    } = useAgentV3Store(
      useShallow((state) => ({
        activeConversationId: state.activeConversationId,
        isCreatingConversation: state.isCreatingConversation,
        loadConversations: state.loadConversations,
        loadMessages: state.loadMessages,
        loadEarlierMessages: state.loadEarlierMessages,
        setActiveConversation: state.setActiveConversation,
        createNewConversation: state.createNewConversation,
        sendMessage: state.sendMessage,
        abortStream: state.abortStream,
        clearError: state.clearError,
      }))
    );

    const timeline = useTimeline();
    const isLoadingHistory = useIsLoadingHistory();
    const isLoadingEarlier = useIsLoadingEarlier();
    const hasEarlier = useHasEarlier();
    const isStreaming = useIsStreaming();
    const error = useAgentError();

    const conversations = useConversationsStore((state) => state.conversations);
    const currentConversation = useConversationsStore((state) => state.currentConversation);

    const doomLoopDetected = useDoomLoopDetected();
    const suggestions = useSuggestions();
    const loadPendingHITL = useAgentV3Store((s) => s.loadPendingHITL);

    // Derive last conversation for resume card
    const lastConversation = useMemo(() => {
      if (conversations.length > 0 && !activeConversationId) {
        const conv = conversations[0];
        if (!conv) return undefined;
        return { id: conv.id, title: conv.title, updated_at: conv.updated_at };
      }
      return undefined;
    }, [conversations, activeConversationId]);

    const handleResumeConversation = useCallback(
      (id: string) => {
        void navigate(`${basePath}/${id}${navigationSuffix}`);
      },
      [navigate, basePath, navigationSuffix]
    );

    const {
      activeSandboxId,
      setProjectId,
      setConnectionStatus,
      subscribeSSE,
      unsubscribeSSE,
      setSandboxId,
    } = useSandboxStore(
      useShallow((state) => ({
        activeSandboxId: state.activeSandboxId,
        setProjectId: state.setProjectId,
        setConnectionStatus: state.setConnectionStatus,
        subscribeSSE: state.subscribeSSE,
        unsubscribeSSE: state.unsubscribeSSE,
        setSandboxId: state.setSandboxId,
      }))
    );
    const { onAct, onObserve } = useSandboxAgentHandlers(activeSandboxId);

    const [activeAgentId, setActiveAgentId] = useState<string | undefined>(undefined);

    // Bind project-scoped sandbox state without creating containers on page load.
    useEffect(() => {
      if (projectId) {
        setSandboxId(null);
        setConnectionStatus('idle');
        setProjectId(projectId);
        subscribeSSE(projectId);
      }
      return () => {
        unsubscribeSSE();
      };
    }, [projectId, setProjectId, setConnectionStatus, subscribeSSE, unsubscribeSSE, setSandboxId]);

    // Get tenant ID from current project
    const currentProject = useProjectStore((state) => state.currentProject);
    const currentTenant = useTenantStore((state) => state.currentTenant);
    const tenantId = currentProject?.tenant_id || currentTenant?.id || '';

    // Note: HITL is now rendered inline in the message timeline via InlineHITLCard.
    // The useUnifiedHITL hook and modal rendering have been removed.

    // Layout mode state
    const {
      mode: layoutMode,
      splitRatio,
      setSplitRatio,
      setMode: setLayoutMode,
    } = useLayoutModeStore(
      useShallow((state) => ({
        mode: state.mode,
        splitRatio: state.splitRatio,
        setSplitRatio: state.setSplitRatio,
        setMode: state.setMode,
      }))
    );

    // Auto-fallback: if collab mode is active but no workspace is available, revert to chat
    useEffect(() => {
      if (layoutMode === 'collab' && !effectiveWorkspaceId) {
        setLayoutMode('chat');
      }
    }, [layoutMode, effectiveWorkspaceId, setLayoutMode]);

    // Tasks from active conversation state (separate selector to avoid re-renders)
    const EMPTY_TASKS: AgentTask[] = useMemo(() => [], []);
    const EMPTY_EXECUTION_NARRATIVE: ExecutionNarrativeEntry[] = useMemo(() => [], []);
    const rawTasks = useAgentV3Store((state) => {
      const convId = state.activeConversationId;
      if (!convId) return undefined;
      return state.conversationStates.get(convId)?.tasks;
    });
    const tasks = rawTasks ?? EMPTY_TASKS;
    const rawAgentNodes = useAgentV3Store((state) => {
      const convId = state.activeConversationId;
      if (!convId) return undefined;
      return state.conversationStates.get(convId)?.agentNodes;
    });

    const activeAgentNode = useMemo(() => {
      if (!rawAgentNodes) return null;
      for (const node of rawAgentNodes.values()) {
        if (node.status === 'running' && node.name !== null) {
          return node;
        }
      }
      return null;
    }, [rawAgentNodes]);
    const {
      executionPathDecision,
      selectionTrace,
      policyFiltered,
      executionNarrative,
      latestToolsetChange,
    }: {
      executionPathDecision: ExecutionPathDecidedEventData | null;
      selectionTrace: SelectionTraceEventData | null;
      policyFiltered: PolicyFilteredEventData | null;
      executionNarrative: ExecutionNarrativeEntry[];
      latestToolsetChange: ToolsetChangedEventData | null;
    } = useAgentV3Store(
      useShallow((state) => {
        const convId = state.activeConversationId;
        const convState = convId ? state.conversationStates.get(convId) : null;
        return {
          executionPathDecision: convState?.executionPathDecision ?? null,
          selectionTrace: convState?.selectionTrace ?? null,
          policyFiltered: convState?.policyFiltered ?? null,
          executionNarrative: convState?.executionNarrative ?? EMPTY_EXECUTION_NARRATIVE,
          latestToolsetChange: convState?.latestToolsetChange ?? null,
        };
      })
    );

    // Local UI state
    const [inputHeight, setInputHeight] = useState(INPUT_DEFAULT_HEIGHT);
    const [chatSearchVisible, setChatSearchVisible] = useState(false);
    const [showOnboarding, setShowOnboarding] = useState(
      () => !localStorage.getItem('memstack_onboarding_complete')
    );

    const inputBarRef = useRef<HTMLTextAreaElement>(null);

    // Auto-switch to task mode when tasks appear
    useEffect(() => {
      if (tasks.length > 0 && layoutMode === 'chat') {
        // Don't auto-switch, just let the user know via the layout selector
      }
    }, [tasks.length, layoutMode]);

    useEffect(() => {
      return subscribeToAgentChatSearchRequests(() => {
        setChatSearchVisible(true);
      });
    }, []);

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
          const newMode = useExecutionStore.getState().agentIsPlanMode ? 'build' : 'plan';
          void import('@/services/planService').then(({ planService }) => {
            planService
              .switchMode(convId, newMode)
              .then(() => {
                useAgentV3Store.getState().updateConversationState(convId, {
                  isPlanMode: newMode === 'plan',
                });
                useExecutionStore.getState().setAgentIsPlanMode(newMode === 'plan');
              })
              .catch((err: unknown) => {
                void message.error(
                  err instanceof Error ? err.message : 'Failed to switch plan mode'
                );
                console.error('AgentChatContent: switchMode failed', err);
              });
          });
          return;
        }

        // / to focus input (when not already in an input)
        if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) {
          const target = e.target as HTMLElement;
          const isInput =
            target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;
          if (!isInput) {
            e.preventDefault();
            inputBarRef.current?.focus();
          }
        }
      };
      window.addEventListener('keydown', handleKeyShortcut);
      return () => {
        window.removeEventListener('keydown', handleKeyShortcut);
      };
    }, [inputBarRef]);

    // Load conversations
    useEffect(() => {
      if (projectId) void loadConversations(projectId);
    }, [projectId, loadConversations]);

    useEffect(() => {
      if (!projectId || !conversationId) {
        return;
      }
      let active = true;
      agentService
        .getConversation(conversationId, projectId)
        .then((conversation) => {
          if (!active || !conversation) {
            return;
          }
          if (useAgentV3Store.getState().activeConversationId === conversationId) {
            useConversationsStore.getState().setCurrentConversation(conversation);
          }
        })
        .catch((error: unknown) => {
          console.error('AgentChatContent: failed to load active conversation', error);
        });
      return () => {
        active = false;
      };
    }, [conversationId, projectId]);

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
          freshState.activeConversationId === conversationId &&
          useStreamingStore.getState().agentIsStreaming;
        if (!alreadyStreaming) {
          void loadMessages(conversationId, projectId);
        }
        // Load any pending HITL requests to restore dialog state after refresh
        void loadPendingHITL(conversationId);
      } else if (projectId && !conversationId) {
        setActiveConversation(null);
      }
    }, [conversationId, projectId, setActiveConversation, loadMessages, loadPendingHITL]);

    // Auto-focus input when conversation finishes loading
    useEffect(() => {
      if (!isLoadingHistory && activeConversationId) {
        const timer = setTimeout(() => {
          inputBarRef.current?.focus();
        }, 100);
        return () => {
          clearTimeout(timer);
        };
      }
      return undefined;
    }, [isLoadingHistory, activeConversationId, inputBarRef]);

    // Return focus to input when agent finishes responding
    useEffect(() => {
      if (!isStreaming && activeConversationId) {
        const timer = setTimeout(() => {
          inputBarRef.current?.focus();
        }, 200);
        return () => {
          clearTimeout(timer);
        };
      }
      return undefined;
    }, [isStreaming, activeConversationId, inputBarRef]);

    // Handle errors
    useEffect(() => {
      if (error) {
        notification?.error({
          message: t('agent.chat.errors.title'),
          description: error,
          onClose: clearError,
        });
      }
    }, [error, clearError, t, notification]);

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
    }, [doomLoopDetected, notification, t]);

    const handleNewConversation = useCallback(async () => {
      if (!projectId) return;
      const newId = await createNewConversation(projectId);
      if (newId) {
        void navigate(`${basePath}/${newId}${newConversationNavigationSuffix}`);
      }
    }, [projectId, createNewConversation, navigate, basePath, newConversationNavigationSuffix]);

    const handleSend = useCallback(
      async (
        content: string,
        fileMetadata?: FileMetadata[],
        forcedSkillName?: string,
        forcedSubAgentName?: string,
        imageAttachments?: string[]
      ) => {
        if (!projectId) return;

        let finalContent = content;
        if (forcedSubAgentName) {
          finalContent = `[System Instruction: Delegate this task strictly to SubAgent "${forcedSubAgentName}"]
${content}`;
        }

        const newId = await sendMessage(finalContent, projectId, {
          onAct,
          onObserve,
          fileMetadata,
          forcedSkillName,
          imageAttachments,
          agentId: activeAgentId,
        });
        if (!conversationId && newId) {
          void navigate(`${basePath}/${newId}${navigationSuffix}`);
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
        navigationSuffix,
        activeAgentId,
      ]
    );

    // Memoized components
    const messageArea = useMemo(
      () =>
        timeline.length === 0 && !activeConversationId ? (
          <EmptyState
            onNewConversation={() => {
              void handleNewConversation();
            }}
            onSendPrompt={(...args) => {
              void handleSend(...args);
            }}
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
                void loadEarlierMessages(activeConversationId, projectId);
              }
            }}
            isLoadingEarlier={isLoadingEarlier}
            conversationId={activeConversationId}
            suggestions={suggestions}
            onSuggestionSelect={(...args) => {
              void handleSend(...args);
            }}
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
      ]
    );

    // Sandbox content for code/desktop/focus split modes
    const sandboxContent = useMemo(
      () => (
        <Suspense fallback={<AgentPanelFallback />}>
          <SandboxSection sandboxId={activeSandboxId || null} />
        </Suspense>
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
          showSandboxStatus={false}
          showTaskProgress={false}
        />
      ),
      [projectId, tenantId, timeline.length]
    );

    const taskProgress = useMemo(
      () => deriveTaskProgress(tasks, isStreaming),
      [tasks, isStreaming]
    );
    const routeConversation =
      currentConversation?.id === activeConversationId ? currentConversation : null;
    const activeWorkspaceId = routeConversation?.workspace_id ?? effectiveWorkspaceId ?? null;
    const activeWorkspaceTaskId = resolveCurrentWorkspaceTaskId(
      routeConversation,
      activeConversationId
    );

    // Split mode drag handler
    // Plan Mode toggle
    const isPlanMode = useIsPlanMode();

    const groupedTimeline = useMemo(() => groupTimelineEvents(timeline), [timeline]);
    const subagentSummaries = useMemo(
      () => getSubAgentSummaries(groupedTimeline),
      [groupedTimeline]
    );

    const handleScrollToSubAgent = useCallback((startIndex: number) => {
      const exact = document.querySelector(`[data-subagent-start-index="${String(startIndex)}"]`);
      if (exact instanceof HTMLElement) {
        exact.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }

      const nearest = document.querySelector(`[data-timeline-index="${String(startIndex)}"]`);
      if (nearest instanceof HTMLElement) {
        nearest.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, []);

    const handleTogglePlanMode = useCallback(async () => {
      const targetConversationId = activeConversationId || conversationId;
      if (!targetConversationId) return;
      const newMode = isPlanMode ? 'build' : 'plan';
      try {
        const { planService } = await import('@/services/planService');
        await planService.switchMode(targetConversationId, newMode);
        useAgentV3Store.getState().updateConversationState(targetConversationId, {
          isPlanMode: newMode === 'plan',
        });
        useExecutionStore.getState().setAgentIsPlanMode(newMode === 'plan');
      } catch (err) {
        void message.error(
          err instanceof Error ? err.message : t('agent.chat.errors.switchPlanModeFailed')
        );
        console.error('Failed to switch plan mode:', err);
      }
    }, [activeConversationId, conversationId, isPlanMode, t]);

    const chatColumn = (
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
        {headerExtra && (
          <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white dark:bg-slate-900 px-4 py-2 flex items-center gap-2">
            {headerExtra}
          </div>
        )}
        {(currentConversation || activeAgentNode?.name) && (
          <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white/60 dark:bg-slate-900/40 px-4 py-1.5 flex items-center gap-2">
            <ConversationAgentBadge conversation={currentConversation} />
            {activeAgentNode?.name && (
              <span className="flex items-center gap-1.5 bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 text-xs font-medium px-2 py-0.5 rounded-full">
                <Bot size={12} />
                {activeAgentNode.name}
              </span>
            )}
          </div>
        )}
        <div className="flex-1 overflow-hidden relative min-h-0">
          {messageArea}
          {subagentSummaries.length >= 3 && (
            <SubAgentMiniMap summaries={subagentSummaries} onScrollTo={handleScrollToSubAgent} />
          )}
          <ChatSearch
            timeline={timeline}
            visible={chatSearchVisible}
            onClose={() => {
              setChatSearchVisible(false);
            }}
          />
        </div>
        <div
          className="relative flex flex-shrink-0 flex-col border-t border-slate-200/60 bg-white shadow-md dark:border-slate-700/50 dark:bg-slate-900"
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
            ref={inputBarRef}
            onSend={(...args) => {
              void handleSend(...args);
            }}
            onAbort={abortStream}
            isStreaming={isStreaming}
            disabled={isLoadingHistory || isCreatingConversation}
            projectId={projectId || undefined}
            conversationId={activeConversationId || undefined}
            onTogglePlanMode={() => {
              void handleTogglePlanMode();
            }}
            isPlanMode={isPlanMode}
            activeAgentId={activeAgentId}
            onAgentSelect={setActiveAgentId}
          />
        </div>
      </div>
    );

    // Export conversation as Markdown
    const handleExportMarkdown = useCallback(() => {
      if (timeline.length === 0) return;
      downloadConversationMarkdown(
        timeline,
        undefined,
        `conversation-${activeConversationId || 'export'}.md`
      );
    }, [timeline, activeConversationId]);

    // Export conversation as PDF
    const handleExportPdf = useCallback(() => {
      if (timeline.length === 0) return;
      void downloadConversationPdf(
        timeline,
        undefined,
        `conversation-${activeConversationId || 'export'}.pdf`
      );
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
    const [evidenceOpen, setEvidenceOpen] = useState(false);

    // Pull all current artifacts and filter to this conversation. Map.values() is
    // a fresh iterator each render, so we memoize the filtered array.
    const allArtifactsMap = useSandboxStore((s) => s.artifacts);
    const conversationArtifacts = useMemo(() => {
      if (!activeConversationId) return [];
      return Array.from(allArtifactsMap.values()).filter(
        (a) => a.conversationId === activeConversationId
      );
    }, [allArtifactsMap, activeConversationId]);

    const sandboxConnectionStatus = useSandboxStore((s) => s.connectionStatus);
    const currentTool = useSandboxStore((s) => s.currentTool);
    const suggestionsCount = suggestions.length;

    const workspaceStatusSlots = useMemo(() => {
      const slots: Parameters<typeof WorkspaceStatusBar>[0] = {};
      if (taskProgress.hasTasks) {
        const taskPercent =
          taskProgress.total > 0
            ? Math.round((taskProgress.current / taskProgress.total) * 100)
            : 0;
        slots.task = {
          label: 'Task',
          value: `${String(taskProgress.current)}/${String(taskProgress.total)} · ${String(taskPercent)}%`,
          tone:
            taskProgress.status === 'failed'
              ? 'error'
              : taskProgress.status === 'completed'
                ? 'ok'
                : 'running',
          hint: taskProgress.label ?? 'Task progress',
          progressPercent: taskPercent,
        };
      }
      if (isStreaming) {
        slots.llm = { label: 'LLM', value: 'streaming', tone: 'running' };
      }
      if (sandboxConnectionStatus !== 'idle') {
        const tone: 'ok' | 'error' | 'running' =
          sandboxConnectionStatus === 'connected'
            ? 'ok'
            : sandboxConnectionStatus === 'error'
              ? 'error'
              : 'running';
        slots.sandbox = {
          label: 'Sandbox',
          value: currentTool
            ? `${sandboxConnectionStatus} · ${currentTool.name}`
            : sandboxConnectionStatus,
          tone,
        };
      }
      if (suggestionsCount > 0 || doomLoopDetected) {
        slots.hitl = {
          label: 'HITL',
          value: doomLoopDetected
            ? 'doom-loop'
            : `${String(suggestionsCount)} suggestion${suggestionsCount === 1 ? '' : 's'}`,
          tone: doomLoopDetected ? 'error' : 'warning',
        };
      }
      if (conversationArtifacts.length > 0) {
        slots.friction = {
          label: 'Evidence',
          value: `${String(conversationArtifacts.length)} artifact${
            conversationArtifacts.length === 1 ? '' : 's'
          }`,
          tone: 'idle',
          hint: 'Open the Evidence drawer to inspect screenshots, diffs, test runs and logs',
        };
      }
      return slots;
    }, [
      taskProgress,
      isStreaming,
      sandboxConnectionStatus,
      currentTool,
      suggestionsCount,
      doomLoopDetected,
      conversationArtifacts.length,
    ]);

    const statusBarWithLayout = (
      <div className="flex-shrink-0 border-t border-slate-200/60 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/80 min-w-0">
        <div className="flex items-center min-w-0">
          <WorkspaceStatusBar
            {...workspaceStatusSlots}
            className="min-w-0 flex-shrink border-0 bg-transparent px-2 py-0"
          />
          <div className="flex-1 min-w-0 overflow-hidden">{statusBar}</div>
          <div className="flex items-center gap-1 sm:gap-2 pr-2 sm:pr-3 flex-shrink-0">
            {conversationArtifacts.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setEvidenceOpen(true);
                }}
                className="flex items-center gap-1 p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title={t('evidence.open', 'Evidence')}
                aria-label={t('evidence.open', 'Evidence')}
                data-testid="open-evidence-drawer"
              >
                <Folder size={14} />
              </button>
            )}
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
                  onClick={() => {
                    setShowExportMenu((v) => !v);
                  }}
                  onBlur={() =>
                    setTimeout(() => {
                      setShowExportMenu(false);
                    }, 150)
                  }
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
                      onMouseDown={(e) => {
                        e.preventDefault();
                        handleExportMarkdown();
                        setShowExportMenu(false);
                      }}
                      className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                    >
                      {t('agent.actions.exportMarkdown', 'Export as Markdown')}
                    </button>
                    <button
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        handleExportPdf();
                        setShowExportMenu(false);
                      }}
                      className="w-full text-left px-3 py-1.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                    >
                      {t('agent.actions.exportPdf', 'Export as PDF')}
                    </button>
                  </div>
                )}
              </div>
            )}
            <LayoutModeSelector hasWorkspace={!!effectiveWorkspaceId} />
          </div>
        </div>
      </div>
    );

    // Comparison mode: side-by-side conversation view
    if (compareMode && activeConversationId) {
      return (
        <div className={`flex flex-col h-full w-full overflow-hidden ${className}`}>
          <Suspense fallback={<AgentPanelFallback />}>
            <ConversationCompareView
              projectId={projectId || ''}
              leftConversationId={activeConversationId}
              rightConversationId={compareConversationId}
              conversations={conversations}
              onClose={() => {
                setCompareMode(false);
                setCompareConversationId(null);
              }}
              onSelectRight={() => {
                setShowComparePicker(true);
              }}
            />
            <ConversationPickerModal
              visible={showComparePicker}
              currentConversationId={activeConversationId}
              conversations={conversations}
              onSelect={(id) => {
                setCompareConversationId(id);
              }}
              onClose={() => {
                setShowComparePicker(false);
              }}
            />
          </Suspense>
          {statusBarWithLayout}
        </div>
      );
    }

    // Task mode: chat + task panel split
    if (layoutMode === 'task') {
      return (
        <SplitPaneLayout
          leftContent={chatColumn}
          rightContent={
            <Suspense fallback={<AgentPanelFallback />}>
              <RightPanel
                tasks={tasks}
                conversationId={activeConversationId}
                sandboxId={activeSandboxId}
                workspaceId={activeWorkspaceId}
                currentWorkspaceTaskId={activeWorkspaceTaskId}
                executionPathDecision={executionPathDecision}
                selectionTrace={selectionTrace}
                policyFiltered={policyFiltered}
                executionNarrative={executionNarrative}
                latestToolsetChange={latestToolsetChange}
                agentNodes={rawAgentNodes}
                collapsed={false}
              />
            </Suspense>
          }
          splitRatio={splitRatio}
          onSplitRatioChange={setSplitRatio}
          handleAccentColor="purple"
          className={className}
          statusBar={statusBarWithLayout}
        />
      );
    }

    // Code split mode
    if (layoutMode === 'code') {
      return (
        <SplitPaneLayout
          leftContent={chatColumn}
          rightContent={sandboxContent}
          splitRatio={splitRatio}
          onSplitRatioChange={setSplitRatio}
          handleAccentColor="primary"
          rightClassName="bg-slate-900"
          className={className}
          statusBar={statusBarWithLayout}
        />
      );
    }

    // Canvas mode: chat + artifact canvas split
    if (layoutMode === 'canvas') {
      return (
        <SplitPaneLayout
          leftContent={chatColumn}
          rightContent={
            <Suspense fallback={<AgentPanelFallback />}>
              <CanvasPanel
                onSendPrompt={(prompt) => {
                  void handleSend(prompt);
                }}
                onUpdateModelContext={(ctx) => {
                  const convId = useAgentV3Store.getState().activeConversationId;
                  if (convId) {
                    const convState = useAgentV3Store.getState().conversationStates.get(convId);
                    const currentCtx = convState?.appModelContext ?? {};
                    const controlFields: Record<string, unknown> = {};
                    if ('llm_overrides' in currentCtx) {
                      controlFields.llm_overrides = currentCtx.llm_overrides;
                    }
                    if ('llm_model_override' in currentCtx) {
                      controlFields.llm_model_override = currentCtx.llm_model_override;
                    }
                    const mergedCtx = { ...ctx, ...controlFields };
                    useAgentV3Store.getState().updateConversationState(convId, {
                      appModelContext: Object.keys(mergedCtx).length > 0 ? mergedCtx : null,
                    });
                  }
                }}
              />
            </Suspense>
          }
          splitRatio={splitRatio}
          onSplitRatioChange={setSplitRatio}
          handleAccentColor="violet"
          leftMinWidth="280px"
          rightMinWidth="320px"
          className={className}
          statusBar={statusBarWithLayout}
        />
      );
    }

    // Collab mode: chat + workspace group chat
    if (layoutMode === 'collab') {
      return (
        <SplitPaneLayout
          leftContent={chatColumn}
          rightContent={
            <Suspense fallback={<AgentPanelFallback />}>
              <WorkspaceGroupChatPanel
                tenantId={tenantId}
                projectId={projectId || ''}
                workspaceId={effectiveWorkspaceId}
                onWorkspaceChange={setCollabWorkspaceOverride}
              />
            </Suspense>
          }
          splitRatio={splitRatio}
          onSplitRatioChange={setSplitRatio}
          handleAccentColor="primary"
          leftMinWidth="280px"
          rightMinWidth="260px"
          className={className}
          statusBar={statusBarWithLayout}
        />
      );
    }

    // Chat mode (default): classic layout
    return (
      <div
        className={`flex flex-col h-full w-full overflow-hidden ${LAYOUT_BG_CLASSES} ${className}`}
      >
        {/* Keyboard shortcut overlay (Cmd+/) */}
        <ShortcutOverlay />

        {/* Evidence bundle drawer */}
        <EvidenceBundleDrawer
          open={evidenceOpen}
          onClose={() => {
            setEvidenceOpen(false);
          }}
          artifacts={conversationArtifacts}
        />

        {/* First-time user onboarding tour */}
        {showOnboarding && !activeConversationId && (
          <OnboardingTour onComplete={handleOnboardingComplete} />
        )}

        {/* Main Content Area */}
        <main
          className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative"
          aria-label={t('agent.focusDesktop.chat', { defaultValue: 'Chat' })}
        >
          {chatColumn}
          {statusBarWithLayout}
        </main>
      </div>
    );
  }
);

AgentChatContent.displayName = 'AgentChatContent';

export default AgentChatContent;
