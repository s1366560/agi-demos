import { projectKnowledgeError, type ProjectKnowledgeScope } from './projectKnowledgeClient';
import type {
  NativeKnowledgeCommand,
  NativeKnowledgeOperation,
  NativeKnowledgeResponse,
  NativeKnowledgeScope,
  NativeKnowledgeSyncOptions,
} from './nativeKnowledgeContracts';
import * as s from './nativeKnowledgeSchema';
import { commands, results } from './nativeKnowledgeCommandSchema';
import { sameJson, validNativeRelationships } from './nativeKnowledgeRelationships';

const scopeSchema = s.object({
  tenant_id: s.identifier,
  project_id: s.identifier,
  context_revision: s.integer(),
  profile_id: s.identifier,
  generation: s.integer(),
  digest: s.identifier,
});
const contextSchema = s.object({ contract_version: s.literal('1.0.0'), scope: scopeSchema });

export function prepareNativeKnowledgeOptions(
  options: NativeKnowledgeSyncOptions = {},
): NativeKnowledgeSyncOptions {
  if (
    !s.object(
      {},
      {
        signal: (value) =>
          value === undefined ||
          (typeof AbortSignal !== 'undefined' && value instanceof AbortSignal),
        expectedScope: (value) => value === undefined || scopeSchema(value),
      },
    )(options)
  )
    throw projectKnowledgeError('native_knowledge_command_invalid', 422);
  return Object.freeze({
    ...(options.signal === undefined ? {} : { signal: options.signal }),
    ...(options.expectedScope === undefined
      ? {}
      : { expectedScope: s.frozenClone(options.expectedScope) }),
  });
}

export function prepareNativeKnowledgeCommand<C extends NativeKnowledgeCommand>(value: C): C {
  if (
    !s.plain(value) ||
    !s.jsonValue(value) ||
    typeof value.operation !== 'string' ||
    !Object.hasOwn(commands, value.operation) ||
    !commands[value.operation](value)
  ) {
    throw projectKnowledgeError('native_knowledge_command_invalid', 422);
  }
  return s.frozenClone(value);
}
export function requireNativeKnowledgeScope(
  value: unknown,
  scope: ProjectKnowledgeScope,
): NativeKnowledgeScope {
  if (!contextSchema(value)) throw projectKnowledgeError('native_knowledge_response_invalid');
  const native = (value as { scope: NativeKnowledgeScope }).scope;
  if (
    scope.authority !== 'local' ||
    native.tenant_id !== scope.tenantId ||
    native.project_id !== scope.projectId
  ) {
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  }
  return s.frozenClone(native);
}
export function requireNativeKnowledgeResponse<C extends NativeKnowledgeCommand>(
  value: unknown,
  command: C,
  scope: ProjectKnowledgeScope,
  expected?: NativeKnowledgeScope,
): NativeKnowledgeResponse<C> {
  const prepared = prepareNativeKnowledgeCommand(command);
  const schema = s.object({
    contract_version: s.literal('1.0.0'),
    operation: s.literal(prepared.operation),
    scope: scopeSchema,
    result: results[prepared.operation as NativeKnowledgeOperation],
  });
  if (!s.jsonValue(value) || !schema(value))
    throw projectKnowledgeError('native_knowledge_response_invalid');
  const response = value as NativeKnowledgeResponse<C>;
  const native = requireNativeKnowledgeScope(
    { contract_version: response.contract_version, scope: response.scope },
    scope,
  );
  if (expected !== undefined && !sameJson(native, expected)) {
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  }
  if (!validNativeRelationships(prepared, response.result, scope)) {
    throw projectKnowledgeError('native_knowledge_response_invalid');
  }
  return s.frozenClone(response);
}

/** These protocol operations persist a caller-selected mapping, conflict, or journal item. */
export function requireNativeKnowledgeCommandOptions(
  command: NativeKnowledgeCommand,
  options?: NativeKnowledgeSyncOptions,
): NativeKnowledgeSyncOptions {
  const prepared = prepareNativeKnowledgeOptions(options);
  if (
    [
      'create',
      'update',
      'delete',
      'sync_link',
      'resolve_pull',
      'resolve_push',
      'resume_resolution',
      'reconcile_resolution',
    ].includes(command.operation) &&
    prepared.expectedScope === undefined
  ) {
    throw projectKnowledgeError('native_knowledge_expected_scope_required', 422);
  }
  if (
    (command.operation === 'create' || command.operation === 'update') &&
    command.memory.project_id !== prepared.expectedScope?.project_id
  ) {
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  }
  return prepared;
}
