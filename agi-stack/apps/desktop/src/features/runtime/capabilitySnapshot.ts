import {
  isCapabilityVersion,
  negotiateCapabilityContract,
} from './capabilityVersion';

export const DESKTOP_CAPABILITY_SNAPSHOT_VERSION = '3.0.0' as const;
export const DESKTOP_LEGACY_CAPABILITY_SNAPSHOT_VERSION = '2.0.0' as const;
export const DESKTOP_MINIMUM_CONTRACT_VERSION = '2.0.0' as const;

export type DesktopCapabilityMode = 'cloud' | 'local' | 'native';
export type DesktopCapabilityStatus =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'not_applicable';

export type DesktopCapabilityName =
  | 'automation_run'
  | 'search'
  | 'workspace_collaboration'
  | 'sandbox_isolation'
  | 'tenant-tenant-overview'
  | 'tenant-tenant-projects'
  | 'tenant-tenant-tasks'
  | 'tenant-tenant-runtimes'
  | 'tenant-tenant-pool'
  | 'tenant-tenant-instances'
  | 'tenant-tenant-clusters'
  | 'tenant-tenant-deploy'
  | 'tenant-tenant-instance-templates'
  | 'tenant-tenant-dead-letter-queue'
  | 'project-project-overview'
  | 'project-project-search'
  | 'project-project-cron-jobs';

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
};

type DesktopCapabilityV3View = DesktopCapabilityAvailability & {
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

export type DesktopCapabilityView =
  | DesktopCapabilityV3View
  | DesktopCapabilityLegacyView;

export type DesktopCapabilitySnapshot = {
  version: typeof DESKTOP_CAPABILITY_SNAPSHOT_VERSION;
  mode: DesktopCapabilityMode;
  capabilities: Record<DesktopCapabilityName, DesktopCapabilityAvailability>;
};

const CAPABILITY_NAMES: readonly DesktopCapabilityName[] = [
  'automation_run',
  'search',
  'workspace_collaboration',
  'sandbox_isolation',
  'tenant-tenant-overview',
  'tenant-tenant-projects',
  'tenant-tenant-tasks',
  'tenant-tenant-runtimes',
  'tenant-tenant-pool',
  'tenant-tenant-instances',
  'tenant-tenant-clusters',
  'tenant-tenant-deploy',
  'tenant-tenant-instance-templates',
  'tenant-tenant-dead-letter-queue',
  'project-project-overview',
  'project-project-search',
  'project-project-cron-jobs',
];

const CURRENT_CAPABILITY_CONTRACT_MINIMUMS = [
  DESKTOP_MINIMUM_CONTRACT_VERSION,
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
] as const;

const LEGACY_CAPABILITY_ENTRY_KEYS = [
  'status',
  'reason_code',
  'service_version',
  'contract_version',
  'minimum_contract_version',
] as const;

const CAPABILITY_SCOPE_KEYS = [
  'tenant_id',
  'project_id',
  'workspace_id',
  'instance_id',
] as const;

const STABLE_ACTION_ID_PATTERN =
  /^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$/;

export function parseDesktopCapabilitySnapshot(
  input: unknown,
): DesktopCapabilitySnapshot | null {
  if (
    !isExactRecord(input, ['version', 'mode', 'capabilities']) ||
    !isCapabilityMode(input.mode) ||
    !isCapabilityRecord(input.capabilities) ||
    (input.version !== DESKTOP_CAPABILITY_SNAPSHOT_VERSION &&
      input.version !== DESKTOP_LEGACY_CAPABILITY_SNAPSHOT_VERSION)
  ) {
    return null;
  }

  const capabilities = {} as Record<
    DesktopCapabilityName,
    DesktopCapabilityAvailability
  >;
  for (const capabilityName of CAPABILITY_NAMES) {
    if (!Object.hasOwn(input.capabilities, capabilityName)) {
      capabilities[capabilityName] = unavailableCapability(
        'capability_not_declared',
      );
      continue;
    }
    const availability =
      input.version === DESKTOP_CAPABILITY_SNAPSHOT_VERSION
        ? readAvailability(input.capabilities[capabilityName])
        : readLegacyAvailability(input.capabilities[capabilityName]);
    if (!availability) return null;
    capabilities[capabilityName] = availability;
  }
  return {
    version: DESKTOP_CAPABILITY_SNAPSHOT_VERSION,
    mode: input.mode,
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
      : snapshot.capabilities[capabilityName as DesktopCapabilityName] ??
        unavailableCapability('capability_not_declared');
  return {
    ...capability,
    status: capability.availability,
    available:
      capability.availability === 'available' ||
      capability.availability === 'degraded',
  };
}

function readAvailability(input: unknown): DesktopCapabilityAvailability | null {
  if (
    !isExactRecord(input, CAPABILITY_ENTRY_KEYS) ||
    !isCapabilityStatus(input.availability) ||
    !isNullableCapabilityVersion(input.service_version) ||
    !isNullableCapabilityVersion(input.contract_version) ||
    !isCapabilityScope(input.scope) ||
    !isAuthorityRevision(input.authority_revision)
  ) {
    return null;
  }

  const allowedActions = readAllowedActions(input.allowed_actions);
  if (
    allowedActions === null ||
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
    (input.availability === 'unavailable' ||
      input.availability === 'not_applicable') &&
    allowedActions.length > 0
  ) {
    return null;
  }
  if (
    input.availability === 'not_applicable' &&
    input.authority_revision !== null
  ) {
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

function readLegacyAvailability(
  input: unknown,
): DesktopCapabilityAvailability | null {
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
  return {
    availability: input.status,
    reason_code: input.reason_code,
    service_version: input.service_version,
    contract_version: input.contract_version,
    allowed_actions: [],
    scope: emptyCapabilityScope(),
    authority_revision: null,
  };
}

function isAvailabilityStateValid(
  availability: DesktopCapabilityStatus,
  reasonCode: unknown,
  serviceVersion: string | null,
  contractVersion: string | null,
  compatibleMinimums: readonly string[] = [
    DESKTOP_MINIMUM_CONTRACT_VERSION,
  ],
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
  return (
    availability !== 'not_applicable' ||
    (serviceVersion === null && contractVersion === null)
  );
}

function unavailableCapability(
  reasonCode: string,
): DesktopCapabilityAvailability {
  return {
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: [],
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

function isCapabilityMode(input: unknown): input is DesktopCapabilityMode {
  return input === 'cloud' || input === 'local' || input === 'native';
}

function isCapabilityStatus(input: unknown): input is DesktopCapabilityStatus {
  return (
    input === 'available' ||
    input === 'degraded' ||
    input === 'unavailable' ||
    input === 'not_applicable'
  );
}

function isNullableCapabilityVersion(input: unknown): input is string | null {
  return input === null || isCapabilityVersion(input);
}

function readAllowedActions(input: unknown): string[] | null {
  if (!Array.isArray(input)) return null;
  const actions: string[] = [];
  const seen = new Set<string>();
  for (const action of input) {
    if (
      typeof action !== 'string' ||
      !STABLE_ACTION_ID_PATTERN.test(action) ||
      seen.has(action)
    ) {
      return null;
    }
    actions.push(action);
    seen.add(action);
  }
  return actions;
}

function isAuthorityRevision(input: unknown): input is number | null {
  return (
    input === null ||
    (typeof input === 'number' &&
      Number.isSafeInteger(input) &&
      input >= 0)
  );
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
    input === null ||
    (typeof input === 'string' && input.length > 0 && input === input.trim())
  );
}

function isStableReasonCode(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(input)
  );
}

function isCapabilityRecord(
  input: unknown,
): input is Partial<Record<DesktopCapabilityName, unknown>> {
  return (
    typeof input === 'object' &&
    input !== null &&
    !Array.isArray(input) &&
    Object.keys(input).every((key) =>
      CAPABILITY_NAMES.includes(key as DesktopCapabilityName),
    )
  );
}

function isExactRecord(
  input: unknown,
  expectedKeys: readonly string[],
): input is Record<string, unknown> {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) return false;
  const keys = Object.keys(input).sort();
  const expected = [...expectedKeys].sort();
  return keys.length === expected.length && keys.every((key, index) => key === expected[index]);
}
