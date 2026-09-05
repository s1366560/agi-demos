const ownerIds = new WeakMap<object, number>();
let nextOwnerId = 0;

/** Structural UI identity only; terminal admission still validates the actual owner. */
export function terminalScopeKeyV2(
  owner: object,
  projectId: string | undefined,
  sandboxId: string
): string {
  let id = ownerIds.get(owner);
  if (id === undefined) {
    id = ++nextOwnerId;
    ownerIds.set(owner, id);
  }
  return JSON.stringify([id, projectId ?? null, sandboxId]);
}
