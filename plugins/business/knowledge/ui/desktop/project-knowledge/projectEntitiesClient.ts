import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_ENTITIES_ROUTE_ID = 'project-project-entities' as const;
export const PROJECT_ENTITIES_LOCAL_REASON =
  'local_project_entities_authority_unavailable' as const;
export const PROJECT_ENTITIES_DEGRADED_REASON =
  'desktop_project_entities_actions_partial' as const;

export type ProjectEntity = Readonly<{
  id: string;
  name: string;
  entityType: string;
  summary: string;
  projectId: string | null;
  createdAt: string | null;
}>;
export type ProjectEntityRelationship = Readonly<{
  edgeId: string;
  relationType: string;
  direction: 'outgoing' | 'incoming';
  fact: string;
  relatedEntity: ProjectEntity;
}>;
export type ProjectEntitiesSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    entities: readonly ProjectEntity[];
    total: number;
    entityTypes: readonly Readonly<{ entityType: string; count: number }>[];
  }>;
export type ProjectEntitiesClient = ProjectKnowledgeClient<ProjectEntitiesSnapshot> &
  Readonly<{
    relationships(
      scope: ProjectKnowledgeScope,
      entityId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<readonly ProjectEntityRelationship[]>;
  }>;
