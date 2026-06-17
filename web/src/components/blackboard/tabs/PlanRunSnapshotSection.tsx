import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock3,
  Filter,
  GitBranch,
  History,
  ListTodo,
  Loader2,
  PackageCheck,
  Pause,
  Play,
  RefreshCw,
  Repeat2,
  RotateCcw,
  Search,
  ShieldCheck,
  SkipForward,
  Split,
  Zap,
} from 'lucide-react';

import { apiFetch } from '@/services/client/urlUtils';
import { projectSandboxService } from '@/services/projectSandboxService';
import {
  workspaceAutonomyService,
  workspacePlanService,
  workspaceTaskService,
} from '@/services/workspaceService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import { confirmAction } from '@/utils/confirmAction';

import { ExecutionDagGraph } from '@/components/executionDag/ExecutionDagGraph';
import {
  buildWorkspaceExecutionDag,
  workspaceDagDimmedNodeIds,
} from '@/components/executionDag/workspaceExecutionDagModel';
import { TaskExperiencePanel } from '@/components/workspace/TaskExperiencePanel';

import { EmptyState } from '../EmptyState';
import { StatBadge } from '../StatBadge';

import { PlanRunIterationLedger } from './PlanRunIterationLedger';
import {
  actionEnabled,
  asRecord,
  asText,
  buildIterationRuns,
  countDone,
  criterionSummary,
  eventLabel,
  eventSummary,
  fallbackTone,
  FILTERS,
  formatRelative,
  formatTime,
  iterationNodeIndex,
  matchesFilter,
  nodeWriteSet,
  outboxNodeId,
  planStage,
  rootGoalNeedsClosure,
  shortId,
} from './planRunSnapshotModel';
import {
  BlackboardEntryRow,
  NodeRow,
  NodeStatusIcon,
  OutboxRow,
  TimelineRow,
} from './PlanRunSnapshotParts';

import type {
  TaskExecutionSession,
  TaskRecoveryAction,
  WorkspaceAgent,
  WorkspacePlanActionCapability,
  WorkspacePlanDeliverySummary,
  WorkspacePlanEvidenceBundle,
  WorkspacePlanGateStatus,
  WorkspacePlanIterationSummary,
  WorkspacePlanNode,
  WorkspacePlanOutboxItem,
  WorkspacePlanSnapshot,
  WorkspaceTaskExperienceSummary,
  WorkspaceTask,
} from '@/types/workspace';

import type { NodeActionId, NodeFilter } from './planRunSnapshotModel';

interface PlanRunSnapshotSectionProps {
  workspaceId: string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
  agents?: WorkspaceAgent[] | undefined;
  tasks?: WorkspaceTask[] | undefined;
  refreshToken?: number | undefined;
}

const OPERATOR_REASON_LIMIT = 500;
const COLLAPSIBLE_TEXT_THRESHOLD = 96;
const FEEDBACK_PREVIEW_LIMIT = 2;
const DEFAULT_NODE_ACTION_REASON = 'operator action from central blackboard';
const DEFAULT_RETRY_ACTION_REASON = 'operator retry from central blackboard';
type DetailTabId = 'story' | 'evidence' | 'runs' | 'review' | 'blocker';
type DagViewMode = 'graph' | 'list' | 'iterations';

const DETAIL_TABS: Array<{ id: DetailTabId; label: string }> = [
  { id: 'story', label: 'Story' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'runs', label: 'Runs' },
  { id: 'review', label: 'Review' },
  { id: 'blocker', label: 'Blocker' },
];

function actionLabel(action: WorkspacePlanActionCapability | undefined, fallback: string): string {
  return action?.label || fallback;
}

function actionDisabledReason(
  action: WorkspacePlanActionCapability | undefined,
  fallback: string
): string {
  return action?.reason || fallback;
}

function reasonOrFallback(value: string, fallback: string): string {
  return value.trim() || fallback;
}

function nodePhaseLabel(nodeMetadata: Record<string, unknown>): string {
  const phase = nodeMetadata.iteration_phase;
  return typeof phase === 'string' && phase ? phase : 'plan';
}

function gateTone(status: string | undefined): string {
  if (status === 'passed') {
    return 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark';
  }
  if (
    status === 'blocked' ||
    status === 'missing' ||
    status === 'failed' ||
    status === 'unhealthy'
  ) {
    return 'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark';
  }
  if (status === 'running') {
    return 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark';
  }
  return 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted';
}

function compactList(items: string[] | undefined, fallback: string): string {
  if (!items || items.length === 0) {
    return fallback;
  }
  return items.slice(0, 3).join(', ');
}

function nodeEvidenceBundle(node: WorkspacePlanNode): WorkspacePlanEvidenceBundle {
  return (
    node.evidence_bundle ?? {
      artifacts: [],
      evidence_refs: [],
      changed_files: nodeWriteSet(node),
      pipeline_refs: [],
      verification_summary: '',
      review_summary: '',
    }
  );
}

function nodeGateStatus(node: WorkspacePlanNode): WorkspacePlanGateStatus {
  return (
    node.gate_status ?? {
      status: node.intent === 'done' ? 'passed' : node.intent,
      summary: '',
      missing: [],
      evidence_refs: [],
      routing: 'continue',
    }
  );
}

function taskStatusFromPlanNode(node: WorkspacePlanNode): WorkspaceTask['status'] {
  if (node.intent === 'done') {
    return 'done';
  }
  if (node.intent === 'blocked') {
    return 'blocked';
  }
  if (
    node.execution === 'running' ||
    node.execution === 'dispatched' ||
    node.execution === 'reported' ||
    node.execution === 'verifying'
  ) {
    return 'in_progress';
  }
  return 'todo';
}

function taskFromPlanNode(node: WorkspacePlanNode, workspaceId: string): WorkspaceTask | null {
  if (!node.workspace_task_id) {
    return null;
  }
  return {
    id: node.workspace_task_id,
    workspace_id: workspaceId,
    title: node.title,
    description: node.description,
    assignee_agent_id: node.assignee_agent_id ?? undefined,
    current_attempt_id: node.current_attempt_id ?? undefined,
    status: taskStatusFromPlanNode(node),
    metadata: {
      ...node.metadata,
      source_plan_node_id: node.id,
      source_plan_node_execution: node.execution,
      source_plan_node_intent: node.intent,
    },
    created_at: node.created_at,
    updated_at: node.updated_at ?? undefined,
    completed_at: node.completed_at ?? undefined,
  };
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[10px] font-semibold uppercase text-text-muted">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold tabular-nums text-text-primary dark:text-text-inverse">
        {value}
      </dd>
    </div>
  );
}

function CollapsibleTextBlock({
  children,
  collapsedLines = 'line-clamp-3',
  toneClassName = 'text-text-secondary dark:text-text-muted',
}: {
  children?: string | null | undefined;
  collapsedLines?: string;
  toneClassName?: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const text = children?.trim();

  if (!text) {
    return null;
  }

  const canToggle = text.length > COLLAPSIBLE_TEXT_THRESHOLD;

  return (
    <div className="min-w-0">
      <p
        className={`break-words text-xs leading-5 ${toneClassName} ${
          canToggle && !expanded ? collapsedLines : ''
        }`}
      >
        {text}
      </p>
      {canToggle && (
        <button
          type="button"
          aria-expanded={expanded}
          className="mt-1 text-xs font-medium text-status-text-info hover:underline dark:text-status-text-info-dark"
          onClick={() => {
            setExpanded((current) => !current);
          }}
        >
          {expanded
            ? t('blackboard.collapseText', 'Collapse')
            : t('blackboard.expandText', 'Expand')}
        </button>
      )}
    </div>
  );
}

function IterationLoopPanel({
  iteration,
  isActionPending,
  onAction,
}: {
  iteration: WorkspacePlanIterationSummary | null | undefined;
  isActionPending: boolean;
  onAction: (actionId: 'pause_auto_loop' | 'resume_auto_loop' | 'trigger_next_iteration') => void;
}) {
  const { t } = useTranslation();
  const [showAllFeedback, setShowAllFeedback] = useState(false);

  if (!iteration) {
    return null;
  }
  const pauseAction = iteration.actions.pause_auto_loop;
  const resumeAction = iteration.actions.resume_auto_loop;
  const triggerAction = iteration.actions.trigger_next_iteration;
  const isAtIterationLimit = iteration.current_iteration >= iteration.max_iterations;
  const statusTone =
    iteration.loop_status === 'completed'
      ? 'text-status-text-success'
      : iteration.loop_status === 'paused' || iteration.loop_status === 'suspended'
        ? 'text-status-text-warning'
        : 'text-status-text-info';
  const feedbackItems = showAllFeedback
    ? iteration.feedback_items
    : iteration.feedback_items.slice(0, FEEDBACK_PREVIEW_LIMIT);
  const hiddenFeedbackItemCount = Math.max(
    0,
    iteration.feedback_items.length - FEEDBACK_PREVIEW_LIMIT
  );
  const hasHiddenFeedbackItems = iteration.feedback_items.length > FEEDBACK_PREVIEW_LIMIT;

  return (
    <div className="border-t border-border-separator px-4 py-4 dark:border-border-dark">
      <div className="grid gap-3">
        <div className="min-w-0 max-w-3xl">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <div className="flex min-w-0 items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
              <Repeat2 className="h-4 w-4 shrink-0" aria-hidden />
              <span className="truncate">Iteration {iteration.current_iteration}</span>
            </div>
            <span className={`text-xs font-medium uppercase ${statusTone}`}>
              {iteration.loop_status}
            </span>
          </div>
          <div className="mt-2 text-sm font-medium text-text-primary dark:text-text-inverse">
            {iteration.active_phase_label}
          </div>
          <div className="mt-2 space-y-2">
            <CollapsibleTextBlock>{iteration.current_sprint_goal}</CollapsibleTextBlock>
            <CollapsibleTextBlock>{iteration.next_action}</CollapsibleTextBlock>
            <CollapsibleTextBlock>{iteration.review_summary}</CollapsibleTextBlock>
            <CollapsibleTextBlock toneClassName="text-status-text-warning dark:text-status-text-warning-dark">
              {iteration.stop_reason}
            </CollapsibleTextBlock>
          </div>
        </div>
        <dl className="grid min-w-0 grid-cols-1 gap-3 rounded-md border border-border-light bg-surface-muted px-3 py-2 sm:grid-cols-3 dark:border-border-dark dark:bg-surface-dark">
          <CompactMetric
            label="Sprint tasks"
            value={`${String(iteration.task_count)}/${String(iteration.task_budget)}`}
          />
          <CompactMetric label="Loop" value={iteration.loop_label} />
          <CompactMetric
            label="Completed"
            value={`${String(iteration.completed_iterations.length)}/${String(iteration.max_iterations)}`}
          />
        </dl>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(pauseAction)}
          title={actionDisabledReason(pauseAction, 'Pause is not available.')}
          onClick={() => {
            onAction('pause_auto_loop');
          }}
        >
          <Pause className="h-3.5 w-3.5" aria-hidden />
          Pause
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(resumeAction)}
          title={actionDisabledReason(resumeAction, 'Resume is not available.')}
          onClick={() => {
            onAction('resume_auto_loop');
          }}
        >
          <Play className="h-3.5 w-3.5" aria-hidden />
          Resume
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
          disabled={isActionPending || !actionEnabled(triggerAction)}
          title={
            isAtIterationLimit
              ? t(
                  'blackboard.planRunPlanNextManualHint',
                  'Iteration limit reached. Plan next is an explicit operator action.'
                )
              : actionDisabledReason(triggerAction, 'Next iteration is not available.')
          }
          onClick={() => {
            onAction('trigger_next_iteration');
          }}
        >
          <SkipForward className="h-3.5 w-3.5" aria-hidden />
          {isAtIterationLimit
            ? t('blackboard.planRunPlanNextManual', 'Plan next manually')
            : t('blackboard.planRunPlanNext', 'Plan next')}
        </button>
      </div>

      {isAtIterationLimit && (
        <p className="mt-2 max-w-3xl break-words text-xs leading-5 text-status-text-warning dark:text-status-text-warning-dark">
          {t(
            'blackboard.planRunIterationLimitHint',
            'The automatic iteration limit has been reached. Plan next remains available as a deliberate operator action.'
          )}
        </p>
      )}

      <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-2">
        {iteration.phases.map((phase) => {
          const isActive = phase.id === iteration.active_phase;
          const gateStatus = phase.gate_status?.status ?? 'pending';
          const missingSummary = compactList(phase.missing_artifacts, 'none');
          return (
            <div
              key={phase.id}
              className={`min-w-0 rounded-md border px-3 py-2 ${
                isActive
                  ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                  : 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-semibold">{phase.label}</span>
                <span
                  className={`min-w-0 max-w-[8.25rem] shrink truncate rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${gateTone(
                    gateStatus
                  )}`}
                  title={gateStatus}
                >
                  {gateStatus}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between gap-2">
                <span className="truncate text-[11px] text-text-secondary dark:text-text-muted">
                  {phase.summary || 'No gate summary yet.'}
                </span>
                <span className="shrink-0 font-mono text-[11px]">{phase.progress}%</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-background-light/70 dark:bg-background-dark/60">
                <div
                  className={`h-full rounded-full ${
                    phase.blocked > 0
                      ? 'bg-status-text-error'
                      : isActive
                        ? 'bg-status-text-info'
                        : 'bg-text-muted'
                  }`}
                  style={{ width: `${String(Math.max(0, Math.min(phase.progress, 100)))}%` }}
                />
              </div>
              <div className="mt-1.5 text-[11px]">
                {phase.done}/{phase.total || 0}
                {phase.running > 0 ? ` · ${String(phase.running)} active` : ''}
                {phase.blocked > 0 ? ` · ${String(phase.blocked)} blocked` : ''}
              </div>
              <div
                className="mt-1 line-clamp-2 break-words text-[11px] leading-4 text-text-secondary dark:text-text-muted"
                title={`Missing: ${missingSummary}`}
              >
                Missing: {missingSummary}
              </div>
            </div>
          );
        })}
      </div>

      {(iteration.deliverables.length > 0 || iteration.feedback_items.length > 0) && (
        <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(18rem,1fr))] gap-3">
          {iteration.deliverables.length > 0 && (
            <div className="min-w-0 rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                <PackageCheck className="h-4 w-4" aria-hidden />
                Outputs
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {iteration.deliverables.map((item) => (
                  <span
                    key={item}
                    className="max-w-full truncate rounded border border-border-light bg-surface-muted px-2 py-1 font-mono text-[11px] text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>
          )}
          {iteration.feedback_items.length > 0 && (
            <div className="min-w-0 rounded-md border border-warning-border bg-warning-bg p-3 text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase">
                <AlertTriangle className="h-4 w-4" aria-hidden />
                Feedback
              </div>
              <ul className="mt-2 space-y-2">
                {feedbackItems.map((item) => (
                  <li key={item}>
                    <CollapsibleTextBlock
                      collapsedLines="line-clamp-5"
                      toneClassName="text-status-text-warning dark:text-status-text-warning-dark"
                    >
                      {item}
                    </CollapsibleTextBlock>
                  </li>
                ))}
              </ul>
              {hasHiddenFeedbackItems && (
                <button
                  type="button"
                  aria-expanded={showAllFeedback}
                  className="mt-2 text-xs font-medium text-status-text-warning hover:underline dark:text-status-text-warning-dark"
                  onClick={() => {
                    setShowAllFeedback((current) => !current);
                  }}
                >
                  {showAllFeedback
                    ? t('blackboard.collapseText', 'Collapse')
                    : `${t('blackboard.expandText', 'Expand')} (${String(hiddenFeedbackItemCount)})`}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {iteration.history.length > 0 && (
        <div className="mt-4 border-t border-border-separator pt-3 dark:border-border-dark">
          <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
            Review history
          </div>
          <div className="mt-2 space-y-2">
            {iteration.history.slice(-3).map((item) => (
              <div
                key={`${String(item.iteration_index)}-${item.verdict}-${item.summary}`}
                className="min-w-0 rounded-md border border-border-light bg-surface-muted px-3 py-2 text-xs text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-text-primary dark:text-text-inverse">
                    Iteration {item.iteration_index}
                  </span>
                  <span className="uppercase">{item.verdict}</span>
                  <span>{Math.round(item.confidence * 100)}%</span>
                </div>
                <p className="mt-1 break-words leading-5">{item.summary}</p>
                {item.next_sprint_goal && (
                  <p className="mt-1 break-words leading-5">{item.next_sprint_goal}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DeliveryPanel({
  delivery,
  isActionPending,
  previewOpeningUrl,
  onRunPipeline,
  onRegenerateContract,
  onOpenPreview,
}: {
  delivery: WorkspacePlanDeliverySummary | null | undefined;
  isActionPending: boolean;
  previewOpeningUrl: string | null;
  onRunPipeline: () => void;
  onRegenerateContract: () => void;
  onOpenPreview: (previewUrl: string, serviceId: string) => void;
}) {
  const { t } = useTranslation();

  if (!delivery) {
    return null;
  }
  const run = delivery.latest_run;
  const deploymentList = delivery.deployments;
  const deployments =
    deploymentList.length > 0 ? deploymentList : delivery.deployment ? [delivery.deployment] : [];
  const deployment = deployments[0];
  const services = delivery.services;
  const requestAction = delivery.actions.request_pipeline;
  const regenerateAction = delivery.actions.regenerate_contract;
  const tone =
    delivery.status === 'success' || delivery.status === 'healthy'
      ? 'text-status-text-success'
      : delivery.status === 'failed' || delivery.status === 'unhealthy'
        ? 'text-status-text-error'
        : 'text-status-text-info';
  const runSummary = `Provider ${delivery.provider}${
    run ? ` · run ${shortId(run.id)} · ${run.status}` : ' · no pipeline run yet'
  }`;
  const deliveryMeta = `${delivery.agent_managed ? 'Agent managed' : 'Manual'} · ${
    delivery.contract_source
  } · ${String(Math.round(delivery.contract_confidence * 100))}% confidence`;

  return (
    <div className="border-t border-border-separator px-4 py-4 dark:border-border-dark">
      <div className="grid gap-3">
        <div className="min-w-0 max-w-3xl">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <div className="flex min-w-0 items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
              <PackageCheck className="h-4 w-4 shrink-0" aria-hidden />
              <span className="truncate">Delivery / CI/CD</span>
            </div>
            <span className={`text-xs font-semibold uppercase ${tone}`}>{delivery.status}</span>
          </div>
          <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
            {runSummary}
          </p>
          {run?.external_url && (
            <a
              href={run.external_url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex max-w-full items-center gap-1 break-all text-xs leading-5 text-brand-primary hover:underline"
            >
              <span className="min-w-0 truncate">{run.external_id ?? run.external_url}</span>
              <ArrowUpRight className="h-3 w-3 shrink-0" aria-hidden />
            </a>
          )}
          {delivery.code_root && (
            <p className="mt-1 line-clamp-2 break-all font-mono text-[11px] leading-5 text-text-secondary dark:text-text-muted">
              {delivery.code_root}
            </p>
          )}
          <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
            {deliveryMeta}
          </p>
          {delivery.run_assessment?.summary && (
            <CollapsibleTextBlock>{delivery.run_assessment.summary}</CollapsibleTextBlock>
          )}
          {run?.reason && (
            <CollapsibleTextBlock
              collapsedLines="line-clamp-4"
              toneClassName="text-status-text-warning dark:text-status-text-warning-dark"
            >
              {run.reason}
            </CollapsibleTextBlock>
          )}
        </div>
        <dl className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4">
          <StatBadge label="Pipeline" value={run?.status ?? 'none'} />
          <StatBadge
            label="Assessment"
            value={delivery.run_assessment?.status ?? run?.status ?? 'none'}
          />
          <StatBadge label="Health" value={deployment?.status ?? 'none'} />
          <StatBadge label="Restarts" value={String(deployment?.restart_count ?? 0)} />
        </dl>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
            disabled={isActionPending || !actionEnabled(requestAction)}
            title={actionDisabledReason(requestAction, 'Pipeline run is not available.')}
            onClick={onRunPipeline}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Run pipeline
          </button>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1 rounded border border-border-light bg-surface-light px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt"
            disabled={isActionPending || !actionEnabled(regenerateAction)}
            title={actionDisabledReason(
              regenerateAction,
              'Contract regeneration is not available.'
            )}
            onClick={onRegenerateContract}
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Regenerate
          </button>
        </div>
      </div>

      {(delivery.warnings?.length ?? 0) > 0 && (
        <div className="mt-3 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-xs leading-5 text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
          <div className="font-semibold uppercase">
            {t('blackboard.planRunWarnings', 'Warnings')}
          </div>
          <ul className="mt-1 space-y-2">
            {delivery.warnings?.map((warning) => (
              <li key={warning}>
                <CollapsibleTextBlock
                  collapsedLines="line-clamp-4"
                  toneClassName="text-status-text-warning dark:text-status-text-warning-dark"
                >
                  {warning}
                </CollapsibleTextBlock>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(services.length > 0 || deployments.length > 0) && (
        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {(services.length > 0 ? services : deployments).map((item) => {
            const serviceId = item.service_id ?? ('id' in item ? item.id : 'default');
            const name =
              'name' in item ? item.name : (item.service_name ?? item.service_id ?? 'Preview');
            const statusValue = item.status;
            const previewUrl = item.preview_url ?? undefined;
            const required = item.required;
            return (
              <div
                key={serviceId}
                className="min-w-0 rounded-md border border-border-light bg-surface-muted px-3 py-2 dark:border-border-dark dark:bg-surface-dark-alt"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold text-text-primary dark:text-text-inverse">
                    {name}
                  </span>
                  <span className="shrink-0 rounded bg-surface-light px-1.5 py-0.5 text-[11px] font-medium uppercase text-text-secondary dark:bg-surface-dark dark:text-text-muted">
                    {statusValue}
                  </span>
                </div>
                <p className="mt-1 truncate font-mono text-[11px] text-text-secondary dark:text-text-muted">
                  {serviceId} · {required ? 'required' : 'optional'}
                </p>
                {'start_command' in item && item.start_command && (
                  <p className="mt-1 line-clamp-2 break-words font-mono text-[11px] text-text-secondary dark:text-text-muted">
                    {item.start_command}
                  </p>
                )}
                {'health_path' in item && item.health_path && (
                  <p className="mt-1 truncate font-mono text-[11px] text-text-secondary dark:text-text-muted">
                    health {item.health_path}
                  </p>
                )}
                {previewUrl && (
                  <button
                    type="button"
                    disabled={isActionPending || previewOpeningUrl === previewUrl}
                    onClick={() => {
                      onOpenPreview(previewUrl, serviceId);
                    }}
                    className="mt-2 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-status-text-info hover:underline"
                  >
                    {previewOpeningUrl === previewUrl ? (
                      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
                    ) : (
                      <ArrowUpRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    )}
                    <span className="truncate">
                      {t('blackboard.planRunOpenPreview', 'Open preview')}
                    </span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {run && run.stages.length > 0 && (
        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {run.stages.map((stage) => {
            const stageTone =
              stage.status === 'success'
                ? 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
                : stage.status === 'failed'
                  ? 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark'
                  : 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted';
            return (
              <div key={stage.id} className={`min-w-0 rounded-md border px-3 py-2 ${stageTone}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold uppercase">{stage.stage}</span>
                  <span className="shrink-0 font-mono text-[11px]">{stage.exit_code ?? '-'}</span>
                </div>
                {stage.service_id && (
                  <p className="mt-1 truncate font-mono text-[11px]">{stage.service_id}</p>
                )}
                <p className="mt-1 line-clamp-2 break-words text-[11px] leading-4">
                  {stage.stderr_preview || stage.stdout_preview || stage.command || stage.status}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function WorkbenchStatusBar({
  snapshot,
  lastUpdatedAt,
  isStale,
}: {
  snapshot: WorkspacePlanSnapshot;
  lastUpdatedAt: Date | null;
  isStale: boolean;
}) {
  const iteration = snapshot.iteration;
  const delivery = snapshot.delivery;
  const outbox = snapshot.outbox;
  const failedQueue = outbox.filter(
    (item) => item.status === 'failed' || item.status === 'dead_letter'
  ).length;
  const healthyServices =
    delivery?.deployments.filter((deployment) => deployment.status === 'healthy').length ?? 0;
  const serviceTotal = delivery?.services.length || delivery?.deployments.length || 0;

  return (
    <div className="border-t border-border-separator bg-surface-muted/60 px-4 py-3 dark:border-border-dark dark:bg-background-dark/30">
      <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        <CompactMetric label="Code root" value={delivery?.code_root || 'not configured'} />
        <CompactMetric
          label="Iteration"
          value={
            iteration
              ? `${String(iteration.current_iteration)} · ${iteration.loop_status}`
              : 'not started'
          }
        />
        <CompactMetric label="Active phase" value={iteration?.active_phase_label ?? 'n/a'} />
        <CompactMetric
          label="Queue"
          value={`${String(outbox.length)} jobs${failedQueue > 0 ? ` · ${String(failedQueue)} failed` : ''}`}
        />
        <CompactMetric
          label="Pipeline"
          value={delivery?.run_assessment?.status ?? delivery?.latest_run?.status ?? 'none'}
        />
        <CompactMetric
          label="Preview"
          value={`${String(healthyServices)} / ${String(serviceTotal)}${
            isStale ? ` · updated ${formatRelative(lastUpdatedAt)}` : ''
          }`}
        />
      </dl>
    </div>
  );
}

export function PlanRunSnapshotSection({
  workspaceId,
  tenantId,
  projectId,
  agents = [],
  tasks,
  refreshToken,
}: PlanRunSnapshotSectionProps) {
  const { t } = useTranslation();
  const taskList = useMemo(() => tasks ?? [], [tasks]);
  const isMountedRef = useRef(true);
  const taskInspectorRef = useRef<HTMLDivElement | null>(null);
  const lastRefreshTokenRef = useRef(refreshToken ?? 0);
  const [snapshot, setSnapshot] = useState<WorkspacePlanSnapshot | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedDetailTab, setSelectedDetailTab] = useState<DetailTabId>('story');
  const [dagViewMode, setDagViewMode] = useState<DagViewMode>('graph');
  const [dagIterationScope, setDagIterationScope] = useState<number | 'all' | null>(null);
  const [filter, setFilter] = useState<NodeFilter>('all');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isActionPending, setIsActionPending] = useState(false);
  const [isTickPending, setIsTickPending] = useState(false);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [previewOpeningUrl, setPreviewOpeningUrl] = useState<string | null>(null);
  const [operatorReason, setOperatorReason] = useState('');
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [selectedIterationIndex, setSelectedIterationIndex] = useState<number | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTaskExperience, setSelectedTaskExperience] =
    useState<WorkspaceTaskExperienceSummary | null>(null);
  const [selectedTaskSession, setSelectedTaskSession] = useState<TaskExecutionSession | null>(null);
  const [isTaskExperienceLoading, setIsTaskExperienceLoading] = useState(false);
  const [isTaskRecoveryPending, setIsTaskRecoveryPending] = useState(false);
  const [taskExperienceError, setTaskExperienceError] = useState<string | null>(null);

  const loadSnapshot = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setIsLoading(true);
      }
      setError(null);
      try {
        const snapshotOptions = {
          outboxLimit: 20,
          eventLimit: 80,
          recoverStaleAttempts: false,
          ...(selectedPlanId ? { planId: selectedPlanId } : {}),
        };
        const nextSnapshot = await workspacePlanService.getSnapshot(workspaceId, snapshotOptions);
        if (!isMountedRef.current) {
          return;
        }
        setSnapshot(nextSnapshot);
        setLastUpdatedAt(new Date());
      } catch (err) {
        if (isMountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (isMountedRef.current) {
          setIsLoading(false);
        }
      }
    },
    [selectedPlanId, workspaceId]
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;

    const schedule = () => {
      const visible = document.visibilityState === 'visible';
      const interval = visible ? 8000 : 30000;
      timer = window.setTimeout(() => {
        if (cancelled) {
          return;
        }
        void loadSnapshot({ silent: true }).then(() => {
          if (!cancelled) {
            schedule();
          }
        });
      }, interval);
    };

    void loadSnapshot();
    schedule();

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [loadSnapshot]);

  useEffect(() => {
    const nextRefreshToken = refreshToken ?? 0;
    if (lastRefreshTokenRef.current === nextRefreshToken) {
      return;
    }
    lastRefreshTokenRef.current = nextRefreshToken;
    void loadSnapshot({ silent: true });
  }, [loadSnapshot, refreshToken]);

  const nodes = useMemo(() => snapshot?.plan?.nodes ?? [], [snapshot]);
  const runnableNodes = useMemo(
    () => nodes.filter((node) => node.kind === 'task' || node.kind === 'verify'),
    [nodes]
  );
  const normalizedQuery = query.trim().toLowerCase();
  const filteredNodes = useMemo(
    () =>
      runnableNodes
        .filter((node) => matchesFilter(node, filter))
        .filter((node) => {
          if (!normalizedQuery) {
            return true;
          }
          return [
            node.id,
            node.title,
            node.description,
            node.intent,
            node.execution,
            node.assignee_agent_id ?? '',
            node.current_attempt_id ?? '',
          ]
            .join(' ')
            .toLowerCase()
            .includes(normalizedQuery);
        }),
    [filter, normalizedQuery, runnableNodes]
  );
  const plan = snapshot?.plan ?? null;
  const planHistory = snapshot?.plan_history ?? [];
  const selectedPlanHistory =
    (plan ? planHistory.find((item) => item.plan_id === plan.id) : null) ?? null;
  const isHistoricalPlan = Boolean(selectedPlanHistory && !selectedPlanHistory.is_latest);
  const outbox = useMemo(() => snapshot?.outbox ?? [], [snapshot]);
  const events = useMemo(() => snapshot?.events ?? [], [snapshot]);
  const blackboard = useMemo(() => snapshot?.blackboard ?? [], [snapshot]);
  const rootGoal = snapshot?.root_goal ?? null;
  const iteration = snapshot?.iteration ?? null;
  const delivery = snapshot?.delivery ?? null;
  const stage = planStage(snapshot);
  const doneCount = countDone(runnableNodes);
  const rootUnitCount = rootGoal ? 1 : 0;
  const totalCompletionUnits = runnableNodes.length + rootUnitCount;
  const completedUnits = doneCount + (rootGoal?.status === 'done' ? 1 : 0);
  const completion =
    totalCompletionUnits > 0 ? Math.round((completedUnits / totalCompletionUnits) * 100) : 0;
  const latestEvent = events[0] ?? null;
  const isStale = lastUpdatedAt ? Date.now() - lastUpdatedAt.getTime() > 20000 : false;
  const iterationRuns = useMemo(() => buildIterationRuns(snapshot, taskList), [snapshot, taskList]);
  const currentIterationIndex = iteration?.current_iteration ?? iterationRuns.at(-1)?.index ?? 1;
  const dagIterationIndex =
    dagIterationScope === 'all' ? null : (dagIterationScope ?? currentIterationIndex);
  const graphScopedNodes = useMemo(
    () =>
      dagIterationIndex
        ? runnableNodes.filter((node) => iterationNodeIndex(node) === dagIterationIndex)
        : runnableNodes,
    [dagIterationIndex, runnableNodes]
  );
  const graphScopedNodeIds = useMemo(
    () => new Set(graphScopedNodes.map((node) => node.id)),
    [graphScopedNodes]
  );
  const graphFilteredNodes = useMemo(
    () => filteredNodes.filter((node) => graphScopedNodeIds.has(node.id)),
    [filteredNodes, graphScopedNodeIds]
  );
  const executionDagModel = useMemo(
    () =>
      buildWorkspaceExecutionDag(snapshot, agents, {
        iterationIndex: dagIterationIndex,
      }),
    [agents, dagIterationIndex, snapshot]
  );
  const dimmedDagNodeIds = useMemo(
    () => workspaceDagDimmedNodeIds(executionDagModel, snapshot, filter, query),
    [executionDagModel, filter, query, snapshot]
  );
  const selectedNode = useMemo(() => {
    const selected = nodes.find((node) => node.id === selectedNodeId) ?? null;
    if (selected && (dagViewMode !== 'graph' || graphScopedNodeIds.has(selected.id))) {
      return selected;
    }
    if (dagViewMode === 'graph') {
      return graphFilteredNodes[0] ?? graphScopedNodes[0] ?? filteredNodes[0] ?? nodes[0] ?? null;
    }
    return selected ?? filteredNodes[0] ?? nodes[0] ?? null;
  }, [
    dagViewMode,
    filteredNodes,
    graphFilteredNodes,
    graphScopedNodeIds,
    graphScopedNodes,
    nodes,
    selectedNodeId,
  ]);

  useEffect(() => {
    if (selectedNode && selectedNode.id !== selectedNodeId) {
      setSelectedNodeId(selectedNode.id);
    }
  }, [selectedNode, selectedNodeId]);
  const selectedIterationRun = useMemo(() => {
    return (
      iterationRuns.find((run) => run.index === selectedIterationIndex) ??
      iterationRuns.find((run) => run.index === iteration?.current_iteration) ??
      iterationRuns.at(-1) ??
      null
    );
  }, [iteration?.current_iteration, iterationRuns, selectedIterationIndex]);

  useEffect(() => {
    if (iterationRuns.length === 0) {
      setSelectedIterationIndex(null);
      return;
    }
    setSelectedIterationIndex((current) => {
      if (current !== null && iterationRuns.some((run) => run.index === current)) {
        return current;
      }
      return iteration?.current_iteration ?? iterationRuns.at(-1)?.index ?? null;
    });
  }, [iteration?.current_iteration, iterationRuns]);

  const selectedEvents = useMemo(() => {
    if (!selectedNode) {
      return events.slice(0, 12);
    }
    const related = events.filter(
      (event) =>
        event.node_id === selectedNode.id ||
        event.attempt_id === selectedNode.current_attempt_id ||
        asText(asRecord(event.payload).node_id) === selectedNode.id
    );
    return (related.length > 0 ? related : events)
      .filter((event) => {
        if (!normalizedQuery) {
          return true;
        }
        return [
          event.event_type,
          event.source,
          event.node_id ?? '',
          event.attempt_id ?? '',
          event.actor_id ?? '',
          eventSummary(event),
        ]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 12);
  }, [events, normalizedQuery, selectedNode]);

  const selectedOutbox = useMemo(() => {
    if (!selectedNode) {
      return outbox.slice(0, 8);
    }
    const related = outbox.filter((item) => outboxNodeId(item) === selectedNode.id);
    return (related.length > 0 ? related : outbox)
      .filter((item) => {
        if (!normalizedQuery) {
          return true;
        }
        return [
          item.id,
          item.event_type,
          item.status,
          item.last_error ?? '',
          outboxNodeId(item),
          asText(item.payload),
        ]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 8);
  }, [normalizedQuery, outbox, selectedNode]);

  const visibleBlackboard = useMemo(() => {
    return blackboard
      .filter((entry) => {
        if (!normalizedQuery) {
          return true;
        }
        return [entry.key, entry.published_by, asText(entry.value)]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery);
      })
      .slice(0, 8);
  }, [blackboard, normalizedQuery]);

  const linkedTask = useMemo(() => {
    if (!selectedNode) {
      return null;
    }
    return (
      taskList.find(
        (task) =>
          task.id === selectedNode.workspace_task_id ||
          task.current_attempt_id === selectedNode.current_attempt_id
      ) ?? null
    );
  }, [selectedNode, taskList]);
  const selectedTask = useMemo(
    () =>
      taskList.find((task) => task.id === selectedTaskId) ??
      (selectedTaskId
        ? (nodes
            .map((node) => taskFromPlanNode(node, workspaceId))
            .find((task) => task?.id === selectedTaskId) ?? null)
        : null),
    [nodes, selectedTaskId, taskList, workspaceId]
  );

  useEffect(() => {
    if (!selectedTaskId || selectedTask) {
      return;
    }
    setSelectedTaskId(null);
    setSelectedTaskExperience(null);
    setSelectedTaskSession(null);
    setTaskExperienceError(null);
  }, [selectedTask, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask) {
      return;
    }
    taskInspectorRef.current?.scrollIntoView({ block: 'nearest' });
  }, [selectedTask]);

  useEffect(() => {
    if (!selectedTaskId || !selectedTask) {
      return;
    }
    let cancelled = false;
    setIsTaskExperienceLoading(true);
    setTaskExperienceError(null);
    Promise.all([
      workspaceTaskService.getExperience(workspaceId, selectedTaskId),
      workspaceTaskService.getExecutionSession(workspaceId, selectedTaskId),
    ])
      .then(([experience, session]) => {
        if (!cancelled) {
          setSelectedTaskExperience(experience);
          setSelectedTaskSession(session);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setTaskExperienceError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsTaskExperienceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTask, selectedTaskId, workspaceId]);

  const attemptHref =
    tenantId && projectId && linkedTask?.current_attempt_conversation_id
      ? buildAgentWorkspacePath({
          tenantId,
          projectId,
          workspaceId,
          conversationId: linkedTask.current_attempt_conversation_id,
        })
      : '';
  const selectedWriteSet = selectedNode ? nodeWriteSet(selectedNode) : [];
  const openAttemptAction = selectedNode?.actions?.open_attempt;
  const requestReplanAction = selectedNode?.actions?.request_replan;
  const reopenBlockedAction = selectedNode?.actions?.reopen_blocked;
  const acceptAfterReviewAction = selectedNode?.actions?.accept_with_human_review;
  const canOpenAttempt =
    Boolean(attemptHref) && (!openAttemptAction || actionEnabled(openAttemptAction));
  const showOpenAttemptAction = Boolean(openAttemptAction || attemptHref);
  const openAttemptDisabledReason = !actionEnabled(openAttemptAction)
    ? actionDisabledReason(openAttemptAction, 'No worker attempt has been linked yet.')
    : 'Attempt conversation is not available in this workspace projection.';
  const requestReplanDisabledReason = !actionEnabled(requestReplanAction)
    ? actionDisabledReason(requestReplanAction, 'This node cannot be replanned.')
    : undefined;
  const reopenBlockedDisabledReason = !actionEnabled(reopenBlockedAction)
    ? actionDisabledReason(reopenBlockedAction, 'This node cannot be reopened.')
    : undefined;
  const acceptAfterReviewDisabledReason = !actionEnabled(acceptAfterReviewAction)
    ? actionDisabledReason(acceptAfterReviewAction, 'This node cannot be accepted after review.')
    : undefined;
  const selectedGate = selectedNode ? nodeGateStatus(selectedNode) : null;
  const selectedEvidence = selectedNode ? nodeEvidenceBundle(selectedNode) : null;
  const selectedContract = selectedNode?.phase_contract ?? null;
  const selectedBlocker = selectedNode?.blocker_analysis ?? null;

  const assertCurrentPlanForAction = () => {
    if (!isHistoricalPlan) {
      return true;
    }
    setActionMessage(null);
    setActionError(
      t(
        'blackboard.planRunHistoryReadOnlyAction',
        'Select the current goal before running plan actions.'
      )
    );
    return false;
  };

  const formatAutonomyTickMessage = (result: { triggered: boolean; reason: string }) => {
    if (result.triggered) {
      return t('blackboard.planRunAutonomyTriggered', 'Leader scheduled the next autonomy step.');
    }
    if (result.reason === 'cooling_down') {
      return t(
        'blackboard.planRunAutonomyCoolingDown',
        'Autonomy is cooling down. Use Force run to bypass the cooldown.'
      );
    }
    if (result.reason === 'no_open_root') {
      return t('blackboard.planRunAutonomyNoRoot', 'No open root goal needs progress.');
    }
    if (result.reason === 'no_root_needs_progress') {
      return t('blackboard.planRunAutonomyStable', 'All root goals are currently stable.');
    }
    return t('blackboard.planRunAutonomyNoop', {
      reason: result.reason || 'unknown',
      defaultValue: `Autonomy did not run: ${result.reason || 'unknown'}`,
    });
  };

  const runAutonomyTick = async (force: boolean) => {
    if (!assertCurrentPlanForAction()) {
      return;
    }
    setIsTickPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await workspaceAutonomyService.tick(workspaceId, { force });
      setActionMessage(formatAutonomyTickMessage(result));
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTickPending(false);
    }
  };

  const runNodeAction = async (actionId: NodeActionId) => {
    if (!selectedNode) {
      return;
    }
    if (!assertCurrentPlanForAction()) {
      return;
    }
    const action = selectedNode.actions?.[actionId];
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This action is not available for the selected node.');
      return;
    }
    if (
      action?.requires_confirmation &&
      !(await confirmAction({
        title: t('blackboard.planRunConfirmNodeAction', {
          action: actionLabel(action, actionId),
          defaultValue: `Run "${actionLabel(action, actionId)}" for this durable plan node?`,
        }),
      }))
    ) {
      return;
    }

    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result =
        actionId === 'accept_with_human_review'
          ? await workspacePlanService.acceptNodeAfterReview(workspaceId, selectedNode.id, {
              reason,
              evidenceRefs: selectedEvidence?.evidence_refs ?? [],
            })
          : actionId === 'reopen_blocked'
            ? await workspacePlanService.reopenBlockedNode(workspaceId, selectedNode.id, {
                reason,
              })
            : await workspacePlanService.requestNodeReplan(workspaceId, selectedNode.id, {
                reason,
              });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const retryOutbox = async (item: WorkspacePlanOutboxItem) => {
    if (!assertCurrentPlanForAction()) {
      return;
    }
    const action = item.actions?.retry_outbox;
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This queue job cannot be retried.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_RETRY_ACTION_REASON);
      const result = await workspacePlanService.retryOutboxItem(workspaceId, item.id, {
        reason,
      });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const runIterationAction = async (
    actionId: 'pause_auto_loop' | 'resume_auto_loop' | 'trigger_next_iteration'
  ) => {
    if (!assertCurrentPlanForAction()) {
      return;
    }
    const action = iteration?.actions[actionId];
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'This iteration action is not available.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result =
        actionId === 'pause_auto_loop'
          ? await workspacePlanService.pauseAutoLoop(workspaceId, { reason })
          : actionId === 'resume_auto_loop'
            ? await workspacePlanService.resumeAutoLoop(workspaceId, { reason })
            : await workspacePlanService.triggerNextIteration(workspaceId, { reason });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const runTaskRecoveryAction = async (action: TaskRecoveryAction) => {
    if (!selectedTaskId) {
      return;
    }
    setIsTaskRecoveryPending(true);
    setTaskExperienceError(null);
    try {
      const result = await workspaceTaskService.applyRecoveryAction(workspaceId, selectedTaskId, {
        action,
      });
      const [experience, session] = await Promise.all([
        workspaceTaskService.getExperience(workspaceId, selectedTaskId),
        workspaceTaskService.getExecutionSession(workspaceId, selectedTaskId),
      ]);
      setSelectedTaskExperience(experience);
      setSelectedTaskSession(result.session ?? session);
    } catch (err) {
      setTaskExperienceError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTaskRecoveryPending(false);
    }
  };

  const closeSelectedTask = () => {
    setSelectedTaskId(null);
    setSelectedTaskExperience(null);
    setSelectedTaskSession(null);
    setTaskExperienceError(null);
  };

  const runDeliveryPipeline = async () => {
    if (!assertCurrentPlanForAction()) {
      return;
    }
    const action = delivery?.actions.request_pipeline;
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'Pipeline run is not available.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result = await workspacePlanService.requestPipelineRun(workspaceId, {
        reason,
        nodeId: selectedNode?.id ?? null,
      });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const regenerateDeliveryContract = async () => {
    if (!assertCurrentPlanForAction()) {
      return;
    }
    const action = delivery?.actions.regenerate_contract;
    if (!actionEnabled(action)) {
      setActionError(action?.reason ?? 'Contract regeneration is not available.');
      return;
    }
    setIsActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const reason = reasonOrFallback(operatorReason, DEFAULT_NODE_ACTION_REASON);
      const result = await workspacePlanService.regenerateDeliveryContract(workspaceId, {
        reason,
      });
      setActionMessage(result.message);
      await loadSnapshot({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsActionPending(false);
    }
  };

  const openPreview = async (previewUrl: string, serviceId?: string) => {
    const previewWindow = window.open('about:blank', '_blank', 'noopener,noreferrer');
    if (previewWindow) {
      previewWindow.opener = null;
    }

    setPreviewOpeningUrl(previewUrl);
    setActionError(null);
    setActionMessage(null);
    try {
      let launchUrl = previewUrl;
      if (projectId && serviceId) {
        const session = await projectSandboxService.createHttpServicePreviewSession(
          projectId,
          serviceId
        );
        launchUrl = session.preview_url;
      }

      const isSandboxProxyUrl =
        launchUrl.startsWith('/api/v1/projects/') && launchUrl.includes('/sandbox/http-services/');
      if (isSandboxProxyUrl && !serviceId) {
        await apiFetch.get(launchUrl, {
          credentials: 'include',
        });
      }

      if (previewWindow) {
        previewWindow.location.replace(launchUrl);
      } else {
        window.open(launchUrl, '_blank', 'noopener,noreferrer');
      }
    } catch (err) {
      if (previewWindow) {
        previewWindow.close();
      }
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewOpeningUrl(null);
    }
  };

  return (
    <section className="rounded-lg border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <GitBranch className="h-4 w-4 shrink-0 text-text-secondary dark:text-text-muted" />
            <h3 className="text-lg font-semibold leading-6 text-text-primary dark:text-text-inverse">
              {t('blackboard.planRunTitle', 'Plan run')}
            </h3>
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-text-secondary dark:text-text-muted">
            <span>{stage}</span>
            <span>Updated {formatRelative(lastUpdatedAt)}</span>
            {latestEvent && <span>{eventLabel(latestEvent)}</span>}
            {isStale && <span className="text-status-text-warning">stale snapshot</span>}
          </div>
          {planHistory.length > 1 && (
            <div className="mt-3 flex max-w-3xl flex-col gap-2 md:flex-row md:items-center">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-xs text-text-secondary dark:text-text-muted">
                <History className="h-4 w-4 shrink-0" aria-hidden />
                <span className="shrink-0 font-semibold uppercase">
                  {t('blackboard.planRunGoalHistory', 'Goal history')}
                </span>
                <select
                  aria-label={t('blackboard.planRunGoalHistory', 'Goal history')}
                  value={plan?.id ?? selectedPlanId ?? ''}
                  onChange={(event) => {
                    const nextPlanId = event.target.value || null;
                    setSelectedPlanId(nextPlanId);
                    setSelectedNodeId(null);
                    closeSelectedTask();
                  }}
                  className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-light px-2.5 py-1.5 text-xs text-text-primary outline-none transition-colors focus:border-info-border focus:ring-2 focus:ring-ring dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse"
                >
                  {planHistory.map((item) => (
                    <option key={item.plan_id} value={item.plan_id}>
                      {`${
                        item.is_latest ? `${t('blackboard.planRunCurrentGoal', 'Current')} · ` : ''
                      }${item.title} · ${t(
                        'blackboard.planRunHistoryIterationSummary',
                        'Iteration {{current}}/{{max}}',
                        {
                          current: item.current_iteration,
                          max: item.max_iterations,
                        }
                      )}`}
                    </option>
                  ))}
                </select>
              </label>
              {isHistoricalPlan && (
                <span className="inline-flex shrink-0 rounded border border-warning-border bg-warning-bg px-2 py-1 text-[11px] font-medium text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
                  {t(
                    'blackboard.planRunHistoryReadOnly',
                    'Viewing a historical goal. Plan actions are read-only.'
                  )}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
          <button
            type="button"
            onClick={() => void runAutonomyTick(false)}
            disabled={isTickPending || isHistoricalPlan}
            title={
              isHistoricalPlan
                ? t(
                    'blackboard.planRunHistoryReadOnlyAction',
                    'Select the current goal before running plan actions.'
                  )
                : undefined
            }
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-info-border bg-info-bg px-3 text-sm font-medium text-status-text-info transition-colors hover:bg-info-bg/80 disabled:cursor-not-allowed disabled:opacity-60 dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark lg:min-h-9 lg:text-xs"
          >
            {isTickPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Zap className="h-4 w-4" aria-hidden />
            )}
            {t('blackboard.planRunRunAutonomy', 'Run')}
          </button>
          <button
            type="button"
            onClick={() => void runAutonomyTick(true)}
            disabled={isTickPending || isHistoricalPlan}
            title={
              isHistoricalPlan
                ? t(
                    'blackboard.planRunHistoryReadOnlyAction',
                    'Select the current goal before running plan actions.'
                  )
                : undefined
            }
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
          >
            <Zap className="h-4 w-4" aria-hidden />
            {t('blackboard.planRunForceAutonomy', 'Force')}
          </button>
          <button
            type="button"
            onClick={() => {
              void loadSnapshot();
            }}
            disabled={isLoading}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden />
            )}
            {t('blackboard.planRunRefreshShort', 'Refresh')}
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-4 flex items-start gap-2 rounded-md border border-error-border bg-error-bg p-3 text-xs text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="break-words">{error}</span>
        </div>
      )}

      {(actionError || actionMessage) && (
        <div
          className={`mx-4 mb-4 rounded-md border p-3 text-xs ${
            actionError
              ? 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark'
              : 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
          }`}
          aria-live="polite"
        >
          {actionError ?? actionMessage}
        </div>
      )}

      {!error && !isLoading && !plan && (
        <div className="border-t border-border-separator px-4 py-6 dark:border-border-dark">
          <EmptyState>
            {t('blackboard.planRunEmpty', 'No durable plan has been started for this workspace.')}
          </EmptyState>
        </div>
      )}

      {plan && (
        <div className="border-t border-border-separator dark:border-border-dark">
          <dl className="grid gap-x-5 gap-y-3 px-4 py-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8">
            <CompactMetric
              label={t('blackboard.planRunStatus', 'Plan status')}
              value={plan.status}
            />
            <CompactMetric label={t('blackboard.planRunStage', 'Stage')} value={stage} />
            <CompactMetric
              label={t('blackboard.planRunCompleted', 'Done')}
              value={`${String(completedUnits)} / ${String(totalCompletionUnits)}`}
            />
            <CompactMetric
              label={t('blackboard.planRunCompletion', 'Completion')}
              value={`${String(completion)}%`}
            />
            {rootGoal && (
              <CompactMetric
                label={t('blackboard.planRunRootStatus', 'Root')}
                value={rootGoal.status}
              />
            )}
            {rootGoal?.evidence_grade && (
              <CompactMetric
                label={t('blackboard.planRunEvidenceGrade', 'Evidence')}
                value={rootGoal.evidence_grade}
              />
            )}
            <CompactMetric
              label={t('blackboard.planRunQueue', 'Queue')}
              value={String(outbox.length)}
            />
            <CompactMetric
              label={t('blackboard.planRunEvents', 'Events')}
              value={String(events.length)}
            />
          </dl>
          {rootGoalNeedsClosure(snapshot) && rootGoal?.completion_blocker_reason && (
            <div className="border-t border-warning-border bg-warning-bg px-4 py-3 text-sm text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
              {rootGoal.completion_blocker_reason}
            </div>
          )}
          {snapshot && (
            <WorkbenchStatusBar
              snapshot={snapshot}
              lastUpdatedAt={lastUpdatedAt}
              isStale={isStale}
            />
          )}
          <IterationLoopPanel
            iteration={iteration}
            isActionPending={isActionPending}
            onAction={(actionId) => void runIterationAction(actionId)}
          />
          <DeliveryPanel
            delivery={delivery}
            isActionPending={isActionPending}
            previewOpeningUrl={previewOpeningUrl}
            onRunPipeline={() => void runDeliveryPipeline()}
            onRegenerateContract={() => void regenerateDeliveryContract()}
            onOpenPreview={(previewUrl, serviceId) => void openPreview(previewUrl, serviceId)}
          />

          <div className="grid min-h-[620px]" data-testid="plan-run-dag-workspace">
            <div className="min-w-0 border-t border-border-separator dark:border-border-dark">
              <div className="border-b border-border-separator px-4 py-3 dark:border-border-dark">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                    <Split className="h-4 w-4" aria-hidden />
                    {t('blackboard.planRunNodesTitle', 'Execution DAG')}
                  </div>
                  <div className="inline-flex w-fit rounded-md border border-border-light bg-surface-muted p-0.5 dark:border-border-dark dark:bg-background-dark/35">
                    <button
                      type="button"
                      onClick={() => {
                        setDagViewMode('graph');
                      }}
                      className={`inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
                        dagViewMode === 'graph'
                          ? 'bg-surface-light text-text-primary shadow-sm dark:bg-surface-dark dark:text-text-inverse'
                          : 'text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse'
                      } whitespace-nowrap`}
                    >
                      <GitBranch className="h-3.5 w-3.5" aria-hidden />
                      {t('blackboard.planRunGraphView', 'Graph')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDagViewMode('list');
                      }}
                      className={`inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
                        dagViewMode === 'list'
                          ? 'bg-surface-light text-text-primary shadow-sm dark:bg-surface-dark dark:text-text-inverse'
                          : 'text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse'
                      } whitespace-nowrap`}
                    >
                      <ListTodo className="h-3.5 w-3.5" aria-hidden />
                      {t('blackboard.planRunListView', 'List')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDagViewMode('iterations');
                      }}
                      className={`inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
                        dagViewMode === 'iterations'
                          ? 'bg-surface-light text-text-primary shadow-sm dark:bg-surface-dark dark:text-text-inverse'
                          : 'text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse'
                      } whitespace-nowrap`}
                    >
                      <Repeat2 className="h-3.5 w-3.5" aria-hidden />
                      {t('blackboard.iterationLedgerTitle', 'Iteration ledger')}
                    </button>
                  </div>
                </div>
                {dagViewMode === 'graph' && (
                  <div className="mt-3 flex min-w-0 flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setDagIterationScope(null);
                      }}
                      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors ${
                        dagIterationScope === null
                          ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                          : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                      }`}
                    >
                      <Repeat2 className="h-3.5 w-3.5" aria-hidden />
                      {t('blackboard.planRunCurrentIterationGraph', 'Current iteration')}
                    </button>
                    {iterationRuns.map((run) => (
                      <button
                        key={run.index}
                        type="button"
                        onClick={() => {
                          setDagIterationScope(run.index);
                        }}
                        className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors ${
                          dagIterationScope === run.index
                            ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                            : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                        }`}
                      >
                        {t('blackboard.iterationLabel', 'Iteration {{index}}', {
                          index: run.index,
                        })}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        setDagIterationScope('all');
                      }}
                      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors ${
                        dagIterationScope === 'all'
                          ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                          : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                      }`}
                    >
                      {t('blackboard.planRunAllIterationsGraph', 'All iterations')}
                    </button>
                  </div>
                )}
                <div className="mt-3 flex min-w-0 flex-col gap-2 md:flex-row md:items-start">
                  <label className="relative min-w-0 md:w-56 md:shrink-0">
                    <span className="sr-only">
                      {t('blackboard.planRunSearch', 'Search plan run')}
                    </span>
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
                      aria-hidden
                    />
                    <input
                      value={query}
                      onChange={(event) => {
                        setQuery(event.target.value);
                      }}
                      placeholder={t('blackboard.planRunSearchPlaceholder', 'Search run')}
                      className="h-10 w-full rounded-md border border-border-light bg-surface-light pl-9 pr-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-info-border focus:ring-2 focus:ring-ring dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:h-9 lg:text-xs"
                    />
                  </label>
                  <div
                    className="flex min-w-0 flex-1 flex-wrap gap-2"
                    aria-label={t('blackboard.planRunFilterNodes', 'Filter plan nodes')}
                  >
                    {FILTERS.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          setFilter(item.id);
                        }}
                        className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors lg:min-h-9 ${
                          filter === item.id
                            ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                            : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                        }`}
                      >
                        <Filter className="h-3.5 w-3.5" aria-hidden />
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {dagViewMode === 'iterations' ? (
                <PlanRunIterationLedger
                  runs={iterationRuns}
                  selectedIndex={selectedIterationRun?.index ?? null}
                  selectedNodeId={selectedNode?.id ?? null}
                  onSelectIteration={(index) => {
                    setSelectedIterationIndex(index);
                    setDagIterationScope(index);
                    closeSelectedTask();
                  }}
                  onSelectNode={(nodeId) => {
                    setSelectedNodeId(nodeId);
                    closeSelectedTask();
                  }}
                  onOpenTask={(taskId, nodeId) => {
                    if (nodeId) {
                      setSelectedNodeId(nodeId);
                    }
                    setSelectedTaskExperience(null);
                    setSelectedTaskSession(null);
                    setTaskExperienceError(null);
                    setSelectedTaskId(taskId);
                  }}
                />
              ) : dagViewMode === 'graph' && executionDagModel ? (
                <div className="p-2 sm:p-3">
                  <ExecutionDagGraph
                    model={executionDagModel}
                    selectedNodeId={selectedNode?.id ?? null}
                    dimmedNodeIds={dimmedDagNodeIds}
                    onNodeSelect={(nodeId) => {
                      setSelectedNodeId(nodeId);
                    }}
                    minHeight={640}
                  />
                </div>
              ) : filteredNodes.length > 0 ? (
                <div className="divide-y-0">
                  {filteredNodes.map((node) => (
                    <NodeRow
                      key={node.id}
                      node={node}
                      isSelected={selectedNode?.id === node.id}
                      onSelect={() => {
                        setSelectedNodeId(node.id);
                      }}
                    />
                  ))}
                </div>
              ) : (
                <div className="px-4 py-6">
                  <EmptyState>
                    {t('blackboard.planRunNoNodes', 'No runnable plan nodes match this view.')}
                  </EmptyState>
                </div>
              )}
            </div>

            <aside className="min-w-0 border-t border-border-separator dark:border-border-dark">
              {selectedNode ? (
                <div className="flex min-h-full flex-col">
                  {selectedTask && (
                    <div
                      ref={taskInspectorRef}
                      className="border-b border-border-separator dark:border-border-dark"
                    >
                      <TaskExperiencePanel
                        task={selectedTask}
                        agents={agents}
                        experience={selectedTaskExperience}
                        executionSession={selectedTaskSession}
                        loading={isTaskExperienceLoading}
                        recoveryActionLoading={isTaskRecoveryPending}
                        error={taskExperienceError}
                        onRecoveryAction={(action) => {
                          void runTaskRecoveryAction(action);
                        }}
                        onClose={closeSelectedTask}
                        embedded
                        className="max-h-[calc(100vh-160px)] overflow-y-auto"
                      />
                    </div>
                  )}
                  <div className="border-b border-border-separator px-4 py-4 dark:border-border-dark">
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-semibold uppercase ${fallbackTone(
                              selectedNode.intent
                            )}`}
                          >
                            {selectedNode.intent}
                          </span>
                          <span className="rounded-full border border-border-light px-2.5 py-1 text-[11px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
                            {selectedNode.execution}
                          </span>
                        </div>
                        <h4 className="mt-3 break-words text-base font-semibold leading-6 text-text-primary dark:text-text-inverse">
                          {selectedNode.title}
                        </h4>
                        {selectedNode.description && (
                          <p className="mt-2 line-clamp-4 break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
                            {selectedNode.description}
                          </p>
                        )}
                      </div>
                      <NodeStatusIcon node={selectedNode} />
                    </div>

                    <div className="mt-4 grid gap-2 text-xs text-text-secondary dark:text-text-muted sm:grid-cols-2">
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Node
                        </span>{' '}
                        <span className="font-mono">{shortId(selectedNode.id)}</span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Owner
                        </span>{' '}
                        <span className="font-mono">{shortId(selectedNode.assignee_agent_id)}</span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Attempt
                        </span>{' '}
                        <span className="font-mono">
                          {shortId(selectedNode.current_attempt_id)}
                        </span>
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Updated
                        </span>{' '}
                        {formatTime(selectedNode.updated_at ?? selectedNode.created_at)}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Phase
                        </span>{' '}
                        {nodePhaseLabel(asRecord(selectedNode.metadata))}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Checks
                        </span>{' '}
                        {criterionSummary(selectedNode)}
                      </div>
                      <div>
                        <span className="font-medium text-text-primary dark:text-text-inverse">
                          Write set
                        </span>{' '}
                        {selectedWriteSet.length > 0
                          ? `${String(selectedWriteSet.length)} file(s)`
                          : 'none'}
                      </div>
                    </div>

                    {selectedWriteSet.length > 0 && (
                      <div className="mt-3 rounded-md border border-border-light bg-surface-muted/70 p-3 dark:border-border-dark dark:bg-background-dark/35">
                        <div className="text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
                          Write-scope guard
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {selectedWriteSet.slice(0, 8).map((path) => (
                            <span
                              key={path}
                              className="rounded border border-border-light bg-surface-light px-1.5 py-0.5 font-mono text-[10px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted"
                            >
                              {path}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <label className="mt-4 block">
                      <span className="text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
                        {t('blackboard.planRunOperatorReason', 'Operator reason')}
                      </span>
                      <textarea
                        value={operatorReason}
                        onChange={(event) => {
                          setOperatorReason(event.target.value.slice(0, OPERATOR_REASON_LIMIT));
                        }}
                        maxLength={OPERATOR_REASON_LIMIT}
                        rows={2}
                        placeholder={t(
                          'blackboard.planRunOperatorReasonPlaceholder',
                          'Optional reason for replan, reopen, or retry'
                        )}
                        className="mt-2 w-full resize-y rounded-md border border-border-light bg-surface-light px-3 py-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted focus:border-info-border focus:ring-2 focus:ring-ring dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:text-xs"
                      />
                    </label>

                    <div className="mt-4 flex flex-wrap gap-2">
                      {showOpenAttemptAction &&
                        (canOpenAttempt ? (
                          <Link
                            to={attemptHref}
                            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                          >
                            <ArrowUpRight className="h-4 w-4" aria-hidden />
                            {actionLabel(
                              openAttemptAction,
                              t('blackboard.planRunOpenAttempt', 'Open attempt')
                            )}
                          </Link>
                        ) : (
                          <button
                            type="button"
                            disabled
                            title={openAttemptDisabledReason}
                            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary opacity-60 disabled:cursor-not-allowed dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse lg:min-h-9 lg:text-xs"
                          >
                            <ArrowUpRight className="h-4 w-4" aria-hidden />
                            {actionLabel(
                              openAttemptAction,
                              t('blackboard.planRunOpenAttempt', 'Open attempt')
                            )}
                          </button>
                        ))}
                      <button
                        type="button"
                        onClick={() => void runNodeAction('request_replan')}
                        disabled={isActionPending || !actionEnabled(requestReplanAction)}
                        title={requestReplanDisabledReason}
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden />
                        {actionLabel(
                          requestReplanAction,
                          t('blackboard.planRunRequestReplan', 'Request replan')
                        )}
                      </button>
                      {actionEnabled(acceptAfterReviewAction) && (
                        <button
                          type="button"
                          onClick={() => void runNodeAction('accept_with_human_review')}
                          disabled={isActionPending}
                          title={acceptAfterReviewDisabledReason}
                          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                        >
                          <ShieldCheck className="h-4 w-4" aria-hidden />
                          {actionLabel(
                            acceptAfterReviewAction,
                            t('blackboard.planRunAcceptAfterReview', 'Accept after review')
                          )}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void runNodeAction('reopen_blocked')}
                        disabled={isActionPending || !actionEnabled(reopenBlockedAction)}
                        title={reopenBlockedDisabledReason}
                        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt lg:min-h-9 lg:text-xs"
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden />
                        {actionLabel(
                          reopenBlockedAction,
                          t('blackboard.planRunReopenNode', 'Reopen')
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="min-w-0 flex-1">
                    <div
                      className="flex min-w-0 flex-wrap gap-2 border-b border-border-separator px-4 py-3 dark:border-border-dark"
                      aria-label={t('blackboard.planRunNodeDetails', 'Plan node details')}
                    >
                      {DETAIL_TABS.map((tab) => (
                        <button
                          key={tab.id}
                          type="button"
                          onClick={() => {
                            setSelectedDetailTab(tab.id);
                          }}
                          className={`inline-flex h-8 items-center rounded-md border px-2.5 text-xs font-medium transition-colors ${
                            selectedDetailTab === tab.id
                              ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                              : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
                          }`}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>

                    <div className="min-w-0 px-4 py-3">
                      {selectedDetailTab === 'story' && (
                        <section className="space-y-3">
                          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                            <ShieldCheck className="h-4 w-4" aria-hidden />
                            Phase contract
                          </div>
                          <div className="rounded-md border border-border-light bg-surface-muted p-3 text-xs leading-5 text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted">
                            <div className="font-medium text-text-primary dark:text-text-inverse">
                              {selectedContract?.title ??
                                nodePhaseLabel(asRecord(selectedNode.metadata))}
                            </div>
                            <p className="mt-2 break-words">
                              Entry: {selectedContract?.entry_gate || 'No entry gate recorded.'}
                            </p>
                            <p className="mt-1 break-words">
                              Exit: {selectedContract?.exit_gate || 'No exit gate recorded.'}
                            </p>
                            <p className="mt-1 break-words">
                              Routing:{' '}
                              {compactList(selectedContract?.allowed_routing, 'standard routing')}
                            </p>
                            <p className="mt-1 break-words">
                              Blocked: {selectedContract?.blocked_semantics ?? 'Human-only stops.'}
                            </p>
                          </div>
                          <div className="rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
                            <div className="text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                              Acceptance criteria
                            </div>
                            {selectedNode.acceptance_criteria.length > 0 ? (
                              <ul className="mt-2 space-y-2 text-xs leading-5 text-text-secondary dark:text-text-muted">
                                {selectedNode.acceptance_criteria.map((criterion, index) => (
                                  <li
                                    key={`${criterion.kind}-${String(index)}`}
                                    className="break-words"
                                  >
                                    <span className="font-mono">{criterion.kind}</span>
                                    {criterion.description ? ` · ${criterion.description}` : ''}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="mt-2 text-xs text-text-secondary dark:text-text-muted">
                                No acceptance criteria recorded.
                              </p>
                            )}
                          </div>
                        </section>
                      )}

                      {selectedDetailTab === 'evidence' && selectedEvidence && (
                        <section className="space-y-3">
                          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                            <PackageCheck className="h-4 w-4" aria-hidden />
                            Evidence bundle
                          </div>
                          <div className="grid gap-3 sm:grid-cols-2">
                            {[
                              ['Changed files', selectedEvidence.changed_files],
                              ['Artifacts', selectedEvidence.artifacts],
                              ['Evidence refs', selectedEvidence.evidence_refs],
                              ['Pipeline refs', selectedEvidence.pipeline_refs],
                            ].map(([label, values]) => (
                              <div
                                key={label as string}
                                className="min-w-0 rounded-md border border-border-light bg-surface-muted p-3 dark:border-border-dark dark:bg-background-dark/35"
                              >
                                <div className="text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
                                  {label as string}
                                </div>
                                {(values as string[]).length > 0 ? (
                                  <div className="mt-2 flex flex-wrap gap-1.5">
                                    {(values as string[]).slice(0, 10).map((item) => (
                                      <span
                                        key={item}
                                        className="max-w-full truncate rounded border border-border-light bg-surface-light px-1.5 py-0.5 font-mono text-[10px] text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted"
                                      >
                                        {item}
                                      </span>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="mt-2 text-xs text-text-secondary dark:text-text-muted">
                                    none
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        </section>
                      )}

                      {selectedDetailTab === 'runs' && (
                        <section className="space-y-4">
                          <div>
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                              <Clock3 className="h-4 w-4" aria-hidden />
                              {t('blackboard.planRunNarrativeTitle', 'Execution narrative')}
                            </div>
                            <ul className="mt-1">
                              {selectedEvents.map((event) => (
                                <TimelineRow key={event.id} event={event} />
                              ))}
                            </ul>
                            {selectedEvents.length === 0 && (
                              <div className="py-3">
                                <EmptyState>
                                  {t('blackboard.planRunNoEvents', 'No plan events.')}
                                </EmptyState>
                              </div>
                            )}
                          </div>
                          <div>
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                              <Activity className="h-4 w-4" aria-hidden />
                              {t('blackboard.planRunOutboxTitle', 'Outbox')}
                            </div>
                            <ul className="mt-1">
                              {selectedOutbox.map((item) => (
                                <OutboxRow
                                  key={item.id}
                                  item={item}
                                  onRetry={(target) => {
                                    void retryOutbox(target);
                                  }}
                                  isActionPending={isActionPending}
                                />
                              ))}
                            </ul>
                            {selectedOutbox.length === 0 && (
                              <div className="py-3">
                                <EmptyState>
                                  {t('blackboard.planRunNoOutbox', 'No queued events.')}
                                </EmptyState>
                              </div>
                            )}
                          </div>
                        </section>
                      )}

                      {selectedDetailTab === 'review' && selectedGate && (
                        <section className="space-y-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                              <ShieldCheck className="h-4 w-4" aria-hidden />
                              Review gate
                            </div>
                            <span
                              className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase ${gateTone(
                                selectedGate.status
                              )}`}
                            >
                              {selectedGate.status}
                            </span>
                          </div>
                          <p className="break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
                            {selectedGate.summary || 'No review summary yet.'}
                          </p>
                          {selectedGate.missing.length > 0 && (
                            <div className="rounded-md border border-warning-border bg-warning-bg p-3 text-xs text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
                              Missing: {selectedGate.missing.join(', ')}
                            </div>
                          )}
                          {selectedEvidence?.verification_summary && (
                            <p className="break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
                              Verification: {selectedEvidence.verification_summary}
                            </p>
                          )}
                          {selectedEvidence?.review_summary && (
                            <p className="break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
                              Review: {selectedEvidence.review_summary}
                            </p>
                          )}
                          <div>
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                              <ShieldCheck className="h-4 w-4" aria-hidden />
                              {t('blackboard.planRunBlackboardTitle', 'Typed blackboard')}
                            </div>
                            <ul className="mt-1">
                              {visibleBlackboard.map((entry) => (
                                <BlackboardEntryRow
                                  key={`${entry.key}:${String(entry.version)}`}
                                  entry={entry}
                                />
                              ))}
                            </ul>
                          </div>
                        </section>
                      )}

                      {selectedDetailTab === 'blocker' && (
                        <section className="space-y-3">
                          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
                            <AlertTriangle className="h-4 w-4" aria-hidden />
                            Blocker analysis
                          </div>
                          <div className="rounded-md border border-border-light bg-surface-muted p-3 text-xs leading-5 text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted">
                            <div className="font-medium text-text-primary dark:text-text-inverse">
                              {selectedBlocker?.blocker_type ?? 'none'}
                            </div>
                            <p className="mt-2 break-words">
                              Root cause: {selectedBlocker?.root_cause || 'No blocker recorded.'}
                            </p>
                            <p className="mt-1 break-words">
                              Resolution:{' '}
                              {selectedBlocker?.resolution ||
                                'Continue normal execution or recovery routing.'}
                            </p>
                            <p className="mt-1 break-words">
                              Routing: {selectedBlocker?.routing_decision ?? 'continue'}
                            </p>
                          </div>
                        </section>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="px-4 py-6">
                  <EmptyState>
                    {t('blackboard.planRunSelectNodeEmpty', 'Select a node to inspect it.')}
                  </EmptyState>
                </div>
              )}
            </aside>
          </div>
        </div>
      )}
    </section>
  );
}
