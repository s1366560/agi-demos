import { DesktopApiError } from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type { SubAgentControlCommand, SubAgentControlReceipt } from '../../hooks/useAgentSocket';
import type { SubAgentControlAuthority } from './subagentControlAuthorityModel';

export type CloudChildControl = Readonly<{
  runId: string;
  controlRevision: number;
  status: string;
  allowedActions: readonly ('steer' | 'kill_run')[];
}>;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function decodeCloudChildAuthority(
  payload: unknown, config: DesktopRuntimeConfig, conversationId: string,
): SubAgentControlAuthority {
  if (!record(payload) || payload.schema_version !== 1 ||
      payload.authority_kind !== 'subagent_execution_registry' ||
      payload.tenant_id !== config.tenantId || payload.project_id !== config.projectId ||
      payload.conversation_id !== conversationId || !Array.isArray(payload.controls)) {
    throw new Error('cloud_child_control_scope_invalid');
  }
  const seen = new Set<string>();
  const cloudControls = payload.controls.map((row): CloudChildControl => {
    if (!record(row) || row.conversation_id !== conversationId ||
        typeof row.run_id !== 'string' || !row.run_id.trim() || seen.has(row.run_id) ||
        typeof row.control_revision !== 'number' || !Number.isSafeInteger(row.control_revision) || row.control_revision < 0 ||
        typeof row.status !== 'string' || !['pending', 'running', 'completed', 'failed', 'cancelled', 'timed_out'].includes(row.status) ||
        typeof row.cancel_requested !== 'boolean' || !Array.isArray(row.allowed_actions) ||
        row.allowed_actions.some((action) => !['steer', 'kill_run'].includes(action)) ||
        new Set(row.allowed_actions).size !== row.allowed_actions.length ||
        (row.allowed_actions.length > 0 && (row.cancel_requested || !['pending', 'running'].includes(row.status))) ||
        (row.allowed_actions.includes('steer') && row.status !== 'running')) {
      throw new Error('cloud_child_control_contract_invalid');
    }
    seen.add(row.run_id);
    return { runId: row.run_id, controlRevision: row.control_revision, status: row.status,
      allowedActions: row.allowed_actions as ('steer' | 'kill_run')[] };
  });
  return { availability: 'available', reasonCode: null, authorityRevision: null,
    conversationId, participantAgentIds: [], allowedActions: [], cloudControls };
}

function query(config: DesktopRuntimeConfig): string {
  return new URLSearchParams({ tenant_id: config.tenantId, project_id: config.projectId }).toString();
}

async function json(config: DesktopRuntimeConfig, path: string, init: RequestInit): Promise<unknown> {
  const headers = new Headers(init.headers);
  if (config.apiKey.trim()) headers.set('Authorization', `Bearer ${config.apiKey.trim()}`);
  const response = await desktopApiFetch(config, path, { ...init, credentials: 'omit', headers });
  const payload: unknown = await response.json();
  if (!response.ok) throw new DesktopApiError('cloud_child_control_request_failed', response.status, payload);
  return payload;
}

export async function loadCloudChildAuthority(config: DesktopRuntimeConfig, conversationId: string, signal?: AbortSignal): Promise<SubAgentControlAuthority> {
  if (config.mode !== 'cloud') throw new Error('cloud_child_control_mode_invalid');
  const payload = await json(config, `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/subagent-controls?${query(config)}`, { signal });
  return decodeCloudChildAuthority(payload, config, conversationId);
}

export async function sendCloudChildControl(config: DesktopRuntimeConfig, command: SubAgentControlCommand): Promise<SubAgentControlReceipt> {
  const rejected = (reasonCode: string): SubAgentControlReceipt => ({ action: command.action, accepted: false, duplicate: false,
    reasonCode, conversationId: command.conversationId, projectId: config.projectId, runId: command.runId,
    runRevision: null, idempotencyKey: command.idempotencyKey, cascade: false });
  if (config.mode !== 'cloud' || command.expectedRunRevision !== null ||
      !Number.isSafeInteger(command.expectedControlRevision) || Number(command.expectedControlRevision) < 0 ||
      !command.conversationId || !command.runId || command.cascade === true) return rejected('cloud_child_control_contract_invalid');
  try {
    const payload = await json(config, `/api/v1/agent/conversations/${encodeURIComponent(command.conversationId)}/subagents/${encodeURIComponent(command.runId)}/control?${query(config)}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action: command.action,
        expected_control_revision: command.expectedControlRevision, idempotency_key: command.idempotencyKey,
        ...(command.action === 'steer' ? { instruction: command.instruction } : {}) }),
    });
    if (!record(payload) || payload.accepted !== true || typeof payload.duplicate !== 'boolean' ||
        payload.action !== command.action || payload.conversation_id !== command.conversationId ||
        payload.run_id !== command.runId || payload.idempotency_key !== command.idempotencyKey ||
        payload.control_revision !== Number(command.expectedControlRevision) + 1) return rejected('cloud_child_control_receipt_invalid');
    return { ...rejected(''), accepted: true, duplicate: payload.duplicate, reasonCode: null };
  } catch (error) {
    return rejected(error instanceof DesktopApiError ? `cloud_child_control_http_${error.status}` : 'cloud_child_control_request_failed');
  }
}
