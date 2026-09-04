import {
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from '../project-knowledge/projectKnowledgeClient';

export const PROJECT_PLAYBOOKS_ROUTE_ID = 'project-playbooks' as const;
export const PROJECT_PLAYBOOKS_LOCAL_REASON =
  'local_project_playbooks_cloud_authority_unavailable' as const;

export type ProjectPlaybookTrigger = Readonly<{
  description: string;
  frictionKinds: readonly string[];
  laneTransitions: readonly (readonly [string, string])[];
}>;
export type ProjectPlaybookStep = Readonly<{
  order: number;
  instruction: string;
  rationale: string | null;
}>;
export type ProjectPlaybook = Readonly<{
  id: string;
  projectId: string;
  name: string;
  status: string;
  trigger: ProjectPlaybookTrigger;
  steps: readonly ProjectPlaybookStep[];
  hitCount: number;
  lastUsedAt: string | null;
  createdAt: string;
  updatedAt: string;
}>;
export type ReflectionVerdictAction = 'create' | 'reinforce' | 'deprecate' | 'noop';
export type ProjectReflectionVerdict = Readonly<{
  id: string;
  projectId: string;
  action: ReflectionVerdictAction;
  playbookId: string | null;
  rationale: string;
  proposedPayload: Readonly<Record<string, unknown>> | null;
  createdAt: string;
}>;
export type ProjectPlaybooksSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    playbooks: readonly ProjectPlaybook[];
    verdicts: readonly ProjectReflectionVerdict[];
  }>;
export type ProjectPlaybooksClient = Readonly<{
  load(
    scope: ProjectKnowledgeScope,
    options?: ProjectKnowledgeReadOptions,
  ): Promise<ProjectPlaybooksSnapshot>;
}>;
