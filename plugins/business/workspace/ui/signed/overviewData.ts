import type { ProjectOverviewData } from '../web/project/ProjectOverviewView';
import type {
  CloudProjectOverviewProject,
  CloudProjectOverviewMemory,
} from '../desktop/project/projectOverviewClient';

type Snapshot = ProjectOverviewData & {
  project: CloudProjectOverviewProject;
  recent: { memories: CloudProjectOverviewMemory[]; total: number } | null;
};

export function readOverview(signal?: AbortSignal): Promise<Snapshot> {
  return window.memstack.invoke('read-project-overview', undefined, { signal }) as Promise<Snapshot>;
}
