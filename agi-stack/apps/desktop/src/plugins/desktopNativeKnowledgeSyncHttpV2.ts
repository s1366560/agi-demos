import {
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type {
  NativeKnowledgeCommand,
  NativeKnowledgeResponse,
  NativeKnowledgeSyncOptions,
  NativeKnowledgeSyncAuthority,
  NativeKnowledgeScopeObservationOptions,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeCommandOptions,
  requireNativeKnowledgeResponse,
  requireNativeKnowledgeScope,
} from '../features/project-knowledge/nativeKnowledgeValidation';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import {
  object,
  literal,
  jsonValue,
  plain,
} from '../features/project-knowledge/nativeKnowledgeSchema';
import type { DesktopRuntimeConfig } from '../types';
import { observeDesktopNativeKnowledgeScopeV2 } from './desktopNativeKnowledgeScopeHttpV2';

export function requireNativeKnowledgeTransportV2(config: DesktopRuntimeConfig): void {
  if (config.mode !== 'local')
    throw projectKnowledgeError('native_knowledge_sync_unavailable', 501);
  let url: URL;
  try {
    url = new URL(config.apiBaseUrl);
  } catch {
    throw projectKnowledgeError('native_knowledge_transport_invalid', 422);
  }
  if (
    url.protocol !== 'http:' ||
    !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== '/'
  ) {
    throw projectKnowledgeError('native_knowledge_transport_invalid', 422);
  }
}

export function createDesktopNativeKnowledgeSyncHttpV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): NativeKnowledgeSyncAuthority {
  return Object.freeze({
    observeScope(options: NativeKnowledgeScopeObservationOptions, requireCurrent?: () => void) {
      requireNativeKnowledgeTransportV2(config);
      return observeDesktopNativeKnowledgeScopeV2(config, scope, options, requireCurrent);
    },
    async executeSync<C extends NativeKnowledgeCommand>(
      command: C,
      inputOptions?: NativeKnowledgeSyncOptions,
    ): Promise<NativeKnowledgeResponse<C>> {
      const prepared = prepareNativeKnowledgeCommand(command);
      const options = requireNativeKnowledgeCommandOptions(prepared, inputOptions);
      requireNativeKnowledgeTransportV2(config);
      options.signal?.throwIfAborted();
      const native = requireNativeKnowledgeScope(
        await requestProjectKnowledgeJson(config, '/api/v1/knowledge/context', {
          signal: options.signal,
        }),
        scope,
      );
      if (options.expectedScope !== undefined && !sameJson(native, options.expectedScope)) {
        throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
      }
      options.signal?.throwIfAborted();
      const request = wire(prepared);
      const payload = await requestProjectKnowledgeJson(
        config,
        `/api/v1/knowledge/${request.path}`,
        {
          method: 'POST',
          signal: options.signal,
          body: { scope: native, ...request.body },
          ...(request.idempotencyKey === undefined
            ? {}
            : {
                mutation: {
                  idempotencyKey: request.idempotencyKey,
                  ...(request.expectedRevision === undefined
                    ? {}
                    : { expectedRevision: request.expectedRevision }),
                },
              }),
        },
      );
      options.signal?.throwIfAborted();
      if (
        !object({ contract_version: literal('1.0.0'), scope: plain, result: jsonValue })(payload)
      ) {
        throw projectKnowledgeError('native_knowledge_response_invalid');
      }
      return requireNativeKnowledgeResponse(
        { ...(payload as Record<string, unknown>), operation: prepared.operation },
        prepared,
        scope,
        native,
      );
    },
  });
}

function wire(command: NativeKnowledgeCommand): Readonly<{
  path: string;
  body: Readonly<Record<string, unknown>>;
  idempotencyKey?: string;
  expectedRevision?: number;
}> {
  const { operation, ...fields } = command;
  switch (command.operation) {
    case 'create':
      return {
        path: 'mutations',
        body: { mutation: { operation, memory: command.memory } },
        idempotencyKey: command.idempotency_key,
      };
    case 'update':
      return {
        path: 'mutations',
        body: {
          mutation: {
            operation,
            memory: command.memory,
            expected_revision: command.expected_revision,
          },
        },
        idempotencyKey: command.idempotency_key,
        expectedRevision: command.expected_revision,
      };
    case 'delete':
      return {
        path: 'mutations',
        body: {
          mutation: { operation, id: command.id, expected_revision: command.expected_revision },
        },
        idempotencyKey: command.idempotency_key,
        expectedRevision: command.expected_revision,
      };
    case 'sync_link':
      return { path: 'sync-link', body: { link: command.link } };
    case 'sync_push':
      return { path: 'sync-push', body: {} };
    case 'sync_pull':
      return { path: 'sync-pull', body: {} };
    case 'resolve_pull':
      return {
        path: 'sync-resolve-pull',
        body: { resolution: command.resolution },
        idempotencyKey: command.idempotency_key,
      };
    case 'resolve_push':
      return {
        path: 'sync-resolve-push',
        body: { resolution: command.resolution },
        idempotencyKey: command.idempotency_key,
      };
    case 'resume_resolution':
      return { path: 'sync-resume-resolution', body: { resolution_id: command.resolution_id } };
    case 'reconcile_resolution':
      return {
        path: 'sync-reconcile-resolution',
        body: { resolution_id: command.resolution_id, reconciliation: command.reconciliation },
      };
    case 'cloud_conflict_context':
      return {
        path: 'sync-cloud-query',
        body: { query: { operation: 'conflict_context', local_sequence: command.local_sequence } },
      };
    case 'resolution':
    case 'resolution_by_key':
    case 'resolutions':
    case 'pending_resolutions':
    case 'reconciliation_context':
      return { path: 'sync-cloud-query', body: { query: { operation, ...fields } } };
    default:
      return { path: 'query', body: { query: { operation, ...fields } } };
  }
}
