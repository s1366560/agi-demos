import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeClient,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_ENTITIES_ROUTE_ID = 'project-project-entities' as const;
export const PROJECT_ENTITIES_LOCAL_REASON =
  'local_project_entities_authority_unavailable' as const;

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

const ACTIONS = Object.freeze(['view', 'list', 'filter', 'inspect-relationships']);

export function createProjectEntitiesClient(config: DesktopRuntimeConfig): ProjectEntitiesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const withScope = (scope: ProjectKnowledgeScope) =>
    requireProjectKnowledgeScope(runtimeConfig, scope, PROJECT_ENTITIES_LOCAL_REASON);
  const client: ProjectEntitiesClient = {
    async load(scope, options) {
      const currentScope = withScope(scope);
      const scopeRevision = await observeProjectKnowledgeScope(
        runtimeConfig,
        currentScope,
        options,
      );
      const params =
        `tenant_id=${encodeURIComponent(currentScope.tenantId)}` +
        `&project_id=${encodeURIComponent(currentScope.projectId)}`;
      const [entitiesPayload, typesPayload] = await Promise.all([
        requestProjectKnowledgeJson(
          runtimeConfig,
          `/api/v1/graph/entities/?${params}&limit=50&offset=0`,
          options,
        ),
        requestProjectKnowledgeJson(
          runtimeConfig,
          `/api/v1/graph/entities/types?${params}`,
          options,
        ),
      ]);
      const page = parseEntityPage(entitiesPayload, currentScope.projectId);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        ...page,
        entityTypes: parseEntityTypes(typesPayload),
      });
    },
    async relationships(scope, entityId, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        entityRelationshipsPath(entityId),
        options,
      );
      if (!isRecord(payload) || !Array.isArray(payload.relationships)) {
        throw projectKnowledgeError('project_entity_relationships_contract_invalid');
      }
      return Object.freeze(
        payload.relationships.map((value) => parseRelationship(value, currentScope.projectId)),
      );
    },
  };
  return Object.freeze(client);
}

function entityRelationshipsPath(entityId: string): string {
  const id = requireIdentifier(entityId, 'project_entity_id_required');
  return `/api/v1/graph/entities/${encodeURIComponent(id)}/relationships?limit=100`;
}

function parseEntityPage(
  payload: unknown,
  projectId: string,
): Readonly<{ entities: readonly ProjectEntity[]; total: number }> {
  if (!isRecord(payload)) throw projectKnowledgeError('project_entities_page_contract_invalid');
  const values = Array.isArray(payload.entities)
    ? payload.entities
    : Array.isArray(payload.items)
      ? payload.items
      : null;
  if (!values) throw projectKnowledgeError('project_entities_page_contract_invalid');
  const entities = Object.freeze(values.map((value) => parseEntity(value, projectId)));
  const total = requireNonnegativeInteger(payload.total, 'project_entities_page_contract_invalid');
  if (total < entities.length) {
    throw projectKnowledgeError('project_entities_page_contract_invalid');
  }
  return Object.freeze({ entities, total });
}

function parseEntity(payload: unknown, projectId: string): ProjectEntity {
  if (!isRecord(payload)) throw projectKnowledgeError('project_entity_contract_invalid');
  if (
    payload.project_id !== undefined &&
    payload.project_id !== null &&
    payload.project_id !== projectId
  ) {
    throw projectKnowledgeError('project_entity_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.uuid, 'project_entity_contract_invalid'),
    name: requireIdentifier(payload.name, 'project_entity_contract_invalid'),
    entityType: requireIdentifier(payload.entity_type, 'project_entity_contract_invalid'),
    summary: requireText(payload.summary, 'project_entity_contract_invalid'),
    projectId: optionalText(payload.project_id, 'project_entity_contract_invalid'),
    createdAt: optionalText(payload.created_at, 'project_entity_contract_invalid'),
  });
}

function parseEntityTypes(
  payload: unknown,
): readonly Readonly<{ entityType: string; count: number }>[] {
  if (!isRecord(payload) || !Array.isArray(payload.entity_types)) {
    throw projectKnowledgeError('project_entity_types_contract_invalid');
  }
  return Object.freeze(
    payload.entity_types.map((value) => {
      if (!isRecord(value)) throw projectKnowledgeError('project_entity_type_contract_invalid');
      return Object.freeze({
        entityType: requireIdentifier(value.entity_type, 'project_entity_type_contract_invalid'),
        count: requireNonnegativeInteger(value.count, 'project_entity_type_contract_invalid'),
      });
    }),
  );
}

function parseRelationship(value: unknown, projectId: string): ProjectEntityRelationship {
  if (!isRecord(value) || !isRecord(value.related_entity)) {
    throw projectKnowledgeError('project_entity_relationship_contract_invalid');
  }
  if (value.direction !== 'outgoing' && value.direction !== 'incoming') {
    throw projectKnowledgeError('project_entity_relationship_contract_invalid');
  }
  return Object.freeze({
    edgeId: requireIdentifier(value.edge_id, 'project_entity_relationship_contract_invalid'),
    relationType: requireIdentifier(
      value.relation_type,
      'project_entity_relationship_contract_invalid',
    ),
    direction: value.direction,
    fact: requireText(value.fact, 'project_entity_relationship_contract_invalid'),
    relatedEntity: parseEntity(value.related_entity, projectId),
  });
}
