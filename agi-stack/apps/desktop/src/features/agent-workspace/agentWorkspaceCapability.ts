import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const SERVICE_VERSION = '0.1.0';
const CONTRACT_VERSION = '3.0.0';
const LOCAL_WORKFLOW_ACTIONS = Object.freeze([
  'view',
  'switch-project',
  'switch-workspace',
  'create-session',
  'send-message',
  'respond-hitl',
  'attach-file',
  'review-plan',
  'manage-roster',
  'manage-subagents',
]);
const CLOUD_AUTHORITY_ACTIONS = Object.freeze([
  'queue-message',
  'steer-message',
  'review-usage',
  'review-changes',
  'open-activity',
  'open-my-work',
]);
const CLOUD_WORKFLOW_ACTIONS = Object.freeze([
  ...LOCAL_WORKFLOW_ACTIONS.slice(0, 5),
  ...CLOUD_AUTHORITY_ACTIONS.slice(0, 2),
  ...LOCAL_WORKFLOW_ACTIONS.slice(5, 8),
  ...CLOUD_AUTHORITY_ACTIONS.slice(2),
  ...LOCAL_WORKFLOW_ACTIONS.slice(8),
]);

export function agentWorkspaceCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const scope = capabilityScope(config);
  if (scope.tenant_id === null) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'agent_workspace_scope_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: config.mode === 'local' ? 'degraded' : 'available',
    reason_code:
      config.mode === 'local'
        ? 'local_cloud_agent_authority_unavailable'
        : null,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions:
      config.mode === 'local' ? LOCAL_WORKFLOW_ACTIONS : CLOUD_WORKFLOW_ACTIONS,
    scope,
    authority_revision: null,
  });
}

function capabilityScope(config: DesktopRuntimeConfig): DesktopCapabilityScope {
  return Object.freeze({
    tenant_id: identifier(config.tenantId),
    project_id: identifier(config.projectId),
    workspace_id: identifier(config.workspaceId),
    instance_id: null,
  });
}

function identifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
