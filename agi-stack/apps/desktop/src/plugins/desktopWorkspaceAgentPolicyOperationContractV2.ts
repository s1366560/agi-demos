import { RuntimeV2Error } from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  WorkspaceAgentPolicy,
  WorkspaceAgentPolicyMutationInput,
} from '../types';
import { normalizeLlmProviderRoutingPolicyV2 } from './desktopTenantProvidersResponseContractV2';
export type WorkspaceAgentPolicyScopeV2 = Readonly<{
  authority: 'cloud' | 'local';
  tenantId: string;
  projectId: string;
  workspaceId: string;
}>;
export type WorkspaceAgentPolicyInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: WorkspaceAgentPolicyScopeV2;
  signal?: AbortSignal;
}>;
export type WorkspaceAgentPolicyUpdateInputV2 = WorkspaceAgentPolicyInputV2 &
  Readonly<{ input: WorkspaceAgentPolicyMutationInput }>;
export interface DesktopWorkspaceAgentPolicyAuthorityV2 {
  load(scope: WorkspaceAgentPolicyScopeV2, signal?: AbortSignal): Promise<WorkspaceAgentPolicy>;
  update(
    scope: WorkspaceAgentPolicyScopeV2,
    input: WorkspaceAgentPolicyMutationInput,
    signal?: AbortSignal,
  ): Promise<WorkspaceAgentPolicy>;
}
const CONFIG_KEYS = [
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
];
export function policyErrorV2(code: string): RuntimeV2Error {
  return new RuntimeV2Error(code, code);
}
export function policyRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function identifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
export function freezeWorkspaceAgentPolicyConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !policyRecordV2(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => typeof config[key as keyof DesktopRuntimeConfig] !== 'string') ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  )
    throw policyErrorV2('workspace_agent_policy_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareWorkspaceAgentPolicyV2(
  input: WorkspaceAgentPolicyInputV2,
): WorkspaceAgentPolicyInputV2 {
  if (
    !policyRecordV2(input) ||
    !policyRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 4
  )
    throw policyErrorV2('workspace_agent_policy_scope_invalid');
  const config = freezeWorkspaceAgentPolicyConfigV2(input.config);
  const { authority, tenantId, projectId, workspaceId } = input.scope;
  if (
    authority !== config.mode ||
    !identifier(tenantId) ||
    tenantId !== config.tenantId ||
    !identifier(projectId) ||
    !identifier(workspaceId) ||
    (config.mode === 'local' &&
      (projectId !== config.projectId || workspaceId !== config.workspaceId))
  )
    throw policyErrorV2('workspace_agent_policy_scope_mismatch');
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw policyErrorV2('workspace_agent_policy_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  return Object.freeze({
    config,
    scope: Object.freeze({ authority, tenantId, projectId, workspaceId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
export function prepareWorkspaceAgentPolicyUpdateV2(
  input: WorkspaceAgentPolicyUpdateInputV2,
): WorkspaceAgentPolicyUpdateInputV2 {
  const common = prepareWorkspaceAgentPolicyV2(input);
  const value = input.input;
  if (
    !policyRecordV2(value) ||
    Object.keys(value).length !== 7 ||
    value.projectId !== common.scope.projectId ||
    value.workspaceId !== common.scope.workspaceId ||
    !Number.isSafeInteger(value.expected_revision) ||
    value.expected_revision < 0 ||
    !['work', 'code'].includes(value.capabilityMode) ||
    !['low', 'medium', 'high'].includes(value.reasoning_effort) ||
    !['ask', 'automatic', 'full_access'].includes(value.permission_mode) ||
    !policyRecordV2(value.route) ||
    Object.keys(value.route).length !== 2 ||
    !identifier(value.route.provider_id) ||
    !identifier(value.route.model_id)
  ) {
    throw policyErrorV2('workspace_agent_policy_update_invalid');
  }
  return Object.freeze({
    ...common,
    input: Object.freeze({ ...value, route: Object.freeze({ ...value.route }) }),
  });
}
export function requireWorkspaceAgentPolicyV2(
  value: unknown,
  scope: WorkspaceAgentPolicyScopeV2,
): WorkspaceAgentPolicy {
  const routing = normalizeLlmProviderRoutingPolicyV2(value);
  if (
    !policyRecordV2(value) ||
    routing.tenant_id !== scope.tenantId ||
    routing.project_id !== scope.projectId ||
    routing.workspace_id !== scope.workspaceId ||
    !['low', 'medium', 'high'].includes(String(value.reasoning_effort)) ||
    !['ask', 'automatic', 'full_access'].includes(String(value.permission_mode)) ||
    value.capability_version !== 'workspace-agent-policy-v1'
  ) {
    throw policyErrorV2('workspace_agent_policy_response_invalid');
  }
  return Object.freeze({
    ...routing,
    roles: Object.freeze(
      Object.fromEntries(
        Object.entries(routing.roles).map(([key, route]) => [
          key,
          route === null ? null : Object.freeze({ ...route }),
        ]),
      ),
    ) as WorkspaceAgentPolicy['roles'],
    fallbacks: Object.freeze(
      routing.fallbacks.map((route) => Object.freeze({ ...route })),
    ) as unknown as WorkspaceAgentPolicy['fallbacks'],
    reasoning_effort: value.reasoning_effort as WorkspaceAgentPolicy['reasoning_effort'],
    permission_mode: value.permission_mode as WorkspaceAgentPolicy['permission_mode'],
    capability_version: value.capability_version,
  });
}
