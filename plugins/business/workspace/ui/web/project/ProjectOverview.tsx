import { projectAPI } from '@/services/api';
import { memoryAPI } from '@business/knowledge/ui/web/services/knowledgeApi';
import { ProjectOverviewView, type ProjectOverviewData } from './ProjectOverviewView';

async function loadOverview(tenant: string, project: string): Promise<ProjectOverviewData> {
  const [info, stats, recent] = await Promise.all([
    projectAPI.get(tenant, project),
    projectAPI.getStats(project),
    memoryAPI.list(project, { page: 1, page_size: 5 }),
  ]);
  return { project: info, stats: stats as ProjectOverviewData['stats'], recent };
}

export function ProjectOverview() {
  return <ProjectOverviewView load={loadOverview} />;
}
