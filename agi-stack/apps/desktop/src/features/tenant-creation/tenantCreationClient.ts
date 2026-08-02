import {
  absoluteUrl,
  desktopApiCredential,
} from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  isTenantCreationPlan,
  validateTenantCreationDraft,
  type TenantCreationInput,
  type TenantCreationRecord,
} from './tenantCreationModel';

type Fetch = typeof globalThis.fetch;

export type TenantCreationClient = Readonly<{
  create(
    input: TenantCreationInput,
    options?: Readonly<{ signal?: AbortSignal }>,
  ): Promise<TenantCreationRecord>;
}>;

export type TenantCreationClientDependencies = Readonly<{
  fetch?: Fetch;
}>;

export class TenantCreationError extends Error {
  readonly reasonCode: string;
  readonly status: number | null;

  constructor(reasonCode: string, status: number | null = null) {
    super(reasonCode);
    this.name = 'TenantCreationError';
    this.reasonCode = reasonCode;
    this.status = status;
  }
}

export function createTenantCreationClient(
  config: DesktopRuntimeConfig,
  dependencies: TenantCreationClientDependencies = {},
): TenantCreationClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchImpl = dependencies.fetch ?? globalThis.fetch;
  return Object.freeze({
    async create(input, options) {
      if (runtimeConfig.mode !== 'cloud') {
        throw new TenantCreationError(
          'local_tenant_creation_not_applicable',
        );
      }
      const validation = validateTenantCreationDraft(input);
      if (!validation.valid) {
        throw new TenantCreationError(validation.reasonCode);
      }
      const credential = desktopApiCredential(runtimeConfig);
      if (!credential) {
        throw new TenantCreationError(
          'tenant_creation_authentication_required',
          401,
        );
      }
      const response = await fetchImpl(
        absoluteUrl(runtimeConfig.apiBaseUrl, '/api/v1/tenants/'),
        {
          method: 'POST',
          headers: new Headers({
            Accept: 'application/json',
            Authorization: `Bearer ${credential}`,
            'Content-Type': 'application/json',
          }),
          signal: options?.signal,
          body: JSON.stringify(validation.value),
        },
      );
      const contentType = response.headers.get('content-type') ?? '';
      const payload = contentType.toLowerCase().includes('application/json')
        ? await response.json().catch(() => null)
        : null;
      if (!response.ok) {
        throw new TenantCreationError(
          reasonCodeForStatus(response.status),
          response.status,
        );
      }
      if (
        response.status !== 201 ||
        !isTenantCreationRecord(payload)
      ) {
        throw new TenantCreationError(
          'tenant_creation_contract_invalid',
          response.status,
        );
      }
      return Object.freeze({ ...payload });
    },
  });
}

function reasonCodeForStatus(status: number): string {
  switch (status) {
    case 400:
    case 422:
      return 'tenant_creation_request_invalid';
    case 401:
      return 'tenant_creation_authentication_required';
    case 403:
      return 'tenant_creation_forbidden';
    case 409:
      return 'tenant_creation_conflict';
    case 429:
      return 'tenant_creation_rate_limited';
    case 502:
    case 503:
    case 504:
      return 'tenant_creation_authority_unavailable';
    default:
      return 'tenant_creation_request_failed';
  }
}

function isTenantCreationRecord(
  value: unknown,
): value is TenantCreationRecord {
  if (
    !isExactRecord(value, [
      'id',
      'name',
      'slug',
      'description',
      'owner_id',
      'plan',
      'max_projects',
      'max_users',
      'max_storage',
      'created_at',
      'updated_at',
    ])
  ) {
    return false;
  }
  return (
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.name) &&
    isNonEmptyString(value.slug) &&
    (value.description === null ||
      typeof value.description === 'string') &&
    isNonEmptyString(value.owner_id) &&
    typeof value.plan === 'string' &&
    isTenantCreationPlan(value.plan) &&
    isPositiveSafeInteger(value.max_projects) &&
    isPositiveSafeInteger(value.max_users) &&
    isNonNegativeSafeInteger(value.max_storage) &&
    isNonEmptyString(value.created_at) &&
    (value.updated_at === null ||
      isNonEmptyString(value.updated_at))
  );
}

function isExactRecord(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value)
  ) {
    return false;
  }
  const actualKeys = Object.keys(value).sort();
  const expectedKeys = [...keys].sort();
  return (
    actualKeys.length === expectedKeys.length &&
    actualKeys.every((key, index) => key === expectedKeys[index])
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isPositiveSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
