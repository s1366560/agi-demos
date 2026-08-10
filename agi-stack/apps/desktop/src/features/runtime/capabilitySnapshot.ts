import { isCapabilityVersion, negotiateCapabilityContract } from './capabilityVersion';

export const DESKTOP_CAPABILITY_SNAPSHOT_VERSION = '5.0.0' as const;
export const DESKTOP_PREVIOUS_CAPABILITY_SNAPSHOT_VERSION = '4.0.0' as const;
export const DESKTOP_COMPATIBILITY_CAPABILITY_SNAPSHOT_VERSION = '3.0.0' as const;
export const DESKTOP_LEGACY_CAPABILITY_SNAPSHOT_VERSION = '2.0.0' as const;
export const DESKTOP_MINIMUM_CONTRACT_VERSION = '2.0.0' as const;

export type DesktopCapabilityMode = 'cloud' | 'local' | 'native';
export type DesktopCapabilityRuntimeState = 'cloud' | 'local_online' | 'local_offline' | 'native';
export type DesktopCapabilityStatus = 'available' | 'degraded' | 'unavailable' | 'not_applicable';
export type DesktopCapabilityAuthoritySource =
  | 'cloud_service'
  | 'sidecar'
  | 'electron'
  | 'native_runtime'
  | 'renderer';
export type DesktopCapabilityProvenance = 'observed' | 'declared';

export const DESKTOP_INTERNAL_CAPABILITY_NAMES = Object.freeze([
  'automation_run',
  'search',
  'workspace_collaboration',
  'sandbox_isolation',
] as const);

export const DESKTOP_PARITY_CAPABILITY_NAMES = Object.freeze([
  'agent-workspace-tenant-agent-workspace',
  'application-encrypted-vault',
  'authentication-and-account-entry',
  'backend-stores',
  'browser-integration-browser-bridge',
  'device-approval',
  'electron-security-boundary',
  'forced-password-change',
  'invitation-acceptance',
  'not-found',
  'oauth-callback',
  'private-sidecar-control-pipe',
  'project-agent-dashboard',
  'project-agent-logs',
  'project-agent-patterns',
  'project-blackboard-dynamic-project-blackboard',
  'project-playbooks',
  'project-project-channels',
  'project-project-communities',
  'project-project-cron-jobs',
  'project-project-entities',
  'project-project-graph',
  'project-project-maintenance',
  'project-project-memories',
  'project-project-overview',
  'project-project-schema',
  'project-project-search',
  'project-project-settings',
  'project-project-team',
  'project-project-workspaces',
  'project-support',
  'signed-update-and-release-boundary',
  'tenant-creation',
  'tenant-tenant-acp',
  'tenant-tenant-agent-bindings',
  'tenant-tenant-agent-configuration',
  'tenant-tenant-agent-definitions',
  'tenant-tenant-analytics',
  'tenant-tenant-audit-logs',
  'tenant-tenant-billing',
  'tenant-tenant-clusters',
  'tenant-tenant-dead-letter-queue',
  'tenant-tenant-decision-records',
  'tenant-tenant-deploy',
  'tenant-tenant-events',
  'tenant-tenant-evolution',
  'tenant-tenant-genes',
  'tenant-tenant-instance-templates',
  'tenant-tenant-instances',
  'tenant-tenant-mcp-servers',
  'tenant-tenant-org-settings',
  'tenant-tenant-overview',
  'tenant-tenant-patterns',
  'tenant-tenant-plugins',
  'tenant-tenant-pool',
  'tenant-tenant-projects',
  'tenant-tenant-providers',
  'tenant-tenant-runtimes',
  'tenant-tenant-settings',
  'tenant-tenant-skills',
  'tenant-tenant-tasks',
  'tenant-tenant-templates',
  'tenant-tenant-trust-policies',
  'tenant-tenant-users',
  'tenant-tenant-webhooks',
  'tenant-tenant-workspaces',
  'user-profile',
] as const);

export const DESKTOP_CAPABILITY_NAMES = Object.freeze([
  ...DESKTOP_INTERNAL_CAPABILITY_NAMES,
  ...DESKTOP_PARITY_CAPABILITY_NAMES,
] as const);

export type DesktopCapabilityName = (typeof DESKTOP_CAPABILITY_NAMES)[number];

export type DesktopCapabilityScope = {
  tenant_id: string | null;
  project_id: string | null;
  workspace_id: string | null;
  instance_id: string | null;
};

export type DesktopCapabilityAvailability = {
  availability: DesktopCapabilityStatus;
  reason_code: string | null;
  service_version: string | null;
  contract_version: string | null;
  allowed_actions: readonly string[];
  scope: DesktopCapabilityScope;
  authority_revision: number | null;
  retryable?: boolean;
  authority_source?: DesktopCapabilityAuthoritySource;
  supporting_authority_sources?: readonly DesktopCapabilityAuthoritySource[];
  provenance?: DesktopCapabilityProvenance;
};

export type DesktopCapabilitySnapshotEntry = DesktopCapabilityAvailability &
  Required<
    Pick<
      DesktopCapabilityAvailability,
      'retryable' | 'authority_source' | 'supporting_authority_sources' | 'provenance'
    >
  >;

type DesktopCapabilityV4View = DesktopCapabilityAvailability & {
  status: DesktopCapabilityStatus;
  available: boolean;
};

type DesktopCapabilityLegacyView = {
  status: DesktopCapabilityStatus;
  available: boolean;
  reason_code: string | null;
  service_version: string | null;
  contract_version: string | null;
  minimum_contract_version: typeof DESKTOP_MINIMUM_CONTRACT_VERSION;
};

export type DesktopCapabilityView = DesktopCapabilityV4View | DesktopCapabilityLegacyView;

export type DesktopCapabilitySnapshot = {
  version: typeof DESKTOP_CAPABILITY_SNAPSHOT_VERSION;
  runtime_state: DesktopCapabilityRuntimeState;
  capabilities: Record<DesktopCapabilityName, DesktopCapabilitySnapshotEntry>;
};

const CURRENT_CAPABILITY_CONTRACT_MINIMUMS = [
  DESKTOP_MINIMUM_CONTRACT_VERSION,
  DESKTOP_COMPATIBILITY_CAPABILITY_SNAPSHOT_VERSION,
  DESKTOP_PREVIOUS_CAPABILITY_SNAPSHOT_VERSION,
  DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
] as const;

const CAPABILITY_ENTRY_KEYS = [
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
  'retryable',
  'authority_source',
  'supporting_authority_sources',
  'provenance',
] as const;

const V4_CAPABILITY_ENTRY_KEYS = [
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
  'authority_source',
  'provenance',
] as const;

const V3_CAPABILITY_ENTRY_KEYS = [
  'availability',
  'reason_code',
  'service_version',
  'contract_version',
  'allowed_actions',
  'scope',
  'authority_revision',
] as const;

const LEGACY_CAPABILITY_ENTRY_KEYS = [
  'status',
  'reason_code',
  'service_version',
  'contract_version',
  'minimum_contract_version',
] as const;

const CAPABILITY_SCOPE_KEYS = ['tenant_id', 'project_id', 'workspace_id', 'instance_id'] as const;

const STABLE_ACTION_ID_PATTERN = /^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$/;

export function parseDesktopCapabilitySnapshot(input: unknown): DesktopCapabilitySnapshot | null {
  if (
    !isRecord(input) ||
    !isCapabilityRecord(input.capabilities) ||
    (input.version !== DESKTOP_CAPABILITY_SNAPSHOT_VERSION &&
      input.version !== DESKTOP_PREVIOUS_CAPABILITY_SNAPSHOT_VERSION &&
      input.version !== DESKTOP_COMPATIBILITY_CAPABILITY_SNAPSHOT_VERSION &&
      input.version !== DESKTOP_LEGACY_CAPABILITY_SNAPSHOT_VERSION)
  ) {
    return null;
  }
  const runtimeState =
    input.version === DESKTOP_CAPABILITY_SNAPSHOT_VERSION
      ? isExactRecord(input, ['version', 'runtime_state', 'capabilities']) &&
        isCapabilityRuntimeState(input.runtime_state)
        ? input.runtime_state
        : null
      : isExactRecord(input, ['version', 'mode', 'capabilities']) && isCapabilityMode(input.mode)
        ? normalizeLegacyRuntimeState(input.mode)
        : null;
  if (runtimeState === null) return null;

  const capabilities = {} as Record<DesktopCapabilityName, DesktopCapabilitySnapshotEntry>;
  for (const capabilityName of DESKTOP_CAPABILITY_NAMES) {
    if (!Object.hasOwn(input.capabilities, capabilityName)) {
      capabilities[capabilityName] = unavailableCapability('capability_not_declared');
      continue;
    }
    const availability = readSnapshotAvailability(
      input.version,
      runtimeState,
      input.capabilities[capabilityName],
    );
    if (!availability) return null;
    capabilities[capabilityName] = availability;
  }
  return {
    version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
    runtime_state: runtimeState,
    capabilities,
  };
}

export function desktopCapability(
  snapshot: DesktopCapabilitySnapshot | null,
  capabilityName: string,
): DesktopCapabilityView {
  const capability =
    snapshot === null
      ? unavailableCapability('capability_snapshot_unavailable')
      : (snapshot.capabilities[capabilityName as DesktopCapabilityName] ??
        unavailableCapability('capability_not_declared'));
  return {
    ...capability,
    status: capability.availability,
    available:
      capability.provenance === 'observed' &&
      (capability.availability === 'available' || capability.availability === 'degraded'),
  };
}

function readSnapshotAvailability(
  version:
    | typeof DESKTOP_CAPABILITY_SNAPSHOT_VERSION
    | typeof DESKTOP_PREVIOUS_CAPABILITY_SNAPSHOT_VERSION
    | typeof DESKTOP_COMPATIBILITY_CAPABILITY_SNAPSHOT_VERSION
    | typeof DESKTOP_LEGACY_CAPABILITY_SNAPSHOT_VERSION,
  runtimeState: DesktopCapabilityRuntimeState,
  input: unknown,
): DesktopCapabilitySnapshotEntry | null {
  if (version === DESKTOP_CAPABILITY_SNAPSHOT_VERSION) {
    return readAvailability(input, runtimeState);
  }
  if (version === DESKTOP_PREVIOUS_CAPABILITY_SNAPSHOT_VERSION) {
    return readV4Availability(input, runtimeState);
  }
  if (version === DESKTOP_COMPATIBILITY_CAPABILITY_SNAPSHOT_VERSION) {
    const availability = readStructuredAvailability(input, V3_CAPABILITY_ENTRY_KEYS);
    return availability ? declaredAvailability(availability) : null;
  }
  return readLegacyAvailability(input);
}

function readAvailability(
  input: unknown,
  runtimeState: DesktopCapabilityRuntimeState,
): DesktopCapabilitySnapshotEntry | null {
  if (
    !isExactRecord(input, CAPABILITY_ENTRY_KEYS) ||
    typeof input.retryable !== 'boolean' ||
    !isCapabilityAuthoritySource(input.authority_source) ||
    !isSupportingAuthoritySources(input.supporting_authority_sources, input.authority_source) ||
    !isCapabilityProvenance(input.provenance)
  ) {
    return null;
  }

  const availability = readStructuredAvailability(input, CAPABILITY_ENTRY_KEYS);
  const active =
    availability?.availability === 'available' || availability?.availability === 'degraded';
  if (
    !availability ||
    (active && availability.authority_revision === null) ||
    (availability.availability === 'not_applicable' && input.retryable) ||
    !isAuthorityStateValid(
      runtimeState,
      availability.availability,
      input.authority_source,
      input.supporting_authority_sources,
      input.provenance,
    )
  ) {
    return null;
  }
  return {
    ...availability,
    retryable: input.retryable,
    authority_source: input.authority_source,
    supporting_authority_sources: Object.freeze([...input.supporting_authority_sources]),
    provenance: input.provenance,
  };
}

function readV4Availability(
  input: unknown,
  runtimeState: DesktopCapabilityRuntimeState,
): DesktopCapabilitySnapshotEntry | null {
  if (
    !isExactRecord(input, V4_CAPABILITY_ENTRY_KEYS) ||
    !isCapabilityAuthoritySource(input.authority_source) ||
    !isCapabilityProvenance(input.provenance)
  ) {
    return null;
  }
  const availability = readStructuredAvailability(input, V4_CAPABILITY_ENTRY_KEYS);
  const active =
    availability?.availability === 'available' || availability?.availability === 'degraded';
  if (
    !availability ||
    (active && availability.authority_revision === null) ||
    !isAuthorityStateValid(
      runtimeState,
      availability.availability,
      input.authority_source,
      [],
      input.provenance,
    )
  ) {
    return null;
  }
  return {
    ...availability,
    retryable: false,
    authority_source: input.authority_source,
    supporting_authority_sources: Object.freeze([]),
    provenance: input.provenance,
  };
}

function readStructuredAvailability(
  input: unknown,
  expectedKeys: readonly string[],
): DesktopCapabilityAvailability | null {
  if (
    !isExactRecord(input, expectedKeys) ||
    !isCapabilityStatus(input.availability) ||
    !isNullableCapabilityVersion(input.service_version) ||
    !isNullableCapabilityVersion(input.contract_version) ||
    !isCapabilityScope(input.scope) ||
    !isAuthorityRevision(input.authority_revision)
  ) {
    return null;
  }
  const allowedActions = readAllowedActions(input.allowed_actions);
  const active = input.availability === 'available' || input.availability === 'degraded';
  if (
    allowedActions === null ||
    (active && allowedActions.length === 0) ||
    !isAvailabilityStateValid(
      input.availability,
      input.reason_code,
      input.service_version,
      input.contract_version,
      CURRENT_CAPABILITY_CONTRACT_MINIMUMS,
    )
  ) {
    return null;
  }
  if (
    (input.availability === 'unavailable' || input.availability === 'not_applicable') &&
    allowedActions.length > 0
  ) {
    return null;
  }
  if (input.availability === 'not_applicable' && input.authority_revision !== null) {
    return null;
  }
  return {
    availability: input.availability,
    reason_code: input.reason_code,
    service_version: input.service_version,
    contract_version: input.contract_version,
    allowed_actions: allowedActions,
    scope: copyCapabilityScope(input.scope),
    authority_revision: input.authority_revision,
  };
}

function readLegacyAvailability(input: unknown): DesktopCapabilitySnapshotEntry | null {
  if (
    !isExactRecord(input, LEGACY_CAPABILITY_ENTRY_KEYS) ||
    !isCapabilityStatus(input.status) ||
    input.minimum_contract_version !== DESKTOP_MINIMUM_CONTRACT_VERSION ||
    !isNullableCapabilityVersion(input.service_version) ||
    !isNullableCapabilityVersion(input.contract_version) ||
    !isAvailabilityStateValid(
      input.status,
      input.reason_code,
      input.service_version,
      input.contract_version,
    )
  ) {
    return null;
  }
  return declaredAvailability({
    availability: input.status,
    reason_code: input.reason_code,
    service_version: input.service_version,
    contract_version: input.contract_version,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  });
}

function isAvailabilityStateValid(
  availability: DesktopCapabilityStatus,
  reasonCode: unknown,
  serviceVersion: string | null,
  contractVersion: string | null,
  compatibleMinimums: readonly string[] = [DESKTOP_MINIMUM_CONTRACT_VERSION],
): reasonCode is string | null {
  if (availability === 'available' || availability === 'degraded') {
    const contract = {
      service_version: serviceVersion,
      contract_version: contractVersion,
    };
    const compatible = compatibleMinimums.some(
      (minimumContractVersion) =>
        negotiateCapabilityContract(contract, minimumContractVersion).compatible,
    );
    if (!compatible) return false;
  }
  if (availability === 'available') return reasonCode === null;
  if (!isStableReasonCode(reasonCode)) return false;
  return availability !== 'not_applicable' || (serviceVersion === null && contractVersion === null);
}

function unavailableCapability(reasonCode: string): DesktopCapabilitySnapshotEntry {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
    retryable: false,
    authority_source: 'renderer',
    supporting_authority_sources: Object.freeze([]),
    provenance: 'declared',
  };
}

function declaredAvailability(
  availability: DesktopCapabilityAvailability,
): DesktopCapabilitySnapshotEntry {
  return {
    ...availability,
    retryable: false,
    authority_source: 'renderer',
    supporting_authority_sources: Object.freeze([]),
    provenance: 'declared',
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

function isCapabilityMode(input: unknown): input is DesktopCapabilityMode {
  return input === 'cloud' || input === 'local' || input === 'native';
}

function normalizeLegacyRuntimeState(mode: DesktopCapabilityMode): DesktopCapabilityRuntimeState {
  return mode === 'local' ? 'local_offline' : mode;
}

function isCapabilityRuntimeState(input: unknown): input is DesktopCapabilityRuntimeState {
  return (
    input === 'cloud' || input === 'local_online' || input === 'local_offline' || input === 'native'
  );
}

function isCapabilityStatus(input: unknown): input is DesktopCapabilityStatus {
  return (
    input === 'available' ||
    input === 'degraded' ||
    input === 'unavailable' ||
    input === 'not_applicable'
  );
}

function isCapabilityAuthoritySource(input: unknown): input is DesktopCapabilityAuthoritySource {
  return (
    input === 'cloud_service' ||
    input === 'sidecar' ||
    input === 'electron' ||
    input === 'native_runtime' ||
    input === 'renderer'
  );
}

function isCapabilityProvenance(input: unknown): input is DesktopCapabilityProvenance {
  return input === 'observed' || input === 'declared';
}

function isAuthorityStateValid(
  runtimeState: DesktopCapabilityRuntimeState,
  availability: DesktopCapabilityStatus,
  source: DesktopCapabilityAuthoritySource,
  supportingSources: readonly DesktopCapabilityAuthoritySource[],
  provenance: DesktopCapabilityProvenance,
): boolean {
  const active = availability === 'available' || availability === 'degraded';
  if (provenance === 'declared') {
    return source === 'renderer' && supportingSources.length === 0 && !active;
  }
  if (!active && supportingSources.length > 0) return false;
  return authoritySourcesForRuntimeState(runtimeState).includes(
    source as Exclude<DesktopCapabilityAuthoritySource, 'renderer' | 'electron'>,
  );
}

function authoritySourcesForRuntimeState(
  runtimeState: DesktopCapabilityRuntimeState,
): readonly Exclude<DesktopCapabilityAuthoritySource, 'renderer' | 'electron'>[] {
  if (runtimeState === 'cloud') return ['cloud_service'];
  if (runtimeState === 'local_online') return ['cloud_service', 'sidecar'];
  if (runtimeState === 'local_offline') return ['sidecar'];
  return ['native_runtime'];
}

function isSupportingAuthoritySources(
  input: unknown,
  primarySource: DesktopCapabilityAuthoritySource,
): input is DesktopCapabilityAuthoritySource[] {
  if (!Array.isArray(input)) return false;
  const seen = new Set<DesktopCapabilityAuthoritySource>();
  for (const source of input) {
    if (
      !isCapabilityAuthoritySource(source) ||
      source === 'renderer' ||
      source === primarySource ||
      seen.has(source)
    ) {
      return false;
    }
    seen.add(source);
  }
  return true;
}

function isNullableCapabilityVersion(input: unknown): input is string | null {
  return input === null || isCapabilityVersion(input);
}

function readAllowedActions(input: unknown): string[] | null {
  if (!Array.isArray(input)) return null;
  const actions: string[] = [];
  const seen = new Set<string>();
  for (const action of input) {
    if (typeof action !== 'string' || !STABLE_ACTION_ID_PATTERN.test(action) || seen.has(action)) {
      return null;
    }
    actions.push(action);
    seen.add(action);
  }
  return actions;
}

function isAuthorityRevision(input: unknown): input is number | null {
  return input === null || (typeof input === 'number' && Number.isSafeInteger(input) && input >= 0);
}

function isCapabilityScope(input: unknown): input is DesktopCapabilityScope {
  return (
    isExactRecord(input, CAPABILITY_SCOPE_KEYS) &&
    CAPABILITY_SCOPE_KEYS.every((key) => isNullableScopeIdentifier(input[key]))
  );
}

function copyCapabilityScope(scope: DesktopCapabilityScope): DesktopCapabilityScope {
  return {
    tenant_id: scope.tenant_id,
    project_id: scope.project_id,
    workspace_id: scope.workspace_id,
    instance_id: scope.instance_id,
  };
}

function isNullableScopeIdentifier(input: unknown): input is string | null {
  return (
    input === null || (typeof input === 'string' && input.length > 0 && input === input.trim())
  );
}

function isStableReasonCode(input: unknown): input is string {
  return typeof input === 'string' && /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(input);
}

function isCapabilityRecord(
  input: unknown,
): input is Partial<Record<DesktopCapabilityName, unknown>> {
  return (
    typeof input === 'object' &&
    input !== null &&
    !Array.isArray(input) &&
    Object.keys(input).every((key) =>
      DESKTOP_CAPABILITY_NAMES.includes(key as DesktopCapabilityName),
    )
  );
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
