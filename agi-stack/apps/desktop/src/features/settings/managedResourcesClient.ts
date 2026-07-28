export type ManagedResourceKind = 'skill' | 'plugin' | 'agent' | 'subagent';

export type ManagedResourceScope = {
  tenant_id: string;
  project_id: string;
};

export type ManagedResourceRecord = {
  id: string;
  kind: ManagedResourceKind;
  revision: number;
  builtin: boolean;
  payload: Record<string, unknown>;
};

export type ManagedResourceMutation = {
  operation: 'create' | 'update' | 'delete' | 'import' | 'rollback' | 'run';
  kind: ManagedResourceKind;
  resource_id?: string;
  expected_revision?: number;
  idempotency_key: string;
  payload: Record<string, unknown>;
};

export type ManagedResourceReceipt = {
  receipt_id: string;
  resource: ManagedResourceRecord | null;
  duplicate: boolean;
};

export type ManagedResourcesClient = {
  list(
    scope: ManagedResourceScope,
    kind: ManagedResourceKind,
    signal?: AbortSignal,
  ): Promise<ManagedResourceRecord[]>;
  getVersions(
    scope: ManagedResourceScope,
    kind: ManagedResourceKind,
    resourceId: string,
    signal?: AbortSignal,
  ): Promise<ManagedResourceRecord[]>;
  mutate(
    scope: ManagedResourceScope,
    mutation: ManagedResourceMutation,
    signal?: AbortSignal,
  ): Promise<ManagedResourceReceipt>;
};

export function createManagedResourcesClient(
  authority: ManagedResourcesClient,
): ManagedResourcesClient {
  return Object.freeze({
    list: (
      scope: ManagedResourceScope,
      kind: ManagedResourceKind,
      signal?: AbortSignal,
    ) => authority.list(scope, kind, signal),
    getVersions: (
      scope: ManagedResourceScope,
      kind: ManagedResourceKind,
      resourceId: string,
      signal?: AbortSignal,
    ) => authority.getVersions(scope, kind, resourceId, signal),
    mutate: (
      scope: ManagedResourceScope,
      mutation: ManagedResourceMutation,
      signal?: AbortSignal,
    ) => authority.mutate(scope, mutation, signal),
  });
}
