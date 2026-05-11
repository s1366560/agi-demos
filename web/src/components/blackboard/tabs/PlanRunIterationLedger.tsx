import type { ReactNode } from 'react';

import { useTranslation } from 'react-i18next';

import { Activity, GitCommit, ListChecks, PackageCheck, Repeat2 } from 'lucide-react';

import { asText, fallbackTone, formatTime, shortId } from './planRunSnapshotModel';
import { NodeStatusIcon, TimelineRow } from './PlanRunSnapshotParts';

import type { WorkspacePlanIterationRun } from './planRunSnapshotModel';

const PHASE_LABEL_KEYS: Record<string, [string, string]> = {
  research: ['blackboard.iterationPhaseResearch', 'Research'],
  plan: ['blackboard.iterationPhasePlan', 'Plan'],
  implement: ['blackboard.iterationPhaseImplement', 'Implement'],
  test: ['blackboard.iterationPhaseTest', 'Test'],
  deploy: ['blackboard.iterationPhaseDeploy', 'Deploy'],
  review: ['blackboard.iterationPhaseReview', 'Review'],
};

interface PlanRunIterationLedgerProps {
  runs: WorkspacePlanIterationRun[];
  selectedIndex: number | null;
  selectedNodeId: string | null;
  onSelectIteration: (index: number) => void;
  onSelectNode: (nodeId: string) => void;
  onOpenTask: (taskId: string, nodeId?: string) => void;
  taskInspector?: ReactNode;
}

export function PlanRunIterationLedger({
  runs,
  selectedIndex,
  selectedNodeId,
  onSelectIteration,
  onSelectNode,
  onOpenTask,
  taskInspector,
}: PlanRunIterationLedgerProps) {
  const { t } = useTranslation();
  if (runs.length === 0) {
    return null;
  }
  const selectedRun = runs.find((run) => run.index === selectedIndex) ?? runs.at(-1) ?? runs[0];
  if (!selectedRun) {
    return null;
  }

  return (
    <section className="border-t border-border-separator px-4 py-4 dark:border-border-dark">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
            <Repeat2 className="h-4 w-4" aria-hidden />
            {t('blackboard.iterationLedgerTitle', 'Iteration ledger')}
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.iterationLedgerDescription',
              'Review each sprint by tasks, outputs, verification, and interactions.'
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] text-text-muted">
          <span>
            {t('blackboard.iterationLedgerTotal', '{{count}} iterations', { count: runs.length })}
          </span>
          <span>
            {t('blackboard.iterationLedgerSelected', 'Selected {{index}}', {
              index: selectedRun.index,
            })}
          </span>
        </div>
      </div>

      <div
        className="mt-3 flex gap-2 overflow-x-auto pb-1"
        role="tablist"
        aria-label={t('blackboard.iterationLedgerAria', 'Iteration ledger')}
      >
        {runs.map((run) => {
          const selected = run.index === selectedRun.index;
          return (
            <button
              key={run.index}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => {
                onSelectIteration(run.index);
              }}
              className={`min-w-[176px] rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                selected
                  ? 'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark'
                  : 'border-border-light bg-surface-light text-text-secondary hover:bg-surface-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted dark:hover:bg-surface-dark-alt'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold">
                  {t('blackboard.iterationLabel', 'Iteration {{index}}', { index: run.index })}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${fallbackTone(
                    run.status
                  )}`}
                >
                  {run.status}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-4 gap-1 font-mono text-[10px]">
                <Metric
                  label={t('blackboard.iterationMetricTasks', 'Tasks')}
                  value={`${String(run.counts.done)}/${String(run.counts.total)}`}
                />
                <Metric
                  label={t('blackboard.iterationMetricOutputs', 'Outputs')}
                  value={String(run.outputs.total)}
                />
                <Metric
                  label={t('blackboard.iterationMetricAttempts', 'Attempts')}
                  value={`${String(run.attempts.accepted ?? 0)}/${String(run.attempts.total ?? 0)}`}
                />
                <Metric
                  label={t('blackboard.iterationMetricCarryover', 'Carry')}
                  value={String(run.carryoverNodeIds.length)}
                />
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,0.9fr)_minmax(400px,0.65fr)]">
        <div className="min-w-0 space-y-4">
          <IterationOverview run={selectedRun} />
          <IterationTaskTable
            run={selectedRun}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            onOpenTask={onOpenTask}
          />
        </div>
        <div className="min-w-0 space-y-4">
          {taskInspector}
          <IterationRunHealth run={selectedRun} />
          <IterationOutputList run={selectedRun} />
          <IterationActivityTimeline run={selectedRun} />
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="min-w-0">
      <span className="block truncate text-text-muted">{label}</span>
      <span className="block truncate font-semibold text-text-primary dark:text-text-inverse">
        {value}
      </span>
    </span>
  );
}

function IterationOverview({ run }: { run: WorkspacePlanIterationRun }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
      <div className="grid gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${fallbackTone(
                run.status
              )}`}
            >
              {run.status}
            </span>
            {run.startedAt && (
              <span className="font-mono text-[11px] text-text-muted">
                {formatTime(run.startedAt)}
                {run.completedAt ? ` - ${formatTime(run.completedAt)}` : ''}
              </span>
            )}
          </div>
          <p className="mt-2 break-words text-sm font-semibold leading-5 text-text-primary dark:text-text-inverse">
            {run.sprintGoal || t('blackboard.iterationGoalFallback', 'No sprint goal recorded')}
          </p>
          {run.reviewSummary && (
            <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
              {run.reviewSummary}
            </p>
          )}
          {run.nextSprintGoal && (
            <p className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
              {t('blackboard.iterationNextGoal', 'Next goal')}: {run.nextSprintGoal}
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <DenseStat
            label={t('blackboard.iterationMetricDone', 'Done')}
            value={String(run.counts.done)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricRunning', 'Running')}
            value={String(run.counts.running)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricBlocked', 'Blocked')}
            value={String(run.counts.blocked)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricVerify', 'Verify')}
            value={String(run.counts.verifying)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricAttempts', 'Attempts')}
            value={String(run.attempts.total ?? 0)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricRejected', 'Rejected')}
            value={String((run.attempts.rejected ?? 0) + (run.attempts.blocked ?? 0))}
          />
          <DenseStat
            label={t('blackboard.iterationMetricRepair', 'Repair')}
            value={String(run.repairTurns.length)}
          />
          <DenseStat
            label={t('blackboard.iterationMetricActivity', 'Activity')}
            value={String(run.interactions.total)}
          />
        </div>
      </div>
    </div>
  );
}

function DenseStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-light bg-surface-muted px-2 py-1.5 dark:border-border-dark dark:bg-background-dark/35">
      <div className="text-[10px] font-semibold uppercase text-text-muted">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold text-text-primary dark:text-text-inverse">
        {value}
      </div>
    </div>
  );
}

function IterationTaskTable({
  run,
  selectedNodeId,
  onSelectNode,
  onOpenTask,
}: {
  run: WorkspacePlanIterationRun;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onOpenTask: (taskId: string, nodeId?: string) => void;
}) {
  const { t } = useTranslation();
  if (run.nodes.length === 0) {
    return (
      <div className="rounded-md border border-border-light bg-surface-light px-3 py-6 text-center text-xs text-text-muted dark:border-border-dark dark:bg-surface-dark">
        {t('blackboard.iterationNoTasks', 'No tasks were recorded for this iteration.')}
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-md border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-center gap-2 border-b border-border-separator px-3 py-2 text-xs font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
        <ListChecks className="h-4 w-4" aria-hidden />
        {t('blackboard.iterationTasksTitle', 'Iteration tasks')}
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[760px] w-full text-left text-xs">
          <thead className="border-b border-border-separator bg-surface-muted text-[10px] uppercase text-text-muted dark:border-border-dark dark:bg-background-dark/35">
            <tr>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTablePhase', 'Phase')}
              </th>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTableTask', 'Task')}
              </th>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTableStatus', 'Status')}
              </th>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTableAttempt', 'Attempt')}
              </th>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTableEvidence', 'Evidence')}
              </th>
              <th className="px-3 py-2 font-semibold">
                {t('blackboard.iterationTableOutput', 'Output')}
              </th>
            </tr>
          </thead>
          <tbody>
            {run.nodes.map((node) => {
              const phase = asText(node.metadata.iteration_phase) || 'plan';
              const phaseLabel = PHASE_LABEL_KEYS[phase]
                ? t(PHASE_LABEL_KEYS[phase][0], PHASE_LABEL_KEYS[phase][1])
                : phase;
              const artifacts = node.evidence_bundle?.artifacts.length ?? 0;
              const checks = node.evidence_bundle?.evidence_refs.length ?? 0;
              const files = node.evidence_bundle?.changed_files.length ?? 0;
              const isSelected = selectedNodeId === node.id;
              return (
                <tr
                  key={node.id}
                  className={`border-b border-border-separator last:border-0 dark:border-border-dark ${
                    isSelected ? 'bg-info-bg dark:bg-info-bg-dark' : ''
                  }`}
                >
                  <td className="px-3 py-2 align-top text-text-muted">{phaseLabel}</td>
                  <td className="px-3 py-2 align-top">
                    <button
                      type="button"
                      onClick={() => {
                        onSelectNode(node.id);
                      }}
                      className="flex min-w-0 items-start gap-2 text-left text-text-primary hover:text-status-text-info focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-text-inverse"
                    >
                      <span className="mt-0.5 shrink-0">
                        <NodeStatusIcon node={node} />
                      </span>
                      <span className="min-w-0">
                        <span className="block break-words font-medium">{node.title}</span>
                        <span className="mt-0.5 block font-mono text-[10px] text-text-muted">
                          {shortId(node.id)}
                        </span>
                      </span>
                    </button>
                    {node.workspace_task_id && (
                      <button
                        type="button"
                        onClick={() => {
                          onOpenTask(node.workspace_task_id as string, node.id);
                        }}
                        className="mt-1 text-[11px] font-medium text-status-text-info hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {t('blackboard.iterationOpenTask', 'Open task details')}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span
                      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${fallbackTone(
                        node.intent
                      )}`}
                    >
                      {node.intent}
                    </span>
                    <div className="mt-1 font-mono text-[10px] text-text-muted">
                      {node.execution}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top font-mono text-[11px] text-text-muted">
                    {node.current_attempt_id ? shortId(node.current_attempt_id) : 'n/a'}
                  </td>
                  <td className="px-3 py-2 align-top text-text-secondary dark:text-text-muted">
                    {checks} {t('blackboard.iterationEvidenceRefs', 'refs')}
                    {node.gate_status?.missing.length ? (
                      <div className="mt-1 line-clamp-2 text-status-text-warning dark:text-status-text-warning-dark">
                        {node.gate_status.missing.join(', ')}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 align-top text-text-secondary dark:text-text-muted">
                    {artifacts} {t('blackboard.iterationArtifacts', 'artifacts')}
                    {files > 0 ? (
                      <div className="mt-1 font-mono text-[10px] text-text-muted">
                        {files} {t('blackboard.iterationFiles', 'files')}
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IterationRunHealth({ run }: { run: WorkspacePlanIterationRun }) {
  const { t } = useTranslation();
  const totalAttempts = run.attempts.total ?? 0;
  const acceptedAttempts = run.attempts.accepted ?? 0;
  const successRate = totalAttempts > 0 ? Math.round((acceptedAttempts / totalAttempts) * 100) : 0;
  const rejectedAttempts = (run.attempts.rejected ?? 0) + (run.attempts.blocked ?? 0);
  const verificationFailures =
    (run.verification.rejected ?? 0) +
    (run.verification.infra_error ?? 0) +
    (run.verification.missing_evidence ?? 0) +
    (run.verification.dirty_worktree ?? 0);
  const workerFeedback = run.feedback['layer:worker'] ?? 0;
  const plannerFeedback =
    (run.feedback['layer:planner'] ?? 0) + (run.feedback['layer:reviewer'] ?? 0);
  const runtimeFeedback = run.feedback['layer:runtime'] ?? 0;
  const staleTargetFeedback = run.feedback['kind:stale_or_invalid_task_target'] ?? 0;
  const hasFeedback = workerFeedback + plannerFeedback + runtimeFeedback + staleTargetFeedback > 0;

  return (
    <div className="rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
          <Activity className="h-4 w-4" aria-hidden />
          {t('blackboard.iterationRunHealthTitle', 'Run health')}
        </div>
        <span className="font-mono text-[11px] text-text-muted">
          {t('blackboard.iterationRunHealthSuccess', '{{value}}% accepted', {
            value: successRate,
          })}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <DenseCounter
          label={t('blackboard.iterationMetricAttempts', 'Attempts')}
          value={totalAttempts}
        />
        <DenseCounter
          label={t('blackboard.iterationMetricRejected', 'Rejected')}
          value={rejectedAttempts}
        />
        <DenseCounter
          label={t('blackboard.iterationMetricRepair', 'Repair')}
          value={run.repairTurns.length}
        />
        <DenseCounter
          label={t('blackboard.iterationMetricVerifyFail', 'Verify fail')}
          value={verificationFailures}
        />
      </div>
      {hasFeedback && (
        <div className="mt-2 grid grid-cols-2 gap-2 border-t border-border-separator pt-2 text-xs dark:border-border-dark sm:grid-cols-4">
          <DenseCounter
            label={t('blackboard.iterationFeedbackWorker', 'Worker retry')}
            value={workerFeedback}
          />
          <DenseCounter
            label={t('blackboard.iterationFeedbackPlanner', 'Planner fix')}
            value={plannerFeedback}
          />
          <DenseCounter
            label={t('blackboard.iterationFeedbackRuntime', 'Runtime')}
            value={runtimeFeedback}
          />
          <DenseCounter
            label={t('blackboard.iterationFeedbackStale', 'Stale target')}
            value={staleTargetFeedback}
          />
        </div>
      )}
      {run.repairTurns.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-border-separator pt-2 text-[11px] dark:border-border-dark">
          {run.repairTurns.slice(-3).map((turn, index) => (
            <div
              key={`${String(turn.attempt_id ?? turn.event_type ?? 'repair')}-${index}`}
              className="flex min-w-0 items-center justify-between gap-2"
            >
              <span className="truncate text-text-secondary dark:text-text-muted">
                {String(turn.event_type ?? 'repair_turn')}
              </span>
              <span className="shrink-0 font-mono text-text-muted">
                {shortId(String(turn.attempt_id ?? '')) || String(turn.repair_turn_index ?? '')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function IterationOutputList({ run }: { run: WorkspacePlanIterationRun }) {
  const { t } = useTranslation();
  const groups = [
    {
      key: 'commits',
      label: t('blackboard.iterationOutputCommits', 'Commits'),
      items: run.outputs.commitRefs,
    },
    {
      key: 'files',
      label: t('blackboard.iterationOutputFiles', 'Changed files'),
      items: run.outputs.changedFiles,
    },
    {
      key: 'artifacts',
      label: t('blackboard.iterationOutputArtifacts', 'Artifacts'),
      items: run.outputs.artifacts,
    },
    {
      key: 'evidence',
      label: t('blackboard.iterationOutputEvidence', 'Evidence'),
      items: run.outputs.evidenceRefs,
    },
    {
      key: 'pipelines',
      label: t('blackboard.iterationOutputPipelines', 'Pipelines'),
      items: run.outputs.pipelineRefs,
    },
    {
      key: 'blackboard',
      label: t('blackboard.iterationOutputBlackboard', 'Blackboard'),
      items: run.outputs.blackboardKeys,
    },
  ];
  return (
    <div className="rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
          <PackageCheck className="h-4 w-4" aria-hidden />
          {t('blackboard.iterationOutputsTitle', 'Outputs')}
        </div>
        <span className="font-mono text-[11px] text-text-muted">{run.outputs.total}</span>
      </div>
      <div className="mt-3 space-y-2">
        {groups.map((group) => (
          <OutputGroup key={group.key} label={group.label} items={group.items} />
        ))}
      </div>
    </div>
  );
}

function OutputGroup({ label, items }: { label: string; items: string[] }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2 text-xs">
      <span className="text-text-muted">{label}</span>
      {items.length === 0 ? (
        <span className="text-[11px] text-text-muted">
          {t('blackboard.iterationOutputEmpty', 'none')}
        </span>
      ) : (
        <div className="flex min-w-0 flex-wrap gap-1">
          {items.slice(0, 8).map((item) => (
            <span
              key={item}
              className="max-w-full truncate rounded border border-border-light bg-surface-muted px-2 py-0.5 font-mono text-[10px] text-text-secondary dark:border-border-dark dark:bg-background-dark/35 dark:text-text-muted"
              title={item}
            >
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function IterationActivityTimeline({ run }: { run: WorkspacePlanIterationRun }) {
  const { t } = useTranslation();
  const visibleEvents = run.events.slice(-5).reverse();
  return (
    <div className="rounded-md border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-text-secondary dark:text-text-muted">
        <Activity className="h-4 w-4" aria-hidden />
        {t('blackboard.iterationActivityTitle', 'Activity')}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs sm:grid-cols-6">
        <DenseCounter
          label={t('blackboard.iterationActivityWorker', 'Worker')}
          value={run.interactions.worker}
        />
        <DenseCounter
          label={t('blackboard.iterationActivityVerifier', 'Verifier')}
          value={run.interactions.verifier}
        />
        <DenseCounter
          label={t('blackboard.iterationActivitySupervisor', 'Supervisor')}
          value={run.interactions.supervisor}
        />
        <DenseCounter
          label={t('blackboard.iterationActivityOperator', 'Operator')}
          value={run.interactions.operator}
        />
        <DenseCounter
          label={t('blackboard.iterationActivityRetry', 'Retry')}
          value={run.interactions.retries}
        />
        <DenseCounter
          label={t('blackboard.iterationActivityFailed', 'Failed')}
          value={run.interactions.failed}
        />
      </div>
      {visibleEvents.length === 0 && run.outbox.length === 0 ? (
        <p className="mt-3 text-xs text-text-muted">
          {t('blackboard.iterationNoActivity', 'No activity was recorded for this iteration.')}
        </p>
      ) : (
        <ul className="mt-2 max-h-[280px] overflow-y-auto">
          {visibleEvents.map((event) => (
            <TimelineRow key={event.id} event={event} />
          ))}
          {run.outbox.slice(-3).map((item) => (
            <li
              key={item.id}
              className="border-b border-border-separator py-3 last:border-b-0 dark:border-border-dark"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="break-words text-sm font-medium text-text-primary dark:text-text-inverse">
                  {item.event_type}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${fallbackTone(
                    item.status
                  )}`}
                >
                  {item.status}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 font-mono text-[10px] text-text-muted">
                <span>{shortId(item.id)}</span>
                <span>
                  <GitCommit className="mr-1 inline h-3 w-3" aria-hidden />
                  {item.attempt_count}/{item.max_attempts}
                </span>
              </div>
              {item.last_error && (
                <p className="mt-1 line-clamp-2 break-words text-xs text-status-text-warning dark:text-status-text-warning-dark">
                  {item.last_error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DenseCounter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-border-light bg-surface-muted px-2 py-1 dark:border-border-dark dark:bg-background-dark/35">
      <div className="font-mono text-sm font-semibold text-text-primary dark:text-text-inverse">
        {value}
      </div>
      <div className="truncate text-[10px] uppercase text-text-muted">{label}</div>
    </div>
  );
}
