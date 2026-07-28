export const DESKTOP_CAPABILITY_SNAPSHOT_VERSION = '1.0.0' as const;

export type DesktopCapabilityMode = 'cloud' | 'local' | 'native';

export type DesktopCapabilityName =
  | 'automation_run'
  | 'search'
  | 'workspace_collaboration'
  | 'sandbox_isolation';

export type DesktopCapabilityAvailability = {
  available: boolean;
  reason_code: string | null;
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
): DesktopCapabilityAvailability {
  return (
    snapshot?.capabilities[capabilityName] ?? {
      available: false,
      reason_code: 'capability_snapshot_unavailable',
    }
  );
}

function readAvailability(input: unknown): DesktopCapabilityAvailability | null {
  if (
    !isExactRecord(input, ['available', 'reason_code']) ||
    typeof input.available !== 'boolean'
  ) {
    return null;
  }
  if (input.available) {
    return input.reason_code === null ? { available: true, reason_code: null } : null;
  }
  if (typeof input.reason_code !== 'string' || !input.reason_code.trim()) return null;
  return { available: false, reason_code: input.reason_code };
}

function isCapabilityMode(input: unknown): input is DesktopCapabilityMode {
  return input === 'cloud' || input === 'local' || input === 'native';
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
