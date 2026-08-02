import type {
  RuntimePoolInstance,
  RuntimePoolInstancePage,
  RuntimePoolStatus,
} from '../runtime-pool/runtimePoolClient';

export type UnifiedRuntimesAuthority = 'cloud' | 'local';
export type UnifiedRuntimesResourceState =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'empty'
  | 'degraded'
  | 'stale'
  | 'error'
  | 'unavailable'
  | 'not_applicable';

export type UnifiedRuntimesScope = Readonly<{
  authority: UnifiedRuntimesAuthority;
  tenantId: string;
  projectId: string;
}>;

export type UnifiedSandbox = Readonly<{
  sandboxId: string;
  tenantId: string;
  projectId: string;
  status: string;
  healthy: boolean;
  createdAt: string | null;
  lastAccessedAt: string | null;
}>;

export type UnifiedSandboxStats = Readonly<{
  projectId: string;
  sandboxId: string;
  status: string;
  memoryUsageBytes: number;
  pids: number;
  collectedAt: string;
}>;

export type UnifiedLocalSidecar = Readonly<{
  running: boolean;
  toolCount: number;
  providerCount: number;
}>;

export type UnifiedCapabilityAvailability =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type UnifiedSandboxCapability = Readonly<{
  availability: UnifiedCapabilityAvailability;
  reasonCode: string | null;
}>;

export type UnifiedSandboxCapabilities = Readonly<{
  serviceVersion: string;
  contractVersion: string;
  terminalInteractive: UnifiedSandboxCapability;
  terminalResume: UnifiedSandboxCapability;
  files: UnifiedSandboxCapability;
  kasmVnc: UnifiedSandboxCapability;
}>;

export type UnifiedRuntimeRow = Readonly<{
  key: string;
  kind: 'pool_actor' | 'sandbox' | 'sidecar' | 'sandbox_capability';
  identifier: string;
  tenantId: string;
  projectId: string;
  status: string;
  health: string;
  tier: string | null;
  loadLabel: string | null;
  memoryMb: number | null;
  lastActivity: string | null;
}>;

export type UnifiedRuntimesModel = Readonly<{
  scope: UnifiedRuntimesScope;
  authority: UnifiedRuntimesAuthority;
  availability: 'degraded' | 'unavailable';
  reasonCode: string;
  poolState: UnifiedRuntimesResourceState;
  sandboxState: UnifiedRuntimesResourceState;
  sidecarState: UnifiedRuntimesResourceState;
  capabilitiesState: UnifiedRuntimesResourceState;
  poolReasonCode: string | null;
  sandboxReasonCode: string | null;
  sidecarReasonCode: string | null;
  capabilitiesReasonCode: string | null;
  retryPoolVisible: boolean;
  retrySandboxVisible: boolean;
  retrySidecarVisible: boolean;
  retryCapabilitiesVisible: boolean;
  allowedActions: readonly string[];
  poolStatus: RuntimePoolStatus | null;
  rows: readonly UnifiedRuntimeRow[];
  lastUpdatedAt: string | null;
}>;

export type UnifiedRuntimesRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export type UnifiedRuntimesClient = Readonly<{
  getPoolStatus(
    scope: UnifiedRuntimesScope,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<RuntimePoolStatus>;
  listPoolInstances(
    scope: UnifiedRuntimesScope,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<RuntimePoolInstancePage>;
  listSandboxes(
    scope: UnifiedRuntimesScope,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<readonly UnifiedSandbox[]>;
  getSandboxStats(
    scope: UnifiedRuntimesScope,
    projectId: string,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<UnifiedSandboxStats | null>;
  getLocalSidecar(
    scope: UnifiedRuntimesScope,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<UnifiedLocalSidecar>;
  getSandboxCapabilities(
    scope: UnifiedRuntimesScope,
    options?: UnifiedRuntimesRequestOptions,
  ): Promise<UnifiedSandboxCapabilities>;
}>;

export function poolInstanceRow(instance: RuntimePoolInstance): UnifiedRuntimeRow {
  return Object.freeze({
    key: `pool:${instance.instanceKey}`,
    kind: 'pool_actor',
    identifier: instance.instanceKey,
    tenantId: instance.tenantId,
    projectId: instance.projectId,
    status: instance.status,
    health: instance.healthStatus,
    tier: instance.tier,
    loadLabel: `${String(instance.activeRequests)} req`,
    memoryMb: instance.memoryUsedMb,
    lastActivity: instance.lastRequestAt,
  });
}
