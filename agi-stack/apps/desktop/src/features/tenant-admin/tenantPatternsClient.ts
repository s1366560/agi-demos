import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  optionalText,
  requireFiniteNumber,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  tenantAdminError,
  type TenantAdminRole,
} from './tenantAdminHttp';
import {
  authorityFor,
  isRecord,
  observeTenantManagementRole,
  requestNativeEquivalentJson,
  requestTenantManagementNoContent,
  requireRecord,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_PATTERNS_ROUTE_ID = 'tenant-tenant-patterns' as const;
export const TENANT_PATTERNS_LOCAL_REASON =
  'local_workflow_patterns_authority_unavailable' as const;

export type TenantWorkflowPatternStep = Readonly<{
  toolName: string;
  toolParameters: Readonly<Record<string, unknown>>;
}>;
export type TenantWorkflowPattern = Readonly<{
  id: string;
  name: string;
  description: string | null;
  usageCount: number;
  successRate: number;
  updatedAt: string;
  steps: readonly TenantWorkflowPatternStep[];
}>;
export type TenantPatternsData = Readonly<{
  membershipRole: TenantAdminRole;
  patterns: readonly TenantWorkflowPattern[];
  total: number;
  page: number;
  pageSize: number;
}>;
export type TenantPatternsSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantPatternsData
> &
  TenantPatternsData;
export type TenantPatternsClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantPatternsSnapshot>;
  deletePattern: (
    scope: TenantManagementScope,
    patternId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
}>;

const MEMBER_ACTIONS = Object.freeze(['view', 'list']);
const ADMIN_ACTIONS = Object.freeze([...MEMBER_ACTIONS, 'delete']);

export function createTenantPatternsClient(config: DesktopRuntimeConfig): TenantPatternsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireTenantManagementScope(
        runtimeConfig,
        scope,
        'native_equivalent',
        TENANT_PATTERNS_LOCAL_REASON,
      );
      const params = new URLSearchParams({
        tenant_id: currentScope.tenantId,
        page: '1',
        page_size: '50',
      });
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () =>
          requestNativeEquivalentJson(
            runtimeConfig,
            `/api/v1/agent/workflows/patterns?${params.toString()}`,
            options ?? {},
            TENANT_PATTERNS_LOCAL_REASON,
          ),
      );
      const membershipRole = observation.membershipRole;
      const page = parsePatterns(observation.value);
      const data = Object.freeze({ membershipRole, ...page });
      return Object.freeze({
        scope: currentScope,
        scopeRevision: observation.scopeRevision,
        authority: authorityFor(runtimeConfig),
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions:
          membershipRole === 'owner' || membershipRole === 'admin'
            ? ADMIN_ACTIONS
            : MEMBER_ACTIONS,
        data,
        ...data,
      });
    },
    async deletePattern(scope, patternId, options) {
      const currentScope = requireTenantManagementScope(
        runtimeConfig,
        scope,
        'native_equivalent',
        TENANT_PATTERNS_LOCAL_REASON,
      );
      const role = await observeTenantManagementRole(runtimeConfig, currentScope, options);
      requirePatternAdmin(role);
      const params = new URLSearchParams({ tenant_id: currentScope.tenantId });
      try {
        await requestTenantManagementNoContent(
          runtimeConfig,
          `/api/v1/agent/workflows/patterns/${encodeURIComponent(
            requireIdentifier(patternId, 'tenant_patterns_pattern_id_required'),
          )}?${params.toString()}`,
          { ...options, method: 'DELETE' },
        );
      } catch (error) {
        rethrowLocalUnavailable(runtimeConfig, error);
      }
    },
  });
}

function parsePatterns(payload: unknown): Readonly<{
  patterns: readonly TenantWorkflowPattern[];
  total: number;
  page: number;
  pageSize: number;
}> {
  if (!isRecord(payload) || !Array.isArray(payload.patterns)) {
    throw tenantAdminError('tenant_patterns_list_contract_invalid');
  }
  return Object.freeze({
    patterns: Object.freeze(payload.patterns.map(parsePattern)),
    total: requireNonnegativeInteger(payload.total, 'tenant_patterns_list_contract_invalid'),
    page: requireNonnegativeInteger(payload.page, 'tenant_patterns_list_contract_invalid'),
    pageSize: requireNonnegativeInteger(
      payload.page_size,
      'tenant_patterns_list_contract_invalid',
    ),
  });
}

function parsePattern(value: unknown): TenantWorkflowPattern {
  if (!isRecord(value) || !Array.isArray(value.steps)) {
    throw tenantAdminError('tenant_patterns_pattern_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_patterns_pattern_contract_invalid'),
    name: requireText(value.name, 'tenant_patterns_pattern_contract_invalid'),
    description: optionalText(value.description, 'tenant_patterns_pattern_contract_invalid'),
    usageCount: requireNonnegativeInteger(
      value.usage_count,
      'tenant_patterns_pattern_contract_invalid',
    ),
    successRate: requireFiniteNumber(
      value.success_rate,
      'tenant_patterns_pattern_contract_invalid',
    ),
    updatedAt: requireText(value.updated_at, 'tenant_patterns_pattern_contract_invalid'),
    steps: Object.freeze(
      value.steps.map((step) => {
        if (!isRecord(step)) throw tenantAdminError('tenant_patterns_step_contract_invalid');
        return Object.freeze({
          toolName: requireText(step.tool_name, 'tenant_patterns_step_contract_invalid'),
          toolParameters: requireRecord(
            step.tool_parameters ?? {},
            'tenant_patterns_step_contract_invalid',
          ),
        });
      }),
    ),
  });
}

function requirePatternAdmin(role: TenantAdminRole): void {
  if (role !== 'owner' && role !== 'admin') {
    throw tenantAdminError('tenant_patterns_delete_forbidden', 403);
  }
}

function rethrowLocalUnavailable(config: DesktopRuntimeConfig, error: unknown): never {
  if (
    config.mode === 'local' &&
    error instanceof DesktopApiError &&
    (error.status === 404 || error.status === 501)
  ) {
    throw tenantAdminError(TENANT_PATTERNS_LOCAL_REASON, 501);
  }
  throw error;
}
