import type {
  NativeKnowledgeSyncConnectionResult,
  NativeKnowledgeSyncTenantsResult,
  NativeKnowledgeSyncProjectsResult,
  NativeKnowledgeSyncEnrollmentResult,
  NativeKnowledgeSyncBindingResult,
} from './nativeKnowledgeDataGenerated';
import type {
  NativeKnowledgeSyncConnectionRequest,
  NativeKnowledgeSyncTenantsRequest,
  NativeKnowledgeSyncProjectsRequest,
  NativeKnowledgeSyncEnrollmentRequest,
  NativeKnowledgeSyncTargetRequest,
} from './nativeKnowledgeRpcGenerated';
import type { NativeKnowledgeScope } from './nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import { projectKnowledgeError } from './projectKnowledgeClient';
import { definitions } from './nativeKnowledgeConnectionSchemaGenerated';
import { requireNativeKnowledgeScope } from './nativeKnowledgeValidation';
import { sameJson } from './nativeKnowledgeRelationships';
import * as s from './nativeKnowledgeSchema';

type Requests = {
  connection: NativeKnowledgeSyncConnectionRequest;
  tenants: NativeKnowledgeSyncTenantsRequest;
  projects: NativeKnowledgeSyncProjectsRequest;
  enrollment: NativeKnowledgeSyncEnrollmentRequest;
  enroll: NativeKnowledgeSyncTargetRequest;
  bind: NativeKnowledgeSyncTargetRequest;
};
type Results = {
  connection: NativeKnowledgeSyncConnectionResult;
  tenants: NativeKnowledgeSyncTenantsResult;
  projects: NativeKnowledgeSyncProjectsResult;
  enrollment: NativeKnowledgeSyncEnrollmentResult;
  enroll: NativeKnowledgeSyncEnrollmentResult;
  bind: NativeKnowledgeSyncBindingResult;
};
export type NativeKnowledgeCloudConnectionOperation = keyof Requests;
export type NativeKnowledgeCloudConnectionCommand = {
  [K in keyof Requests]: Readonly<{ operation: K }> & Omit<Requests[K], 'scope'>;
}[keyof Requests];
export type NativeKnowledgeCloudConnectionOptions = Readonly<{
  expectedScope: NativeKnowledgeScope;
  signal?: AbortSignal;
}>;
export type NativeKnowledgeCloudConnectionResponse<
  C extends NativeKnowledgeCloudConnectionCommand,
> = Readonly<{
  contract_version: '1.0.0';
  scope: NativeKnowledgeScope;
  result: Results[C['operation']];
}>;
export type NativeKnowledgeCloudConnectionClient = Readonly<{
  execute<C extends NativeKnowledgeCloudConnectionCommand>(
    scope: ProjectKnowledgeScope,
    command: C,
    options: NativeKnowledgeCloudConnectionOptions,
  ): Promise<NativeKnowledgeCloudConnectionResponse<C>>;
}>;
export type NativeKnowledgeCloudConnectionAuthority = Readonly<{
  executeConnection<C extends NativeKnowledgeCloudConnectionCommand>(
    command: C,
    options: NativeKnowledgeCloudConnectionOptions,
    requireCurrent?: () => void,
  ): Promise<NativeKnowledgeCloudConnectionResponse<C>>;
}>;

const requestSchemas = {
  connection: 'NativeKnowledgeSyncConnectionRequest',
  tenants: 'NativeKnowledgeSyncTenantsRequest',
  projects: 'NativeKnowledgeSyncProjectsRequest',
  enrollment: 'NativeKnowledgeSyncEnrollmentRequest',
  enroll: 'NativeKnowledgeSyncTargetRequest',
  bind: 'NativeKnowledgeSyncTargetRequest',
} as const;
const resultSchemas = {
  connection: 'NativeKnowledgeSyncConnectionResult',
  tenants: 'NativeKnowledgeSyncTenantsResult',
  projects: 'NativeKnowledgeSyncProjectsResult',
  enrollment: 'NativeKnowledgeSyncEnrollmentResult',
  enroll: 'NativeKnowledgeSyncEnrollmentResult',
  bind: 'NativeKnowledgeSyncBindingResult',
} as const;

export function prepareNativeKnowledgeCloudConnection<
  C extends NativeKnowledgeCloudConnectionCommand,
>(command: C, options: NativeKnowledgeCloudConnectionOptions) {
  if (
    !s.plain(command) ||
    !Object.hasOwn(requestSchemas, command.operation) ||
    !s.object({ expectedScope: s.plain }, { signal: () => true })(options) ||
    (options.signal !== undefined && !(options.signal instanceof AbortSignal))
  )
    throw invalid();
  const { operation, ...fields } = command;
  const request = { scope: options.expectedScope, ...fields };
  if (!s.jsonValue(request) || !definitions[requestSchemas[operation]]!(request)) throw invalid();
  return Object.freeze({
    command: s.frozenClone(command),
    options: Object.freeze({
      expectedScope: s.frozenClone(options.expectedScope),
      signal: options.signal,
    }),
  });
}

export function requireNativeKnowledgeCloudConnectionResponse<
  C extends NativeKnowledgeCloudConnectionCommand,
>(
  payload: unknown,
  command: C,
  scope: ProjectKnowledgeScope,
  expectedScope: NativeKnowledgeScope,
): NativeKnowledgeCloudConnectionResponse<C> {
  if (
    !s.object({
      contract_version: s.literal('1.0.0'),
      scope: s.plain,
      result: s.jsonValue,
    })(payload)
  )
    throw invalid();
  const value = payload as NativeKnowledgeCloudConnectionResponse<C>;
  const observed = requireNativeKnowledgeScope(
    { contract_version: value.contract_version, scope: value.scope },
    scope,
  );
  if (!sameJson(observed, expectedScope))
    throw projectKnowledgeError('knowledge_scope_mismatch', 409);
  if (!definitions[resultSchemas[command.operation]]!(value.result)) throw invalid();
  const result = value.result;
  if (command.operation !== 'connection') {
    if (
      !result.connection ||
      result.connection.connection_revision !== command.expected_connection_revision
    )
      throw invalid();
  }
  if ('tenant_id' in command && 'tenant_id' in result && command.tenant_id !== result.tenant_id)
    throw invalid();
  if (
    'tenant_id' in command &&
    'items' in result &&
    command.operation === 'projects' &&
    result.items.some((item) => !('tenant_id' in item) || item.tenant_id !== command.tenant_id)
  )
    throw invalid();
  if (
    'enrollment' in result &&
    'project_id' in command &&
    (result.enrollment.tenant_id !== command.tenant_id ||
      result.enrollment.project_id !== command.project_id ||
      result.enrollment.actor_id !== result.connection.actor_id ||
      ('expected_generation' in command &&
        !sameJson(command.expected_generation, result.enrollment.generation)))
  )
    throw invalid();
  if (
    'association_state' in result &&
    'project_id' in command &&
    (!result.enrollment.enabled ||
      !result.status.link ||
      result.status.link.remote_tenant_id !== command.tenant_id ||
      result.status.link.remote_project_id !== command.project_id ||
      result.status.link.remote_actor_id !== result.connection.actor_id)
  )
    throw invalid();
  if (
    'items' in result &&
    new Set(result.items.map((item) => item.id)).size !== result.items.length
  )
    throw invalid();
  return s.frozenClone(value);
}
const invalid = () => projectKnowledgeError('native_knowledge_cloud_connection_invalid', 422);
