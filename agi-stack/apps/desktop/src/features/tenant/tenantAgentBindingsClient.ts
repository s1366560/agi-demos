export type TenantAgentBindingsAuthority = 'cloud' | 'local';
export type TenantAgentBindingsAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type TenantAgentBindingsAction =
  | 'view'
  | 'list'
  | 'create'
  | 'delete'
  | 'set-enabled'
  | 'test';

export type TenantAgentBindingsScope = Readonly<{
  authority: TenantAgentBindingsAuthority;
  tenantId: string;
}>;

export type TenantAgentBinding = Readonly<{
  id: string;
  tenantId: string;
  agentId: string;
  agentName: string;
  channelType: string | null;
  channelId: string | null;
  accountId: string | null;
  peerId: string | null;
  groupId: string | null;
  priority: number;
  enabled: boolean;
  createdAt: string;
  specificityScore: number;
}>;

export type TenantAgentBindingDefinition = Readonly<{
  id: string;
  name: string;
  displayName: string;
}>;

export type TenantAgentBindingTraceEntry = Readonly<{
  bindingId: string;
  agentId: string;
  specificityScore: number;
  channelType: string | null;
  channelId: string | null;
  accountId: string | null;
  peerId: string | null;
  priority: number;
  eliminated: boolean;
  eliminationReason: string | null;
  selected: boolean;
}>;

export type TenantAgentBindingTestResult = Readonly<{
  agentId: string | null;
  agentName: string | null;
  bindingId: string | null;
  specificityScore: number;
  confidence: number;
  matched: boolean;
  trace: readonly TenantAgentBindingTraceEntry[];
}>;

export type TenantAgentBindingsSnapshot = Readonly<{
  scope: TenantAgentBindingsScope;
  authority: TenantAgentBindingsAuthority;
  availability: TenantAgentBindingsAvailability;
  reasonCode: string | null;
  serviceVersion: string;
  contractVersion: string;
  allowedActions: readonly TenantAgentBindingsAction[];
  authorityRevision: number | null;
  bindings: readonly TenantAgentBinding[];
  definitions: readonly TenantAgentBindingDefinition[];
}>;

export type CreateTenantAgentBindingInput = Readonly<{
  agentId: string;
  channelType: string | null;
  channelId: string | null;
  accountId: string | null;
  peerId: string | null;
  groupId: string | null;
  priority: number;
}>;

export type TestTenantAgentBindingInput = Readonly<{
  channelType: string;
  channelId: string | null;
  accountId: string | null;
  peerId: string | null;
}>;

export type TenantAgentBindingsListQuery = Readonly<{
  agentId?: string;
  enabledOnly?: boolean;
}>;

export type TenantAgentBindingsReadOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type TenantAgentBindingsMutationOptions = Readonly<{
  idempotencyKey?: string;
  signal?: AbortSignal;
}>;

export type TenantAgentBindingsClient = Readonly<{
  list: (
    scope: TenantAgentBindingsScope,
    query?: TenantAgentBindingsListQuery,
    options?: TenantAgentBindingsReadOptions,
  ) => Promise<TenantAgentBindingsSnapshot>;
  create: (
    scope: TenantAgentBindingsScope,
    input: CreateTenantAgentBindingInput,
    options?: TenantAgentBindingsMutationOptions,
  ) => Promise<TenantAgentBinding>;
  delete: (
    scope: TenantAgentBindingsScope,
    bindingId: string,
    options?: TenantAgentBindingsMutationOptions,
  ) => Promise<void>;
  setEnabled: (
    scope: TenantAgentBindingsScope,
    bindingId: string,
    enabled: boolean,
    options?: TenantAgentBindingsMutationOptions,
  ) => Promise<TenantAgentBinding>;
  test: (
    scope: TenantAgentBindingsScope,
    input: TestTenantAgentBindingInput,
    options?: TenantAgentBindingsMutationOptions,
  ) => Promise<TenantAgentBindingTestResult>;
}>;

export function createTenantAgentBindingMutationKey(action: string): string {
  const suffix =
    typeof globalThis.crypto?.randomUUID === 'function'
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `tenant-agent-binding:${action}:${suffix}`;
}
