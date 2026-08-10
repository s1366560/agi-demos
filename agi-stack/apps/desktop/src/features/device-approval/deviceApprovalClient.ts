import {
  absoluteUrl,
  desktopApiCredential,
} from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import { isCompleteDeviceApprovalCode } from './deviceApprovalModel';

type Fetch = typeof globalThis.fetch;

export type DeviceApprovalOutcome = Readonly<{ status: 'approved' }>;

export type DeviceApprovalClient = Readonly<{
  approve(
    userCode: string,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<DeviceApprovalOutcome>;
}>;

export type DeviceApprovalClientDependencies = Readonly<{
  fetch?: Fetch;
}>;

export class DeviceApprovalError extends Error {
  readonly reasonCode: string;
  readonly status: number | null;

  constructor(reasonCode: string, status: number | null = null) {
    super(reasonCode);
    this.name = 'DeviceApprovalError';
    this.reasonCode = reasonCode;
    this.status = status;
  }
}

export function createDeviceApprovalClient(
  config: DesktopRuntimeConfig,
  dependencies: DeviceApprovalClientDependencies = {},
): DeviceApprovalClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchPath = (path: string, init: RequestInit): Promise<Response> =>
    dependencies.fetch
      ? dependencies.fetch(absoluteUrl(runtimeConfig.apiBaseUrl, path), init)
      : desktopApiFetch(runtimeConfig, path, init);
  return Object.freeze({
    async approve(userCode, options) {
      if (runtimeConfig.mode !== 'cloud') {
        throw new DeviceApprovalError(
          'local_cloud_device_approval_not_applicable',
        );
      }
      if (!isCompleteDeviceApprovalCode(userCode)) {
        throw new DeviceApprovalError('device_approval_code_invalid');
      }
      const credential = desktopApiCredential(runtimeConfig);
      if (!desktopApiAuthenticationAvailable(runtimeConfig)) {
        throw new DeviceApprovalError(
          'device_approval_authentication_required',
          401,
        );
      }
      const headers = new Headers({
        Accept: 'application/json',
        'Content-Type': 'application/json',
      });
      if (credential) headers.set('Authorization', `Bearer ${credential}`);
      const response = await fetchPath(
        '/api/v1/auth/device/approve',
        {
          method: 'POST',
          headers,
          signal: options?.signal,
          body: JSON.stringify({ user_code: userCode }),
        },
      );
      const contentType = response.headers.get('content-type') ?? '';
      const isJson = contentType.toLowerCase().includes('application/json');
      const payload = isJson
        ? await response.json().catch(() => null)
        : null;
      if (!response.ok) {
        throw new DeviceApprovalError(
          reasonCodeForStatus(response.status),
          response.status,
        );
      }
      if (!isApprovedOutcome(payload)) {
        throw new DeviceApprovalError('device_approval_contract_invalid');
      }
      return Object.freeze({ status: 'approved' });
    },
  });
}

function reasonCodeForStatus(status: number): string {
  switch (status) {
    case 400:
      return 'device_approval_request_invalid';
    case 401:
      return 'device_approval_authentication_required';
    case 403:
      return 'device_approval_forbidden';
    case 404:
      return 'device_approval_code_unknown';
    case 409:
      return 'device_approval_code_already_handled';
    case 410:
      return 'device_approval_code_expired';
    case 503:
      return 'device_approval_authority_busy';
    default:
      return 'device_approval_request_failed';
  }
}

function isApprovedOutcome(
  value: unknown,
): value is DeviceApprovalOutcome {
  return (
    isRecord(value) &&
    Object.keys(value).length === 1 &&
    value.status === 'approved'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
