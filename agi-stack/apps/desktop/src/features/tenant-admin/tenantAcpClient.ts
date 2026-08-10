import type { DesktopRuntimeConfig } from '../../types';
import {
  optionalText,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestTenantManagementJson,
  requestTenantManagementNoContent,
  requireBoolean,
  requireRecord,
  requireRole,
  requireStringArray,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_ACP_ROUTE_ID = 'tenant-tenant-acp' as const;
export const TENANT_ACP_LOCAL_REASON = 'local_external_acp_not_applicable' as const;

export type TenantAcpTransport = 'stdio' | 'websocket';
export type TenantAcpAgent = Readonly<{
  id: string;
  agentKey: string;
  name: string;
  transport: TenantAcpTransport;
  command: string | null;
  url: string | null;
  enabled: boolean;
  available: boolean;
  missingEnv: readonly string[];
}>;
export type TenantAcpRunnerPool = Readonly<{
  id: string;
  poolKey: string;
  name: string;
  enabled: boolean;
  runnerCount: number;
  readyRunnerCount: number;
}>;
export type TenantAcpStatus = Readonly<{
  enabled: boolean;
  websocketEnabled: boolean;
  httpBaseUrl: string;
  agentCount: number;
  availableCount: number;
  activeSessionCount: number;
  agents: readonly TenantAcpAgent[];
  sessions: readonly Readonly<Record<string, unknown>>[];
}>;
export type TenantAcpAgentInput = Readonly<{
  agentKey?: string;
  name: string;
  transport: TenantAcpTransport;
  command?: string | null;
  args?: readonly string[];
  url?: string | null;
  env?: Readonly<Record<string, unknown>>;
  headers?: Readonly<Record<string, unknown>>;
  runnerPoolKey?: string | null;
  requiredLabels?: Readonly<Record<string, string>>;
  cwdPolicy?: Readonly<Record<string, unknown>>;
  enabled?: boolean;
}>;
export type TenantAcpTestInput = Readonly<{
  cwd: string;
  projectId?: string;
  prompt: string;
  timeoutSeconds?: number;
}>;
export type TenantAcpData = Readonly<{
  membershipRole: TenantAdminRole;
  status: TenantAcpStatus;
  runnerPools: readonly TenantAcpRunnerPool[];
}>;
export type TenantAcpSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantAcpData
> &
  TenantAcpData;
export type TenantAcpClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantAcpSnapshot>;
  createAgent: (
    scope: TenantManagementScope,
    input: TenantAcpAgentInput & Readonly<{ agentKey: string }>,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantAcpAgent>;
  updateAgent: (
    scope: TenantManagementScope,
    agentKey: string,
    input: TenantAcpAgentInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantAcpAgent>;
  deleteAgent: (
    scope: TenantManagementScope,
    agentKey: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
  testAgent: (
    scope: TenantManagementScope,
    agentKey: string,
    input: TenantAcpTestInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
}>;

const MEMBER_ACTIONS = Object.freeze([
  'view',
  'view-status',
  'list-runner-pools',
  'list-agents',
  'list-sessions',
]);
const ADMIN_ACTIONS = Object.freeze([
  ...MEMBER_ACTIONS,
  'create-agent',
  'update-agent',
  'delete-agent',
  'test-agent',
]);

export function createTenantAcpClient(config: DesktopRuntimeConfig): TenantAcpClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(runtimeConfig, scope, 'cloud_only', TENANT_ACP_LOCAL_REASON);
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () =>
          Promise.all([
            requestTenantManagementJson(runtimeConfig, `${root(currentScope)}/status`, options),
            requestTenantManagementJson(
              runtimeConfig,
              `${root(currentScope)}/runner-pools`,
              options,
            ),
          ]),
      );
      const [statusPayload, poolPayload] = observation.value;
      const membershipRole = observation.membershipRole;
      const data = Object.freeze({
        membershipRole,
        status: parseStatus(statusPayload),
        runnerPools: parseRunnerPools(poolPayload),
      });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions:
          membershipRole === 'owner' || membershipRole === 'admin'
            ? ADMIN_ACTIONS
            : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async createAgent(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${root(currentScope)}/external-agents`,
        { ...options, method: 'POST', body: agentBody(input, true) },
      );
      return parseAgent(payload);
    },
    async updateAgent(scope, agentKey, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${root(currentScope)}/external-agents/${encodeURIComponent(
          requireIdentifier(agentKey, 'tenant_acp_agent_key_required'),
        )}`,
        { ...options, method: 'PUT', body: agentBody(input, false) },
      );
      return parseAgent(payload);
    },
    async deleteAgent(scope, agentKey, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await requestTenantManagementNoContent(
        runtimeConfig,
        `${root(currentScope)}/external-agents/${encodeURIComponent(
          requireIdentifier(agentKey, 'tenant_acp_agent_key_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
    async testAgent(scope, agentKey, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await requestTenantManagementJson(
        runtimeConfig,
        `${root(currentScope)}/external-agents/${encodeURIComponent(
          requireIdentifier(agentKey, 'tenant_acp_agent_key_required'),
        )}/test`,
        {
          ...options,
          method: 'POST',
          body: {
            cwd: requireIdentifier(input.cwd, 'tenant_acp_test_cwd_required'),
            projectId: input.projectId,
            prompt: requireIdentifier(input.prompt, 'tenant_acp_test_prompt_required'),
            timeoutSeconds: input.timeoutSeconds ?? 30,
          },
        },
      );
      return requireRecord(payload, 'tenant_acp_test_contract_invalid');
    },
  });
}

async function requireAdmin(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  const role = await observeTenantManagementRole(config, scope, options);
  requireRole(role, ['owner', 'admin'], 'tenant_acp_mutation_forbidden');
}

function root(scope: TenantManagementScope): string {
  return `/api/v1/acp/tenants/${encodeURIComponent(scope.tenantId)}`;
}

function agentBody(input: TenantAcpAgentInput, includeKey: boolean): Readonly<Record<string, unknown>> {
  const transport = requireTransport(input.transport);
  return Object.freeze({
    ...(includeKey
      ? { agentKey: requireIdentifier(input.agentKey, 'tenant_acp_agent_key_required') }
      : {}),
    name: requireIdentifier(input.name, 'tenant_acp_agent_name_required'),
    transport,
    command: input.command ?? null,
    args: Object.freeze([...(input.args ?? [])]),
    url: input.url ?? null,
    env: Object.freeze({ ...(input.env ?? {}) }),
    headers: Object.freeze({ ...(input.headers ?? {}) }),
    runnerPoolKey: input.runnerPoolKey ?? null,
    requiredLabels: Object.freeze({ ...(input.requiredLabels ?? {}) }),
    cwdPolicy: Object.freeze({ ...(input.cwdPolicy ?? {}) }),
    enabled: input.enabled ?? true,
  });
}

function parseStatus(value: unknown): TenantAcpStatus {
  if (!isRecord(value) || !Array.isArray(value.agents) || !Array.isArray(value.sessions)) {
    throw tenantAdminError('tenant_acp_status_contract_invalid');
  }
  return Object.freeze({
    enabled: requireBoolean(value.enabled, 'tenant_acp_status_contract_invalid'),
    websocketEnabled: requireBoolean(
      value.websocketEnabled,
      'tenant_acp_status_contract_invalid',
    ),
    httpBaseUrl: requireText(value.httpBaseUrl, 'tenant_acp_status_contract_invalid'),
    agentCount: requireNonnegativeInteger(value.agentCount, 'tenant_acp_status_contract_invalid'),
    availableCount: requireNonnegativeInteger(
      value.availableCount,
      'tenant_acp_status_contract_invalid',
    ),
    activeSessionCount: requireNonnegativeInteger(
      value.activeSessionCount,
      'tenant_acp_status_contract_invalid',
    ),
    agents: Object.freeze(value.agents.map(parseAgent)),
    sessions: Object.freeze(
      value.sessions.map((session) => requireRecord(session, 'tenant_acp_session_contract_invalid')),
    ),
  });
}

function parseAgent(value: unknown): TenantAcpAgent {
  if (!isRecord(value)) throw tenantAdminError('tenant_acp_agent_contract_invalid');
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_acp_agent_contract_invalid'),
    agentKey: requireIdentifier(value.agentKey, 'tenant_acp_agent_contract_invalid'),
    name: requireText(value.name, 'tenant_acp_agent_contract_invalid'),
    transport: requireTransport(value.transport),
    command: optionalText(value.command, 'tenant_acp_agent_contract_invalid'),
    url: optionalText(value.url, 'tenant_acp_agent_contract_invalid'),
    enabled: requireBoolean(value.enabled, 'tenant_acp_agent_contract_invalid'),
    available: requireBoolean(value.available, 'tenant_acp_agent_contract_invalid'),
    missingEnv: requireStringArray(value.missingEnv, 'tenant_acp_agent_contract_invalid'),
  });
}

function parseRunnerPools(value: unknown): readonly TenantAcpRunnerPool[] {
  if (!Array.isArray(value)) throw tenantAdminError('tenant_acp_runner_pools_contract_invalid');
  return Object.freeze(
    value.map((pool) => {
      if (!isRecord(pool)) throw tenantAdminError('tenant_acp_runner_pool_contract_invalid');
      return Object.freeze({
        id: requireIdentifier(pool.id, 'tenant_acp_runner_pool_contract_invalid'),
        poolKey: requireIdentifier(pool.poolKey, 'tenant_acp_runner_pool_contract_invalid'),
        name: requireText(pool.name, 'tenant_acp_runner_pool_contract_invalid'),
        enabled: requireBoolean(pool.enabled, 'tenant_acp_runner_pool_contract_invalid'),
        runnerCount: requireNonnegativeInteger(
          pool.runnerCount,
          'tenant_acp_runner_pool_contract_invalid',
        ),
        readyRunnerCount: requireNonnegativeInteger(
          pool.readyRunnerCount,
          'tenant_acp_runner_pool_contract_invalid',
        ),
      });
    }),
  );
}

function requireTransport(value: unknown): TenantAcpTransport {
  if (value !== 'stdio' && value !== 'websocket') {
    throw tenantAdminError('tenant_acp_transport_invalid', 422);
  }
  return value;
}
