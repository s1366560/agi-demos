/**
 * RightPanel - Side panel with Tasks
 *
 * Features:
 * - Agent-managed task checklist (DB-persistent, SSE-streamed)
 * - Execution insights (routing + selection + policy)
 * - Draggable resize support
 */

import { useEffect, memo, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Bot, Filter, GitBranch, ListTodo, Route, X } from 'lucide-react';

import { useActiveGraphRunForConversation } from '@/stores/graphStore';
import { useTenantStore } from '@/stores/tenant';
import { useWorkspaceStore } from '@/stores/workspace';

import { agentService } from '@/services/agentService';
import {
  workspacePlanService,
  workspaceService,
  workspaceTaskService,
} from '@/services/workspaceService';

import { LazyButton } from '@/components/ui/lazyAntd';

import { useUrlState } from '../../hooks/useUrlState';

import { AgentGraphView } from './AgentGraphView';
import { MultiAgentPanel } from './multiAgent/MultiAgentPanel';
import { buildWorkspaceAgentNodes } from './multiAgent/workspaceAgentPanelModel';
import { Resizer } from './Resizer';
import { TaskList } from './TaskList';
import { TaskLanePanel } from './tasks/TaskLanePanel';
import { WorkspaceTaskPlanPanel } from './workspace/WorkspaceTaskPlanPanel';
import { buildWorkspaceTaskPlanRows } from './workspace/WorkspaceTaskPlanPanelModel';

import type { WorkspaceAgent, WorkspacePlanSnapshot, WorkspaceTask } from '@/types/workspace';

import type {
  AgentTask,
  ExecutionNarrativeEntry,
  ExecutionPathDecidedEventData,
  PolicyFilteredEventData,
  SelectionTraceEventData,
  ToolsetChangedEventData,
  TimelineEvent as AgentTimelineEvent,
} from '../../types/agent';
import type { AgentNode } from '../../types/multiAgent';
import type { TFunction } from 'i18next';

export interface RightPanelProps {
  tasks?: AgentTask[] | undefined;
  conversationId?: string | null | undefined;
  sandboxId?: string | null | undefined;
  workspaceId?: string | null | undefined;
  currentWorkspaceTaskId?: string | null | undefined;
  projectId?: string | null | undefined;
  selectedAgentSessionId?: string | null | undefined;
  onAgentSessionSelect?: ((sessionId: string) => void) | undefined;
  getAgentSessionHref?: ((sessionId: string) => string) | undefined;
  executionPathDecision?: ExecutionPathDecidedEventData | null | undefined;
  selectionTrace?: SelectionTraceEventData | null | undefined;
  policyFiltered?: PolicyFilteredEventData | null | undefined;
  executionNarrative?: ExecutionNarrativeEntry[] | undefined;
  latestToolsetChange?: ToolsetChangedEventData | null | undefined;
  agentNodes?: Map<string, AgentNode> | undefined;
  onClose?: (() => void) | undefined;
  onFileClick?: ((filePath: string) => void) | undefined;
  collapsed?: boolean | undefined;
  width?: number | undefined;
  onWidthChange?: ((width: number) => void) | undefined;
  minWidth?: number | undefined;
  maxWidth?: number | undefined;
}

type PanelTab = 'tasks' | 'agent' | 'insights' | 'agents' | 'graph';

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

interface ExecutionInsightsProps {
  executionPathDecision?: ExecutionPathDecidedEventData | null | undefined;
  selectionTrace?: SelectionTraceEventData | null | undefined;
  policyFiltered?: PolicyFilteredEventData | null | undefined;
  executionNarrative?: ExecutionNarrativeEntry[] | undefined;
  latestToolsetChange?: ToolsetChangedEventData | null | undefined;
}

const ExecutionInsights = memo<ExecutionInsightsProps>(
  ({
    executionPathDecision,
    selectionTrace,
    policyFiltered,
    executionNarrative,
    latestToolsetChange,
  }) => {
    const { t } = useTranslation();
    const metadataLane =
      executionPathDecision?.metadata &&
      typeof executionPathDecision.metadata['domain_lane'] === 'string'
        ? executionPathDecision.metadata['domain_lane']
        : null;
    const lane = metadataLane ?? selectionTrace?.domain_lane ?? policyFiltered?.domain_lane ?? null;
    const traceId =
      executionPathDecision?.trace_id ??
      selectionTrace?.trace_id ??
      policyFiltered?.trace_id ??
      null;
    const narrativeEntries = (executionNarrative ?? []).slice(-8).reverse();

    if (
      !executionPathDecision &&
      !selectionTrace &&
      !policyFiltered &&
      !latestToolsetChange &&
      narrativeEntries.length === 0
    ) {
      return (
        <div
          data-testid="execution-insights"
          className="rounded-lg border border-slate-200/60 dark:border-slate-700/50 p-4 text-sm text-slate-500 dark:text-slate-400"
        >
          {tFallback(
            t,
            'agent.rightPanel.insights.empty',
            'Execution diagnostics will appear after the agent makes routing and tool-selection decisions.'
          )}
        </div>
      );
    }

    return (
      <div
        data-testid="execution-insights"
        className="space-y-3 rounded-lg border border-slate-200/60 dark:border-slate-700/50 p-3"
      >
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {tFallback(t, 'agent.rightPanel.insights.title', 'Execution Insights')}
        </h3>

        {executionPathDecision ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <Route size={13} />
              <span>{tFallback(t, 'agent.rightPanel.insights.routing', 'Routing')}</span>
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {tFallback(t, 'agent.rightPanel.insights.path', 'Path')}:{' '}
              <span className="font-medium">{executionPathDecision.path}</span> ·{' '}
              {tFallback(t, 'agent.rightPanel.insights.confidence', 'Confidence')}:{' '}
              <span className="font-medium">{executionPathDecision.confidence.toFixed(2)}</span>
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              {executionPathDecision.reason}
            </div>
            {executionPathDecision.route_id ? (
              <div className="mt-1 text-xs-plus text-slate-500 dark:text-slate-400">
                route_id: <span className="font-mono">{executionPathDecision.route_id}</span>
              </div>
            ) : null}
            {traceId ? (
              <div className="mt-1 text-xs-plus text-slate-500 dark:text-slate-400">
                trace_id: <span className="font-mono">{traceId}</span>
              </div>
            ) : null}
            {lane ? (
              <div className="mt-1 text-xs-plus text-slate-500 dark:text-slate-400">
                domain_lane: <span className="font-medium">{lane}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {selectionTrace ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {tFallback(t, 'agent.rightPanel.insights.selection', 'Selection')}
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {t('agent.rightPanel.insights.selectionSummary', {
                defaultValue: '{{final}}/{{initial}} tools kept · removed {{removed}}',
                final: selectionTrace.final_count,
                initial: selectionTrace.initial_count,
                removed: selectionTrace.removed_total,
              })}
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              {t('agent.rightPanel.insights.stageSummary', {
                defaultValue: '{{count}} stage(s) executed',
                count: selectionTrace.stages.length,
              })}
            </div>
            {typeof selectionTrace.tool_budget === 'number' ? (
              <div className="mt-1 text-xs-plus text-slate-500 dark:text-slate-400">
                tool_budget: <span className="font-medium">{selectionTrace.tool_budget}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {policyFiltered ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <Filter size={13} />
              <span>{tFallback(t, 'agent.rightPanel.insights.policy', 'Policy')}</span>
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {t('agent.rightPanel.insights.policySummary', {
                defaultValue: 'Filtered {{removed}} tool(s) across {{stages}} stage(s)',
                removed: policyFiltered.removed_total,
                stages: policyFiltered.stage_count,
              })}
            </div>
            {policyFiltered.budget_exceeded_stages?.length ? (
              <div className="mt-1 text-xs-plus text-amber-600 dark:text-amber-400">
                budget_exceeded: {policyFiltered.budget_exceeded_stages.join(', ')}
              </div>
            ) : null}
          </div>
        ) : null}

        {latestToolsetChange ? (
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3">
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {tFallback(t, 'agent.rightPanel.insights.toolset', 'Toolset')}
            </div>
            <div className="mt-1 text-sm text-slate-800 dark:text-slate-100">
              {latestToolsetChange.action || 'update'}
              {latestToolsetChange.plugin_name ? ` ${latestToolsetChange.plugin_name}` : ''}
            </div>
            <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
              refresh: {latestToolsetChange.refresh_status || 'not_applicable'}
              {typeof latestToolsetChange.refreshed_tool_count === 'number'
                ? ` (${String(latestToolsetChange.refreshed_tool_count)} tools)`
                : ''}
            </div>
            {latestToolsetChange.trace_id ? (
              <div className="mt-1 text-xs-plus text-slate-500 dark:text-slate-400">
                trace_id: <span className="font-mono">{latestToolsetChange.trace_id}</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {narrativeEntries.length ? (
          <div
            className="rounded-md bg-slate-50 dark:bg-slate-800/50 p-3"
            data-testid="execution-narrative"
          >
            <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {tFallback(t, 'agent.rightPanel.insights.narrative', 'Execution Narrative')}
            </div>
            <div className="mt-2 space-y-2">
              {narrativeEntries.map((entry) => (
                <div
                  key={entry.id}
                  className="rounded border border-slate-200/70 dark:border-slate-700/70 p-2"
                >
                  <div className="text-xs-plus uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {entry.stage}
                  </div>
                  <div className="text-xs text-slate-700 dark:text-slate-200">{entry.summary}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    );
  }
);

ExecutionInsights.displayName = 'ExecutionInsights';

function agentEventRole(event: AgentTimelineEvent): string {
  if (event.type === 'user_message') return 'User';
  if (event.type === 'assistant_message' || event.type === 'text_end') return 'Agent';
  if (event.type === 'act') return 'Tool';
  if (event.type === 'observe') return 'Result';
  return event.type.replace(/_/g, ' ');
}

function agentEventContent(event: AgentTimelineEvent): string {
  if ('content' in event && typeof event.content === 'string') {
    return event.content;
  }
  if (event.type === 'text_end' && typeof event.fullText === 'string') {
    return event.fullText;
  }
  if (event.type === 'act') {
    return JSON.stringify({ tool: event.toolName, input: event.toolInput }, null, 2);
  }
  if (event.type === 'observe') {
    return event.toolOutput || (event.isError ? 'Tool failed' : 'Tool completed');
  }
  return '';
}

function agentEventTimestamp(event: AgentTimelineEvent, locale: string): string {
  const date = new Date(event.timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

const AgentSessionMessagesPanel = memo<{
  projectId?: string | null | undefined;
  sessionId?: string | null | undefined;
}>(({ projectId, sessionId }) => {
  const { t, i18n } = useTranslation();
  const [events, setEvents] = useState<AgentTimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    if (!projectId || !sessionId) {
      return;
    }

    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    void Promise.resolve().then(async () => {
      if (requestSeqRef.current !== requestSeq) return;
      setLoading(true);
      setError(null);
      try {
        const response = await agentService.getConversationMessages(sessionId, projectId, 100);
        if (requestSeqRef.current !== requestSeq) return;
        setEvents(response.timeline);
      } catch (err) {
        if (requestSeqRef.current !== requestSeq) return;
        setEvents([]);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (requestSeqRef.current === requestSeq) setLoading(false);
      }
    });

    return () => {
      requestSeqRef.current += 1;
    };
  }, [projectId, sessionId, retryCount]);

  if (!sessionId) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-4 py-12 text-center">
        <Bot size={30} className="mb-3 text-slate-300 dark:text-slate-600" />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {tFallback(
            t,
            'agent.rightPanel.agentSession.empty',
            'Click an agent interaction card to inspect its session messages.'
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200/60 px-4 py-3 dark:border-slate-700/50">
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-slate-500 dark:text-slate-400" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {tFallback(t, 'agent.rightPanel.agentSession.title', 'Agent session')}
            </p>
            <code className="block truncate text-[11px] text-slate-500 dark:text-slate-400">
              {sessionId}
            </code>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="space-y-2" role="status">
            <div className="h-12 rounded-md bg-slate-100 dark:bg-slate-800" />
            <div className="h-16 rounded-md bg-slate-100 dark:bg-slate-800" />
          </div>
        ) : error ? (
          <div
            className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800/50 dark:bg-amber-950/30 dark:text-amber-300"
            role="alert"
          >
            <p className="break-words">{error}</p>
            <button
              type="button"
              onClick={() => {
                setRetryCount((count) => count + 1);
              }}
              className="mt-2 rounded-md border border-amber-300 px-2 py-1 font-medium text-amber-800 transition-colors hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60 dark:border-amber-700 dark:text-amber-200 dark:hover:bg-amber-900/40"
            >
              {tFallback(t, 'agent.rightPanel.agentSession.retry', 'Retry')}
            </button>
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {tFallback(
              t,
              'agent.rightPanel.agentSession.noMessages',
              'No messages recorded for this session yet.'
            )}
          </p>
        ) : (
          <div className="space-y-2">
            {events.map((event) => {
              const content = agentEventContent(event);
              if (!content) return null;
              return (
                <article
                  key={event.id}
                  className="rounded-md border border-slate-200/70 bg-white px-3 py-2 dark:border-slate-700/60 dark:bg-slate-900/35"
                >
                  <div className="mb-1 flex min-w-0 items-center gap-2">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {agentEventRole(event)}
                    </span>
                    <span className="ml-auto shrink-0 text-[11px] text-slate-400 dark:text-slate-500">
                      {agentEventTimestamp(event, i18n.language || 'en')}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-xs leading-5 text-slate-700 dark:text-slate-200">
                    {content}
                  </p>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
});
AgentSessionMessagesPanel.displayName = 'AgentSessionMessagesPanel';

export const RightPanel = memo<RightPanelProps>(
  ({
    tasks = [],
    conversationId,
    workspaceId,
    currentWorkspaceTaskId,
    projectId,
    selectedAgentSessionId,
    onAgentSessionSelect,
    getAgentSessionHref,
    executionPathDecision,
    selectionTrace,
    policyFiltered,
    executionNarrative,
    latestToolsetChange,
    agentNodes,
    onClose,
    collapsed,
    width = 360,
    onWidthChange,
    minWidth = 280,
    maxWidth = 600,
  }) => {
    const { t } = useTranslation();
    const hasInsights = Boolean(
      executionPathDecision ||
      selectionTrace ||
      policyFiltered ||
      latestToolsetChange ||
      (executionNarrative && executionNarrative.length > 0)
    );
    const hasAgentSession = Boolean(selectedAgentSessionId);
    const tenantId = useTenantStore((state) => state.currentTenant?.id);
    const storeWorkspaceId = useWorkspaceStore((state) => state.currentWorkspace?.id);
    const storeWorkspaceAgents = useWorkspaceStore((state) => state.agents);
    const activeGraphRun = useActiveGraphRunForConversation(conversationId);
    const isWorkspaceActive = Boolean(workspaceId);
    const hasGraph = Boolean(activeGraphRun) || isWorkspaceActive;
    const [workspaceTasks, setWorkspaceTasks] = useState<WorkspaceTask[]>([]);
    const [workspaceAgents, setWorkspaceAgents] = useState<WorkspaceAgent[]>([]);
    const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
    const [workspaceLoading, setWorkspaceLoading] = useState(false);
    const [workspaceError, setWorkspaceError] = useState<string | null>(null);
    const [workspaceDataId, setWorkspaceDataId] = useState<string | null>(null);
    const workspaceRequestSeqRef = useRef(0);
    const activeWorkspaceTasks = useMemo(
      () => (workspaceDataId === workspaceId ? workspaceTasks : []),
      [workspaceDataId, workspaceId, workspaceTasks]
    );
    const activeWorkspaceAgents = useMemo(() => {
      if (!isWorkspaceActive) return [];
      if (workspaceDataId === workspaceId && workspaceAgents.length > 0) return workspaceAgents;
      return storeWorkspaceId === workspaceId ? storeWorkspaceAgents : [];
    }, [
      isWorkspaceActive,
      storeWorkspaceAgents,
      storeWorkspaceId,
      workspaceAgents,
      workspaceDataId,
      workspaceId,
    ]);
    const activeWorkspaceSnapshot = workspaceDataId === workspaceId ? workspaceSnapshot : null;
    const workspaceAgentNodes = useMemo(
      () =>
        buildWorkspaceAgentNodes({
          workspaceId,
          conversationId,
          agents: activeWorkspaceAgents,
          tasks: activeWorkspaceTasks,
          snapshot: activeWorkspaceSnapshot,
        }),
      [
        activeWorkspaceAgents,
        activeWorkspaceSnapshot,
        activeWorkspaceTasks,
        conversationId,
        workspaceId,
      ]
    );
    const displayAgentNodes = useMemo(() => {
      const merged = new Map(workspaceAgentNodes);
      agentNodes?.forEach((node, key) => {
        merged.set(key, node);
      });
      return merged;
    }, [agentNodes, workspaceAgentNodes]);
    const hasAgents = displayAgentNodes.size > 0;
    const activeWorkspaceLoading =
      isWorkspaceActive && (workspaceLoading || workspaceDataId !== workspaceId);
    const activeWorkspaceError = workspaceDataId === workspaceId ? workspaceError : null;
    const workspaceRows = useMemo(
      () =>
        buildWorkspaceTaskPlanRows(
          activeWorkspaceTasks,
          activeWorkspaceSnapshot,
          currentWorkspaceTaskId
        ),
      [activeWorkspaceTasks, activeWorkspaceSnapshot, currentWorkspaceTaskId]
    );
    const visibleTaskCount = isWorkspaceActive ? workspaceRows.length : tasks.length;
    const initialTab: PanelTab = isWorkspaceActive
      ? hasAgentSession
        ? 'agent'
        : 'tasks'
      : hasGraph && tasks.length === 0
        ? 'graph'
        : hasInsights && tasks.length === 0
          ? 'insights'
          : 'tasks';
    const [preferredTab, setPreferredTab] = useUrlState<PanelTab>('panel', initialTab, {
      allowed: ['tasks', 'agent', 'insights', 'agents', 'graph'],
    });
    const [taskView, setTaskView] = useUrlState<'flat' | 'lanes'>('tasks', 'flat', {
      allowed: ['flat', 'lanes'],
    });
    const activeTab: PanelTab =
      preferredTab === 'agent' && !hasAgentSession
        ? 'tasks'
        : preferredTab === 'insights' && !hasInsights
          ? 'tasks'
          : preferredTab === 'agents' && !hasAgents
            ? 'tasks'
            : preferredTab === 'graph' && !hasGraph
              ? 'tasks'
              : preferredTab;

    useEffect(() => {
      if (selectedAgentSessionId) {
        setPreferredTab('agent');
      }
    }, [selectedAgentSessionId, setPreferredTab]);

    useEffect(() => {
      if (!workspaceId) return;

      const requestSeq = workspaceRequestSeqRef.current + 1;
      workspaceRequestSeqRef.current = requestSeq;

      void Promise.resolve().then(async () => {
        setWorkspaceLoading(true);
        setWorkspaceError(null);

        const agentsRequest =
          tenantId && projectId
            ? workspaceService.listAgents(tenantId, projectId, workspaceId)
            : Promise.resolve([] as WorkspaceAgent[]);

        const [tasksResult, snapshotResult, agentsResult] = await Promise.allSettled([
          workspaceTaskService.list(workspaceId),
          workspacePlanService.getSnapshot(workspaceId, {
            outboxLimit: 0,
            eventLimit: 0,
            includeDetails: false,
            recoverStaleAttempts: false,
          }),
          agentsRequest,
        ]);

        if (workspaceRequestSeqRef.current !== requestSeq) return;

        setWorkspaceDataId(workspaceId);
        if (tasksResult.status === 'fulfilled') {
          setWorkspaceTasks(tasksResult.value);
        } else {
          setWorkspaceTasks([]);
        }

        if (agentsResult.status === 'fulfilled') {
          setWorkspaceAgents(agentsResult.value);
        } else {
          setWorkspaceAgents([]);
        }

        if (snapshotResult.status === 'fulfilled') {
          setWorkspaceSnapshot(snapshotResult.value);
        } else {
          setWorkspaceSnapshot(null);
        }

        setWorkspaceError(
          tasksResult.status === 'rejected' || snapshotResult.status === 'rejected'
            ? 'workspace-load-failed'
            : null
        );
        setWorkspaceLoading(false);
      });

      return () => {
        workspaceRequestSeqRef.current += 1;
      };
    }, [projectId, tenantId, workspaceId]);

    if (collapsed) {
      return null;
    }

    return (
      <div
        className="h-full w-full flex bg-white dark:bg-slate-900 relative"
        data-testid="right-panel"
      >
        {onWidthChange ? (
          <Resizer
            direction="horizontal"
            currentSize={width}
            minSize={minWidth}
            maxSize={maxWidth}
            onResize={onWidthChange}
            position="left"
            className="left-0 -ml-1.5"
          />
        ) : null}

        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                <ListTodo size={16} className="text-slate-600 dark:text-slate-300" />
              </div>
              <div className="flex flex-col min-w-0">
                <h2 className="font-semibold text-slate-900 dark:text-slate-100 leading-tight">
                  {tFallback(t, 'agent.rightPanel.tabs.tasks', 'Tasks')}
                </h2>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {t('agent.rightPanel.taskCount', {
                    defaultValue: '{{count}} item',
                    count: visibleTaskCount,
                  })}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div
                className="inline-flex items-center rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-800/70"
                role="tablist"
                aria-label={tFallback(t, 'agent.rightPanel.tabs.ariaLabel', 'Panel views')}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'tasks'}
                  onClick={() => {
                    setPreferredTab('tasks');
                  }}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'tasks'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  }`}
                >
                  {tFallback(t, 'agent.rightPanel.tabs.tasks', 'Tasks')}
                </button>
                {activeTab === 'tasks' ? (
                  <button
                    type="button"
                    onClick={() => {
                      setTaskView(taskView === 'lanes' ? 'flat' : 'lanes');
                    }}
                    title={
                      taskView === 'lanes'
                        ? tFallback(t, 'agent.rightPanel.switchToList', 'Switch to list view')
                        : tFallback(t, 'agent.rightPanel.switchToLane', 'Switch to lane view')
                    }
                    aria-label={
                      taskView === 'lanes'
                        ? tFallback(t, 'agent.rightPanel.switchToList', 'Switch to list view')
                        : tFallback(t, 'agent.rightPanel.switchToLane', 'Switch to lane view')
                    }
                    aria-pressed={taskView === 'lanes'}
                    className="ml-1 px-2 py-1 text-xs rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
                    data-testid="task-view-toggle"
                  >
                    {taskView === 'lanes'
                      ? tFallback(t, 'agent.rightPanel.list', 'List')
                      : tFallback(t, 'agent.rightPanel.lanes', 'Lanes')}
                  </button>
                ) : null}
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'agent'}
                  onClick={() => {
                    if (hasAgentSession) {
                      setPreferredTab('agent');
                    }
                  }}
                  disabled={!hasAgentSession}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'agent'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  } ${!hasAgentSession ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <span className="inline-flex items-center gap-1">
                    <Bot size={12} aria-hidden />
                    {tFallback(t, 'agent.rightPanel.tabs.agent', 'Agent')}
                  </span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'insights'}
                  onClick={() => {
                    if (hasInsights) {
                      setPreferredTab('insights');
                    }
                  }}
                  disabled={!hasInsights}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'insights'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  } ${!hasInsights ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {tFallback(t, 'agent.rightPanel.tabs.insights', 'Insights')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'agents'}
                  onClick={() => {
                    if (hasAgents) {
                      setPreferredTab('agents');
                    }
                  }}
                  disabled={!hasAgents}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'agents'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  } ${!hasAgents ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {tFallback(t, 'agent.rightPanel.tabs.agents', 'Agents')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'graph'}
                  onClick={() => {
                    if (hasGraph) {
                      setPreferredTab('graph');
                    }
                  }}
                  disabled={!hasGraph}
                  className={`px-2 py-1 text-xs rounded-md transition-colors ${
                    activeTab === 'graph'
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100'
                      : 'text-slate-500 dark:text-slate-400'
                  } ${!hasGraph ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <span className="inline-flex items-center gap-1">
                    <GitBranch size={12} aria-hidden />
                    {tFallback(t, 'agent.rightPanel.tabs.graph', 'Graph')}
                  </span>
                </button>
              </div>

              <div className="flex items-center gap-1">
                {onClose ? (
                  <LazyButton
                    type="text"
                    size="small"
                    icon={<X size={18} />}
                    onClick={onClose}
                    aria-label={tFallback(t, 'agent.rightPanel.close', 'Close panel')}
                    className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
                    data-testid="close-button"
                  />
                ) : null}
              </div>
            </div>
          </div>

          {activeTab === 'agent' ? (
            <div className="min-h-0 flex-1 overflow-hidden">
              <AgentSessionMessagesPanel projectId={projectId} sessionId={selectedAgentSessionId} />
            </div>
          ) : activeTab === 'insights' ? (
            <div className="flex-1 overflow-y-auto p-3">
              <ExecutionInsights
                executionPathDecision={executionPathDecision}
                selectionTrace={selectionTrace}
                policyFiltered={policyFiltered}
                executionNarrative={executionNarrative}
                latestToolsetChange={latestToolsetChange}
              />
            </div>
          ) : activeTab === 'agents' ? (
            <div className="flex-1 overflow-y-auto">
              <MultiAgentPanel
                agentNodes={displayAgentNodes}
                onSessionSelect={onAgentSessionSelect}
                getSessionHref={getAgentSessionHref}
              />
            </div>
          ) : activeTab === 'graph' ? (
            <div className="min-h-0 flex-1 overflow-hidden">
              <AgentGraphView
                conversationId={conversationId}
                workspaceId={workspaceId}
                currentWorkspaceTaskId={currentWorkspaceTaskId}
              />
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {isWorkspaceActive ? (
                <WorkspaceTaskPlanPanel
                  rows={workspaceRows}
                  snapshot={activeWorkspaceSnapshot}
                  loading={activeWorkspaceLoading}
                  error={activeWorkspaceError}
                  view={taskView}
                />
              ) : taskView === 'lanes' ? (
                <TaskLanePanel tasks={tasks} />
              ) : (
                <TaskList tasks={tasks} />
              )}
            </div>
          )}
        </div>
      </div>
    );
  }
);

RightPanel.displayName = 'RightPanel';

export default RightPanel;
