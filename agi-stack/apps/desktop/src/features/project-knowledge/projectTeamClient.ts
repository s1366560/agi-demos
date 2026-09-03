import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_TEAM_ROUTE_ID = 'project-project-team' as const;
export const PROJECT_TEAM_LOCAL_REASON = 'local_project_team_authority_unavailable' as const;
export const PROJECT_TEAM_DEGRADED_REASON = 'desktop_project_team_actions_partial' as const;

export type ProjectTeamRole = 'owner' | 'admin' | 'member' | 'editor' | 'viewer';
export type ProjectTeamMember = Readonly<{
  userId: string;
  email: string;
  name: string | null;
  role: ProjectTeamRole;
  permissions: Readonly<Record<string, unknown>>;
  createdAt: string;
}>;
export type ProjectAgentTeammate = Readonly<{
  id: string;
  name: string;
  enabled: boolean;
  model: string | null;
}>;
export type ProjectTeamSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    members: readonly ProjectTeamMember[];
    agents: readonly ProjectAgentTeammate[];
    currentUserRole: ProjectTeamRole;
  }>;
export type ProjectTeamClient = ProjectKnowledgeClient<ProjectTeamSnapshot>;
