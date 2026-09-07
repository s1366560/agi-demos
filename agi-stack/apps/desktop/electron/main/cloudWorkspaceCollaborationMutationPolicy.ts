import { WORKSPACE_HTTP_MUTATION_ACTIONS } from '../../src/features/workspace/workspaceCollaborationHttpMutations';

const ENVELOPE_KEYS = new Set([
  'contract_version', 'surface', 'action', 'expected_revision', 'idempotency_key', 'payload',
]);
const PAYLOAD_RESERVED_KEYS = new Set([
  '__proto__', 'constructor', 'prototype', 'tenant_id', 'project_id', 'workspace_id',
  'expected_revision', 'idempotency_key',
]);

export function authorizeWorkspaceCollaborationMutation(
  body: Readonly<Record<string, unknown>> | undefined,
  mutation: unknown,
): boolean {
  if (!body || Object.keys(body).length !== ENVELOPE_KEYS.size ||
      Object.keys(body).some((key) => !ENVELOPE_KEYS.has(key)) ||
      body.contract_version !== '2.0.0' || typeof body.surface !== 'string' ||
      !Object.hasOwn(WORKSPACE_HTTP_MUTATION_ACTIONS, body.surface) ||
      typeof body.action !== 'string') return false;
  const actions: readonly string[] = Reflect.get(WORKSPACE_HTTP_MUTATION_ACTIONS, body.surface);
  if (!actions.includes(body.action) ||
      !Number.isSafeInteger(body.expected_revision) || Number(body.expected_revision) < 0 ||
      typeof body.idempotency_key !== 'string' || body.idempotency_key.length < 8 ||
      body.idempotency_key.length > 256 || body.idempotency_key !== body.idempotency_key.trim() ||
      !isRecord(body.payload) || Object.keys(body.payload).some((key) => PAYLOAD_RESERVED_KEYS.has(key)) ||
      !isRecord(mutation) || Object.keys(mutation).length !== 2 ||
      mutation.expected_revision !== body.expected_revision ||
      mutation.idempotency_key !== body.idempotency_key) return false;
  return true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
