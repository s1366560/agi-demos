import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  createRuntimePoolHttpClient,
  type RuntimePoolClient,
} from '../runtime-pool/runtimePoolClient';
import type {
  UnifiedCapabilityAvailability,
  UnifiedLocalSidecar,
  UnifiedRuntimesClient,
  UnifiedRuntimesScope,
  UnifiedSandbox,
  UnifiedSandboxCapabilities,
  UnifiedSandboxCapability,
  UnifiedSandboxStats,
} from './unifiedRuntimesTypes';

type Fetch = typeof globalThis.fetch;
type LocalRuntimeStatusReader = () => Promise<unknown>;

export type UnifiedRuntimesClientDependencies = Readonly<{
  fetch?: Fetch;
  poolClient?: Pick<RuntimePoolClient, 'getStatus' | 'listInstances'>;
  readLocalRuntimeStatus?: LocalRuntimeStatusReader;
}>;

export class UnifiedRuntimesUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'UnifiedRuntimesUnavailableError';
    this.reasonCode = reasonCode;
  }
}

export function createUnifiedRuntimesClient(
  config: DesktopRuntimeConfig,
  dependencies: UnifiedRuntimesClientDependencies = {},
): UnifiedRuntimesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchImpl = dependencies.fetch ?? globalThis.fetch;
  const poolClient =
    dependencies.poolClient ?? createRuntimePoolHttpClient(runtimeConfig);
  const readLocalRuntimeStatus =
    dependencies.readLocalRuntimeStatus ?? defaultLocalRuntimeStatusReader;

  return Object.freeze({
    async getPoolStatus(scope, options) {
      requireAuthority(runtimeConfig, scope, 'cloud');
      return poolClient.getStatus(poolScope(scope), options);
    },
    async listPoolInstances(scope, options) {
      requireAuthority(runtimeConfig, scope, 'cloud');
      return poolClient.listInstances(
        poolScope(scope),
        { page: 1, pageSize: 100 },
        options,
      );
    },
    async listSandboxes(scope, options) {
      requireAuthority(runtimeConfig, scope, 'cloud');
      const payload = await requestJson(
        runtimeConfig,
        '/api/v1/projects/sandboxes?limit=100&offset=0',
        fetchImpl,
        options?.signal,
      );
      const sandboxes = parseSandboxList(payload);
      if (sandboxes.some((sandbox) => sandbox.tenantId !== scope.tenantId)) {
        throw new UnifiedRuntimesUnavailableError(
          'unified_runtimes_sandbox_scope_mismatch',
        );
      }
      return sandboxes;
    },
    async getSandboxStats(scope, projectId, options) {
      requireAuthority(runtimeConfig, scope, 'cloud');
      const resolvedProjectId = identifier(
        projectId,
        'unified_runtimes_project_scope_invalid',
      );
      try {
        const payload = await requestJson(
          runtimeConfig,
          `/api/v1/projects/${encodeURIComponent(resolvedProjectId)}/sandbox/stats`,
          fetchImpl,
          options?.signal,
        );
        const stats = parseSandboxStats(payload);
        if (stats.projectId !== resolvedProjectId) {
          throw new UnifiedRuntimesUnavailableError(
            'unified_runtimes_sandbox_stats_scope_mismatch',
          );
        }
        return stats;
      } catch (error) {
        if (error instanceof DesktopApiError && error.status === 404) return null;
        throw error;
      }
    },
    async getLocalSidecar(scope, options) {
      requireAuthority(runtimeConfig, scope, 'local');
      const payload = await readLocalRuntimeStatus();
      if (options?.signal?.aborted) throw abortError();
      return parseLocalSidecar(payload);
    },
    async getSandboxCapabilities(scope, options) {
      requireAuthority(runtimeConfig, scope, 'local');
      const payload = await requestJson(
        runtimeConfig,
        `/api/v1/projects/${encodeURIComponent(scope.projectId)}/sandbox/capabilities`,
        fetchImpl,
        options?.signal,
      );
      return parseSandboxCapabilities(payload);
    },
  });
}

function poolScope(scope: UnifiedRuntimesScope) {
  return Object.freeze({
    authority: 'cloud' as const,
    tenantId: scope.tenantId,
  });
}

function requireAuthority(
  config: DesktopRuntimeConfig,
  scope: UnifiedRuntimesScope,
  expected: 'cloud' | 'local',
): void {
  if (config.mode !== expected || scope.authority !== expected) {
    throw new UnifiedRuntimesUnavailableError(
      expected === 'cloud'
        ? 'local_pool_not_applicable_sidecar_projection'
        : 'unified_runtimes_local_authority_unavailable',
    );
  }
  if (
    identifier(config.tenantId, 'unified_runtimes_tenant_scope_invalid') !==
      identifier(scope.tenantId, 'unified_runtimes_tenant_scope_invalid') ||
    (expected === 'local' &&
      identifier(config.projectId, 'unified_runtimes_project_scope_invalid') !==
        identifier(scope.projectId, 'unified_runtimes_project_scope_invalid'))
  ) {
    throw new UnifiedRuntimesUnavailableError(
      'unified_runtimes_runtime_scope_mismatch',
    );
  }
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  fetchImpl: Fetch,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await fetchImpl(absoluteUrl(config.apiBaseUrl, path), {
    method: 'GET',
    headers,
    signal,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

function parseSandboxList(payload: unknown): readonly UnifiedSandbox[] {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.sandboxes) ||
    !isNonnegativeInteger(payload.total)
  ) {
    throw contractError();
  }
  const sandboxes = payload.sandboxes.map(parseSandbox);
  if (sandboxes.length > payload.total) throw contractError();
  return Object.freeze(sandboxes);
}

function parseSandbox(value: unknown): UnifiedSandbox {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.sandbox_id) ||
    !isNonEmptyString(value.tenant_id) ||
    !isNonEmptyString(value.project_id) ||
    !isNonEmptyString(value.status) ||
    typeof value.is_healthy !== 'boolean' ||
    !isOptionalNullableString(value.created_at) ||
    !isOptionalNullableString(value.last_accessed_at)
  ) {
    throw contractError();
  }
  return Object.freeze({
    sandboxId: value.sandbox_id,
    tenantId: value.tenant_id,
    projectId: value.project_id,
    status: value.status,
    healthy: value.is_healthy,
    createdAt: value.created_at ?? null,
    lastAccessedAt: value.last_accessed_at ?? null,
  });
}

function parseSandboxStats(payload: unknown): UnifiedSandboxStats {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.project_id) ||
    !isNonEmptyString(payload.sandbox_id) ||
    !isNonEmptyString(payload.status) ||
    !isFiniteNonnegative(payload.memory_usage) ||
    !isNonnegativeInteger(payload.pids) ||
    !isNonEmptyString(payload.collected_at)
  ) {
    throw contractError();
  }
  return Object.freeze({
    projectId: payload.project_id,
    sandboxId: payload.sandbox_id,
    status: payload.status,
    memoryUsageBytes: payload.memory_usage,
    pids: payload.pids,
    collectedAt: payload.collected_at,
  });
}

function parseLocalSidecar(payload: unknown): UnifiedLocalSidecar {
  if (
    !isRecord(payload) ||
    typeof payload.running !== 'boolean' ||
    !isNonnegativeInteger(payload.tool_count) ||
    !Array.isArray(payload.runtime_providers)
  ) {
    throw contractError();
  }
  return Object.freeze({
    running: payload.running,
    toolCount: payload.tool_count,
    providerCount: payload.runtime_providers.length,
  });
}

function parseSandboxCapabilities(payload: unknown): UnifiedSandboxCapabilities {
  if (
    !isRecord(payload) ||
    !isNonEmptyString(payload.service_version) ||
    !(isNonEmptyString(payload.contract_version) ||
      isNonnegativeInteger(payload.contract_version))
  ) {
    throw contractError();
  }
  return Object.freeze({
    serviceVersion: payload.service_version,
    contractVersion: String(payload.contract_version),
    terminalInteractive: parseCapability(payload.terminal_interactive),
    terminalResume: parseCapability(payload.terminal_resume),
    files: parseCapability(payload.files),
    kasmVnc: parseCapability(payload.kasm_vnc),
  });
}

function parseCapability(value: unknown): UnifiedSandboxCapability {
  if (
    !isRecord(value) ||
    !isCapabilityAvailability(value.availability) ||
    !isNullableString(value.reason_code)
  ) {
    throw contractError();
  }
  return Object.freeze({
    availability: value.availability,
    reasonCode: value.reason_code,
  });
}

async function defaultLocalRuntimeStatusReader(): Promise<unknown> {
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  if (!invoke) {
    throw new UnifiedRuntimesUnavailableError(
      'unified_runtimes_native_bridge_unavailable',
    );
  }
  return invoke<unknown>('local_runtime_status');
}

function identifier(input: string, reasonCode: string): string {
  if (!input || input !== input.trim()) {
    throw new UnifiedRuntimesUnavailableError(reasonCode);
  }
  return input;
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload)) {
    if (typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail;
    }
    if (typeof payload.reason_code === 'string' && payload.reason_code.trim()) {
      return payload.reason_code;
    }
  }
  return `Request failed (${String(status)})`;
}

function contractError(): DesktopApiError {
  return new DesktopApiError('unified_runtimes_contract_invalid', 502, null);
}

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isOptionalNullableString(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || isNullableString(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isFiniteNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isCapabilityAvailability(
  value: unknown,
): value is UnifiedCapabilityAvailability {
  return (
    value === 'available' ||
    value === 'degraded' ||
    value === 'unavailable' ||
    value === 'not_applicable'
  );
}
