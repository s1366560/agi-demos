import {
  EmptyState as Welcome,
  type EmptyStateProps,
} from '@business/agent/ui/web/chat/EmptyState';
import { ProjectContextCard } from './chat/ProjectContextCard';
import { RecentSkills } from './chat/RecentSkills';
import { TrendingEntities } from './chat/TrendingEntities';

export function EmptyState({
  projectId,
  ...props
}: Omit<EmptyStateProps, 'projectContext'> & { projectId?: string | undefined }) {
  return (
    <Welcome
      {...props}
      projectContext={
        projectId && (
          <div className="space-y-4 mb-6 max-w-2xl w-full relative z-10">
            <ProjectContextCard projectId={projectId} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <TrendingEntities projectId={projectId} onEntityClick={props.onSendPrompt} />
              <RecentSkills projectId={projectId} onSkillClick={props.onSendPrompt} />
            </div>
          </div>
        )
      }
    />
  );
}
export default EmptyState;
