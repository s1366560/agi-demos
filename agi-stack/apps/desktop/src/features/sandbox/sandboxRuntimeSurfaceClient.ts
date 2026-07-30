import {
  absoluteUrl,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  parseKasmProxySession,
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

export type RemoteDesktopResolution =
  | '1280x720'
  | '1600x900'
  | '1920x1080'
  | '2560x1440';

export type RemoteDesktopSession = {
  descriptor: KasmProxySession;
  frame_url: string;
};

export type SandboxRuntimeSurfaceClient = {
  loadCapabilities(signal?: AbortSignal): Promise<SandboxRuntimeCapabilitySnapshot>;
  openRemoteDesktop(
    capabilities: SandboxRuntimeCapabilitySnapshot,
    request: { resolution: RemoteDesktopResolution },
    signal?: AbortSignal,
  ): Promise<SandboxRuntimeResult<RemoteDesktopSession>>;
};

const CAPABILITY_KEYS = [
  'terminal_interactive',
  'terminal_resume',
  'files',
  'kasm_vnc',
] as const;
const EXPECTED_CAPABILITY_VERSIONS = {
  terminal_interactive: 1,
  terminal_resume: 2,
  files: 1,
  kasm_vnc: 1,
} as const;
const ALLOWED_RESOLUTIONS = new Set<RemoteDesktopResolution>([
  '1280x720',
  '1600x900',
  '1920x1080',
  '2560x1440',
]);
const MAX_RESPONSE_BYTES = 64 * 1024;

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
  config: DesktopRuntimeConfig,
): SandboxRuntimeSurfaceClient {
  return Object.freeze({
    async loadCapabilities(signal?: AbortSignal): Promise<SandboxRuntimeCapabilitySnapshot> {
      const projectId = requireProjectId(config);
      const payload = await requestJson(
        config,
        `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/capabilities`,
        { signal },
      );
      const snapshot = parseSandboxRuntimeCapabilitySnapshot(payload);
      if (!snapshot) {
        throw new Error('sandbox runtime capability contract is invalid');
      }
      return snapshot;
    },

    async openRemoteDesktop(
      capabilities: SandboxRuntimeCapabilitySnapshot,
      request: { resolution: RemoteDesktopResolution },
      signal?: AbortSignal,
    ): Promise<SandboxRuntimeResult<RemoteDesktopSession>> {
      const parsedCapabilities = parseSandboxRuntimeCapabilitySnapshot(capabilities);
      if (!parsedCapabilities) {
        return {
          status: 'unavailable',
          reason_code: 'sandbox_runtime_capability_contract_invalid',
        };
      }
      if (parsedCapabilities.kasm_vnc.availability !== 'available') {
        return {
          status: 'unavailable',
          reason_code:
            parsedCapabilities.kasm_vnc.reason_code ?? 'kasm_proxy_contract_unavailable',
        };
      }
      if (!ALLOWED_RESOLUTIONS.has(request.resolution)) {
        throw new Error('sandbox remote desktop resolution is invalid');
      }

      const projectId = requireProjectId(config);
      const query = new URLSearchParams({ resolution: request.resolution });
      const payload = await requestJson(
        config,
        `/api/v1/projects/${encodeURIComponent(
          projectId,
        )}/sandbox/desktop/session?${query.toString()}`,
        { method: 'POST', signal },
      );
      const descriptor = parseKasmProxySession(payload, projectId);
      if (!descriptor) {
        throw new Error('sandbox remote desktop descriptor is invalid');
      }
      return {
        status: 'ready',
        value: {
          descriptor,
          frame_url: trustedFrameUrl(config.apiBaseUrl, descriptor.proxy_url),
        },
      };
    },
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

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: { method?: 'GET' | 'POST'; signal?: AbortSignal },
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);

  const response = await fetch(absoluteUrl(config.apiBaseUrl, path), {
    method: options.method ?? 'GET',
    headers,
    credentials: config.mode === 'local' ? 'omit' : 'include',
    signal: options.signal,
  });
  if (!response.ok) {
    throw new Error('sandbox runtime request failed');
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw new Error('sandbox runtime response is not JSON');
  }
  const declaredLength = parseContentLength(response.headers.get('content-length'));
  if (declaredLength !== null && declaredLength > MAX_RESPONSE_BYTES) {
    throw new Error('sandbox runtime response exceeds the metadata limit');
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new Error('sandbox runtime response exceeds the metadata limit');
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error('sandbox runtime response is malformed');
  }
}

function trustedFrameUrl(apiBaseUrl: string, proxyUrl: string): string {
  const base = new URL(apiBaseUrl);
  if (
    (base.protocol !== 'http:' && base.protocol !== 'https:') ||
    base.username ||
    base.password
  ) {
    throw new Error('sandbox API origin is invalid');
  }
  const frame = new URL(proxyUrl, base.origin);
  if (
    frame.origin !== base.origin ||
    (frame.protocol !== 'http:' && frame.protocol !== 'https:') ||
    frame.username ||
    frame.password ||
    frame.search ||
    frame.hash
  ) {
    throw new Error('sandbox remote desktop descriptor is invalid');
  }
  return frame.toString();
}

function requireProjectId(config: DesktopRuntimeConfig): string {
  const projectId = config.projectId.trim();
  if (!projectId) throw new Error('sandbox project scope is unavailable');
  return projectId;
}

function parseContentLength(input: string | null): number | null {
  if (input === null) return null;
  const value = Number(input);
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function isAvailability(
  input: unknown,
): input is SandboxRuntimeCapability['availability'] {
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
