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
  requireBoolean,
  requireRecord,
  requireRole,
  requireTenantManagementScope,
  withStableTenantManagementAuthority,
  type TenantManagementAuthoritySnapshot,
  type TenantManagementRequestOptions,
  type TenantManagementScope,
} from './tenantManagementHttp';

export const TENANT_GENES_ROUTE_ID = 'tenant-tenant-genes' as const;
export const TENANT_GENES_LOCAL_REASON = 'local_gene_market_authority_unavailable' as const;

export type TenantGene = Readonly<{
  id: string;
  name: string;
  slug: string;
  tenantId: string | null;
  description: string | null;
  category: string | null;
  version: string;
  visibility: string;
  installCount: number;
  averageRating: number | null;
  isPublished: boolean;
  createdAt: string;
  updatedAt: string | null;
}>;
export type TenantGeneInput = Readonly<{
  name: string;
  slug: string;
  description?: string | null;
  category?: string | null;
  version?: string;
  visibility?: string;
  manifest?: Readonly<Record<string, unknown>>;
}>;
export type TenantGeneReview = Readonly<{
  id: string;
  geneId: string;
  userId: string;
  rating: number;
  content: string;
  createdAt: string;
}>;
export type TenantGenesData = Readonly<{
  membershipRole: TenantAdminRole;
  genes: readonly TenantGene[];
  total: number;
  page: number;
  pageSize: number;
}>;
export type TenantGenesSnapshot = TenantManagementAuthoritySnapshot<
  TenantManagementScope,
  TenantGenesData
> &
  TenantGenesData;
export type TenantGenesClient = Readonly<{
  load: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGenesSnapshot>;
  createGene: (
    scope: TenantManagementScope,
    input: TenantGeneInput,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGene>;
  updateGene: (
    scope: TenantManagementScope,
    geneId: string,
    input: Partial<TenantGeneInput>,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGene>;
  deleteGene: (
    scope: TenantManagementScope,
    geneId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
  publishGene: (
    scope: TenantManagementScope,
    geneId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGene>;
  unpublishGene: (
    scope: TenantManagementScope,
    geneId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGene>;
  installGene: (
    scope: TenantManagementScope,
    instanceId: string,
    geneId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
  rateGene: (
    scope: TenantManagementScope,
    geneId: string,
    rating: number,
    comment?: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
  listGenomes: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<readonly Readonly<Record<string, unknown>>[]>;
  listEvolution: (
    scope: TenantManagementScope,
    options?: TenantManagementRequestOptions,
  ) => Promise<Readonly<Record<string, unknown>>>;
  listReviews: (
    scope: TenantManagementScope,
    geneId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<readonly TenantGeneReview[]>;
  createReview: (
    scope: TenantManagementScope,
    geneId: string,
    rating: number,
    content: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<TenantGeneReview>;
  deleteReview: (
    scope: TenantManagementScope,
    geneId: string,
    reviewId: string,
    options?: TenantManagementRequestOptions,
  ) => Promise<void>;
}>;

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

export function createTenantGenesClient(config: DesktopRuntimeConfig): TenantGenesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const scopeFor = (scope: TenantManagementScope) =>
    requireTenantManagementScope(
      runtimeConfig,
      scope,
      'native_equivalent',
      TENANT_GENES_LOCAL_REASON,
    );
  const nativeJson = (
    path: string,
    options: TenantManagementRequestOptions &
      Readonly<{
        method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
        body?: Readonly<Record<string, unknown>> | null;
      }> = {},
  ) => requestNativeEquivalentJson(runtimeConfig, path, options, TENANT_GENES_LOCAL_REASON);
  return Object.freeze({
    async load(scope, options) {
      const currentScope = scopeFor(scope);
      const params = new URLSearchParams({
        tenant_id: currentScope.tenantId,
        page: '1',
        page_size: '20',
      });
      const observation = await withStableTenantManagementAuthority(
        runtimeConfig,
        currentScope,
        options,
        () => nativeJson(`/api/v1/genes/?${params.toString()}`, options),
      );
      const membershipRole = observation.membershipRole;
      const page = parseGenePage(observation.value, currentScope);
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
    async createGene(scope, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await nativeJson(withTenantQuery('/api/v1/genes/', currentScope), {
        ...options,
        method: 'POST',
        body: geneBody(input, currentScope, false),
      });
      return parseGene(payload, currentScope);
    },
    async updateGene(scope, geneId, input, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await nativeJson(withTenantQuery(geneResourcePath(geneId), currentScope), {
        ...options,
        method: 'PUT',
        body: geneBody(input, currentScope, true),
      });
      return parseGene(payload, currentScope);
    },
    async deleteGene(scope, geneId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      await nativeNoContent(
        runtimeConfig,
        withTenantQuery(geneResourcePath(geneId), currentScope),
        {
          ...options,
          method: 'DELETE',
        },
      );
    },
    async publishGene(scope, geneId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      return parseGene(
        await nativeJson(
          withTenantQuery(`${geneResourcePath(geneId)}/publish`, currentScope),
          {
            ...options,
            method: 'POST',
            body: null,
          },
        ),
        currentScope,
      );
    },
    async unpublishGene(scope, geneId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      return parseGene(
        await nativeJson(
          withTenantQuery(`${geneResourcePath(geneId)}/unpublish`, currentScope),
          {
            ...options,
            method: 'POST',
            body: null,
          },
        ),
        currentScope,
      );
    },
    async installGene(scope, instanceId, geneId, options) {
      const currentScope = scopeFor(scope);
      await requireAdmin(runtimeConfig, currentScope, options);
      const payload = await nativeJson(
        `/api/v1/genes/instances/${encodeURIComponent(
          requireIdentifier(instanceId, 'tenant_genes_instance_id_required'),
        )}/install?tenant_id=${encodeURIComponent(currentScope.tenantId)}`,
        {
          ...options,
          method: 'POST',
          body: {
            gene_id: requireIdentifier(geneId, 'tenant_genes_gene_id_required'),
            config: {},
          },
        },
      );
      return requireRecord(payload, 'tenant_genes_install_contract_invalid');
    },
    async rateGene(scope, geneId, rating, comment, options) {
      const currentScope = scopeFor(scope);
      const payload = await nativeJson(
        withTenantQuery(`${geneResourcePath(geneId)}/ratings`, currentScope),
        {
          ...options,
          method: 'POST',
          body: { rating: requireRating(rating), comment: comment?.trim() || null },
        },
      );
      return requireRecord(payload, 'tenant_genes_rating_contract_invalid');
    },
    async listGenomes(scope, options) {
      const currentScope = scopeFor(scope);
      const params = new URLSearchParams({
        tenant_id: currentScope.tenantId,
        page: '1',
        page_size: '20',
      });
      const payload = await nativeJson(`/api/v1/genes/genomes?${params.toString()}`, options);
      if (!isRecord(payload) || !Array.isArray(payload.genomes)) {
        throw tenantAdminError('tenant_genes_genomes_contract_invalid');
      }
      return Object.freeze(
        payload.genomes.map((item) =>
          requireRecord(item, 'tenant_genes_genome_contract_invalid'),
        ),
      );
    },
    async listEvolution(scope, options) {
      const currentScope = scopeFor(scope);
      const payload = await nativeJson(
        `/api/v1/genes/evolution?tenant_id=${encodeURIComponent(currentScope.tenantId)}`,
        options,
      );
      return requireRecord(payload, 'tenant_genes_evolution_contract_invalid');
    },
    async listReviews(scope, geneId, options) {
      const currentScope = scopeFor(scope);
      const payload = await nativeJson(
        withTenantQuery(`${geneResourcePath(geneId)}/reviews`, currentScope, {
          page: '1',
          page_size: '50',
        }),
        options,
      );
      if (!isRecord(payload) || !Array.isArray(payload.items)) {
        throw tenantAdminError('tenant_genes_reviews_contract_invalid');
      }
      return Object.freeze(payload.items.map(parseReview));
    },
    async createReview(scope, geneId, rating, content, options) {
      const currentScope = scopeFor(scope);
      return parseReview(
        await nativeJson(
          withTenantQuery(`${geneResourcePath(geneId)}/reviews`, currentScope),
          {
            ...options,
            method: 'POST',
            body: {
              rating: requireRating(rating),
              content: requireIdentifier(content, 'tenant_genes_review_content_required'),
            },
          },
        ),
      );
    },
    async deleteReview(scope, geneId, reviewId, options) {
      const currentScope = scopeFor(scope);
      await nativeNoContent(
        runtimeConfig,
        withTenantQuery(
          `${geneResourcePath(geneId)}/reviews/${encodeURIComponent(
            requireIdentifier(reviewId, 'tenant_genes_review_id_required'),
          )}`,
          currentScope,
        ),
        { ...options, method: 'DELETE' },
      );
    },
  });
}

async function requireAdmin(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): Promise<void> {
  const role = await observeTenantManagementRole(config, scope, options);
  requireRole(role, ['owner', 'admin'], 'tenant_genes_admin_required');
}

async function nativeNoContent(
  config: DesktopRuntimeConfig,
  path: string,
  options: TenantManagementRequestOptions & Readonly<{ method: 'DELETE' }>,
): Promise<void> {
  try {
    await requestTenantManagementNoContent(config, path, options);
  } catch (error) {
    if (
      config.mode === 'local' &&
      error instanceof DesktopApiError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw tenantAdminError(TENANT_GENES_LOCAL_REASON, 501);
    }
    throw error;
  }
}

function geneResourcePath(geneId: string): string {
  return `/api/v1/genes/${encodeURIComponent(
    requireIdentifier(geneId, 'tenant_genes_gene_id_required'),
  )}`;
}

function withTenantQuery(
  path: string,
  scope: TenantManagementScope,
  extra: Readonly<Record<string, string>> = {},
): string {
  const params = new URLSearchParams({ tenant_id: scope.tenantId, ...extra });
  return `${path}?${params.toString()}`;
}

function geneBody(
  input: Partial<TenantGeneInput>,
  scope: TenantManagementScope,
  partial: boolean,
): Readonly<Record<string, unknown>> {
  const body: Record<string, unknown> = {};
  if (!partial || input.name !== undefined) {
    body.name = requireIdentifier(input.name, 'tenant_genes_name_required');
  }
  if (!partial || input.slug !== undefined) {
    body.slug = requireIdentifier(input.slug, 'tenant_genes_slug_required');
  }
  if (!partial) body.tenant_id = scope.tenantId;
  if (input.description !== undefined) body.description = input.description;
  if (input.category !== undefined) body.category = input.category;
  if (input.version !== undefined || !partial) body.version = input.version ?? '1.0.0';
  if (input.visibility !== undefined || !partial) body.visibility = input.visibility ?? 'tenant';
  if (input.manifest !== undefined || !partial) body.manifest = { ...(input.manifest ?? {}) };
  return Object.freeze(body);
}

function parseGenePage(
  payload: unknown,
  scope: TenantManagementScope,
): Readonly<{ genes: readonly TenantGene[]; total: number; page: number; pageSize: number }> {
  if (!isRecord(payload) || !Array.isArray(payload.genes)) {
    throw tenantAdminError('tenant_genes_list_contract_invalid');
  }
  return Object.freeze({
    genes: Object.freeze(payload.genes.map((item) => parseGene(item, scope))),
    total: requireNonnegativeInteger(payload.total, 'tenant_genes_list_contract_invalid'),
    page: requireNonnegativeInteger(payload.page, 'tenant_genes_list_contract_invalid'),
    pageSize: requireNonnegativeInteger(payload.page_size, 'tenant_genes_list_contract_invalid'),
  });
}

function parseGene(value: unknown, scope: TenantManagementScope): TenantGene {
  if (!isRecord(value)) throw tenantAdminError('tenant_genes_gene_contract_invalid');
  const tenantId = optionalText(value.tenant_id, 'tenant_genes_gene_contract_invalid');
  if (tenantId !== null && tenantId !== scope.tenantId) {
    throw tenantAdminError('tenant_genes_gene_scope_mismatch', 409);
  }
  const averageRating = value.avg_rating === null || value.avg_rating === undefined
    ? null
    : requireFiniteNumber(value.avg_rating, 'tenant_genes_gene_contract_invalid');
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_genes_gene_contract_invalid'),
    name: requireText(value.name, 'tenant_genes_gene_contract_invalid'),
    slug: requireText(value.slug, 'tenant_genes_gene_contract_invalid'),
    tenantId,
    description: optionalText(value.description, 'tenant_genes_gene_contract_invalid'),
    category: optionalText(value.category, 'tenant_genes_gene_contract_invalid'),
    version: requireText(value.version, 'tenant_genes_gene_contract_invalid'),
    visibility: requireText(value.visibility, 'tenant_genes_gene_contract_invalid'),
    installCount: requireNonnegativeInteger(
      value.install_count,
      'tenant_genes_gene_contract_invalid',
    ),
    averageRating,
    isPublished: requireBoolean(value.is_published, 'tenant_genes_gene_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_genes_gene_contract_invalid'),
    updatedAt: optionalText(value.updated_at, 'tenant_genes_gene_contract_invalid'),
  });
}

function parseReview(value: unknown): TenantGeneReview {
  if (!isRecord(value)) throw tenantAdminError('tenant_genes_review_contract_invalid');
  return Object.freeze({
    id: requireIdentifier(value.id, 'tenant_genes_review_contract_invalid'),
    geneId: requireIdentifier(value.gene_id, 'tenant_genes_review_contract_invalid'),
    userId: requireIdentifier(value.user_id, 'tenant_genes_review_contract_invalid'),
    rating: requireRating(value.rating),
    content: requireText(value.content, 'tenant_genes_review_contract_invalid'),
    createdAt: requireText(value.created_at, 'tenant_genes_review_contract_invalid'),
  });
}

function requireRating(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 5) {
    throw tenantAdminError('tenant_genes_rating_invalid', 422);
  }
  return value;
}
