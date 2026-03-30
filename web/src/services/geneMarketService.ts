import { httpClient } from './client/httpClient';

const BASE_URL = '/genes';

export interface GeneCreate {
  name: string;
  description?: string | null;
  category?: string | null;
  version: string;
  manifest: Record<string, unknown>;
  visibility?: string;
  tags?: string[];
}

export interface GeneUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  version?: string;
  manifest?: Record<string, unknown>;
  visibility?: string;
  tags?: string[];
}

export interface GeneResponse {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  version: string;
  manifest: Record<string, unknown>;
  visibility: string;
  tags: string[];
  author_id: string | null;
  download_count: number;
  avg_rating: number | null;
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
  description?: string | null;
  gene_ids: string[];
  config?: Record<string, unknown>;
  visibility?: string;
}

export interface GenomeUpdate {
  name?: string;
  description?: string | null;
  gene_ids?: string[];
  config?: Record<string, unknown>;
  visibility?: string;
}

export interface GenomeResponse {
  id: string;
  name: string;
  description: string | null;
  gene_ids: string[];
  config: Record<string, unknown>;
  visibility: string;
  author_id: string | null;
  avg_rating: number | null;
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
  score: number;
  comment?: string | null;
}

export interface GeneRatingResponse {
  id: string;
  gene_id: string;
  user_id: string;
  score: number;
  comment: string | null;
  created_at: string;
}

export interface GenomeRatingCreate {
  score: number;
  comment?: string | null;
}

export interface GenomeRatingResponse {
  id: string;
  genome_id: string;
  user_id: string;
  score: number;
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
  installed_version: string;
  config_override: Record<string, unknown>;
  status: string;
  installed_at: string;
}

export interface EvolutionEventCreate {
  instance_id: string;
  gene_id: string;
  event_type: string;
  from_version?: string | null;
  to_version?: string | null;
  trigger?: string | null;
  payload?: Record<string, unknown>;
  status?: string;
}

export interface EvolutionEventResponse {
  id: string;
  instance_id: string;
  gene_id: string;
  event_type: string;
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
  listGenes: (params?: {
    page?: number;
    page_size?: number;
    category?: string;
    search?: string;
    visibility?: string;
  }) => httpClient.get<GeneListResponse>(BASE_URL, { params }),

  createGene: (data: GeneCreate) => httpClient.post<GeneResponse>(BASE_URL, data),

  getGene: (id: string) => httpClient.get<GeneResponse>(`${BASE_URL}/${id}`),

  updateGene: (id: string, data: GeneUpdate) =>
    httpClient.put<GeneResponse>(`${BASE_URL}/${id}`, data),

  deleteGene: (id: string) => httpClient.delete<unknown>(`${BASE_URL}/${id}`),

  listGenomes: (params?: { page?: number; page_size?: number }) =>
    httpClient.get<GenomeListResponse>(`${BASE_URL}/genomes`, { params }),

  createGenome: (data: GenomeCreate) =>
    httpClient.post<GenomeResponse>(`${BASE_URL}/genomes`, data),

  getGenome: (id: string) => httpClient.get<GenomeResponse>(`${BASE_URL}/genomes/${id}`),

  updateGenome: (id: string, data: GenomeUpdate) =>
    httpClient.put<GenomeResponse>(`${BASE_URL}/genomes/${id}`, data),

  deleteGenome: (id: string) => httpClient.delete<unknown>(`${BASE_URL}/genomes/${id}`),

  installGene: (instanceId: string, data: GeneInstallRequest) =>
    httpClient.post<InstanceGeneResponse>(`${BASE_URL}/instances/${instanceId}/install`, data),

  uninstallGene: (instanceId: string, instanceGeneId: string) =>
    httpClient.delete(`${BASE_URL}/instances/${instanceId}/genes/${instanceGeneId}`),

  listInstanceGenes: (instanceId: string) =>
    httpClient.get<InstanceGeneResponse[]>(`${BASE_URL}/instances/${instanceId}`),

  listGeneRatings: (geneId: string) =>
    httpClient.get<GeneRatingResponse[]>(`${BASE_URL}/${geneId}/ratings`),

  rateGene: (geneId: string, data: GeneRatingCreate) =>
    httpClient.post<GeneRatingResponse>(`${BASE_URL}/${geneId}/ratings`, data),

  listGenomeRatings: (genomeId: string) =>
    httpClient.get<GenomeRatingResponse[]>(`${BASE_URL}/genomes/${genomeId}/ratings`),

  rateGenome: (genomeId: string, data: GenomeRatingCreate) =>
    httpClient.post<GenomeRatingResponse>(`${BASE_URL}/genomes/${genomeId}/ratings`, data),

  listEvolutionEvents: (instanceId: string, params?: { page?: number; page_size?: number }) =>
    httpClient.get<EvolutionEventListResponse>(`${BASE_URL}/evolution`, {
      params: { instance_id: instanceId, ...params },
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
    httpClient.delete<unknown>(`${BASE_URL}/${geneId}/reviews/${reviewId}`),
};
