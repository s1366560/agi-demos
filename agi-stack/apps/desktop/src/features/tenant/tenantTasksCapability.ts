import { DesktopApiError } from '../../api/client';
import type { DesktopTenantTasksOperationsV2 } from '../../plugins/desktopTenantTasksAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'retry-task',
  'stop-task',
  'retry-pending',
  'navigate-dead-letter-queue',
]);
const LOCAL_ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'paginate',
  'refresh',
  'open-workspace',
]);

export async function loadTenantTasksCapability(
  config: DesktopRuntimeConfig,
  tenantTasksOperationsV2: Pick<DesktopTenantTasksOperationsV2, 'loadTenantTasks'>,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const projectId = config.mode === 'local' ? scopeIdentifier(config.projectId) : null;
  const scope = capabilityScope(tenantId, projectId);
  if (!tenantId || (config.mode === 'local' && !projectId)) {
    return unavailable('tenant_tasks_scope_unavailable', scope);
  }
  try {
    const operationScope =
      config.mode === 'cloud'
        ? ({ authority: 'cloud', tenantId, projectId: null } as const)
        : ({ authority: 'local', tenantId, projectId: projectId as string } as const);
    const snapshot = await tenantTasksOperationsV2.loadTenantTasks({
      config,
      scope: operationScope,
      query: { limit: 1, offset: 0 },
      ...(signal === undefined ? {} : { signal }),
    });
    const actionOrder = config.mode === 'cloud' ? CLOUD_ACTIONS : LOCAL_ACTIONS;
    if (!isOrderedActionSubset(snapshot.allowedActions, actionOrder)) {
      return unavailable('tenant_tasks_contract_invalid', scope);
    }
    return {
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version: config.mode === 'cloud' ? '0.1.0' : snapshot.serviceVersion,
      contract_version: snapshot.contractVersion,
      allowed_actions: snapshot.allowedActions,
      scope,
      authority_revision: snapshot.authorityRevision,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('tenant_tasks_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_tasks_contract_invalid', scope);
    }
    return unavailable('tenant_tasks_authority_unavailable', scope);
  }
}

function unavailable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope,
    authority_revision: null,
  };
}

function capabilityScope(
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

function isOrderedActionSubset(actions: readonly string[], order: readonly string[]): boolean {
  let lastIndex = -1;
  for (const action of actions) {
    const index = order.indexOf(action);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}
