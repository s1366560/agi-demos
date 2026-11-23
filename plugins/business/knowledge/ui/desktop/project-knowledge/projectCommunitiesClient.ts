import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_COMMUNITIES_ROUTE_ID = 'project-project-communities' as const;
export const PROJECT_COMMUNITIES_LOCAL_REASON =
  'local_project_communities_authority_unavailable' as const;
export const PROJECT_COMMUNITIES_DEGRADED_REASON =
  'desktop_project_communities_actions_partial' as const;

export type ProjectCommunity = Readonly<{
  id: string;
  name: string;
  summary: string;
  memberCount: number;
  projectId: string | null;
  createdAt: string | null;
}>;
export type ProjectCommunitiesSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{ communities: readonly ProjectCommunity[]; total: number }>;
export type ProjectCommunitiesClient = ProjectKnowledgeClient<ProjectCommunitiesSnapshot>;
