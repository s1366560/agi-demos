import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requireIdentifier,
  requireProjectAdministrationScope,
  requireText,
  type ProjectAdministrationScope,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_SCHEMA_DEGRADED_REASON,
  PROJECT_SCHEMA_LOCAL_REASON,
  type ProjectSchemaMapping,
  type ProjectSchemaSnapshot,
  type ProjectSchemaType,
} from '../features/project-administration/projectSchemaClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectSchemaRuntimeConfigV2,
  cloneDesktopProjectSchemaScopeV2,
} from './desktopProjectSchemaOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list-entity-types']);

export type DesktopProjectSchemaHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectSchemaSnapshot>;
}>;

export function createDesktopProjectSchemaHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAdministrationScope,
): DesktopProjectSchemaHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectSchemaRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectSchemaScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        operationScope,
        PROJECT_SCHEMA_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, {
        signal,
      });
      const [entityPayload, edgePayload, mappingPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, schemaPathV2(currentScope, 'entities'), {
          signal,
        }),
        requestProjectAdministrationJson(runtimeConfig, schemaPathV2(currentScope, 'edges'), {
          signal,
        }),
        requestProjectAdministrationJson(runtimeConfig, schemaPathV2(currentScope, 'mappings'), {
          signal,
        }),
      ]);
      return Object.freeze({
        scope: currentScope,
        scopeRevision: authority.revision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_SCHEMA_DEGRADED_REASON,
        contractVersion: '4.0.0',
        allowedActions: ACTIONS_V2,
        membershipRole: authority.membershipRole,
        entityTypes: parseTypesV2(entityPayload, currentScope),
        edgeTypes: parseTypesV2(edgePayload, currentScope),
        mappings: parseMappingsV2(mappingPayload, currentScope),
      });
    },
  });
}

function schemaPathV2(scope: ProjectAdministrationScope, resource: string): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}/schema/${resource}`;
}

function parseTypesV2(
  payload: unknown,
  scope: ProjectAdministrationScope,
): readonly ProjectSchemaType[] {
  if (!Array.isArray(payload)) {
    throw projectAdministrationError('project_schema_contract_invalid');
  }
  return Object.freeze(payload.map((value) => parseTypeV2(value, scope)));
}

function parseTypeV2(value: unknown, scope: ProjectAdministrationScope): ProjectSchemaType {
  if (!isRecord(value) || value.project_id !== scope.projectId || !isRecord(value.schema)) {
    throw projectAdministrationError('project_schema_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'project_schema_contract_invalid'),
    projectId: scope.projectId,
    name: requireIdentifier(value.name, 'project_schema_contract_invalid'),
    description: optionalText(value.description, 'project_schema_contract_invalid'),
    schema: Object.freeze({ ...value.schema }),
    status: requireIdentifier(value.status, 'project_schema_contract_invalid'),
    source: requireIdentifier(value.source, 'project_schema_contract_invalid'),
    createdAt: requireIdentifier(value.created_at, 'project_schema_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'project_schema_contract_invalid'),
  });
}

function parseMappingsV2(
  payload: unknown,
  scope: ProjectAdministrationScope,
): readonly ProjectSchemaMapping[] {
  if (!Array.isArray(payload)) {
    throw projectAdministrationError('project_schema_contract_invalid');
  }
  return Object.freeze(
    payload.map((value) => {
      if (!isRecord(value) || value.project_id !== scope.projectId) {
        throw projectAdministrationError('project_schema_scope_conflict', 409);
      }
      return Object.freeze({
        id: requireIdentifier(value.id, 'project_schema_contract_invalid'),
        projectId: scope.projectId,
        sourceType: requireText(value.source_type, 'project_schema_contract_invalid'),
        targetType: requireText(value.target_type, 'project_schema_contract_invalid'),
        edgeType: requireText(value.edge_type, 'project_schema_contract_invalid'),
        status: requireIdentifier(value.status, 'project_schema_contract_invalid'),
        source: requireIdentifier(value.source, 'project_schema_contract_invalid'),
        createdAt: requireIdentifier(value.created_at, 'project_schema_contract_invalid'),
      });
    }),
  );
}
