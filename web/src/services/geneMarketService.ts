import { httpClient } from './client/httpClient';

const BASE_URL = '/genes';

export interface TenantScopedOptions {
  tenant_id?: string | null | undefined;
}

export interface TenantScopedPaginationOptions extends TenantScopedOptions {
  limit?: number | undefined;
  offset?: number | undefined;
  search?: string | undefined;
}

const tenantParams = (options: TenantScopedOptions = {}): { tenant_id?: string } =>
  options.tenant_id ? { tenant_id: options.tenant_id } : {};

const tenantConfig = (options: TenantScopedOptions = {}) => {
  const params = tenantParams(options);
  return params.tenant_id ? { params } : undefined;
};

const getWithTenant = <T>(url: string, options?: TenantScopedOptions) => {
  const config = tenantConfig(options);
  return config ? httpClient.get<T>(url, config) : httpClient.get<T>(url);
};

const postWithTenant = <T>(url: string, data: unknown, options?: TenantScopedOptions) => {
  const config = tenantConfig(options);
  return config ? httpClient.post<T>(url, data, config) : httpClient.post<T>(url, data);
};

const putWithTenant = <T>(url: string, data: unknown, options?: TenantScopedOptions) => {
  const config = tenantConfig(options);
  return config ? httpClient.put<T>(url, data, config) : httpClient.put<T>(url, data);
};

const deleteWithTenant = <T = unknown>(url: string, options?: TenantScopedOptions) => {
  const config = tenantConfig(options);
  return config ? httpClient.delete<T>(url, config) : httpClient.delete<T>(url);
};

export interface GeneCreate {
  name: string;
  slug: string;
  tenant_id?: string | null;
  description?: string | null;
  short_description?: string | null;
  category?: string | null;
  version?: string;
  source?: string;
  source_ref?: string | null;
  icon?: string | null;
  manifest?: Record<string, unknown>;
  dependencies?: string[];
  synergies?: string[];
  parent_gene_id?: string | null;
  visibility?: string;
  tags?: string[];
}

export interface GeneUpdate {
  name?: string;
  slug?: string;
  description?: string | null;
  short_description?: string | null;
  category?: string | null;
  version?: string;
  source?: string;
  source_ref?: string | null;
  icon?: string | null;
  manifest?: Record<string, unknown>;
  dependencies?: string[];
  synergies?: string[];
  parent_gene_id?: string | null;
  visibility?: string;
  tags?: string[];
}

export interface GeneResponse {
  id: string;
  name: string;
  slug: string;
  tenant_id: string | null;
  description: string | null;
  short_description: string | null;
  category: string | null;
  version: string;
  source: string;
  source_ref: string | null;
  icon: string | null;
  manifest: Record<string, unknown>;
  dependencies: string[];
  synergies: string[];
  parent_gene_id: string | null;
  visibility: string;
  tags: string[];
  install_count: number;
  avg_rating: number | null;
  effectiveness_score: number | null;
  is_featured: boolean;
  review_status: string | null;
  is_published: boolean;
  created_by: string | null;
  created_by_instance_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface GeneListResponse {
  genes: GeneResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface GenomeCreate {
  name: string;
  slug: string;
  tenant_id?: string | null;
  description?: string | null;
  short_description?: string | null;
  icon?: string | null;
  gene_slugs?: string[];
  config_override?: Record<string, unknown>;
  visibility?: string;
}

export interface GenomeUpdate {
  name?: string;
  slug?: string;
  description?: string | null;
  short_description?: string | null;
  icon?: string | null;
  gene_slugs?: string[];
  config_override?: Record<string, unknown>;
  visibility?: string;
}

export interface GenomeResponse {
  id: string;
  name: string;
  slug: string;
  tenant_id: string | null;
  description: string | null;
  short_description: string | null;
  icon: string | null;
  gene_slugs: string[];
  config_override: Record<string, unknown>;
  visibility: string;
  install_count: number;
  avg_rating: number | null;
  is_featured: boolean;
  is_published: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface GenomeListResponse {
  genomes: GenomeResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface GeneRatingCreate {
  rating: number;
  comment?: string | null;
}

export interface GeneRatingResponse {
  id: string;
  gene_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface GenomeRatingCreate {
  rating: number;
  comment?: string | null;
}

export interface GenomeRatingResponse {
  id: string;
  genome_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface GeneInstallRequest {
  gene_id: string;
  config?: Record<string, unknown>;
}

export interface InstanceGeneResponse {
  id: string;
  instance_id: string;
  gene_id: string;
  genome_id: string | null;
  status: string;
  installed_version: string | null;
  config_snapshot: Record<string, unknown>;
  usage_count: number;
  installed_at: string | null;
  created_at: string;
  // Extra fields from gene details
  gene_name?: string;
  gene_description?: string;
  gene_category?: string;
}

export interface InstanceGeneListResponse {
  items: InstanceGeneResponse[];
  total: number;
  active_total: number;
  usage_total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface EvolutionEventCreate {
  instance_id: string;
  gene_id?: string | null;
  genome_id?: string | null;
  event_type: string;
  from_version?: string | null;
  to_version?: string | null;
  trigger?: string | null;
  payload?: Record<string, unknown>;
  status?: string;
  gene_name?: string;
  gene_slug?: string | null;
}

export interface EvolutionEventResponse {
  id: string;
  instance_id: string;
  gene_id: string | null;
  genome_id: string | null;
  event_type: string;
  gene_name: string;
  gene_slug: string | null;
  details: Record<string, unknown>;
  from_version: string | null;
  to_version: string | null;
  trigger: string | null;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface EvolutionEventListResponse {
  events: EvolutionEventResponse[];
  total: number;
  page: number;
  page_size: number;
}

export type EvolutionEventType =
  | 'learned'
  | 'forgot'
  | 'upgraded'
  | 'created_variant'
  | 'installed_genome'
  | 'uninstalled_genome'
  | 'simplified';

export interface GeneListParams {
  page?: number;
  page_size?: number;
  category?: string;
  search?: string | undefined;
  slugs?: string[];
  visibility?: string;
  is_published?: boolean;
  exclude_installed_instance_id?: string | undefined;
  tenant_id?: string | null | undefined;
}

const geneListParams = (params?: GeneListParams) => {
  if (!params?.slugs?.length) {
    return params;
  }
  return {
    ...params,
    slugs: params.slugs.join(','),
  };
};

export interface GenomeListParams {
  page?: number;
  page_size?: number;
  search?: string | undefined;
  visibility?: string;
  is_published?: boolean;
  tenant_id?: string | null | undefined;
}

export interface EvolutionEventListParams {
  page?: number;
  page_size?: number;
  event_type?: EvolutionEventType;
  tenant_id?: string | null | undefined;
}

export interface GeneReview {
  id: string;
  gene_id: string;
  user_id: string;
  rating: number;
  content: string;
  created_at: string;
}

export interface CreateReviewRequest {
  rating: number;
  content: string;
}

export interface GeneReviewListResponse {
  items: GeneReview[];
  total: number;
}

export const geneMarketService = {
  listGenes: (params?: GeneListParams) =>
    httpClient.get<GeneListResponse>(`${BASE_URL}/`, { params: geneListParams(params) }),

  createGene: (data: GeneCreate, options?: TenantScopedOptions) =>
    postWithTenant<GeneResponse>(`${BASE_URL}/`, data, options),

  getGene: (id: string, options?: TenantScopedOptions) =>
    getWithTenant<GeneResponse>(`${BASE_URL}/${id}`, options),

  updateGene: (id: string, data: GeneUpdate, options?: TenantScopedOptions) =>
    putWithTenant<GeneResponse>(`${BASE_URL}/${id}`, data, options),

  deleteGene: (id: string, options?: TenantScopedOptions) =>
    deleteWithTenant(`${BASE_URL}/${id}`, options),

  publishGene: (id: string, options?: TenantScopedOptions) =>
    postWithTenant<GeneResponse>(`${BASE_URL}/${id}/publish`, {}, options),

  unpublishGene: (id: string, options?: TenantScopedOptions) =>
    postWithTenant<GeneResponse>(`${BASE_URL}/${id}/unpublish`, {}, options),

  listGenomes: (params?: GenomeListParams) =>
    httpClient.get<GenomeListResponse>(`${BASE_URL}/genomes`, { params }),

  createGenome: (data: GenomeCreate, options?: TenantScopedOptions) =>
    postWithTenant<GenomeResponse>(`${BASE_URL}/genomes`, data, options),

  getGenome: (id: string, options?: TenantScopedOptions) =>
    getWithTenant<GenomeResponse>(`${BASE_URL}/genomes/${id}`, options),

  updateGenome: (id: string, data: GenomeUpdate, options?: TenantScopedOptions) =>
    putWithTenant<GenomeResponse>(`${BASE_URL}/genomes/${id}`, data, options),

  deleteGenome: (id: string, options?: TenantScopedOptions) =>
    deleteWithTenant(`${BASE_URL}/genomes/${id}`, options),

  publishGenome: (id: string, options?: TenantScopedOptions) =>
    postWithTenant<GenomeResponse>(`${BASE_URL}/genomes/${id}/publish`, {}, options),

  unpublishGenome: (id: string, options?: TenantScopedOptions) =>
    postWithTenant<GenomeResponse>(`${BASE_URL}/genomes/${id}/unpublish`, {}, options),

  installGene: (instanceId: string, data: GeneInstallRequest, options?: TenantScopedOptions) =>
    postWithTenant<InstanceGeneResponse>(
      `${BASE_URL}/instances/${instanceId}/install`,
      data,
      options
    ),

  uninstallGene: (instanceId: string, instanceGeneId: string, options?: TenantScopedOptions) =>
    deleteWithTenant(`${BASE_URL}/instances/${instanceId}/genes/${instanceGeneId}`, options),

  listInstanceGenes: (instanceId: string, options?: TenantScopedPaginationOptions) =>
    httpClient.get<InstanceGeneListResponse>(`${BASE_URL}/instances/${instanceId}/genes`, {
      params: {
        ...tenantParams(options),
        limit: options?.limit,
        offset: options?.offset,
        search: options?.search,
      },
    }),

  listGeneRatings: (geneId: string, options?: TenantScopedOptions) =>
    getWithTenant<GeneRatingResponse[]>(`${BASE_URL}/${geneId}/ratings`, options),

  rateGene: (geneId: string, data: GeneRatingCreate, options?: TenantScopedOptions) =>
    postWithTenant<GeneRatingResponse>(`${BASE_URL}/${geneId}/ratings`, data, options),

  listGenomeRatings: (genomeId: string, options?: TenantScopedOptions) =>
    getWithTenant<GenomeRatingResponse[]>(`${BASE_URL}/genomes/${genomeId}/ratings`, options),

  rateGenome: (genomeId: string, data: GenomeRatingCreate, options?: TenantScopedOptions) =>
    postWithTenant<GenomeRatingResponse>(`${BASE_URL}/genomes/${genomeId}/ratings`, data, options),

  listEvolutionEvents: (instanceId: string, params?: EvolutionEventListParams) =>
    httpClient.get<EvolutionEventListResponse>(`${BASE_URL}/evolution`, {
      params: { instance_id: instanceId, ...params },
    }),

  listGeneEvolutionEvents: (geneId: string, params?: EvolutionEventListParams) =>
    httpClient.get<EvolutionEventListResponse>(`${BASE_URL}/evolution`, {
      params: { gene_id: geneId, ...params },
    }),

  createEvolutionEvent: (data: EvolutionEventCreate, options?: TenantScopedOptions) =>
    postWithTenant<EvolutionEventResponse>(`${BASE_URL}/evolution`, data, options),

  getEvolutionEvent: (id: string, options?: TenantScopedOptions) =>
    getWithTenant<EvolutionEventResponse>(`${BASE_URL}/evolution/${id}`, options),
  getGeneReviews: (geneId: string, page = 1, pageSize = 10, options: TenantScopedOptions = {}) =>
    httpClient.get<GeneReviewListResponse>(`${BASE_URL}/${geneId}/reviews`, {
      params: { page, page_size: pageSize, ...tenantParams(options) },
    }),

  createGeneReview: (geneId: string, data: CreateReviewRequest, options?: TenantScopedOptions) =>
    postWithTenant<GeneReview>(`${BASE_URL}/${geneId}/reviews`, data, options),

  deleteGeneReview: (geneId: string, reviewId: string, options?: TenantScopedOptions) =>
    deleteWithTenant(`${BASE_URL}/${geneId}/reviews/${reviewId}`, options),
};
