import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';

import { ApiError, ApiErrorType } from './client/ApiError';
import { httpClient, type HttpRequestConfig } from './client/httpClient';

import type { Memory, MemoryCreate, MemoryUpdate } from '../types/memory';

/** A caller replaying a known versioned command retains this key and the exact body/revision. */
export interface MemoryMutationOptions {
  readonly idempotencyKey?: string | undefined;
}

const MAX_REVISION = 2147483647;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;

function requireRevision(value: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value >= MAX_REVISION) {
    throw new ApiError(ApiErrorType.VALIDATION, 'INVALID_INPUT', 'Invalid memory revision', 422);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiresCommand(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.statusCode === 428 &&
    isRecord(error.details) &&
    isRecord(error.details.detail) &&
    error.details.detail.code === 'memory_command_precondition_required'
  );
}

/** Negotiate only the production no-write challenge, inside one identity/generation operation. */
async function mutate<T>(
  operation: WebOperationContextV2,
  expectedRevision: number,
  options: MemoryMutationOptions | undefined,
  send: (config: HttpRequestConfig) => Promise<T>
): Promise<T> {
  const key = options?.idempotencyKey ?? crypto.randomUUID();
  if (!UUID_PATTERN.test(key)) {
    throw new ApiError(ApiErrorType.VALIDATION, 'INVALID_INPUT', 'Invalid memory command key', 422);
  }
  if (!options?.idempotencyKey) {
    try {
      return await send({ operation });
    } catch (error) {
      operation.check();
      if (!requiresCommand(error)) throw error;
    }
  }
  const headers = Object.freeze({
    'Idempotency-Key': key,
    'X-Memory-Expected-Revision': String(expectedRevision),
  });
  try {
    return await send({ operation, headers });
  } catch (error) {
    operation.check();
    // A versioned request is replay-safe even if its first response was lost.
    // Never retry a conflict, permission failure, 428, or server availability response.
    if (!(error instanceof ApiError) || error.type !== ApiErrorType.NETWORK) throw error;
    return await send({ operation, headers });
  }
}

export const memoryCommandTransport = {
  create: (
    projectId: string,
    data: Omit<MemoryCreate, 'project_id'> & Partial<Pick<MemoryCreate, 'project_id'>>,
    options?: MemoryMutationOptions
  ): Promise<Memory> => {
    // Capture JSON wire bytes before awaiting admission/network; caller edits cannot change retries.
    const payload = JSON.parse(JSON.stringify({ ...data, project_id: projectId })) as MemoryCreate;
    return runWebOperationV2((operation) =>
      mutate(operation, 0, options, (config) => httpClient.post('/memories/', payload, config))
    );
  },

  update: async (
    projectId: string,
    memoryId: string,
    data: MemoryUpdate,
    options?: MemoryMutationOptions
  ): Promise<Memory> => {
    const revision = requireRevision(data.version);
    const payload = JSON.parse(JSON.stringify(data)) as MemoryUpdate;
    return runWebOperationV2((operation) =>
      mutate(operation, revision, options, (config) =>
        httpClient.patch(`/memories/${encodeURIComponent(memoryId)}`, payload, {
          ...config,
          params: { project_id: projectId },
        })
      )
    );
  },

  delete: (
    projectId: string,
    memoryId: string,
    expectedRevision?: number,
    options?: MemoryMutationOptions
  ): Promise<void> =>
    runWebOperationV2(async (operation) => {
      const path = `/memories/${encodeURIComponent(memoryId)}`;
      let revision = expectedRevision;
      if (revision === undefined) {
        // Compatibility callers capture once before the first delete, never after a conflict.
        const memory = await httpClient.get<Memory>(path, {
          operation,
          params: { project_id: projectId },
        });
        operation.check();
        if (memory.id !== memoryId || memory.project_id !== projectId) {
          throw new ApiError(
            ApiErrorType.NOT_FOUND,
            'RESOURCE_NOT_FOUND',
            'Memory scope mismatch',
            404
          );
        }
        revision = memory.version;
      }
      const capturedRevision = requireRevision(revision);
      await mutate(operation, capturedRevision, options, (config) =>
        httpClient.delete(path, { ...config, params: { project_id: projectId } })
      );
    }),
};
