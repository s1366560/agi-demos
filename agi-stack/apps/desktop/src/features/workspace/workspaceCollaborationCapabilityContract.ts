import type { DesktopRuntimeConfig } from '../../types';
import {
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  type DesktopCapabilityAvailability,
  type DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import {
  negotiateCapabilityContract,
  type CapabilityContractNegotiation,
} from '../runtime/capabilityVersion';
import { WORKSPACE_HTTP_MUTATION_ACTIONS } from './workspaceCollaborationHttpMutations';

export type WorkspaceCollaborationCapabilityScope = Readonly<{
  tenantId: string;
  projectId: string;
  workspaceId: string;
}>;

const WORKSPACE_COLLABORATION_DEGRADED_REASON =
  'workspace_collaboration_mutation_guards_unavailable';

const WORKSPACE_COLLABORATION_READ_SURFACES = Object.freeze([
  'goals',
  'discussion',
  'status',
  'collaboration',
  'members',
  'genes',
  'files',
  'notes',
  'topology',
  'settings',
]);

export function normalizeWorkspaceCollaborationCapabilityContract(
  input: unknown,
  scope: WorkspaceCollaborationCapabilityScope,
  expectedAuthority: DesktopRuntimeConfig['mode'] = 'cloud',
): DesktopCapabilityAvailability {
  const negotiation = negotiateCapabilityContract(input, DESKTOP_MINIMUM_CONTRACT_VERSION);
  if (!negotiation.compatible) {
    return unavailable(
      negotiation.reason_code ?? 'capability_contract_version_invalid',
      negotiation,
    );
  }
  if (!isRecord(input)) {
    return unavailable('workspace_collaboration_capability_contract_invalid', negotiation);
  }
  if (
    input.authority !== expectedAuthority ||
    input.canonical_read !== true ||
    !matchesExactStringArray(input.read_surfaces, WORKSPACE_COLLABORATION_READ_SURFACES) ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    input.workspace_id !== scope.workspaceId
  ) {
    return unavailable(
      input.tenant_id !== scope.tenantId ||
        input.project_id !== scope.projectId ||
        input.workspace_id !== scope.workspaceId
        ? 'workspace_collaboration_capability_scope_mismatch'
        : 'workspace_collaboration_capability_contract_invalid',
      negotiation,
    );
  }
  const capabilityKeys = [
    'service_version',
    'contract_version',
    'authority',
    'tenant_id',
    'project_id',
    'workspace_id',
    'status',
    'reason_code',
    'canonical_read',
    'read_surfaces',
    'mutations',
    'allowed_actions',
  ];
  if (
    input.status === 'available' &&
    isExactRecord(input, capabilityKeys) &&
    input.reason_code === null &&
    isExactRecord(input.mutations, [
      'allowed',
      'revision_guarded',
      'idempotency_guarded',
      'actions',
    ]) &&
    input.mutations.allowed === true &&
    input.mutations.revision_guarded === true &&
    input.mutations.idempotency_guarded === true &&
    matchesWorkspaceMutationActions(input.mutations.actions) &&
    JSON.stringify(input.allowed_actions) === JSON.stringify(input.mutations.actions)
  ) {
    return available(negotiation, [
      ...workspaceReadActions(),
      ...flattenWorkspaceMutationActions(input.mutations.actions),
    ]);
  }
  if (
    !isExactRecord(input, capabilityKeys) ||
    input.status !== 'degraded' ||
    input.reason_code !== WORKSPACE_COLLABORATION_DEGRADED_REASON ||
    !isExactRecord(input.mutations, ['allowed', 'revision_guarded', 'idempotency_guarded']) ||
    input.mutations.allowed !== false ||
    input.mutations.revision_guarded !== false ||
    input.mutations.idempotency_guarded !== false
  ) {
    return unavailable('workspace_collaboration_capability_contract_invalid', negotiation);
  }
  return degraded(WORKSPACE_COLLABORATION_DEGRADED_REASON, negotiation, workspaceReadActions());
}

export function normalizeWorkspaceCollaborationAuthorityContract(
  input: unknown,
  scope: WorkspaceCollaborationCapabilityScope,
): number | null {
  if (
    !isExactRecord(input, [
      'contract_version',
      'tenant_id',
      'project_id',
      'workspace_id',
      'revision',
      'cursor',
    ]) ||
    input.contract_version !== '2.0.0' ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    input.workspace_id !== scope.workspaceId ||
    !Number.isSafeInteger(input.revision) ||
    Number(input.revision) < 0 ||
    typeof input.cursor !== 'string' ||
    input.cursor.length === 0 ||
    input.cursor !== input.cursor.trim()
  ) {
    return null;
  }
  return Number(input.revision);
}

function workspaceReadActions(): string[] {
  return WORKSPACE_COLLABORATION_READ_SURFACES.map((surface) => `${surface}:view`);
}

function matchesWorkspaceMutationActions(input: unknown): boolean {
  const surfaces = Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS);
  if (!isExactRecord(input, surfaces)) return false;
  return surfaces.every((surface) =>
    matchesExactStringArray(
      input[surface],
      WORKSPACE_HTTP_MUTATION_ACTIONS[surface as keyof typeof WORKSPACE_HTTP_MUTATION_ACTIONS],
    ),
  );
}

function flattenWorkspaceMutationActions(input: unknown): string[] {
  if (!isRecord(input) || !matchesWorkspaceMutationActions(input)) return [];
  return Object.keys(WORKSPACE_HTTP_MUTATION_ACTIONS).flatMap((surface) =>
    (input[surface] as string[]).map((action) => `${surface}:${action}`),
  );
}

function available(
  negotiation: CapabilityContractNegotiation,
  allowedActions: readonly string[],
): DesktopCapabilityAvailability {
  return capability('available', null, negotiation, [...new Set(allowedActions)]);
}

function degraded(
  reasonCode: string,
  negotiation: CapabilityContractNegotiation,
  allowedActions: readonly string[],
): DesktopCapabilityAvailability {
  return capability('degraded', reasonCode, negotiation, allowedActions);
}

function unavailable(
  reasonCode: string,
  negotiation?: CapabilityContractNegotiation,
): DesktopCapabilityAvailability {
  return capability('unavailable', reasonCode, negotiation, []);
}

function capability(
  availability: DesktopCapabilityAvailability['availability'],
  reasonCode: string | null,
  negotiation: CapabilityContractNegotiation | undefined,
  allowedActions: readonly string[],
): DesktopCapabilityAvailability {
  return {
    availability,
    reason_code: reasonCode,
    service_version: negotiation?.service_version ?? null,
    contract_version: negotiation?.contract_version ?? null,
    allowed_actions: [...allowedActions],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  };
}

function emptyCapabilityScope(): DesktopCapabilityScope {
  return {
    tenant_id: null,
    project_id: null,
    workspace_id: null,
    instance_id: null,
  };
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isExactRecord(
  input: unknown,
  expectedKeys: readonly string[],
): input is Record<string, unknown> {
  if (!isRecord(input)) return false;
  const keys = Object.keys(input).sort();
  const expected = [...expectedKeys].sort();
  return keys.length === expected.length && keys.every((key, index) => key === expected[index]);
}

function matchesExactStringArray(input: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(input) &&
    input.length === expected.length &&
    input.every((value, index) => value === expected[index])
  );
}
