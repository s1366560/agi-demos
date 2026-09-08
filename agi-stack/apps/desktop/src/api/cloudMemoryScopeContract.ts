/** Credential-free expectation bound to the main process's captured vault session. */
export type CloudMemoryRequestScope = Readonly<{
  actor_id: string;
  tenant_id: string;
  project_id: string;
  context_revision: number;
}>;

export function requireCloudMemoryRequestScope(value: unknown): CloudMemoryRequestScope {
  if (
    !record(value) ||
    Object.keys(value).length !== 4 ||
    !identifier(value.actor_id) ||
    !identifier(value.tenant_id) ||
    !identifier(value.project_id) ||
    !Number.isSafeInteger(value.context_revision) ||
    Number(value.context_revision) < 0
  ) {
    throw new Error('cloud_memory_scope_invalid');
  }
  return Object.freeze({
    actor_id: value.actor_id,
    tenant_id: value.tenant_id,
    project_id: value.project_id,
    context_revision: Number(value.context_revision),
  });
}

export function assertCloudMemoryContext(scope: CloudMemoryRequestScope, payload: unknown): void {
  if (
    !record(payload) ||
    !record(payload.context) ||
    payload.context.tenant_id !== scope.tenant_id ||
    payload.context.project_id !== scope.project_id ||
    payload.context.revision !== scope.context_revision
  )
    throw new Error('cloud_memory_scope_conflict');
}

export function assertCloudMemoryActor(scope: CloudMemoryRequestScope, payload: unknown): void {
  if (!record(payload) || payload.user_id !== scope.actor_id)
    throw new Error('cloud_memory_scope_conflict');
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function identifier(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 512 &&
    value === value.trim() &&
    !/[\u0000-\u001f\u007f]/u.test(value)
  );
}
