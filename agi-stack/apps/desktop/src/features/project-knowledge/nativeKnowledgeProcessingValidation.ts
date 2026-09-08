import { projectKnowledgeError, type ProjectKnowledgeScope } from './projectKnowledgeClient';
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingResponse,
  NativeKnowledgeProcessingCommandResponse,
  NativeKnowledgeScope,
  NativeKnowledgeSyncOptions,
} from './nativeKnowledgeContracts';
import * as s from './nativeKnowledgeSchema';
import {
  definitions,
  processingResults,
  processingCommandResults,
} from './nativeKnowledgeProcessingSchemaGenerated';
import {
  prepareNativeKnowledgeOptions,
  requireNativeKnowledgeScope,
} from './nativeKnowledgeValidation';
import { sameJson } from './nativeKnowledgeRelationships';
import {
  validProcessingResult,
  validProcessingSource,
  validProcessingCursor,
  validProcessingIndexInput,
} from './nativeKnowledgeProcessingRelationships';

export type ProcessingOperation = NativeKnowledgeProcessingQuery | NativeKnowledgeProcessingCommand;
export const PROCESSING_QUERY_ACTIONS = Object.freeze(Object.keys(processingResults));
export const PROCESSING_COMMAND_ACTIONS = Object.freeze(Object.keys(processingCommandResults));
const invalid = () => projectKnowledgeError('native_knowledge_command_invalid', 422);

export function prepareNativeKnowledgeProcessingQuery<Q extends NativeKnowledgeProcessingQuery>(
  value: Q,
  scope: ProjectKnowledgeScope,
): Q {
  if (!s.jsonValue(value) || !definitions.NativeKnowledgeProcessingQuery!(value)) throw invalid();
  if (value.operation === 'processing_task') {
    if (!validProcessingSource(value.source, scope)) throw invalid();
  } else if (value.operation === 'semantic') {
    if (
      !s.identifier(value.build_id) ||
      !boundedText(value.query) ||
      value.query.trim().length === 0
    )
      throw invalid();
  } else if (
    value.operation === 'failed_processing' ||
    value.operation === 'failed_index' ||
    value.operation === 'processing_audits'
  ) {
    if (
      (value.operation === 'failed_index' && !s.identifier(value.build_id)) ||
      (value.operation === 'processing_audits' && !validProcessingSource(value.source, scope)) ||
      (value.request.cursor != null &&
        (value.request.cursor.length === 0 || value.request.cursor.length > 8192))
    )
      throw invalid();
  } else if (value.operation !== 'configuration') {
    if (value.operation === 'text' && !boundedText(value.literal)) throw invalid();
    if (value.request.source && !validProcessingSource(value.request.source, scope))
      throw invalid();
    if (value.request.cursor && !validProcessingCursor(value.request.cursor, value, scope))
      throw invalid();
  }
  return s.frozenClone(value);
}

export function prepareNativeKnowledgeProcessingCommand<C extends NativeKnowledgeProcessingCommand>(
  value: C,
  scope: ProjectKnowledgeScope,
): C {
  if (!s.jsonValue(value) || !definitions.NativeKnowledgeProcessingCommand!(value)) throw invalid();
  if (value.operation === 'retry_processing') {
    if (!validProcessingSource(value.source, scope) || !s.localRevision(value.expected_attempt))
      throw invalid();
  } else if (value.operation === 'process_one') {
    if (!s.identifier(value.workspace_id)) throw invalid();
  } else {
    if (!s.identifier(value.build_id)) throw invalid();
    if (
      value.operation === 'configure_embedding' &&
      (!s.identifier(value.provider_id) || !s.identifier(value.model_id))
    )
      throw invalid();
    if (
      'expected_config_revision' in value &&
      value.expected_config_revision !== null &&
      value.expected_config_revision >= Number.MAX_SAFE_INTEGER
    )
      throw invalid();
    if (
      value.operation === 'promote_index' &&
      value.expected_active_build_id !== null &&
      !s.identifier(value.expected_active_build_id)
    )
      throw invalid();
    if (
      value.operation === 'retry_index' &&
      (!validProcessingIndexInput(value.input, scope) || !s.localRevision(value.expected_attempt))
    )
      throw invalid();
  }
  return s.frozenClone(value);
}

export function prepareNativeKnowledgeProcessingOptions(
  operation: ProcessingOperation,
  input?: NativeKnowledgeSyncOptions,
): NativeKnowledgeSyncOptions {
  const options = prepareNativeKnowledgeOptions(input);
  if (
    (operation.operation === 'semantic' ||
      Object.hasOwn(processingCommandResults, operation.operation)) &&
    options.expectedScope === undefined
  ) {
    throw projectKnowledgeError('native_knowledge_expected_scope_required', 422);
  }
  return options;
}

export function requireNativeKnowledgeProcessingQueryResponse<
  Q extends NativeKnowledgeProcessingQuery,
>(
  value: unknown,
  query: Q,
  scope: ProjectKnowledgeScope,
  expected: NativeKnowledgeScope,
): NativeKnowledgeProcessingResponse<Q> {
  requireResponse(value, query, processingResults[query.operation]!, scope, expected);
  return s.frozenClone(value as NativeKnowledgeProcessingResponse<Q>);
}

export function requireNativeKnowledgeProcessingCommandResponse<
  C extends NativeKnowledgeProcessingCommand,
>(
  value: unknown,
  command: C,
  scope: ProjectKnowledgeScope,
  expected: NativeKnowledgeScope,
): NativeKnowledgeProcessingCommandResponse<C> {
  requireResponse(value, command, processingCommandResults[command.operation]!, scope, expected);
  return s.frozenClone(value as NativeKnowledgeProcessingCommandResponse<C>);
}

function requireResponse(
  value: unknown,
  operation: ProcessingOperation,
  result: s.NativeCheck,
  scope: ProjectKnowledgeScope,
  expected: NativeKnowledgeScope,
): void {
  if (
    !s.jsonValue(value) ||
    !s.object({
      contract_version: s.literal('1.0.0'),
      scope: definitions.NativeKnowledgeScope!,
      result,
    })(value)
  ) {
    throw projectKnowledgeError('native_knowledge_response_invalid');
  }
  const payload = value as {
    contract_version: '1.0.0';
    scope: NativeKnowledgeScope;
    result: unknown;
  };
  const native = requireNativeKnowledgeScope(
    { contract_version: payload.contract_version, scope: payload.scope },
    scope,
  );
  if (!sameJson(native, expected))
    throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
  if (!validProcessingResult(operation, payload.result, scope))
    throw projectKnowledgeError('native_knowledge_response_invalid');
}
function boundedText(value: string): boolean {
  return value.length > 0 && new TextEncoder().encode(value).byteLength <= 4096;
}
