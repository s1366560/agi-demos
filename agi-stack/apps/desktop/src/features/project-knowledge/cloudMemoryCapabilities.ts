import type { ProjectKnowledgeScope } from './projectKnowledgeClient';

export type CloudMemoryCapabilities = Readonly<{
  protocolVersion: 1;
  tenantId: string;
  projectId: string;
  actorId: string;
  allowedActions: readonly 'create'[];
  objects: readonly Readonly<{
    memoryId: string;
    revision: number;
    allowedActions: readonly ('update' | 'delete')[];
  }>[];
}>;

/** Independent malformed data disables affordances; identity conflicts fail the operation. */
export function parseCloudMemoryCapabilities(
  value: unknown,
  scope: ProjectKnowledgeScope,
  memories: readonly Readonly<{ id: string; version: number }>[],
  actorId: string,
): CloudMemoryCapabilities | null {
  if (!record(value) || value.protocol_version !== 1) return null;
  if (
    (identifier(value.tenant_id) && value.tenant_id !== scope.tenantId) ||
    (identifier(value.project_id) && value.project_id !== scope.projectId) ||
    (identifier(value.actor_id) && value.actor_id !== actorId) ||
    scope.authority !== 'cloud'
  )
    throw new Error('cloud_memory_capability_scope_conflict');
  if (
    !exact(value, [
      'protocol_version',
      'tenant_id',
      'project_id',
      'actor_id',
      'allowed_actions',
      'objects',
    ]) ||
    !identifier(value.tenant_id) ||
    !identifier(value.project_id) ||
    !identifier(value.actor_id) ||
    !actions(value.allowed_actions, ['create']) ||
    !Array.isArray(value.objects) ||
    value.objects.length > memories.length
  )
    return null;
  const revisions = new Map(memories.map((memory) => [memory.id, memory.version]));
  const seen = new Set<string>();
  const objects: CloudMemoryCapabilities['objects'][number][] = [];
  for (const item of value.objects) {
    if (
      !record(item) ||
      !exact(item, ['memory_id', 'revision', 'allowed_actions']) ||
      !identifier(item.memory_id) ||
      seen.has(item.memory_id) ||
      !Number.isSafeInteger(item.revision) ||
      Number(item.revision) < 1 ||
      Number(item.revision) >= 2147483647 ||
      revisions.get(item.memory_id) !== item.revision ||
      !actions(item.allowed_actions, ['update', 'delete'])
    )
      return null;
    seen.add(item.memory_id);
    objects.push(
      Object.freeze({
        memoryId: item.memory_id,
        revision: Number(item.revision),
        allowedActions: Object.freeze([...item.allowed_actions]) as readonly (
          | 'update'
          | 'delete'
        )[],
      }),
    );
  }
  return Object.freeze({
    protocolVersion: 1,
    tenantId: value.tenant_id,
    projectId: value.project_id,
    actorId: value.actor_id,
    allowedActions: Object.freeze([...value.allowed_actions]) as readonly 'create'[],
    objects: Object.freeze(objects),
  });
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function validCloudMemoryCapabilitySnapshot(
  value: unknown,
  scope: ProjectKnowledgeScope,
  memories: readonly Readonly<{ id: string; version: number }>[],
): boolean {
  if (value === null) return true;
  if (
    !record(value) ||
    !exact(value, [
      'protocolVersion',
      'tenantId',
      'projectId',
      'actorId',
      'allowedActions',
      'objects',
    ]) ||
    !identifier(value.actorId) ||
    !Array.isArray(value.objects)
  )
    return false;
  const objects = [];
  for (const item of value.objects) {
    if (!record(item) || !exact(item, ['memoryId', 'revision', 'allowedActions'])) return false;
    objects.push({
      memory_id: item.memoryId,
      revision: item.revision,
      allowed_actions: item.allowedActions,
    });
  }
  try {
    return (
      parseCloudMemoryCapabilities(
        {
          protocol_version: value.protocolVersion,
          tenant_id: value.tenantId,
          project_id: value.projectId,
          actor_id: value.actorId,
          allowed_actions: value.allowedActions,
          objects,
        },
        scope,
        memories,
        value.actorId,
      ) !== null
    );
  } catch {
    return false;
  }
}
function exact(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}
function identifier(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value.length <= 512 && value.trim() === value
  );
}
function actions(value: unknown, allowed: readonly string[]): value is string[] {
  return (
    Array.isArray(value) &&
    new Set(value).size === value.length &&
    value.every((action) => typeof action === 'string' && allowed.includes(action))
  );
}
