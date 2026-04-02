import { useTranslation } from 'react-i18next';

import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import { StatBadge } from '../StatBadge';

import type { CyberObjective, WorkspaceTask } from '@/types/workspace';

export interface GoalsTabProps {
  objectives: CyberObjective[];
  tasks: WorkspaceTask[];
  completionRatio: number;
  workspaceId: string;
  onDeleteObjective: (objectiveId: string) => void;
  onCreateObjective: () => void;
}

export function GoalsTab({
  objectives,
  tasks,
  completionRatio,
  workspaceId,
  onDeleteObjective,
  onCreateObjective,
}: GoalsTabProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-border-light bg-surface-muted px-4 py-4 dark:border-border-dark dark:bg-background-dark/35">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.goalsOverviewTitle', 'Goals and delivery')}
            </h3>
          </div>
          <dl className="flex flex-wrap gap-2">
            {[
              {
                key: 'completion',
                label: t('blackboard.metrics.completion', 'Task completion'),
                value: `${String(completionRatio)}%`,
              },
              {
                key: 'objectives',
                label: t('blackboard.objectivesTitle', 'Goals'),
                value: String(objectives.length),
              },
              {
                key: 'tasks',
                label: t('blackboard.metrics.tasks', 'Tasks'),
                value: String(tasks.length),
              },
            ].map((metric) => (
              <StatBadge key={metric.key} label={metric.label} value={metric.value} />
            ))}
          </dl>
        </div>
      </section>

      <ObjectiveList
        objectives={objectives}
        onDelete={onDeleteObjective}
        onCreate={onCreateObjective}
      />

      <TaskBoard workspaceId={workspaceId} />
    </div>
  );
}
