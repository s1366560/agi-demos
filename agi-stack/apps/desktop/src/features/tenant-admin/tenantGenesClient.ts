import type { TenantAdminRole } from './tenantAdminHttp';
import type {
  TenantManagementAuthoritySnapshot,
  TenantManagementRequestOptions,
  TenantManagementScope,
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
