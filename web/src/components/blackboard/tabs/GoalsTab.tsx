import { Button } from 'antd';

import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import type { CyberObjective, WorkspaceGoalCandidate, WorkspaceTask } from '@/types/workspace';

function formatCandidateDecision(decision: WorkspaceGoalCandidate['decision']): string {
  return decision.replace(/_/g, ' ');
}

export interface GoalsTabProps {
  objectives: CyberObjective[];
  goalCandidates: WorkspaceGoalCandidate[];
  goalCandidatesLoading: boolean;
  goalCandidatesError: string | null;
  tasks: WorkspaceTask[];
  completionRatio: number;
  workspaceId: string;
  onDeleteObjective: (objectiveId: string) => void;
  onProjectObjective: (objectiveId: string) => void;
  onCreateObjective: () => void;
  onRefreshGoalCandidates: () => void;
  onMaterializeGoalCandidate: (candidateId: string) => void;
}

export function GoalsTab({
  objectives,
  goalCandidates,
  goalCandidatesLoading,
  goalCandidatesError,
  workspaceId,
  onDeleteObjective,
  onProjectObjective,
  onCreateObjective,
  onRefreshGoalCandidates,
  onMaterializeGoalCandidate,
}: GoalsTabProps) {
  return (
    <div className="space-y-6">
      <ObjectiveList
        objectives={objectives}
        onDelete={onDeleteObjective}
        onProject={onProjectObjective}
        onCreate={onCreateObjective}
      />

      <section className="space-y-3 rounded-xl border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            Goal candidates
          </h3>
          <Button size="small" onClick={onRefreshGoalCandidates}>
            Refresh
          </Button>
        </div>
        {goalCandidatesLoading ? (
          <p className="text-xs text-text-secondary dark:text-text-muted">Loading candidates…</p>
        ) : goalCandidatesError ? (
          <p className="text-xs text-status-text-error dark:text-status-text-error-dark">
            {goalCandidatesError}
          </p>
        ) : goalCandidates.length === 0 ? (
          <p className="text-xs text-text-secondary dark:text-text-muted">
            No goal candidates available.
          </p>
        ) : (
          <div className="space-y-2">
            {goalCandidates.map((candidate) => (
              <div
                key={candidate.candidate_id}
                className="rounded-lg border border-border-light bg-surface-muted/60 p-3 dark:border-border-dark dark:bg-surface-dark-alt/60"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-text-primary dark:text-text-inverse">
                      {candidate.candidate_text}
                    </div>
                    <div className="mt-1 text-[11px] text-text-secondary dark:text-text-muted">
                      {formatCandidateDecision(candidate.decision)} · evidence{' '}
                      {candidate.evidence_strength.toFixed(2)}
                    </div>
                  </div>
                  {(candidate.decision === 'formalize_new_goal' ||
                    candidate.decision === 'adopt_existing_goal') && (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => {
                        onMaterializeGoalCandidate(candidate.candidate_id);
                      }}
                    >
                      Materialize
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <TaskBoard workspaceId={workspaceId} />
    </div>
  );
}
