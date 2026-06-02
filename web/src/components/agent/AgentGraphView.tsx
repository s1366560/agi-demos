import { memo, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, GitBranch, Loader2, Network } from 'lucide-react';

import { useActiveGraphRunForConversation } from '@/stores/graphStore';
import { useWorkspaceStore } from '@/stores/workspace';

import { agentGraphApi } from '@/services/agent/graph/agentGraphApi';
import type { AgentGraphApiResponse } from '@/services/agent/graph/agentGraphApi';
import { workspacePlanService } from '@/services/workspaceService';

import { buildChatExecutionDag } from '@/components/executionDag/chatExecutionDagModel';
import { ExecutionDagGraph } from '@/components/executionDag/ExecutionDagGraph';
import { buildWorkspaceExecutionDag } from '@/components/executionDag/workspaceExecutionDagModel';

import type { WorkspacePlanSnapshot } from '@/types/workspace';

export interface AgentGraphViewProps {
  conversationId?: string | null | undefined;
  workspaceId?: string | null | undefined;
  currentWorkspaceTaskId?: string | null | undefined;
}

function formatDuration(seconds: number | undefined): string {
  if (seconds == null) {
    return '--';
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  return `${String(Math.floor(seconds / 60))}m ${String(Math.round(seconds % 60))}s`;
}

function resolveCurrentWorkspaceNodeId(
  model: ReturnType<typeof buildWorkspaceExecutionDag>,
  currentWorkspaceTaskId: string | null | undefined
): string | null {
  if (!model) {
    return null;
  }

  if (currentWorkspaceTaskId) {
    const linkedNode = model.nodes.find(
      (node) =>
        node.workspaceTaskId === currentWorkspaceTaskId ||
        node.sourceNodeId === currentWorkspaceTaskId
    );
    if (linkedNode) {
      return linkedNode.id;
    }
  }

  const activeNodes = model.nodes.filter((node) => {
    if (node.selectable === false) {
      return false;
    }
    return (
      node.execution === 'running' ||
      node.execution === 'dispatched' ||
      node.execution === 'verifying' ||
      node.status === 'in_progress'
    );
  });
  return activeNodes.length === 1 ? (activeNodes[0]?.id ?? null) : null;
}

export const AgentGraphView = memo<AgentGraphViewProps>(
  ({ conversationId, workspaceId, currentWorkspaceTaskId }) => {
    const { t } = useTranslation();
    const run = useActiveGraphRunForConversation(conversationId);
    const shouldUseGraphRun = !workspaceId && Boolean(run);
    const [graphDefinition, setGraphDefinition] = useState<AgentGraphApiResponse | null>(null);
    const [isGraphLoading, setIsGraphLoading] = useState(false);
    const [graphError, setGraphError] = useState<string | null>(null);
    const [workspaceSnapshot, setWorkspaceSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
    const [isWorkspaceLoading, setIsWorkspaceLoading] = useState(false);
    const [workspaceError, setWorkspaceError] = useState<string | null>(null);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const workspaceAgents = useWorkspaceStore((state) => state.agents);
    const workspacePlanRefresh = useWorkspaceStore((state) =>
      workspaceId ? (state.planRefreshCounters[workspaceId] ?? 0) : 0
    );

    useEffect(() => {
      if (!shouldUseGraphRun || !run?.graphId) {
        let active = true;
        queueMicrotask(() => {
          if (active) {
            setGraphDefinition(null);
            setGraphError(null);
          }
        });
        return () => {
          active = false;
        };
      }
      let active = true;
      queueMicrotask(() => {
        if (active) {
          setIsGraphLoading(true);
          setGraphError(null);
        }
      });
      agentGraphApi
        .getGraph(run.graphId)
        .then((definition) => {
          if (active) {
            setGraphDefinition(definition);
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setGraphDefinition(null);
            setGraphError(error instanceof Error ? error.message : 'Graph definition unavailable');
          }
        })
        .finally(() => {
          if (active) {
            setIsGraphLoading(false);
          }
        });
      return () => {
        active = false;
      };
    }, [run?.graphId, shouldUseGraphRun]);

    useEffect(() => {
      if (shouldUseGraphRun || !workspaceId) {
        let active = true;
        queueMicrotask(() => {
          if (active) {
            setWorkspaceSnapshot(null);
            setWorkspaceError(null);
          }
        });
        return () => {
          active = false;
        };
      }
      let active = true;
      queueMicrotask(() => {
        if (active) {
          setIsWorkspaceLoading(true);
          setWorkspaceError(null);
        }
      });
      workspacePlanService
        .getSnapshot(workspaceId, {
          outboxLimit: 0,
          eventLimit: 0,
          includeDetails: false,
          recoverStaleAttempts: false,
        })
        .then((snapshot) => {
          if (active) {
            setWorkspaceSnapshot(snapshot);
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setWorkspaceError(
              error instanceof Error ? error.message : 'Workspace graph unavailable'
            );
          }
        })
        .finally(() => {
          if (active) {
            setIsWorkspaceLoading(false);
          }
        });
      return () => {
        active = false;
      };
    }, [shouldUseGraphRun, workspaceId, workspacePlanRefresh]);

    useEffect(() => {
      let active = true;
      queueMicrotask(() => {
        if (active) {
          setSelectedNodeId(null);
        }
      });
      return () => {
        active = false;
      };
    }, [conversationId, currentWorkspaceTaskId, run?.graphRunId, workspaceId]);

    const model = useMemo(
      () =>
        shouldUseGraphRun && run
          ? buildChatExecutionDag(run, graphDefinition)
          : buildWorkspaceExecutionDag(workspaceSnapshot, workspaceAgents),
      [graphDefinition, run, shouldUseGraphRun, workspaceAgents, workspaceSnapshot]
    );
    const selectedNode = useMemo(
      () => model?.nodes.find((node) => node.id === selectedNodeId) ?? null,
      [model, selectedNodeId]
    );
    const highlightedWorkspaceNodeId = useMemo(
      () =>
        shouldUseGraphRun ? null : resolveCurrentWorkspaceNodeId(model, currentWorkspaceTaskId),
      [currentWorkspaceTaskId, model, shouldUseGraphRun]
    );

    if (!shouldUseGraphRun) {
      const isWorkspaceActive = Boolean(workspaceId);
      if (isWorkspaceActive && isWorkspaceLoading && !workspaceSnapshot) {
        return (
          <div className="flex min-h-[320px] flex-col items-center justify-center p-6 text-center text-sm text-text-muted">
            <Loader2 className="h-8 w-8 animate-spin text-text-muted motion-reduce:animate-none" />
            <p className="mt-2">
              {t('agent.graphView.loadingWorkspaceGraph', {
                defaultValue: 'Loading workspace graph',
              })}
            </p>
          </div>
        );
      }

      if (isWorkspaceActive && model) {
        return (
          <div className="flex h-full min-h-0 flex-col bg-surface-light dark:bg-surface-dark">
            <div className="border-b border-border-separator px-4 py-3 dark:border-border-dark">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                <GitBranch className="h-4 w-4" aria-hidden />
                {t('agent.graphView.workspaceTitle', { defaultValue: 'Workspace Execution Graph' })}
              </div>
              {workspaceError ? (
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-status-text-warning dark:text-status-text-warning-dark">
                  <AlertCircle className="h-3.5 w-3.5" aria-hidden />
                  {t('agent.graphView.workspaceFallback', {
                    defaultValue: 'Showing the latest available workspace graph.',
                  })}
                </div>
              ) : null}
            </div>
            <div className="relative min-h-0 flex-1 overflow-auto p-3">
              {isWorkspaceLoading ? (
                <div
                  aria-label={t('agent.graphView.refreshingWorkspaceGraph', {
                    defaultValue: 'Refreshing workspace graph',
                  })}
                  className="pointer-events-none absolute right-5 top-5 z-20 h-2 w-2 rounded-full bg-text-muted/45"
                  data-testid="workspace-graph-refreshing"
                  title={t('agent.graphView.refreshingWorkspaceGraph', {
                    defaultValue: 'Refreshing workspace graph',
                  })}
                >
                  <span className="sr-only">
                    {t('agent.graphView.refreshingWorkspaceGraph', {
                      defaultValue: 'Refreshing workspace graph',
                    })}
                  </span>
                </div>
              ) : null}
              <ExecutionDagGraph
                model={model}
                selectedNodeId={selectedNodeId}
                highlightedNodeId={highlightedWorkspaceNodeId}
                onNodeSelect={setSelectedNodeId}
                className="h-full"
                minHeight={420}
              />
            </div>
            {selectedNode ? (
              <div className="border-t border-border-separator px-4 py-3 text-xs dark:border-border-dark">
                <div className="truncate font-semibold text-text-primary dark:text-text-inverse">
                  {selectedNode.title}
                </div>
                <div className="mt-1 truncate text-text-muted">
                  {selectedNode.agentLabel ??
                    t('agent.graphView.unassigned', { defaultValue: 'Unassigned' })}
                </div>
              </div>
            ) : null}
          </div>
        );
      }

      return (
        <div className="flex min-h-[320px] flex-col items-center justify-center p-6 text-center text-sm text-text-muted">
          <Network className="h-9 w-9 text-text-muted" aria-hidden />
          <p className="mt-2 font-medium text-text-secondary dark:text-text-muted">
            {isWorkspaceActive
              ? t('agent.graphView.workspaceReadyTitle', {
                  defaultValue: 'Workspace graph is ready',
                })
              : t('agent.graphView.emptyTitle', { defaultValue: 'No active graph run' })}
          </p>
          <p className="mt-1 max-w-sm text-xs leading-5">
            {isWorkspaceActive
              ? t('agent.graphView.workspaceReadyDescription', {
                  defaultValue:
                    'Execution topology will appear here when the workspace starts dispatching graph or handoff events.',
                })
              : t('agent.graphView.emptyDescription', {
                  defaultValue: 'Start a multi-agent graph run to see execution topology.',
                })}
          </p>
        </div>
      );
    }

    const graphRun = run;
    if (!graphRun) {
      return null;
    }

    return (
      <div className="flex h-full min-h-0 flex-col bg-surface-light dark:bg-surface-dark">
        <div className="border-b border-border-separator px-4 py-3 dark:border-border-dark">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                <GitBranch className="h-4 w-4" aria-hidden />
                {t('agent.graphView.title', { defaultValue: 'Execution Graph' })}
              </div>
              <h3 className="mt-1 truncate text-sm font-semibold text-text-primary dark:text-text-inverse">
                {graphRun.graphName}
              </h3>
            </div>
            <div className="shrink-0 text-right text-[11px] text-text-muted">
              <div className="font-mono uppercase">{graphRun.status}</div>
              <div>{formatDuration(graphRun.durationSeconds)}</div>
            </div>
          </div>
          {isGraphLoading ? (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-text-muted">
              <Loader2
                className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none"
                aria-hidden
              />
              {t('agent.graphView.loadingDefinition', {
                defaultValue: 'Loading graph definition',
              })}
            </div>
          ) : graphError ? (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-status-text-warning dark:text-status-text-warning-dark">
              <AlertCircle className="h-3.5 w-3.5" aria-hidden />
              {t('agent.graphView.fallbackDefinition', {
                defaultValue: 'Using live handoffs because the graph definition is unavailable.',
              })}
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-3">
          <ExecutionDagGraph
            model={model}
            selectedNodeId={selectedNodeId}
            onNodeSelect={setSelectedNodeId}
            className="h-full"
            minHeight={420}
          />
        </div>

        {selectedNode ? (
          <div className="border-t border-border-separator px-4 py-3 text-xs dark:border-border-dark">
            <div className="flex min-w-0 items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-semibold text-text-primary dark:text-text-inverse">
                  {selectedNode.title}
                </div>
                <div className="mt-1 truncate text-text-muted">
                  {selectedNode.agentLabel ??
                    t('agent.graphView.unassigned', { defaultValue: 'Unassigned' })}
                </div>
              </div>
              <div className="shrink-0 text-right font-mono text-[11px] text-text-muted">
                <div>{selectedNode.status}</div>
                <div>{selectedNode.attemptId ?? selectedNode.kind}</div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
);

AgentGraphView.displayName = 'AgentGraphView';
