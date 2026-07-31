import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import { createTenantProjectsHttpClient } from './tenantProjectsHttpClient';

const TENANT_PROJECT_ACTIONS = Object.freeze([
  'view',
  'list',
  'create',
  'update',
  'delete',
]);

export async function loadTenantProjectsCapability(
  config: DesktopRuntimeConfig,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = tenantCapabilityScope(tenantId);
  if (!tenantId) return unavailable('tenant_projects_scope_unavailable', scope);
  try {
    const authority = config.mode === 'local' ? 'local' : 'cloud';
    const snapshot = await createTenantProjectsHttpClient(config).list(
      { authority, tenantId },
      { page: 1, pageSize: 1 },
      { signal },
    );
    if (!isOrderedActionSubset(snapshot.allowedActions)) {
      return unavailable('tenant_projects_contract_invalid', scope);
    }
    return {
      availability: snapshot.availability,
      reason_code: snapshot.reasonCode,
      service_version: snapshot.serviceVersion,
      contract_version: snapshot.contractVersion,
      allowed_actions: snapshot.allowedActions,
      scope,
      authority_revision: snapshot.authorityRevision,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof DesktopApiError && error.status === 403) {
      return unavailable('tenant_projects_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_projects_contract_invalid', scope);
    }
    return unavailable('tenant_projects_authority_unavailable', scope);
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

function tenantCapabilityScope(
  tenantId: string | null,
): DesktopCapabilityScope {
  return {
    tenant_id: tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}

function isOrderedActionSubset(actions: readonly string[]): boolean {
  let lastIndex = -1;
  for (const action of actions) {
    const index = TENANT_PROJECT_ACTIONS.indexOf(action);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}
