import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const SERVICE_VERSION = '0.1.0' as const;
const CONTRACT_VERSION = '4.0.0' as const;
const OBSERVED_ACTIONS = Object.freeze(['view', 'list-conversations']);

export type AgentWorkspaceAuthority = 'cloud' | 'local';

export type AgentWorkspaceAuthorityScope = Readonly<{
  authority: AgentWorkspaceAuthority;
  tenantId: string;
  projectId: string;
  workspaceId: string | null;
}>;

export type AgentWorkspaceAuthorityObservation = Readonly<{
  authority: AgentWorkspaceAuthority;
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  serviceVersion: typeof SERVICE_VERSION;
  contractVersion: typeof CONTRACT_VERSION;
  allowedActions: readonly string[];
  scope: AgentWorkspaceAuthorityScope;
  authorityRevision: number | null;
}>;

export interface AgentWorkspaceAuthorityClient {
  probe(signal?: AbortSignal): Promise<AgentWorkspaceAuthorityObservation>;
}

export function createAgentWorkspaceAuthorityClient(
  config: DesktopRuntimeConfig,
): AgentWorkspaceAuthorityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const credential = desktopApiCredential(runtimeConfig);
  const launchCapability = desktopLaunchCapability(runtimeConfig);
  const tenantId = identifier(runtimeConfig.tenantId);
  const projectId = identifier(runtimeConfig.projectId);
  if (!credential) throw contractError('agent_workspace_trusted_session_required');
  if (!tenantId || !projectId) {
    throw contractError('agent_workspace_scope_unavailable');
  }
  if (runtimeConfig.mode === 'local' && !launchCapability) {
    throw contractError('agent_workspace_launch_capability_required');
  }
  const scope = Object.freeze({
    authority: runtimeConfig.mode,
    tenantId,
    projectId,
    workspaceId: identifier(runtimeConfig.workspaceId),
  });
  return Object.freeze({
    async probe(signal?: AbortSignal) {
      const parameters = new URLSearchParams({
        project_id: projectId,
        status: 'active',
        limit: '1',
        offset: '0',
      });
      const headers = new Headers({
        Accept: 'application/json',
        Authorization: `Bearer ${credential}`,
      });
      if (runtimeConfig.mode === 'local') {
        headers.set('X-Agistack-Launch', launchCapability);
      }
      const response = await fetch(
        absoluteUrl(
          runtimeConfig.apiBaseUrl,
          `/api/v1/agent/conversations?${parameters.toString()}`,
        ),
        { method: 'GET', headers, credentials: 'omit', signal },
      );
      const payload = await responsePayload(response);
      if (!response.ok) {
        throw new DesktopApiError(
          `agent_workspace_authority_http_${response.status}`,
          response.status,
          payload,
        );
      }
      requireConversationPage(payload, scope);
      return Object.freeze({
        authority: runtimeConfig.mode,
        availability:
          runtimeConfig.mode === 'local' ? 'degraded' : 'available',
        reasonCode:
          runtimeConfig.mode === 'local'
            ? 'local_cloud_agent_authority_unavailable'
            : null,
        serviceVersion: SERVICE_VERSION,
        contractVersion: CONTRACT_VERSION,
        allowedActions: OBSERVED_ACTIONS,
        scope,
        authorityRevision: null,
      });
    },
  });
}

async function responsePayload(response: Response): Promise<unknown> {
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw contractError('agent_workspace_authority_response_too_large');
  }
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw contractError('agent_workspace_authority_response_too_large');
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw contractError('agent_workspace_authority_response_not_json');
  }
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    throw contractError('agent_workspace_authority_response_invalid_json');
  }
}

function requireConversationPage(
  input: unknown,
  scope: AgentWorkspaceAuthorityScope,
): void {
  if (
    !isRecord(input) ||
    !Array.isArray(input.items) ||
    !nonNegativeInteger(input.total) ||
    input.offset !== 0 ||
    input.limit !== 1 ||
    typeof input.has_more !== 'boolean' ||
    input.items.length > 1 ||
    input.items.length > input.total
  ) {
    throw contractError('agent_workspace_authority_contract_invalid');
  }
  const expectedHasMore = input.total > input.items.length;
  if (
    input.has_more !== expectedHasMore ||
    input.next_offset !== (expectedHasMore ? 1 : null)
  ) {
    throw contractError('agent_workspace_authority_contract_invalid');
  }
  for (const item of input.items) {
    if (
      !isRecord(item) ||
      !identifier(item.id) ||
      item.project_id !== scope.projectId ||
      (typeof item.tenant_id === 'string' && item.tenant_id !== scope.tenantId)
    ) {
      throw contractError('agent_workspace_authority_contract_invalid');
    }
  }
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === 'number' && value >= 0;
}

function identifier(value: unknown): string | null {
  return typeof value === 'string' && value.trim() === value && value.length > 0
    ? value
    : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
