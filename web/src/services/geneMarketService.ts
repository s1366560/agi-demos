import { httpClient } from './client/httpClient';

const BASE_URL = '/genes';

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
  search?: string;
  visibility?: string;
  is_published?: boolean;
}

export interface GenomeListParams {
  page?: number;
  page_size?: number;
  is_published?: boolean;
}

export interface EvolutionEventListParams {
  page?: number;
  page_size?: number;
  event_type?: EvolutionEventType;
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
    httpClient.get<GeneListResponse>(`${BASE_URL}/`, { params }),

  createGene: (data: GeneCreate) => httpClient.post<GeneResponse>(`${BASE_URL}/`, data),

  getGene: (id: string) => httpClient.get<GeneResponse>(`${BASE_URL}/${id}`),

  updateGene: (id: string, data: GeneUpdate) =>
    httpClient.put<GeneResponse>(`${BASE_URL}/${id}`, data),

  deleteGene: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  listGenomes: (params?: GenomeListParams) =>
    httpClient.get<GenomeListResponse>(`${BASE_URL}/genomes`, { params }),

  createGenome: (data: GenomeCreate) =>
    httpClient.post<GenomeResponse>(`${BASE_URL}/genomes`, data),

  getGenome: (id: string) => httpClient.get<GenomeResponse>(`${BASE_URL}/genomes/${id}`),

  updateGenome: (id: string, data: GenomeUpdate) =>
    httpClient.put<GenomeResponse>(`${BASE_URL}/genomes/${id}`, data),

  deleteGenome: (id: string) => httpClient.delete(`${BASE_URL}/genomes/${id}`),

  installGene: (instanceId: string, data: GeneInstallRequest) =>
    httpClient.post<InstanceGeneResponse>(`${BASE_URL}/instances/${instanceId}/install`, data),

  uninstallGene: (instanceId: string, instanceGeneId: string) =>
    httpClient.delete(`${BASE_URL}/instances/${instanceId}/genes/${instanceGeneId}`),

  listInstanceGenes: (instanceId: string) =>
    httpClient.get<InstanceGeneListResponse>(`${BASE_URL}/instances/${instanceId}/genes`),

  listGeneRatings: (geneId: string) =>
    httpClient.get<GeneRatingResponse[]>(`${BASE_URL}/${geneId}/ratings`),

  rateGene: (geneId: string, data: GeneRatingCreate) =>
    httpClient.post<GeneRatingResponse>(`${BASE_URL}/${geneId}/ratings`, data),

  listGenomeRatings: (genomeId: string) =>
    httpClient.get<GenomeRatingResponse[]>(`${BASE_URL}/genomes/${genomeId}/ratings`),

  rateGenome: (genomeId: string, data: GenomeRatingCreate) =>
    httpClient.post<GenomeRatingResponse>(`${BASE_URL}/genomes/${genomeId}/ratings`, data),

  listEvolutionEvents: (instanceId: string, params?: EvolutionEventListParams) =>
    httpClient.get<EvolutionEventListResponse>(`${BASE_URL}/evolution`, {
      params: { instance_id: instanceId, ...params },
    }),

  listGeneEvolutionEvents: (geneId: string, params?: EvolutionEventListParams) =>
    httpClient.get<EvolutionEventListResponse>(`${BASE_URL}/evolution`, {
      params: { gene_id: geneId, ...params },
    }),

  createEvolutionEvent: (data: EvolutionEventCreate) =>
    httpClient.post<EvolutionEventResponse>(`${BASE_URL}/evolution`, data),

  getEvolutionEvent: (id: string) =>
    httpClient.get<EvolutionEventResponse>(`${BASE_URL}/evolution/${id}`),
  getGeneReviews: (geneId: string, page = 1, pageSize = 10) =>
    httpClient.get<GeneReviewListResponse>(`${BASE_URL}/${geneId}/reviews`, {
      params: { page, page_size: pageSize },
    }),

  createGeneReview: (geneId: string, data: CreateReviewRequest) =>
    httpClient.post<GeneReview>(`${BASE_URL}/${geneId}/reviews`, data),

  deleteGeneReview: (geneId: string, reviewId: string) =>
    httpClient.delete(`${BASE_URL}/${geneId}/reviews/${reviewId}`),
};
