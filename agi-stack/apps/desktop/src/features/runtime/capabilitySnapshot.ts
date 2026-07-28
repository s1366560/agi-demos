import {
  isCapabilityVersion,
  negotiateCapabilityContract,
} from './capabilityVersion';

export const DESKTOP_CAPABILITY_SNAPSHOT_VERSION = '2.0.0' as const;
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
  | 'sandbox_isolation';

export type DesktopCapabilityAvailability = {
  status: DesktopCapabilityStatus;
  reason_code: string | null;
  service_version: string | null;
  contract_version: string | null;
  minimum_contract_version: typeof DESKTOP_MINIMUM_CONTRACT_VERSION;
};

export type DesktopCapabilityView = DesktopCapabilityAvailability & {
  available: boolean;
};

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
];

export function parseDesktopCapabilitySnapshot(
  input: unknown,
): DesktopCapabilitySnapshot | null {
  if (
    !isExactRecord(input, ['version', 'mode', 'capabilities']) ||
    input.version !== DESKTOP_CAPABILITY_SNAPSHOT_VERSION ||
    !isCapabilityMode(input.mode) ||
    !isExactRecord(input.capabilities, CAPABILITY_NAMES)
  ) {
    return null;
  }

  const capabilities = {} as Record<
    DesktopCapabilityName,
    DesktopCapabilityAvailability
  >;
  for (const capabilityName of CAPABILITY_NAMES) {
    const availability = readAvailability(input.capabilities[capabilityName]);
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
  capabilityName: DesktopCapabilityName,
): DesktopCapabilityView {
  const capability = snapshot?.capabilities[capabilityName] ?? {
    status: 'unavailable' as const,
    reason_code: 'capability_snapshot_unavailable',
    service_version: null,
    contract_version: null,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
  };
  return {
    ...capability,
    available: capability.status === 'available' || capability.status === 'degraded',
  };
}

function readAvailability(input: unknown): DesktopCapabilityAvailability | null {
  if (
    !isExactRecord(input, [
      'status',
      'reason_code',
      'service_version',
      'contract_version',
      'minimum_contract_version',
    ]) ||
    !isCapabilityStatus(input.status) ||
    input.minimum_contract_version !== DESKTOP_MINIMUM_CONTRACT_VERSION ||
    !isNullableCapabilityVersion(input.service_version) ||
    !isNullableCapabilityVersion(input.contract_version)
  ) {
    return null;
  }

  if (input.status === 'available' || input.status === 'degraded') {
    const negotiation = negotiateCapabilityContract(
      {
        service_version: input.service_version,
        contract_version: input.contract_version,
      },
      DESKTOP_MINIMUM_CONTRACT_VERSION,
    );
    if (!negotiation.compatible) return null;
  }
  if (input.status === 'available') {
    if (input.reason_code !== null) return null;
  } else if (!isStableReasonCode(input.reason_code)) {
    return null;
  }
  if (
    input.status === 'not_applicable' &&
    (input.service_version !== null || input.contract_version !== null)
  ) {
    return null;
  }
  return {
    status: input.status,
    reason_code: input.reason_code,
    service_version: input.service_version,
    contract_version: input.contract_version,
    minimum_contract_version: DESKTOP_MINIMUM_CONTRACT_VERSION,
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

function isStableReasonCode(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(input)
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
