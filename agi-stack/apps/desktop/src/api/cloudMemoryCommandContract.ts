/** Shared renderer/main wire facts for the versioned memory command API. */
export const CLOUD_MEMORY_REVISION_HEADER = 'X-Memory-Expected-Revision';
export type CloudMemoryMutation = Readonly<{
  kind: 'memory-command';
  expected_revision: number;
  idempotency_key: string;
}>;

export function requireCloudMemoryMutation(value: unknown): CloudMemoryMutation {
  if (
    !record(value) ||
    Object.keys(value).length !== 3 ||
    value.kind !== 'memory-command' ||
    !Number.isSafeInteger(value.expected_revision) ||
    Number(value.expected_revision) < 0 ||
    Number(value.expected_revision) >= 2147483647 ||
    typeof value.idempotency_key !== 'string' ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(value.idempotency_key)
  )
    throw new Error('cloud_request_memory_command_invalid');
  return Object.freeze({
    kind: 'memory-command',
    expected_revision: Number(value.expected_revision),
    idempotency_key: value.idempotency_key,
  });
}

export function cloudMemoryMutationFromHeaders(headers: Headers): CloudMemoryMutation | null {
  const revision = headers.get(CLOUD_MEMORY_REVISION_HEADER);
  if (revision === null) return null;
  if (headers.has('X-Expected-Revision') || !/^(0|[1-9][0-9]*)$/u.test(revision)) {
    throw new Error('cloud_request_memory_command_invalid');
  }
  return requireCloudMemoryMutation({
    kind: 'memory-command',
    expected_revision: Number(revision),
    idempotency_key: headers.get('Idempotency-Key'),
  });
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
