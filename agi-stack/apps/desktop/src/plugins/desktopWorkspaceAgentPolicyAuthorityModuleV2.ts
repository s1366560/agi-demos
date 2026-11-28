import {
  PLUGIN_MODULE_CATALOG_V2,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  WorkspaceAgentPolicy,
  WorkspaceAgentPolicyMutationInput,
} from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopWorkspaceAgentPolicyHttpProjectionV2 } from './desktopWorkspaceAgentPolicyHttpProjectionV2';
import {
  freezeWorkspaceAgentPolicyConfigV2,
  prepareWorkspaceAgentPolicyV2,
  prepareWorkspaceAgentPolicyUpdateV2,
  requireWorkspaceAgentPolicyV2,
  policyErrorV2,
  policyRecordV2,
  type DesktopWorkspaceAgentPolicyAuthorityV2,
  type WorkspaceAgentPolicyInputV2,
  type WorkspaceAgentPolicyUpdateInputV2,
} from './desktopWorkspaceAgentPolicyOperationContractV2';
export const DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/workspace-agent-policy-authority';
export const DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.workspace-agent-policy-authority';
export const DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopWorkspaceAgentPolicyAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopWorkspaceAgentPolicyAuthorityV2;
}
export interface DesktopWorkspaceAgentPolicyOperationsV2 {
  loadWorkspaceAgentPolicy(input: WorkspaceAgentPolicyInputV2): Promise<WorkspaceAgentPolicy>;
  updateWorkspaceAgentPolicy(
    input: WorkspaceAgentPolicyUpdateInputV2,
  ): Promise<WorkspaceAgentPolicy>;
}
export interface DesktopWorkspaceAgentPolicyClientV2 {
  getWorkspaceAgentPolicy(
    projectId: string,
    workspaceId: string,
    signal?: AbortSignal,
  ): Promise<WorkspaceAgentPolicy>;
  updateWorkspaceAgentPolicy(
    input: WorkspaceAgentPolicyMutationInput,
    signal?: AbortSignal,
  ): Promise<WorkspaceAgentPolicy>;
}
export function applyDesktopWorkspaceAgentPolicyAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw policyErrorV2('workspace_agent_policy_module_config_invalid');
  context.provide(
    DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopWorkspaceAgentPolicyHttpProjectionV2 }),
  );
}
export const desktopWorkspaceAgentPolicyAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopWorkspaceAgentPolicyAuthorityV2,
});
export function createDesktopWorkspaceAgentPolicyOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopWorkspaceAgentPolicyOperationsV2 {
  return Object.freeze({
    loadWorkspaceAgentPolicy(input: WorkspaceAgentPolicyInputV2) {
      const p = prepareWorkspaceAgentPolicyV2(input);
      return run(resolve, p, async (a) =>
        requireWorkspaceAgentPolicyV2(await a.load(p.scope, p.signal), p.scope),
      );
    },
    updateWorkspaceAgentPolicy(input: WorkspaceAgentPolicyUpdateInputV2) {
      const p = prepareWorkspaceAgentPolicyUpdateV2(input);
      return run(resolve, p, async (a) =>
        requireWorkspaceAgentPolicyV2(await a.update(p.scope, p.input, p.signal), p.scope),
      );
    },
  });
}
export function createDesktopWorkspaceAgentPolicyClientV2(
  operations: DesktopWorkspaceAgentPolicyOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopWorkspaceAgentPolicyClientV2 {
  const frozen = freezeWorkspaceAgentPolicyConfigV2(config);
  const common = (
    projectId: string,
    workspaceId: string,
    signal?: AbortSignal,
  ): WorkspaceAgentPolicyInputV2 => ({
    config: frozen,
    scope: { authority: frozen.mode, tenantId: frozen.tenantId, projectId, workspaceId },
    ...(signal === undefined ? {} : { signal }),
  });
  const client: DesktopWorkspaceAgentPolicyClientV2 = {
    getWorkspaceAgentPolicy: (projectId, workspaceId, signal) =>
      operations.loadWorkspaceAgentPolicy(common(projectId, workspaceId, signal)),
    updateWorkspaceAgentPolicy: (input, signal) =>
      operations.updateWorkspaceAgentPolicy({
        ...common(input.projectId, input.workspaceId, signal),
        input,
      }),
  };
  return Object.freeze(client);
}
async function run(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  input: WorkspaceAgentPolicyInputV2,
  operation: (authority: DesktopWorkspaceAgentPolicyAuthorityV2) => Promise<WorkspaceAgentPolicy>,
): Promise<WorkspaceAgentPolicy> {
  const actions = resolve();
  if (!actions) throw policyErrorV2('desktop_renderer_generation_actions_unavailable');
  const admission =
    await actions.acquireServiceOperationLease<DesktopWorkspaceAgentPolicyAuthorityServiceV2>({
      service: DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
      scope: Object.freeze({
        kind: 'project',
        tenant_id: input.scope.tenantId,
        project_id: input.scope.projectId,
      }),
    });
  if (admission.status === 'rejected') throw policyErrorV2(admission.reasonCode);
  let active = true;
  let failed = false;
  const assertActive = () => {
    if (!active) throw policyErrorV2('workspace_agent_policy_operation_released');
    if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  };
  try {
    return await admission.useService(async (service) => {
      assertActive();
      if (
        !policyRecordV2(service) ||
        Object.keys(service).length !== 1 ||
        typeof service.bindOperation !== 'function'
      )
        throw policyErrorV2('workspace_agent_policy_service_invalid');
      const raw = service.bindOperation(input.config);
      if (
        !policyRecordV2(raw) ||
        Object.keys(raw).length !== 2 ||
        typeof raw.load !== 'function' ||
        typeof raw.update !== 'function'
      )
        throw policyErrorV2('workspace_agent_policy_service_invalid');
      const authority: DesktopWorkspaceAgentPolicyAuthorityV2 = {
        load(...args) {
          assertActive();
          return raw.load(...args);
        },
        update(...args) {
          assertActive();
          return raw.update(...args);
        },
      };
      const result = await operation(Object.freeze(authority));
      assertActive();
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_WORKSPACE_AGENT_POLICY_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) throw policyErrorV2('workspace_agent_policy_catalog_missing');
  return entry.contract_digest;
}
