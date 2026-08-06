import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requestProjectAdministrationNoContent,
  requireIdentifier,
  requireProjectAdministrationScope,
  requireText,
  type ProjectAdministrationOptions,
  type ProjectAdministrationScope,
  type ProjectAdministrationSnapshotBase,
  type ProjectMembershipRole,
} from './projectAdministrationClient';

export const PROJECT_SCHEMA_ROUTE_ID = 'project-project-schema' as const;
export const PROJECT_SCHEMA_LOCAL_REASON = 'local_project_schema_authority_unavailable' as const;
export const PROJECT_SCHEMA_DEGRADED_REASON =
  'project_schema_export_file_ipc_unavailable' as const;

export type ProjectSchemaType = Readonly<{
  id: string;
  projectId: string;
  name: string;
  description: string | null;
  schema: Readonly<Record<string, unknown>>;
  status: string;
  source: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectSchemaMapping = Readonly<{
  id: string;
  projectId: string;
  sourceType: string;
  targetType: string;
  edgeType: string;
  status: string;
  source: string;
  createdAt: string;
}>;
export type ProjectSchemaSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    entityTypes: readonly ProjectSchemaType[];
    edgeTypes: readonly ProjectSchemaType[];
    mappings: readonly ProjectSchemaMapping[];
  }>;
export type ProjectSchemaMutation = Readonly<Record<string, unknown>>;
export type ProjectSchemaClient = Readonly<{
  load(scope: ProjectAdministrationScope, options?: ProjectAdministrationOptions): Promise<ProjectSchemaSnapshot>;
  createEntityType(scope: ProjectAdministrationScope, input: ProjectSchemaMutation): Promise<void>;
  updateEntityType(scope: ProjectAdministrationScope, id: string, input: ProjectSchemaMutation): Promise<void>;
  deleteEntityType(scope: ProjectAdministrationScope, id: string): Promise<void>;
  createEdgeType(scope: ProjectAdministrationScope, input: ProjectSchemaMutation): Promise<void>;
  updateEdgeType(scope: ProjectAdministrationScope, id: string, input: ProjectSchemaMutation): Promise<void>;
  deleteEdgeType(scope: ProjectAdministrationScope, id: string): Promise<void>;
  createMapping(scope: ProjectAdministrationScope, input: ProjectSchemaMutation): Promise<void>;
  deleteMapping(scope: ProjectAdministrationScope, id: string): Promise<void>;
}>;

const READ_ACTIONS = ['view', 'list-entity-types', 'list-edge-types', 'list-mappings'] as const;
const WRITE_ACTIONS = [
  'create-entity-type',
  'update-entity-type',
  'delete-entity-type',
  'create-edge-type',
  'update-edge-type',
  'delete-edge-type',
  'create-mapping',
  'delete-mapping',
] as const;

export function createProjectSchemaClient(config: DesktopRuntimeConfig): ProjectSchemaClient {
  const runtimeConfig = Object.freeze({ ...config });
  const path = (scope: ProjectAdministrationScope, resource: string) =>
    `/api/v1/projects/${encodeURIComponent(scope.projectId)}/schema/${resource}`;
  const mutate = async (
    scope: ProjectAdministrationScope,
    resource: string,
    method: 'POST' | 'PUT' | 'DELETE',
    body?: ProjectSchemaMutation,
  ): Promise<void> => {
    const currentScope = requireProjectAdministrationScope(
      runtimeConfig,
      scope,
      PROJECT_SCHEMA_LOCAL_REASON,
    );
    await requestProjectAdministrationNoContent(runtimeConfig, path(currentScope, resource), {
      method,
      body,
    });
  };
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SCHEMA_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, options);
      const [entityPayload, edgePayload, mappingPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, path(currentScope, 'entities'), options),
        requestProjectAdministrationJson(runtimeConfig, path(currentScope, 'edges'), options),
        requestProjectAdministrationJson(runtimeConfig, path(currentScope, 'mappings'), options),
      ]);
      return Object.freeze({
        scope: currentScope,
        scopeRevision: authority.revision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_SCHEMA_DEGRADED_REASON,
        contractVersion: '4.0.0',
        allowedActions: allowedActions(authority.membershipRole),
        membershipRole: authority.membershipRole,
        entityTypes: parseTypes(entityPayload, currentScope),
        edgeTypes: parseTypes(edgePayload, currentScope),
        mappings: parseMappings(mappingPayload, currentScope),
      });
    },
    createEntityType: (scope, input) => mutate(scope, 'entities', 'POST', input),
    updateEntityType: (scope, id, input) =>
      mutate(scope, `entities/${encodeURIComponent(id)}`, 'PUT', input),
    deleteEntityType: (scope, id) =>
      mutate(scope, `entities/${encodeURIComponent(id)}`, 'DELETE'),
    createEdgeType: (scope, input) => mutate(scope, 'edges', 'POST', input),
    updateEdgeType: (scope, id, input) =>
      mutate(scope, `edges/${encodeURIComponent(id)}`, 'PUT', input),
    deleteEdgeType: (scope, id) => mutate(scope, `edges/${encodeURIComponent(id)}`, 'DELETE'),
    createMapping: (scope, input) => mutate(scope, 'mappings', 'POST', input),
    deleteMapping: (scope, id) =>
      mutate(scope, `mappings/${encodeURIComponent(id)}`, 'DELETE'),
  });
}

function allowedActions(role: ProjectMembershipRole): readonly string[] {
  return Object.freeze([
    ...READ_ACTIONS,
    ...(role === 'owner' || role === 'admin' ? WRITE_ACTIONS : []),
  ]);
}

function parseTypes(payload: unknown, scope: ProjectAdministrationScope): readonly ProjectSchemaType[] {
  if (!Array.isArray(payload)) throw projectAdministrationError('project_schema_contract_invalid');
  return Object.freeze(payload.map((value) => parseType(value, scope)));
}

function parseType(value: unknown, scope: ProjectAdministrationScope): ProjectSchemaType {
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

function parseMappings(
  payload: unknown,
  scope: ProjectAdministrationScope,
): readonly ProjectSchemaMapping[] {
  if (!Array.isArray(payload)) throw projectAdministrationError('project_schema_contract_invalid');
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
