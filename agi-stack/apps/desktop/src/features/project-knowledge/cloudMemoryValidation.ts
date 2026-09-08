import type { CloudMemoryCommand, CloudMemoryOptions } from './cloudMemoryClient';
import { requireCloudMemoryMutation } from '../../api/cloudMemoryCommandContract';
import { projectKnowledgeError } from './projectKnowledgeClient';

/** Protocol validation only. Preserve the exact draft and idempotency key across a retry. */
export function prepareCloudMemoryCommand<C extends CloudMemoryCommand>(input: C): C {
  const value = object(input);
  if (value.operation === 'get') {
    keys(value, ['operation', 'id']);
    pathId(value.id);
  } else if (value.operation === 'create') {
    keys(value, ['operation', 'idempotencyKey', 'memory']);
    requireCloudMemoryMutation({
      kind: 'memory-command',
      expected_revision: 0,
      idempotency_key: value.idempotencyKey,
    });
    const memory = object(value.memory);
    fields(memory, true);
  } else if (value.operation === 'update' || value.operation === 'delete') {
    keys(value, [
      'operation',
      'id',
      'expectedRevision',
      'idempotencyKey',
      ...(value.operation === 'update' ? ['patch'] : []),
    ]);
    pathId(value.id);
    const mutation = requireCloudMemoryMutation({
      kind: 'memory-command',
      expected_revision: value.expectedRevision,
      idempotency_key: value.idempotencyKey,
    });
    if (mutation.expected_revision < 1) throw invalid();
    if (value.operation === 'update') {
      const patch = object(value.patch);
      if (Object.keys(patch).length === 0) throw invalid();
      fields(patch, false);
    }
  } else throw invalid();
  const result = jsonCopy(input);
  if (new TextEncoder().encode(JSON.stringify(result)).byteLength > 512 * 1024) throw invalid();
  return result as C;
}

export function prepareCloudMemoryOptions(input: CloudMemoryOptions): CloudMemoryOptions {
  const value = object(input);
  keys(value, ['expectedActorId', 'expectedContextRevision', 'signal']);
  identifier(value.expectedActorId);
  if (
    !Number.isSafeInteger(value.expectedContextRevision) ||
    Number(value.expectedContextRevision) < 0 ||
    (value.signal !== undefined && !(value.signal instanceof AbortSignal))
  )
    throw invalid();
  return Object.freeze({ ...input });
}

function fields(value: Record<string, unknown>, create: boolean): void {
  keys(value, ['title', 'content', 'tags', 'metadata', ...(create ? ['contentType'] : [])]);
  if (create || Object.hasOwn(value, 'title')) identifier(value.title);
  if ((create || Object.hasOwn(value, 'content')) && typeof value.content !== 'string')
    throw invalid();
  if (Object.hasOwn(value, 'contentType')) identifier(value.contentType);
  if (
    Object.hasOwn(value, 'tags') &&
    (!Array.isArray(value.tags) || !value.tags.every((tag) => typeof tag === 'string'))
  )
    throw invalid();
  if (Object.hasOwn(value, 'metadata')) object(value.metadata);
}
function object(value: unknown): Record<string, unknown> {
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw invalid();
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, allowed: readonly string[]): void {
  if (Object.keys(value).some((key) => !allowed.includes(key))) throw invalid();
}
function identifier(value: unknown): asserts value is string {
  if (
    typeof value !== 'string' ||
    !value ||
    value !== value.trim() ||
    value.length > 512 ||
    /[\u0000-\u001f\u007f]/u.test(value)
  )
    throw invalid();
}
function pathId(value: unknown): void {
  identifier(value);
  if (value.includes('/') || value.includes('\\') || value === '.' || value === '..')
    throw invalid();
}
function jsonCopy(value: unknown, depth = 0): unknown {
  if (depth > 32) throw invalid();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return Object.freeze(value.map((item) => jsonCopy(item, depth + 1)));
  const record = object(value);
  return Object.freeze(
    Object.fromEntries(
      Object.entries(record).map(([key, item]) => [key, jsonCopy(item, depth + 1)]),
    ),
  );
}
function invalid(): Error {
  return projectKnowledgeError('cloud_memory_command_invalid', 422);
}
