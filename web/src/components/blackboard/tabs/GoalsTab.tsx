import { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, message } from 'antd';
import { Zap } from 'lucide-react';

import { workspaceAutonomyService } from '@/services/workspaceService';

import { buildBlackboardTaskBoardTasks } from '@/components/blackboard/blackboardUtils';
import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import type {
  CyberObjective,
  WorkspaceAgent,
  WorkspacePlan,
  WorkspacePlanRootGoal,
  WorkspaceTask,
} from '@/types/workspace';

export interface GoalsTabProps {
  objectives: CyberObjective[];
  tasks: WorkspaceTask[];
  agents?: WorkspaceAgent[] | undefined;
  completionRatio: number;
  workspaceId: string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
  plan?: WorkspacePlan | null | undefined;
  rootGoal?: WorkspacePlanRootGoal | null | undefined;
  onDeleteObjective: (objectiveId: string) => void;
  onProjectObjective: (objectiveId: string) => void;
  onCreateObjective: () => void;
}

export function GoalsTab({
  objectives,
  tasks,
  completionRatio,
  workspaceId,
  plan,
  rootGoal,
  onDeleteObjective,
  onProjectObjective,
  onCreateObjective,
}: GoalsTabProps) {
  const { t } = useTranslation();
  const [autonomyTicking, setAutonomyTicking] = useState(false);
  const taskBoardTasks = useMemo(
    () => buildBlackboardTaskBoardTasks(tasks, workspaceId, plan, rootGoal),
    [plan, rootGoal, tasks, workspaceId]
  );

  const handleRunAutonomy = async (force: boolean) => {
    setAutonomyTicking(true);
    try {
      const result = await workspaceAutonomyService.tick(workspaceId, { force });
      if (result.triggered) {
        message.success(
          t(
            'blackboard.autonomy.success',
            'Autonomy triggered. The leader will advance the next step.'
          )
        );
      } else if (result.reason === 'cooling_down') {
        message.info(
          t(
            'blackboard.autonomy.coolingDown',
            'Cooling down. Hold Shift and click again to force a tick.'
          )
        );
      } else if (result.reason === 'no_open_root') {
        message.info(
          t('blackboard.autonomy.noOpenRoot', 'This workspace has no open goal to progress.')
        );
      } else if (result.reason === 'no_root_needs_progress') {
        message.info(t('blackboard.autonomy.stable', 'All goals are stable right now.'));
      } else {
        message.warning(
          t('blackboard.autonomy.noop', 'Autonomy was not triggered: {{reason}}', {
            reason: result.reason || 'unknown',
          })
        );
      }
    } catch (err) {
      const description = err instanceof Error ? err.message : String(err);
      message.error(
        t('blackboard.autonomy.failed', 'Failed to start autonomy: {{description}}', {
          description,
        })
      );
    } finally {
      setAutonomyTicking(false);
    }
  };

  return (
    <div className="min-w-0 space-y-6">
      <ObjectiveList
        objectives={objectives}
        tasks={tasks}
        completionRatio={completionRatio}
        onDelete={onDeleteObjective}
        onProject={onProjectObjective}
        onCreate={onCreateObjective}
      />

      <section className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-light px-4 py-3 dark:border-border-dark dark:bg-surface-dark">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.autonomy.title', 'Autonomy')}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.autonomy.description',
              'Ask the leader to inspect workspace state and advance the next step. Shift-click bypasses cooldown.'
            )}
          </p>
        </div>
        <Button
          size="small"
          type="primary"
          icon={<Zap size={14} />}
          loading={autonomyTicking}
          onClick={(event) => {
            const force = event.shiftKey;
            void handleRunAutonomy(force);
          }}
        >
          {t('blackboard.autonomy.run', 'Run autonomy')}
        </Button>
      </section>

      <TaskBoard workspaceId={workspaceId} tasks={taskBoardTasks} showAutonomyAction={false} />
    </div>
  );
}
