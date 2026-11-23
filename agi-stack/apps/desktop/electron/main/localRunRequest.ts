import { isAbsolute } from 'node:path';

import { localRootBasename } from '../../src/features/chat/executionPlacementModel';

type LocalRunCommand = 'local_run_execute' | 'local_run_stop';

const commonKeys = ['user_id', 'tenant_id', 'conversation_id', 'device_id', 'idempotency_key'];
const executeKeys = new Set([
  ...commonKeys,
  'message',
  'local_root',
  'local_root_label',
  'execution_target',
]);
const stopKeys = new Set([...commonKeys, 'run_id', 'expected_revision']);

function pathId(value: unknown): value is string {
  return typeof value === 'string' && /^[a-zA-Z0-9_~-][a-zA-Z0-9._~-]{0,255}$/u.test(value);
}

/** The private pipe receives the cloud origin and bearer from Electron Main. */
export function parseLocalRunRequest(command: LocalRunCommand, value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('local run request is invalid');
  }
  const input = value as Record<string, unknown>;
  const allowed = command === 'local_run_execute' ? executeKeys : stopKeys;
  if (
    Object.keys(input).some((key) => !allowed.has(key)) ||
    commonKeys.some((key) => typeof input[key] !== 'string' || !input[key].trim()) ||
    !pathId(input.conversation_id)
  ) {
    throw new Error('local run request is invalid');
  }
  if (
    command === 'local_run_execute' &&
    (input.execution_target !== 'local' ||
      typeof input.message !== 'string' ||
      typeof input.local_root !== 'string' ||
      !isAbsolute(input.local_root) ||
      typeof input.local_root_label !== 'string' ||
      localRootBasename(input.local_root) !== input.local_root_label)
  ) {
    throw new Error('local run execution request is invalid');
  }
  if (
    command === 'local_run_stop' &&
    ((input.run_id != null && !pathId(input.run_id)) ||
      (input.expected_revision != null &&
        !(
          typeof input.expected_revision === 'number' &&
          Number.isSafeInteger(input.expected_revision) &&
          input.expected_revision >= 0
        )))
  ) {
    throw new Error('local run stop request is invalid');
  }
  return {
    args: input,
    conversationId: input.conversation_id,
    runId: command === 'local_run_stop' && typeof input.run_id === 'string' ? input.run_id : null,
  };
}
