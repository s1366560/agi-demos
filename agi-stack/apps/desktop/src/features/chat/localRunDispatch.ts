/**
 * Hand a local composer send to the sidecar. The absolute directory is an
 * execution argument. The cloud payload carries only the basename label.
 */

import type { LocalExecutionWire } from './executionPlacementModel';

export type LocalRunSync = 'synced' | 'pending' | 'failed' | 'conflict';

export type LocalRunDispatchInput = {
  apiBaseUrl: string;
  apiKey: string;
  userId: string;
  tenantId: string;
  conversationId: string;
  message: string;
  idempotencyKey: string;
  wire: LocalExecutionWire;
  localRoot: string;
};

export type LocalRunDispatchReport = {
  sync: LocalRunSync;
  runId: string | null;
  status: string;
  lateTerminal: boolean;
  executed: boolean;
  detail: string;
};

type Invoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

const DETAILS: Record<LocalRunSync, string> = {
  synced: 'The local run record is on the cloud.',
  pending: 'This computer is executing the run. The cloud record is not synced yet.',
  failed: 'Local execution did not finish uploading. Nothing was marked synced.',
  conflict: 'The cloud rejected a conflicting execution record. The run stopped.',
};

export function localRunCloudFields(input: LocalRunDispatchInput): Record<string, unknown> {
  return {
    user_id: input.userId.trim(),
    tenant_id: input.tenantId.trim(),
    device_id: input.wire.execution_machine_id,
    conversation_id: input.conversationId.trim(),
    idempotency_key: input.idempotencyKey.trim(),
    message: input.message,
    local_root_label: input.wire.local_root_label,
    api_base_url: input.apiBaseUrl.trim(),
    authorization: `Bearer ${input.apiKey.trim()}`,
    execution_target: 'local',
  };
}

export async function dispatchDesktopLocalRun(
  input: LocalRunDispatchInput,
  invoke: Invoke,
): Promise<LocalRunDispatchReport> {
  if (!input.apiKey.trim() || !input.apiBaseUrl.trim() || !input.userId.trim()) {
    return report('failed', null, 'failed', false, false);
  }
  const cloud = localRunCloudFields(input);
  if (JSON.stringify(cloud).includes(input.localRoot)) {
    return report('failed', null, 'failed', false, false);
  }
  try {
    const raw = await invoke('local_run_execute', {
      ...cloud,
      local_root: input.localRoot,
    });
    return normalizeReport(raw);
  } catch {
    return report('failed', null, 'failed', false, false);
  }
}

function normalizeReport(raw: unknown): LocalRunDispatchReport {
  if (!raw || typeof raw !== 'object') return report('failed', null, 'failed', false, false);
  const record = raw as Record<string, unknown>;
  const sync = record.sync;
  if (sync !== 'synced' && sync !== 'pending' && sync !== 'failed' && sync !== 'conflict') {
    return report('failed', null, 'failed', false, false);
  }
  const runId = typeof record.run_id === 'string' ? record.run_id : null;
  const status = typeof record.status === 'string' ? record.status : sync;
  const lateTerminal = record.late_terminal === true;
  const executed = record.executed === true;
  const detail = typeof record.detail === 'string' && record.detail.trim() ? record.detail : DETAILS[sync];
  if (sync !== 'synced' && detail.toLowerCase().includes('synced') && !detail.toLowerCase().includes('not synced')) {
    return report(sync, runId, status, lateTerminal, executed);
  }
  return {
    sync,
    runId,
    status,
    lateTerminal,
    executed,
    detail,
  };
}

function report(
  sync: LocalRunSync,
  runId: string | null,
  status: string,
  lateTerminal: boolean,
  executed: boolean,
): LocalRunDispatchReport {
  return {
    sync,
    runId,
    status,
    lateTerminal,
    executed,
    detail: DETAILS[sync],
  };
}
