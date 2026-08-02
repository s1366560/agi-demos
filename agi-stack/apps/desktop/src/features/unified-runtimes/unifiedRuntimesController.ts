import { DesktopApiError } from '../../api/client';
import { UnifiedRuntimesUnavailableError } from './unifiedRuntimesClient';
import {
  poolInstanceRow,
  type UnifiedLocalSidecar,
  type UnifiedRuntimeRow,
  type UnifiedRuntimesAuthority,
  type UnifiedRuntimesClient,
  type UnifiedRuntimesModel,
  type UnifiedRuntimesResourceState,
  type UnifiedRuntimesScope,
  type UnifiedSandbox,
  type UnifiedSandboxCapabilities,
  type UnifiedSandboxStats,
} from './unifiedRuntimesTypes';

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'inspect-pool',
  'inspect-sandbox',
]);
const LOCAL_ACTIONS = Object.freeze([
  'view',
  'refresh',
  'inspect-sidecar',
  'inspect-sandbox-capabilities',
]);

export type UnifiedRuntimesControllerOptions = Readonly<{
  authority: UnifiedRuntimesAuthority;
  client: UnifiedRuntimesClient;
  initialScope: UnifiedRuntimesScope;
  now?: () => Date;
}>;

export type UnifiedRuntimesController = Readonly<{
  getSnapshot(): UnifiedRuntimesModel;
  subscribe(listener: () => void): () => void;
  load(scope: UnifiedRuntimesScope): Promise<void>;
  retry(scope: UnifiedRuntimesScope): Promise<void>;
  cancel(): void;
  stop(): void;
}>;

export function createUnifiedRuntimesController({
  authority,
  client,
  initialScope,
  now = () => new Date(),
}: UnifiedRuntimesControllerOptions): UnifiedRuntimesController {
  requireScope(initialScope, authority);
  const listeners = new Set<() => void>();
  let generation = 0;
  let controller: AbortController | null = null;
  let model = initialModel(initialScope);

  const publish = (next: UnifiedRuntimesModel) => {
    model = freezeModel(next);
    for (const listener of listeners) listener();
  };

  const load = async (scope: UnifiedRuntimesScope): Promise<void> => {
    requireScope(scope, authority);
    const requestGeneration = ++generation;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    const retain = sameScope(model.scope, scope);
    publish(loadingModel(model, scope, retain));

    if (authority === 'cloud') {
      await loadCloud({
        client,
        scope,
        signal,
        prior: retain ? model : initialModel(scope),
        active: () => generation === requestGeneration && !signal.aborted,
        publish,
        now,
      });
      return;
    }
    await loadLocal({
      client,
      scope,
      signal,
      prior: retain ? model : initialModel(scope),
      active: () => generation === requestGeneration && !signal.aborted,
      publish,
      now,
    });
  };

  return Object.freeze({
    getSnapshot: () => model,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    load,
    retry: load,
    cancel() {
      generation += 1;
      controller?.abort();
      controller = null;
    },
    stop() {
      generation += 1;
      controller?.abort();
      controller = null;
      listeners.clear();
    },
  });
}

type LoadContext = Readonly<{
  client: UnifiedRuntimesClient;
  scope: UnifiedRuntimesScope;
  signal: AbortSignal;
  prior: UnifiedRuntimesModel;
  active: () => boolean;
  publish: (model: UnifiedRuntimesModel) => void;
  now: () => Date;
}>;

async function loadCloud(context: LoadContext): Promise<void> {
  const { client, scope, signal } = context;
  const [statusResult, instancesResult, sandboxesResult] =
    await Promise.allSettled([
      client.getPoolStatus(scope, { signal }),
      client.listPoolInstances(scope, { signal }),
      client.listSandboxes(scope, { signal }),
    ]);
  if (!context.active()) return;

  const poolSucceeded =
    statusResult.status === 'fulfilled' &&
    instancesResult.status === 'fulfilled';
  const priorPoolRows = rowsOfKind(context.prior.rows, 'pool_actor');
  const poolRows = poolSucceeded
    ? instancesResult.value.instances.map(poolInstanceRow)
    : priorPoolRows;
  const poolState = poolSucceeded
    ? resourceState(poolRows.length)
    : retainedFailureState(priorPoolRows);
  const poolReasonCode = poolSucceeded
    ? statusResult.value.reasonCode
    : failureReason(
        statusResult.status === 'rejected'
          ? statusResult.reason
          : instancesResult.status === 'rejected'
            ? instancesResult.reason
            : null,
        'unified_runtimes_pool_load_failed',
      );

  let sandboxRows = rowsOfKind(context.prior.rows, 'sandbox');
  let sandboxState: UnifiedRuntimesResourceState;
  let sandboxReasonCode: string | null;
  if (sandboxesResult.status === 'fulfilled') {
    const stats = await Promise.allSettled(
      sandboxesResult.value.map((sandbox) =>
        client.getSandboxStats(scope, sandbox.projectId, { signal }),
      ),
    );
    if (!context.active()) return;
    sandboxRows = sandboxesResult.value.map((sandbox, index) =>
      sandboxRow(
        sandbox,
        stats[index]?.status === 'fulfilled'
          ? (stats[index] as PromiseFulfilledResult<UnifiedSandboxStats | null>)
              .value
          : null,
      ),
    );
    const missingStats = stats.some((entry) => entry.status === 'rejected');
    sandboxState = missingStats
      ? 'degraded'
      : resourceState(sandboxRows.length);
    sandboxReasonCode = missingStats
      ? 'unified_runtimes_sandbox_metrics_partial'
      : null;
  } else {
    sandboxState = retainedFailureState(sandboxRows);
    sandboxReasonCode = failureReason(
      sandboxesResult.reason,
      'unified_runtimes_sandbox_load_failed',
    );
  }

  context.publish({
    ...initialModel(scope),
    poolState,
    sandboxState,
    poolReasonCode,
    sandboxReasonCode,
    retryPoolVisible: !poolSucceeded,
    retrySandboxVisible: sandboxesResult.status === 'rejected',
    poolStatus:
      statusResult.status === 'fulfilled'
        ? statusResult.value
        : context.prior.poolStatus,
    rows: Object.freeze([...poolRows, ...sandboxRows]),
    lastUpdatedAt: context.now().toISOString(),
  });
}

async function loadLocal(context: LoadContext): Promise<void> {
  const { client, scope, signal } = context;
  const [sidecarResult, capabilitiesResult] = await Promise.allSettled([
    client.getLocalSidecar(scope, { signal }),
    client.getSandboxCapabilities(scope, { signal }),
  ]);
  if (!context.active()) return;

  const priorSidecar = rowsOfKind(context.prior.rows, 'sidecar');
  const priorCapabilities = rowsOfKind(
    context.prior.rows,
    'sandbox_capability',
  );
  const sidecarRows =
    sidecarResult.status === 'fulfilled'
      ? [sidecarRow(scope, sidecarResult.value)]
      : priorSidecar;
  const capabilityRows =
    capabilitiesResult.status === 'fulfilled'
      ? [sandboxCapabilityRow(scope, capabilitiesResult.value)]
      : priorCapabilities;
  const sidecarState =
    sidecarResult.status === 'fulfilled'
      ? sidecarResult.value.running
        ? 'ready'
        : 'degraded'
      : retainedFailureState(priorSidecar);
  const capabilitiesState =
    capabilitiesResult.status === 'fulfilled'
      ? 'ready'
      : retainedFailureState(priorCapabilities);

  context.publish({
    ...initialModel(scope),
    poolState: 'not_applicable',
    sandboxState:
      capabilitiesResult.status === 'fulfilled'
        ? 'degraded'
        : retainedFailureState(priorCapabilities),
    sidecarState,
    capabilitiesState,
    poolReasonCode: 'local_pool_not_applicable_sidecar_projection',
    sandboxReasonCode:
      capabilitiesResult.status === 'fulfilled'
        ? 'local_isolated_sandbox_not_applicable'
        : failureReason(
            capabilitiesResult.reason,
            'unified_runtimes_sandbox_capabilities_load_failed',
          ),
    sidecarReasonCode:
      sidecarResult.status === 'fulfilled'
        ? sidecarResult.value.running
          ? null
          : 'unified_runtimes_sidecar_not_running'
        : failureReason(
            sidecarResult.reason,
            'unified_runtimes_sidecar_load_failed',
          ),
    capabilitiesReasonCode:
      capabilitiesResult.status === 'fulfilled'
        ? null
        : failureReason(
            capabilitiesResult.reason,
            'unified_runtimes_sandbox_capabilities_load_failed',
          ),
    retrySidecarVisible: sidecarResult.status === 'rejected',
    retryCapabilitiesVisible: capabilitiesResult.status === 'rejected',
    retrySandboxVisible: capabilitiesResult.status === 'rejected',
    rows: Object.freeze([...sidecarRows, ...capabilityRows]),
    lastUpdatedAt: context.now().toISOString(),
  });
}

function initialModel(scope: UnifiedRuntimesScope): UnifiedRuntimesModel {
  const local = scope.authority === 'local';
  return freezeModel({
    scope,
    authority: scope.authority,
    availability: 'degraded',
    reasonCode: local
      ? 'local_pool_not_applicable_sidecar_projection'
      : 'global_pool_capacity_not_available_in_tenant_scope',
    poolState: local ? 'not_applicable' : 'idle',
    sandboxState: 'idle',
    sidecarState: local ? 'idle' : 'not_applicable',
    capabilitiesState: local ? 'idle' : 'not_applicable',
    poolReasonCode: local
      ? 'local_pool_not_applicable_sidecar_projection'
      : null,
    sandboxReasonCode: null,
    sidecarReasonCode: null,
    capabilitiesReasonCode: null,
    retryPoolVisible: false,
    retrySandboxVisible: false,
    retrySidecarVisible: false,
    retryCapabilitiesVisible: false,
    allowedActions: local ? LOCAL_ACTIONS : CLOUD_ACTIONS,
    poolStatus: null,
    rows: Object.freeze([]),
    lastUpdatedAt: null,
  });
}

function loadingModel(
  current: UnifiedRuntimesModel,
  scope: UnifiedRuntimesScope,
  retain: boolean,
): UnifiedRuntimesModel {
  const initial = initialModel(scope);
  if (!retain) {
    return {
      ...initial,
      poolState: scope.authority === 'cloud' ? 'loading' : 'not_applicable',
      sandboxState: 'loading',
      sidecarState: scope.authority === 'local' ? 'loading' : 'not_applicable',
      capabilitiesState:
        scope.authority === 'local' ? 'loading' : 'not_applicable',
    };
  }
  return {
    ...current,
    poolState:
      scope.authority === 'cloud' ? loadingOrStale(current.poolState) : 'not_applicable',
    sandboxState: loadingOrStale(current.sandboxState),
    sidecarState:
      scope.authority === 'local'
        ? loadingOrStale(current.sidecarState)
        : 'not_applicable',
    capabilitiesState:
      scope.authority === 'local'
        ? loadingOrStale(current.capabilitiesState)
        : 'not_applicable',
    retryPoolVisible: false,
    retrySandboxVisible: false,
    retrySidecarVisible: false,
    retryCapabilitiesVisible: false,
  };
}

function loadingOrStale(
  state: UnifiedRuntimesResourceState,
): UnifiedRuntimesResourceState {
  return state === 'ready' || state === 'empty' || state === 'degraded'
    ? 'stale'
    : 'loading';
}

function resourceState(rowCount: number): UnifiedRuntimesResourceState {
  return rowCount === 0 ? 'empty' : 'ready';
}

function retainedFailureState(
  rows: readonly UnifiedRuntimeRow[],
): UnifiedRuntimesResourceState {
  return rows.length > 0 ? 'stale' : 'error';
}

function rowsOfKind(
  rows: readonly UnifiedRuntimeRow[],
  kind: UnifiedRuntimeRow['kind'],
): readonly UnifiedRuntimeRow[] {
  return rows.filter((row) => row.kind === kind);
}

function sandboxRow(
  sandbox: UnifiedSandbox,
  stats: UnifiedSandboxStats | null,
): UnifiedRuntimeRow {
  return Object.freeze({
    key: `sandbox:${sandbox.sandboxId}`,
    kind: 'sandbox',
    identifier: sandbox.sandboxId,
    tenantId: sandbox.tenantId,
    projectId: sandbox.projectId,
    status: stats?.status ?? sandbox.status,
    health: sandbox.healthy ? 'healthy' : 'unhealthy',
    tier: 'project',
    loadLabel: stats ? `${String(stats.pids)} pids` : null,
    memoryMb: stats ? stats.memoryUsageBytes / (1024 * 1024) : null,
    lastActivity: sandbox.lastAccessedAt ?? sandbox.createdAt,
  });
}

function sidecarRow(
  scope: UnifiedRuntimesScope,
  sidecar: UnifiedLocalSidecar,
): UnifiedRuntimeRow {
  return Object.freeze({
    key: 'sidecar:agistack-desktop-sidecar',
    kind: 'sidecar',
    identifier: 'agistack-desktop-sidecar',
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    status: sidecar.running ? 'running' : 'stopped',
    health: sidecar.running ? 'healthy' : 'unhealthy',
    tier: 'local',
    loadLabel: `${String(sidecar.toolCount)} tools · ${String(
      sidecar.providerCount,
    )} providers`,
    memoryMb: null,
    lastActivity: null,
  });
}

function sandboxCapabilityRow(
  scope: UnifiedRuntimesScope,
  capabilities: UnifiedSandboxCapabilities,
): UnifiedRuntimeRow {
  const available = [
    capabilities.terminalInteractive,
    capabilities.terminalResume,
    capabilities.files,
    capabilities.kasmVnc,
  ].filter((capability) => capability.availability === 'available').length;
  return Object.freeze({
    key: `sandbox-capability:${scope.projectId}`,
    kind: 'sandbox_capability',
    identifier: scope.projectId,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    status: 'degraded',
    health: 'degraded',
    tier: 'native_workspace',
    loadLabel: `${String(available)} / 4 capabilities`,
    memoryMb: null,
    lastActivity: null,
  });
}

function failureReason(error: unknown, fallback: string): string {
  if (error instanceof UnifiedRuntimesUnavailableError) {
    return error.reasonCode;
  }
  if (
    error instanceof DesktopApiError &&
    typeof error.payload === 'object' &&
    error.payload !== null &&
    'reason_code' in error.payload &&
    typeof error.payload.reason_code === 'string'
  ) {
    return error.payload.reason_code;
  }
  return fallback;
}

function requireScope(
  scope: UnifiedRuntimesScope,
  authority: UnifiedRuntimesAuthority,
): void {
  if (
    scope.authority !== authority ||
    !scope.tenantId ||
    scope.tenantId !== scope.tenantId.trim() ||
    !scope.projectId ||
    scope.projectId !== scope.projectId.trim()
  ) {
    throw new Error('unified_runtimes_controller_scope_invalid');
  }
}

function sameScope(
  left: UnifiedRuntimesScope,
  right: UnifiedRuntimesScope,
): boolean {
  return (
    left.authority === right.authority &&
    left.tenantId === right.tenantId &&
    left.projectId === right.projectId
  );
}

function freezeModel(model: UnifiedRuntimesModel): UnifiedRuntimesModel {
  return Object.freeze({
    ...model,
    scope: Object.freeze({ ...model.scope }),
    allowedActions: Object.freeze([...model.allowedActions]),
    rows: Object.freeze([...model.rows]),
  });
}
