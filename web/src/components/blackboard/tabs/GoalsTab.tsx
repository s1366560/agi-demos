import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

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
  workspaceId,
  onDeleteObjective,
  onCreateObjective,
}: GoalsTabProps) {
  return (
    <div className="space-y-6">
      <ObjectiveList
        objectives={objectives}
        onDelete={onDeleteObjective}
        onCreate={onCreateObjective}
      />

      <TaskBoard workspaceId={workspaceId} />
    </div>
  );
}
