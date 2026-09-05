import {
  type KasmProxySession,
  type SandboxRuntimeCapabilities,
  type SandboxRuntimeCapability,
  type SandboxRuntimeResult,
} from './sandboxRuntimeClient';

export const SANDBOX_RUNTIME_CAPABILITY_CONTRACT_VERSION = 2 as const;

export type SandboxRuntimeCapabilitySnapshot = SandboxRuntimeCapabilities & {
  service_version: string;
  contract_version: number;
};

export type RemoteDesktopResolution = '1280x720' | '1600x900' | '1920x1080' | '2560x1440';

export type RemoteDesktopSession = {
  descriptor: KasmProxySession;
  frame_url: string;
  frame_name?: string;
};

export type SandboxRuntimeSurfaceClient = {
  loadCapabilities(signal?: AbortSignal): Promise<SandboxRuntimeCapabilitySnapshot>;
  openRemoteDesktop(
    capabilities: SandboxRuntimeCapabilitySnapshot,
    request: { resolution: RemoteDesktopResolution },
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<RemoteDesktopSession>>;
};

const CAPABILITY_KEYS = ['terminal_interactive', 'terminal_resume', 'files', 'kasm_vnc'] as const;
const EXPECTED_CAPABILITY_VERSIONS = {
  terminal_interactive: 1,
  terminal_resume: 2,
  files: 1,
  kasm_vnc: 1,
} as const;
export function parseSandboxRuntimeCapabilitySnapshot(
  input: unknown,
): SandboxRuntimeCapabilitySnapshot | null {
  if (
    !isRecord(input) ||
    !Number.isSafeInteger(input.contract_version) ||
    Number(input.contract_version) < SANDBOX_RUNTIME_CAPABILITY_CONTRACT_VERSION ||
    !isServiceVersion(input.service_version)
  ) {
    return null;
  }

  const parsed = {} as SandboxRuntimeCapabilities;
  for (const capabilityName of CAPABILITY_KEYS) {
    const capability = parseCapability(
      input[capabilityName],
      EXPECTED_CAPABILITY_VERSIONS[capabilityName],
    );
    if (!capability) return null;
    parsed[capabilityName] = capability;
  }

  return {
    service_version: input.service_version,
    contract_version: Number(input.contract_version),
    ...parsed,
  };
}

export function createSandboxRuntimeSurfaceClient(
  authority: SandboxRuntimeSurfaceClient,
): SandboxRuntimeSurfaceClient {
  return Object.freeze({
    loadCapabilities: (signal?: AbortSignal) => authority.loadCapabilities(signal),
    openRemoteDesktop: (
      capabilities: SandboxRuntimeCapabilitySnapshot,
      request: { resolution: RemoteDesktopResolution },
      signal?: AbortSignal,
    ) => authority.openRemoteDesktop(capabilities, request, signal),
  });
}

export function remoteDesktopReconnectDelay(attempt: number): number {
  const boundedAttempt = Number.isInteger(attempt) && attempt > 0 ? attempt : 0;
  return Math.min(1_000 * 2 ** boundedAttempt, 15_000);
}

function parseCapability(
  input: unknown,
  minimumContractVersion: number,
): SandboxRuntimeCapability | null {
  if (
    !isRecord(input) ||
    !isAvailability(input.availability) ||
    !Number.isSafeInteger(input.contract_version) ||
    Number(input.contract_version) < minimumContractVersion
  ) {
    return null;
  }
  if (input.availability === 'available') {
    if (input.reason_code !== null) return null;
  } else if (!isReasonCode(input.reason_code)) {
    return null;
  }
  return {
    availability: input.availability,
    contract_version: Number(input.contract_version),
    reason_code: input.reason_code,
  };
}

function isAvailability(input: unknown): input is SandboxRuntimeCapability['availability'] {
  return (
    input === 'available' ||
    input === 'degraded' ||
    input === 'unavailable' ||
    input === 'not_applicable'
  );
}

function isReasonCode(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    input.length <= 127 &&
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u.test(input)
  );
}

function isServiceVersion(input: unknown): input is string {
  return (
    typeof input === 'string' &&
    input.length <= 63 &&
    /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/u.test(input)
  );
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}
