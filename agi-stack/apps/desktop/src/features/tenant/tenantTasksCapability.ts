import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const TENANT_TASKS_SERVICE_VERSION = '0.1.0';
const TENANT_TASKS_CONTRACT_VERSION = '3.0.0';
const TENANT_TASKS_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'retry-task',
  'stop-task',
  'retry-pending',
]);
const TENANT_TASKS_LOCAL_ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'open-workspace',
]);

export function tenantTasksCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId =
    config.mode === 'local' ? scopeIdentifier(config.projectId) : null;
  const scope = tenantTasksCapabilityScope(tenantId, projectId);
  if (!tenantId || (config.mode === 'local' && !projectId)) {
    return unavailable(scope);
  }
  return {
    availability: 'degraded',
    reason_code:
      config.mode === 'local'
        ? 'local_task_dashboard_partial'
        : 'desktop_tenant_tasks_dlq_navigation_partial',
    service_version: TENANT_TASKS_SERVICE_VERSION,
    contract_version: TENANT_TASKS_CONTRACT_VERSION,
    allowed_actions:
      config.mode === 'local'
        ? TENANT_TASKS_LOCAL_ACTIONS
        : TENANT_TASKS_CLOUD_ACTIONS,
    scope,
    authority_revision: null,
  };
}

function unavailable(
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: 'tenant_tasks_scope_unavailable',
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope,
    authority_revision: null,
  };
}

function tenantTasksCapabilityScope(
  tenantId: string | null,
  projectId: string | null,
): DesktopCapabilityScope {
  return {
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: null,
    instance_id: null,
  };
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
