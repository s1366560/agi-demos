import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TenantGene,
  TenantGeneInput,
  TenantGeneReview,
  TenantGenesSnapshot,
} from '../features/tenant-admin/tenantGenesClient';
import type {
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopTenantGenesLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantManagementScope;
  signal?: AbortSignal;
}>;
export type DesktopTenantGenesCreateInputV2 = DesktopTenantGenesLoadInputV2 &
  Readonly<{ input: TenantGeneInput }>;
export type DesktopTenantGenesGeneIdInputV2 = DesktopTenantGenesLoadInputV2 &
  Readonly<{ geneId: string }>;
export type DesktopTenantGenesUpdateInputV2 = DesktopTenantGenesGeneIdInputV2 &
  Readonly<{ input: Partial<TenantGeneInput> }>;
export type DesktopTenantGenesInstallInputV2 = DesktopTenantGenesGeneIdInputV2 &
  Readonly<{ instanceId: string }>;
export type DesktopTenantGenesRateInputV2 = DesktopTenantGenesGeneIdInputV2 &
  Readonly<{ rating: number; comment?: string }>;
export type DesktopTenantGenesCreateReviewInputV2 = DesktopTenantGenesGeneIdInputV2 &
  Readonly<{ rating: number; content: string }>;
export type DesktopTenantGenesDeleteReviewInputV2 = DesktopTenantGenesGeneIdInputV2 &
  Readonly<{ reviewId: string }>;

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const COMMON_KEYS = Object.freeze(['config', 'scope', 'signal']);
const GENE_INPUT_KEYS = Object.freeze([
  'name',
  'slug',
  'description',
  'category',
  'version',
  'visibility',
  'manifest',
]);
const MEMBER_ACTIONS = Object.freeze([
  'view',
  'list',
  'inspect-genome',
  'inspect-evolution',
  'list-reviews',
  'rate',
  'create-review',
  'delete-own-review',
]);
const ADMIN_ACTIONS = Object.freeze([
  ...MEMBER_ACTIONS,
  'create',
  'update',
  'delete',
  'publish',
  'unpublish',
  'install',
]);
const TENANT_ROLES = new Set(['owner', 'admin', 'member', 'editor', 'viewer']);

export function prepareDesktopTenantGenesLoadV2(
  input: DesktopTenantGenesLoadInputV2,
): DesktopTenantGenesLoadInputV2 {
  return Object.freeze(prepareCommon(input, COMMON_KEYS));
}

export function prepareDesktopTenantGenesCreateV2(
  input: DesktopTenantGenesCreateInputV2,
): DesktopTenantGenesCreateInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'input']);
  return Object.freeze({ ...common, input: freezeGeneInput(input.input, false) });
}

export function prepareDesktopTenantGenesGeneIdV2(
  input: DesktopTenantGenesGeneIdInputV2,
): DesktopTenantGenesGeneIdInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId']);
  return Object.freeze({ ...common, geneId: identifier(input.geneId) });
}

export function prepareDesktopTenantGenesUpdateV2(
  input: DesktopTenantGenesUpdateInputV2,
): DesktopTenantGenesUpdateInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId', 'input']);
  return Object.freeze({
    ...common,
    geneId: identifier(input.geneId),
    input: freezeGeneInput(input.input, true),
  });
}

export function prepareDesktopTenantGenesInstallV2(
  input: DesktopTenantGenesInstallInputV2,
): DesktopTenantGenesInstallInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId', 'instanceId']);
  return Object.freeze({
    ...common,
    geneId: identifier(input.geneId),
    instanceId: identifier(input.instanceId),
  });
}

export function prepareDesktopTenantGenesRateV2(
  input: DesktopTenantGenesRateInputV2,
): DesktopTenantGenesRateInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId', 'rating', 'comment']);
  return Object.freeze({
    ...common,
    geneId: identifier(input.geneId),
    rating: rating(input.rating),
    ...(input.comment === undefined ? {} : { comment: string(input.comment) }),
  });
}

export function prepareDesktopTenantGenesCreateReviewV2(
  input: DesktopTenantGenesCreateReviewInputV2,
): DesktopTenantGenesCreateReviewInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId', 'rating', 'content']);
  return Object.freeze({
    ...common,
    geneId: identifier(input.geneId),
    rating: rating(input.rating),
    content: identifier(input.content),
  });
}

export function prepareDesktopTenantGenesDeleteReviewV2(
  input: DesktopTenantGenesDeleteReviewInputV2,
): DesktopTenantGenesDeleteReviewInputV2 {
  const common = prepareCommon(input, [...COMMON_KEYS, 'geneId', 'reviewId']);
  return Object.freeze({
    ...common,
    geneId: identifier(input.geneId),
    reviewId: identifier(input.reviewId),
  });
}

export function freezeDesktopTenantGenesConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    Object.keys(config).length !== CONFIG_KEYS.length ||
    CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireDesktopTenantGenesSnapshotV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantGenesSnapshot {
  if (
    !record(value) ||
    !record(value.scope) ||
    !record(value.data) ||
    value.scope.authority !== scope.authority ||
    value.scope.tenantId !== scope.tenantId ||
    value.authority !== (scope.authority === 'cloud' ? 'cloud' : 'sidecar') ||
    !nonnegativeInteger(value.scopeRevision) ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    value.contractVersion !== '4.0.0' ||
    !TENANT_ROLES.has(value.data.membershipRole as string) ||
    value.membershipRole !== value.data.membershipRole ||
    value.genes !== value.data.genes ||
    value.total !== value.data.total ||
    value.page !== value.data.page ||
    value.pageSize !== value.data.pageSize ||
    !Array.isArray(value.data.genes) ||
    !nonnegativeInteger(value.data.total) ||
    !nonnegativeInteger(value.data.page) ||
    !nonnegativeInteger(value.data.pageSize)
  ) {
    throw invalidResponse();
  }
  const expectedActions =
    value.data.membershipRole === 'owner' || value.data.membershipRole === 'admin'
      ? ADMIN_ACTIONS
      : MEMBER_ACTIONS;
  if (!sameStrings(value.allowedActions, expectedActions)) throw invalidResponse();
  value.data.genes.forEach((gene) => requireDesktopTenantGeneV2(gene, scope));
  return value as unknown as TenantGenesSnapshot;
}

export function requireDesktopTenantGeneV2(
  value: unknown,
  scope: TenantManagementScope,
): TenantGene {
  if (
    !record(value) ||
    responseIdentifier(value.id) === null ||
    typeof value.name !== 'string' ||
    typeof value.slug !== 'string' ||
    (value.tenantId !== null && value.tenantId !== scope.tenantId) ||
    !nullableStringResponse(value.description) ||
    !nullableStringResponse(value.category) ||
    typeof value.version !== 'string' ||
    typeof value.visibility !== 'string' ||
    !nonnegativeInteger(value.installCount) ||
    !(value.averageRating === null || finiteNumber(value.averageRating)) ||
    typeof value.isPublished !== 'boolean' ||
    typeof value.createdAt !== 'string' ||
    !nullableStringResponse(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantGene;
}

export function requireDesktopTenantGeneReviewV2(
  value: unknown,
  geneId: string,
): TenantGeneReview {
  if (
    !record(value) ||
    responseIdentifier(value.id) === null ||
    value.geneId !== geneId ||
    responseIdentifier(value.userId) === null ||
    !validRating(value.rating) ||
    typeof value.content !== 'string' ||
    typeof value.createdAt !== 'string'
  ) {
    throw invalidResponse();
  }
  return value as unknown as TenantGeneReview;
}

export function requireDesktopTenantGeneReviewsV2(
  value: unknown,
  geneId: string,
): readonly TenantGeneReview[] {
  if (!Array.isArray(value)) throw invalidResponse();
  value.forEach((review) => requireDesktopTenantGeneReviewV2(review, geneId));
  return value as readonly TenantGeneReview[];
}

export function requireDesktopTenantGenesJsonRecordV2(
  value: unknown,
): Readonly<Record<string, unknown>> {
  if (!record(value)) throw invalidResponse();
  try {
    return freezeJsonRecord(value);
  } catch {
    throw invalidResponse();
  }
}

export function requireDesktopTenantGenesJsonRecordsV2(
  value: unknown,
): readonly Readonly<Record<string, unknown>>[] {
  if (!Array.isArray(value) || value.some((item) => !record(item))) throw invalidResponse();
  try {
    return Object.freeze(value.map((item) => freezeJsonRecord(item)));
  } catch {
    throw invalidResponse();
  }
}

export function requireDesktopTenantGenesVoidV2(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}

function prepareCommon(
  input: DesktopTenantGenesLoadInputV2,
  allowedKeys: readonly string[],
): DesktopTenantGenesLoadInputV2 {
  if (!record(input) || !exactKeys(input, ['config', 'scope'], allowedKeys)) throw invalidInput();
  const config = freezeDesktopTenantGenesConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId'], ['authority', 'tenantId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  ) {
    throw invalidInput();
  }
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalidInput();
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function freezeGeneInput(value: unknown, partial: boolean): TenantGeneInput {
  if (
    !record(value) ||
    Object.keys(value).some((key) => !GENE_INPUT_KEYS.includes(key)) ||
    (!partial && (!Object.hasOwn(value, 'name') || !Object.hasOwn(value, 'slug')))
  ) {
    throw invalidInput();
  }
  const input = value as Record<string, unknown>;
  const frozen: Record<string, unknown> = {};
  if (Object.hasOwn(input, 'name')) frozen.name = identifier(input.name);
  if (Object.hasOwn(input, 'slug')) frozen.slug = identifier(input.slug);
  if (Object.hasOwn(input, 'description')) frozen.description = nullableString(input.description);
  if (Object.hasOwn(input, 'category')) frozen.category = nullableString(input.category);
  if (Object.hasOwn(input, 'version')) frozen.version = identifier(input.version);
  if (Object.hasOwn(input, 'visibility')) frozen.visibility = identifier(input.visibility);
  if (Object.hasOwn(input, 'manifest')) {
    if (!record(input.manifest)) throw invalidInput();
    frozen.manifest = freezeJsonRecord(input.manifest);
  }
  return Object.freeze(frozen) as TenantGeneInput;
}

function freezeJsonRecord(value: Record<string, unknown>): Readonly<Record<string, unknown>> {
  return freezeJson(value, new WeakSet<object>()) as Readonly<Record<string, unknown>>;
}

function freezeJson(value: unknown, ancestors: WeakSet<object>): unknown {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    finiteNumber(value)
  ) {
    return value;
  }
  if (typeof value !== 'object' || ancestors.has(value)) throw invalidInput();
  ancestors.add(value);
  try {
    if (Array.isArray(value)) return Object.freeze(value.map((item) => freezeJson(item, ancestors)));
    if (!record(value)) throw invalidInput();
    return Object.freeze(
      Object.fromEntries(Object.entries(value).map(([key, item]) => [key, freezeJson(item, ancestors)])),
    );
  } finally {
    ancestors.delete(value);
  }
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  allowed: readonly string[],
): boolean {
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => allowed.includes(key))
  );
}

function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput();
  return value;
}

function responseIdentifier(value: unknown): string | null {
  return typeof value === 'string' && value && value === value.trim() ? value : null;
}

function string(value: unknown): string {
  if (typeof value !== 'string') throw invalidInput();
  return value;
}

function nullableString(value: unknown): string | null {
  if (value === null || typeof value === 'string') return value;
  throw invalidInput();
}

function nullableStringResponse(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function rating(value: unknown): number {
  if (!validRating(value)) throw invalidInput();
  return value;
}

function validRating(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 5;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function nonnegativeInteger(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function abortSignal(value: unknown): value is AbortSignal {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function'
  );
}

function sameStrings(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_genes_operation_input_invalid',
    'desktop tenant genes operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_genes_operation_response_invalid',
    'desktop tenant genes operation response invalid',
  );
}
