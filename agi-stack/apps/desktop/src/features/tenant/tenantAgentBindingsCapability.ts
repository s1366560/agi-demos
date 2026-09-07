import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopTenantAgentBindingsOperationsV2 } from '../../plugins/desktopTenantAgentBindingsAuthorityModuleV2';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import type { TenantAgentBindingsAction } from './tenantAgentBindingsClient';

const ACTION_ORDER = Object.freeze<TenantAgentBindingsAction[]>([
  'view',
  'list',
  'create',
  'delete',
  'set-enabled',
  'test',
]);

export async function loadTenantAgentBindingsCapability(
  config: DesktopRuntimeConfig,
  tenantAgentBindingsOperationsV2: Pick<
    DesktopTenantAgentBindingsOperationsV2,
    'listTenantAgentBindings'
  >,
  signal?: AbortSignal,
): Promise<DesktopCapabilityAvailability> {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = tenantCapabilityScope(tenantId);
  if (!tenantId) {
    return unavailable('tenant_agent_bindings_scope_unavailable', scope);
  }
  try {
    const snapshot = await tenantAgentBindingsOperationsV2.listTenantAgentBindings({
      config,
      scope: { authority: config.mode, tenantId },
      ...(signal === undefined ? {} : { signal }),
    });
    if (!isOrderedActionSubset(snapshot.allowedActions)) {
      return unavailable('tenant_agent_bindings_contract_invalid', scope);
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
      return unavailable('tenant_agent_bindings_forbidden', scope);
    }
    if (error instanceof DesktopApiError && error.status === 0) {
      return unavailable('tenant_agent_bindings_contract_invalid', scope);
    }
    return unavailable('tenant_agent_bindings_authority_unavailable', scope);
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

function scopeIdentifier(value: string): string | null {
  return value.length > 0 && value === value.trim() ? value : null;
}

function isOrderedActionSubset(
  actions: readonly TenantAgentBindingsAction[],
): boolean {
  let lastIndex = -1;
  for (const action of actions) {
    const index = ACTION_ORDER.indexOf(action);
    if (index <= lastIndex) return false;
    lastIndex = index;
  }
  return true;
}
