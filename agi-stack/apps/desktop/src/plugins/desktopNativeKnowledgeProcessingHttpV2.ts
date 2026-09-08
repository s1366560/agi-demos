import type { DesktopRuntimeConfig } from '../types';
import type { DesktopCapabilitySnapshotEntry } from '../features/runtime/capabilitySnapshot';
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingDiscoveryQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingResponse,
  NativeKnowledgeProcessingCommandResponse,
  NativeKnowledgeObservedOptions,
  NativeKnowledgeSyncOptions,
  NativeKnowledgeScope,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import { requireNativeKnowledgeTransportV2 } from './desktopNativeKnowledgeSyncHttpV2';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import {
  prepareNativeKnowledgeProcessingQuery,
  prepareNativeKnowledgeProcessingCommand,
  prepareNativeKnowledgeProcessingOptions,
  requireNativeKnowledgeProcessingQueryResponse,
  requireNativeKnowledgeProcessingCommandResponse,
} from '../features/project-knowledge/nativeKnowledgeProcessingValidation';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import * as s from '../features/project-knowledge/nativeKnowledgeSchema';

export type NativeKnowledgeProcessingCapabilityGetter = () => DesktopCapabilitySnapshotEntry | null;
export interface DesktopNativeKnowledgeProcessingHttpV2 {
  queryProcessing<Q extends NativeKnowledgeProcessingQuery>(
    query: Q,
    options: NativeKnowledgeObservedOptions,
  ): Promise<NativeKnowledgeProcessingResponse<Q>>;
  queryProcessing<Q extends NativeKnowledgeProcessingDiscoveryQuery>(
    query: Q,
    options?: NativeKnowledgeSyncOptions,
  ): Promise<NativeKnowledgeProcessingResponse<Q>>;
  executeProcessing<C extends NativeKnowledgeProcessingCommand>(
    command: C,
    options: NativeKnowledgeObservedOptions,
  ): Promise<NativeKnowledgeProcessingCommandResponse<C>>;
}

/** The getter is authority-owned; missing capabilities fail closed for processing only. */
export function createDesktopNativeKnowledgeProcessingHttpV2(
  inputConfig: DesktopRuntimeConfig,
  inputScope: ProjectKnowledgeScope,
  getCapability?: NativeKnowledgeProcessingCapabilityGetter,
): DesktopNativeKnowledgeProcessingHttpV2 {
  const config = Object.freeze({ ...inputConfig });
  const scope = Object.freeze({ ...inputScope });
  const requireLocal = (): void => {
    requireNativeKnowledgeTransportV2(config);
    if (
      !s.object({
        authority: s.literal('local'),
        tenantId: s.identifier,
        projectId: s.identifier,
      })(scope) ||
      config.tenantId !== scope.tenantId ||
      config.projectId !== scope.projectId
    ) {
      throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
    }
  };
  const capability = (operation: string, native?: NativeKnowledgeScope): void => {
    requireLocal();
    const value = getCapability?.();
    if (
      !capabilityShape(value) ||
      !value ||
      value.provenance !== 'observed' ||
      value.authority_source !== 'sidecar' ||
      (value.availability !== 'available' && value.availability !== 'degraded') ||
      !value.allowed_actions.includes(operation)
    ) {
      throw projectKnowledgeError('native_knowledge_processing_unavailable', 501);
    }
    if (
      value.scope.tenant_id !== scope.tenantId ||
      value.scope.project_id !== scope.projectId ||
      (native && value.authority_revision !== native.context_revision)
    ) {
      throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
    }
  };
  const observe = async (signal?: AbortSignal): Promise<NativeKnowledgeScope> => {
    signal?.throwIfAborted();
    const current = requireNativeKnowledgeScope(
      await requestProjectKnowledgeJson(config, '/api/v1/knowledge/context', {
        signal,
      }),
      scope,
    );
    signal?.throwIfAborted();
    return current;
  };
  const invoke = async (
    operation: NativeKnowledgeProcessingQuery | NativeKnowledgeProcessingCommand,
    key: 'query' | 'command',
    inputOptions?: NativeKnowledgeSyncOptions,
  ): Promise<{ payload: unknown; native: NativeKnowledgeScope }> => {
    const options = prepareNativeKnowledgeProcessingOptions(operation, inputOptions);
    options.signal?.throwIfAborted();
    if (options.expectedScope !== undefined) {
      requireNativeKnowledgeScope(
        { contract_version: '1.0.0', scope: options.expectedScope },
        scope,
      );
    }
    capability(operation.operation);
    const native = await observe(options.signal);
    if (options.expectedScope !== undefined && !sameJson(native, options.expectedScope)) {
      throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
    }
    capability(operation.operation, native);
    const payload = await requestProjectKnowledgeJson(
      config,
      `/api/v1/knowledge/processing-${key}`,
      {
        method: 'POST',
        signal: options.signal,
        body: { scope: native, [key]: operation },
      },
    );
    options.signal?.throwIfAborted();
    capability(operation.operation, native);
    // A late response cannot hide a changed live scope or plugin generation.
    const after = await observe(options.signal);
    if (!sameJson(native, after))
      throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
    capability(operation.operation, after);
    return { payload, native };
  };
  return Object.freeze({
    async queryProcessing<Q extends NativeKnowledgeProcessingQuery>(
      query: Q,
      options?: NativeKnowledgeSyncOptions,
    ): Promise<NativeKnowledgeProcessingResponse<Q>> {
      const prepared = prepareNativeKnowledgeProcessingQuery(query, scope);
      const { payload, native } = await invoke(prepared, 'query', options);
      return requireNativeKnowledgeProcessingQueryResponse(payload, prepared, scope, native);
    },
    async executeProcessing<C extends NativeKnowledgeProcessingCommand>(
      command: C,
      options: NativeKnowledgeObservedOptions,
    ): Promise<NativeKnowledgeProcessingCommandResponse<C>> {
      const prepared = prepareNativeKnowledgeProcessingCommand(command, scope);
      const { payload, native } = await invoke(prepared, 'command', options);
      return requireNativeKnowledgeProcessingCommandResponse(payload, prepared, scope, native);
    },
  });
}

const capabilityShape = s.object({
  availability: s.literal('available', 'degraded', 'unavailable', 'not_applicable'),
  reason_code: s.nullable(s.identifier),
  service_version: s.nullable(s.identifier),
  contract_version: s.nullable(s.identifier),
  allowed_actions: s.array(s.identifier),
  scope: s.object({
    tenant_id: s.nullable(s.identifier),
    project_id: s.nullable(s.identifier),
    workspace_id: s.nullable(s.identifier),
    instance_id: s.nullable(s.identifier),
  }),
  authority_revision: s.integer(),
  retryable: s.bool,
  authority_source: s.literal('cloud_service', 'sidecar', 'electron', 'native_runtime', 'renderer'),
  supporting_authority_sources: s.array(
    s.literal('cloud_service', 'sidecar', 'electron', 'native_runtime', 'renderer'),
  ),
  provenance: s.literal('observed', 'declared'),
});
