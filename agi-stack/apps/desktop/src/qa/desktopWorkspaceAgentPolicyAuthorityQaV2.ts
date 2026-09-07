import type { DesktopWorkspaceAgentPolicyOperationsV2 } from '../plugins/desktopWorkspaceAgentPolicyAuthorityModuleV2';
import { createDesktopWorkspaceAgentPolicyHttpProjectionV2 } from '../plugins/desktopWorkspaceAgentPolicyHttpProjectionV2';
import {
  prepareWorkspaceAgentPolicyV2,
  prepareWorkspaceAgentPolicyUpdateV2,
  requireWorkspaceAgentPolicyV2,
} from '../plugins/desktopWorkspaceAgentPolicyOperationContractV2';
// Standalone QA shares production transport/contracts but does not claim native generation lease evidence.
export function createDesktopWorkspaceAgentPolicyQaOperationsV2(): DesktopWorkspaceAgentPolicyOperationsV2 {
  const operations: DesktopWorkspaceAgentPolicyOperationsV2 = {
    async loadWorkspaceAgentPolicy(input) {
      const prepared = prepareWorkspaceAgentPolicyV2(input);
      return requireWorkspaceAgentPolicyV2(
        await createDesktopWorkspaceAgentPolicyHttpProjectionV2(prepared.config).load(
          prepared.scope,
          prepared.signal,
        ),
        prepared.scope,
      );
    },
    async updateWorkspaceAgentPolicy(input) {
      const prepared = prepareWorkspaceAgentPolicyUpdateV2(input);
      return requireWorkspaceAgentPolicyV2(
        await createDesktopWorkspaceAgentPolicyHttpProjectionV2(prepared.config).update(
          prepared.scope,
          prepared.input,
          prepared.signal,
        ),
        prepared.scope,
      );
    },
  };
  return Object.freeze(operations);
}
