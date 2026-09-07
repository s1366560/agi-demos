import type { DesktopRuntimeConfig } from '../types';
import { requestNativeRouteJson } from '../features/settings-routes/nativeRouteHttpClient';
import {
  freezeWorkspaceAgentPolicyConfigV2,
  prepareWorkspaceAgentPolicyV2,
  requireWorkspaceAgentPolicyV2,
  type DesktopWorkspaceAgentPolicyAuthorityV2,
  type WorkspaceAgentPolicyScopeV2,
} from './desktopWorkspaceAgentPolicyOperationContractV2';
export function createDesktopWorkspaceAgentPolicyHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceAgentPolicyAuthorityV2 {
  const frozen = freezeWorkspaceAgentPolicyConfigV2(config);
  const path = (scope: WorkspaceAgentPolicyScopeV2) => {
    prepareWorkspaceAgentPolicyV2({ config: frozen, scope });
    return `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/${encodeURIComponent(scope.projectId)}/workspaces/${encodeURIComponent(scope.workspaceId)}/agent-policy`;
  };
  const authority: DesktopWorkspaceAgentPolicyAuthorityV2 = {
    async load(scope, signal) {
      return requireWorkspaceAgentPolicyV2(
        await requestNativeRouteJson(frozen, path(scope), { signal }),
        scope,
      );
    },
    async update(scope, input, signal) {
      return requireWorkspaceAgentPolicyV2(
        await requestNativeRouteJson(frozen, path(scope), {
          method: 'PATCH',
          signal,
          body: {
            expected_revision: input.expected_revision,
            capability_mode: input.capabilityMode,
            route: input.route,
            reasoning_effort: input.reasoning_effort,
            permission_mode: input.permission_mode,
          },
        }),
        scope,
      );
    },
  };
  return Object.freeze(authority);
}
