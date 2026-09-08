import { DesktopApiError } from '../api/client';
import {
  desktopVaultBoundCloudRequestBroker,
  type VaultBoundCloudRequest,
} from '../api/cloudRequestBroker';
import { requireCloudMemoryRequestScope } from '../api/cloudMemoryScopeContract';
import type {
  CloudMemoryClient,
  CloudMemoryCommand,
  CloudMemoryResponse,
} from '../features/project-knowledge/cloudMemoryClient';
import {
  prepareCloudMemoryCommand,
  prepareCloudMemoryOptions,
} from '../features/project-knowledge/cloudMemoryValidation';
import { parseMemoryV2 } from '../features/project-knowledge/cloudMemoryProjection';
import {
  isRecord,
  projectKnowledgeError,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectMemoriesRuntimeConfigV2,
  cloneDesktopProjectMemoriesScopeV2,
} from './desktopProjectMemoriesOperationContractV2';

export function createDesktopCloudMemoryHttpV2(config: DesktopRuntimeConfig): CloudMemoryClient {
  const runtime = cloneDesktopProjectMemoriesRuntimeConfigV2(config);
  return Object.freeze({
    async execute(scope, input, inputOptions) {
      const pinned = cloneDesktopProjectMemoriesScopeV2(scope, runtime);
      if (pinned.authority !== 'cloud')
        throw projectKnowledgeError('cloud_memory_authority_invalid', 409);
      const command = prepareCloudMemoryCommand(input);
      const options = prepareCloudMemoryOptions(inputOptions);
      options.signal?.throwIfAborted();
      const broker = desktopVaultBoundCloudRequestBroker();
      if (!broker) throw projectKnowledgeError('project_knowledge_trusted_session_required', 401);
      const request = commandRequest(command, pinned.projectId);
      const response = await broker
        .requestResponse({
          ...request,
          signal: options.signal,
          memory_scope: requireCloudMemoryRequestScope({
            actor_id: options.expectedActorId,
            tenant_id: pinned.tenantId,
            project_id: pinned.projectId,
            context_revision: options.expectedContextRevision,
          }),
        })
        .catch((error: unknown) => {
          if (
            error instanceof Error &&
            [
              'cloud request project scope mismatch',
              'cloud request tenant scope mismatch',
              'cloud_memory_scope_conflict',
            ].includes(error.message)
          )
            throw projectKnowledgeError('cloud_memory_scope_conflict', 409);
          throw error;
        });
      options.signal?.throwIfAborted();
      if (response.status < 200 || response.status >= 300)
        throw responseError(response.status, response.body);
      if (command.operation === 'delete') {
        if (response.status !== 204 || response.body !== null) throw invalidResponse();
        return Object.freeze({
          operation: command.operation,
          result: Object.freeze({ memoryId: command.id, deleted: true }),
        }) as CloudMemoryResponse<typeof input>;
      }
      if (response.status !== (command.operation === 'create' ? 201 : 200)) throw invalidResponse();
      const memory = parseMemoryV2(response.body, pinned);
      if (
        (command.operation !== 'create' && memory.id !== command.id) ||
        (command.operation === 'create' && memory.version !== 1) ||
        (command.operation === 'update' && memory.version !== command.expectedRevision + 1) ||
        memory.version < 1
      )
        throw invalidResponse();
      return Object.freeze({ operation: command.operation, result: memory }) as CloudMemoryResponse<
        typeof input
      >;
    },
  } satisfies CloudMemoryClient);
}
function commandRequest(command: CloudMemoryCommand, projectId: string): VaultBoundCloudRequest {
  const path =
    command.operation === 'create'
      ? '/api/v1/memories/'
      : `/api/v1/memories/${encodeURIComponent(command.id)}?project_id=${encodeURIComponent(projectId)}`;
  if (command.operation === 'get') return Object.freeze({ path, method: 'GET' });
  const mutation = Object.freeze({
    kind: 'memory-command' as const,
    expected_revision: command.operation === 'create' ? 0 : command.expectedRevision,
    idempotency_key: command.idempotencyKey,
  });
  if (command.operation === 'delete') return Object.freeze({ path, method: 'DELETE', mutation });
  if (command.operation === 'update')
    return Object.freeze({
      path,
      method: 'PATCH',
      mutation,
      body: Object.freeze({ version: command.expectedRevision, ...command.patch }),
    });
  const { contentType, ...fields } = command.memory;
  return Object.freeze({
    path,
    method: 'POST',
    mutation,
    body: Object.freeze({
      project_id: projectId,
      ...fields,
      ...(contentType === undefined ? {} : { content_type: contentType }),
    }),
  });
}
function responseError(status: number, body: unknown): DesktopApiError {
  const detail = isRecord(body) ? body.detail : null;
  const code = isRecord(body)
    ? (body.reason_code ?? body.code ?? (isRecord(detail) ? detail.code : null))
    : null;
  return new DesktopApiError(
    typeof code === 'string' && code.trim() === code && code ? code : `HTTP ${status}`,
    status,
    body,
  );
}
function invalidResponse(): Error {
  return projectKnowledgeError('cloud_memory_response_invalid');
}
