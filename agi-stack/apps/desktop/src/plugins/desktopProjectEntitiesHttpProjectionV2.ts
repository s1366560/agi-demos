import {
  PROJECT_ENTITIES_DEGRADED_REASON,
  PROJECT_ENTITIES_LOCAL_REASON,
  type ProjectEntitiesSnapshot,
  type ProjectEntity,
  type ProjectEntityRelationship,
} from '../features/project-knowledge/projectEntitiesClient';
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
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectEntitiesRuntimeConfigV2,
  cloneDesktopProjectEntitiesScopeV2,
} from './desktopProjectEntitiesOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list']);

export type DesktopProjectEntitiesHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectEntitiesSnapshot>;
  relationships: (
    entityId: string,
    signal?: AbortSignal,
  ) => Promise<readonly ProjectEntityRelationship[]>;
}>;

export function createDesktopProjectEntitiesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectEntitiesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectEntitiesRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectEntitiesScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_ENTITIES_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      const params = scopeQueryV2(currentScope);
      const [entitiesPayload, typesPayload] = await Promise.all([
        requestProjectKnowledgeJson(
          runtimeConfig,
          `/api/v1/graph/entities/?${params}&limit=50&offset=0`,
          { signal },
        ),
        requestProjectKnowledgeJson(
          runtimeConfig,
          `/api/v1/graph/entities/types?${params}`,
          { signal },
        ),
      ]);
      const page = parseEntityPageV2(entitiesPayload, currentScope);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_ENTITIES_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...page,
        entityTypes: parseEntityTypesV2(typesPayload),
      });
    },
    async relationships(entityId, signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_ENTITIES_LOCAL_REASON,
      );
      const canonicalEntityId = requireIdentifier(entityId, 'project_entity_id_required');
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        `/api/v1/graph/entities/${encodeURIComponent(canonicalEntityId)}/relationships?limit=100`,
        { signal },
      );
      if (!isRecord(payload) || !Array.isArray(payload.relationships)) {
        throw projectKnowledgeError('project_entity_relationships_contract_invalid');
      }
      return Object.freeze(
        payload.relationships.map((value) => parseRelationshipV2(value, currentScope)),
      );
    },
  });
}

function scopeQueryV2(scope: ProjectKnowledgeScope): string {
  return (
    `tenant_id=${encodeURIComponent(scope.tenantId)}` +
    `&project_id=${encodeURIComponent(scope.projectId)}`
  );
}

function parseEntityPageV2(
  payload: unknown,
  scope: ProjectKnowledgeScope,
): Readonly<{ entities: readonly ProjectEntity[]; total: number }> {
  if (!isRecord(payload)) {
    throw projectKnowledgeError('project_entities_page_contract_invalid');
  }
  const values = Array.isArray(payload.entities)
    ? payload.entities
    : Array.isArray(payload.items)
      ? payload.items
      : null;
  if (values === null) {
    throw projectKnowledgeError('project_entities_page_contract_invalid');
  }
  const entities = Object.freeze(values.map((value) => parseEntityV2(value, scope)));
  const total = requireNonnegativeInteger(
    payload.total,
    'project_entities_page_contract_invalid',
  );
  if (total < entities.length) {
    throw projectKnowledgeError('project_entities_page_contract_invalid');
  }
  return Object.freeze({ entities, total });
}

function parseEntityV2(payload: unknown, scope: ProjectKnowledgeScope): ProjectEntity {
  if (!isRecord(payload)) throw projectKnowledgeError('project_entity_contract_invalid');
  if (
    (payload.tenant_id !== undefined &&
      payload.tenant_id !== null &&
      payload.tenant_id !== scope.tenantId) ||
    (payload.project_id !== undefined &&
      payload.project_id !== null &&
      payload.project_id !== scope.projectId)
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

function parseEntityTypesV2(
  payload: unknown,
): readonly Readonly<{ entityType: string; count: number }>[] {
  if (!isRecord(payload) || !Array.isArray(payload.entity_types)) {
    throw projectKnowledgeError('project_entity_types_contract_invalid');
  }
  return Object.freeze(
    payload.entity_types.map((value) => {
      if (!isRecord(value)) {
        throw projectKnowledgeError('project_entity_type_contract_invalid');
      }
      return Object.freeze({
        entityType: requireIdentifier(
          value.entity_type,
          'project_entity_type_contract_invalid',
        ),
        count: requireNonnegativeInteger(
          value.count,
          'project_entity_type_contract_invalid',
        ),
      });
    }),
  );
}

function parseRelationshipV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectEntityRelationship {
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
    relatedEntity: parseEntityV2(value.related_entity, scope),
  });
}
