import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';

const SERVICE_VERSION = '0.1.0';
const CONTRACT_VERSION = '3.0.0';
const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'inspect-stats',
  'inspect-message',
  'filter',
  'paginate',
  'refresh',
  'retry-message',
  'retry-batch',
  'discard',
  'cleanup',
]);

export function deadLetterQueueCapability(
  config: DesktopRuntimeConfig,
): DesktopCapabilityAvailability {
  const tenantId = scopeIdentifier(config.tenantId);
  const scope = capabilityScope(tenantId);
  if (!tenantId) {
    return Object.freeze({
      availability: 'unavailable',
      reason_code: 'dead_letter_queue_scope_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  if (config.mode === 'local') {
    return Object.freeze({
      availability: 'not_applicable',
      reason_code: 'cloud_message_bus_dlq_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope,
      authority_revision: null,
    });
  }
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions: CLOUD_ACTIONS,
    scope,
    authority_revision: null,
  });
}

function capabilityScope(tenantId: string | null): DesktopCapabilityScope {
  return Object.freeze({
    tenant_id: tenantId,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  });
}

function scopeIdentifier(input: string): string | null {
  return input.length > 0 && input === input.trim() ? input : null;
}
