import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { geneMarketService } from '../services/geneMarketService';

import type {
  GeneResponse,
  GeneCreate,
  GeneUpdate,
  GenomeResponse,
  GenomeCreate,
  GenomeUpdate,
  InstanceGeneResponse,
  EvolutionEventResponse,
  GeneInstallRequest,
  GeneRatingCreate,
  GenomeRatingCreate,
  EvolutionEventCreate,
  GeneListParams,
  GenomeListParams,
  EvolutionEventListParams,
  GeneReview,
  CreateReviewRequest,
  TenantScopedOptions,
} from '../services/geneMarketService';

// ============================================================================
// ERROR HELPER
// ============================================================================

interface UnknownError {
  response?: { data?: { detail?: string | Record<string, unknown> } };
  message?: string;
}

function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) return err.message;
  return fallback;
}

const GENE_SLUG_LOOKUP_BATCH_SIZE = 100;

const normalizeSlugs = (slugs: string[]): string[] =>
  Array.from(new Set(slugs.map((slug) => slug.trim()).filter(Boolean)));

const orderGenesBySlugs = (genes: GeneResponse[], slugs: string[]): GeneResponse[] => {
  const genesBySlug = new Map(genes.map((gene) => [gene.slug, gene]));
  return slugs.flatMap((slug) => {
    const gene = genesBySlug.get(slug);
    return gene ? [gene] : [];
  });
};

const decrementNonNegative = (value: number): number => Math.max(0, value - 1);

type DetailRequestScope = 'currentGene' | 'currentGenome' | 'currentGenomeGenes';
type ListRequestScope = 'genes' | 'genomes' | 'installedGenes' | 'reviews' | 'evolutionEvents';

const detailRequestVersions: Record<DetailRequestScope, number> = {
  currentGene: 0,
  currentGenome: 0,
  currentGenomeGenes: 0,
};

const listRequestVersions: Record<ListRequestScope, number> = {
  genes: 0,
  genomes: 0,
  installedGenes: 0,
  reviews: 0,
  evolutionEvents: 0,
};

const nextDetailRequestVersion = (scope: DetailRequestScope): number => {
  detailRequestVersions[scope] += 1;
  return detailRequestVersions[scope];
};

const isLatestDetailRequest = (scope: DetailRequestScope, version: number): boolean =>
  detailRequestVersions[scope] === version;

const nextListRequestVersion = (scope: ListRequestScope): number => {
  listRequestVersions[scope] += 1;
  return listRequestVersions[scope];
};

const isLatestListRequest = (scope: ListRequestScope, version: number): boolean =>
  listRequestVersions[scope] === version;

const invalidateDetailRequests = (...scopes: DetailRequestScope[]): void => {
  scopes.forEach((scope) => {
    detailRequestVersions[scope] += 1;
  });
};

const invalidateListRequests = (...scopes: ListRequestScope[]): void => {
  scopes.forEach((scope) => {
    listRequestVersions[scope] += 1;
  });
};

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface GeneMarketState {
  genes: GeneResponse[];
  currentGene: GeneResponse | null;
  genomes: GenomeResponse[];
  currentGenome: GenomeResponse | null;
  currentGenomeGenes: GeneResponse[];
  installedGenes: InstanceGeneResponse[];
  evolutionEvents: EvolutionEventResponse[];
  evolutionTotal: number;
  geneTotal: number;
  genomeTotal: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isSubmitting: boolean;
  currentGenomeGenesLoading: boolean;
  error: string | null;
  activeTab: 'genes' | 'genomes';
  reviews: GeneReview[];
  reviewsTotal: number;
  reviewsLoading: boolean;

  // Actions - Gene CRUD
  listGenes: (params?: GeneListParams) => Promise<void>;
  getGene: (id: string, options?: TenantScopedOptions) => Promise<GeneResponse>;
  createGene: (data: GeneCreate, options?: TenantScopedOptions) => Promise<GeneResponse>;
  updateGene: (
    id: string,
    data: GeneUpdate,
    options?: TenantScopedOptions
  ) => Promise<GeneResponse>;
  deleteGene: (id: string, options?: TenantScopedOptions) => Promise<void>;
  publishGene: (id: string, options?: TenantScopedOptions) => Promise<GeneResponse>;
  unpublishGene: (id: string, options?: TenantScopedOptions) => Promise<GeneResponse>;

  // Actions - Genome CRUD
  listGenomes: (params?: GenomeListParams) => Promise<void>;
  getGenome: (id: string, options?: TenantScopedOptions) => Promise<GenomeResponse>;
  fetchGenomeGenes: (slugs: string[], options?: TenantScopedOptions) => Promise<GeneResponse[]>;
  createGenome: (data: GenomeCreate, options?: TenantScopedOptions) => Promise<GenomeResponse>;
  updateGenome: (
    id: string,
    data: GenomeUpdate,
    options?: TenantScopedOptions
  ) => Promise<GenomeResponse>;
  deleteGenome: (id: string, options?: TenantScopedOptions) => Promise<void>;
  publishGenome: (id: string, options?: TenantScopedOptions) => Promise<GenomeResponse>;
  unpublishGenome: (id: string, options?: TenantScopedOptions) => Promise<GenomeResponse>;

  // Actions - Install
  installGene: (
    instanceId: string,
    data: GeneInstallRequest,
    options?: TenantScopedOptions
  ) => Promise<void>;
  uninstallGene: (
    instanceId: string,
    instanceGeneId: string,
    options?: TenantScopedOptions
  ) => Promise<void>;
  listInstalledGenes: (instanceId: string, options?: TenantScopedOptions) => Promise<void>;

  // Actions - Reviews
  fetchGeneReviews: (
    geneId: string,
    page?: number,
    pageSize?: number,
    options?: TenantScopedOptions
  ) => Promise<void>;
  createGeneReview: (
    geneId: string,
    data: CreateReviewRequest,
    options?: TenantScopedOptions
  ) => Promise<void>;
  deleteGeneReview: (
    geneId: string,
    reviewId: string,
    options?: TenantScopedOptions
  ) => Promise<void>;

  // Actions - Ratings
  rateGene: (
    geneId: string,
    data: GeneRatingCreate,
    options?: TenantScopedOptions
  ) => Promise<void>;
  rateGenome: (
    genomeId: string,
    data: GenomeRatingCreate,
    options?: TenantScopedOptions
  ) => Promise<void>;

  // Actions - Evolution
  listEvolutionEvents: (instanceId: string, params?: EvolutionEventListParams) => Promise<void>;
  listGeneEvolutionEvents: (geneId: string, params?: EvolutionEventListParams) => Promise<void>;
  getEvolutionEvent: (id: string, options?: TenantScopedOptions) => Promise<EvolutionEventResponse>;
  createEvolutionEvent: (
    data: EvolutionEventCreate,
    options?: TenantScopedOptions
  ) => Promise<EvolutionEventResponse>;

  // Actions - UI
  setActiveTab: (tab: 'genes' | 'genomes') => void;
  setCurrentGene: (gene: GeneResponse | null) => void;
  setCurrentGenome: (genome: GenomeResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

type GeneMarketDataState = Pick<
  GeneMarketState,
  | 'genes'
  | 'currentGene'
  | 'genomes'
  | 'currentGenome'
  | 'currentGenomeGenes'
  | 'installedGenes'
  | 'evolutionEvents'
  | 'evolutionTotal'
  | 'geneTotal'
  | 'genomeTotal'
  | 'page'
  | 'pageSize'
  | 'isLoading'
  | 'isSubmitting'
  | 'currentGenomeGenesLoading'
  | 'error'
  | 'activeTab'
  | 'reviews'
  | 'reviewsTotal'
  | 'reviewsLoading'
>;

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState: GeneMarketDataState = {
  genes: [] as GeneResponse[],
  currentGene: null as GeneResponse | null,
  genomes: [] as GenomeResponse[],
  currentGenome: null as GenomeResponse | null,
  currentGenomeGenes: [] as GeneResponse[],
  installedGenes: [] as InstanceGeneResponse[],
  evolutionEvents: [] as EvolutionEventResponse[],
  evolutionTotal: 0,
  geneTotal: 0,
  genomeTotal: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  currentGenomeGenesLoading: false,
  error: null as string | null,
  activeTab: 'genes' as const,
  reviews: [] as GeneReview[],
  reviewsTotal: 0,
  reviewsLoading: false,
};

// ============================================================================
// STORE
// ============================================================================

export const useGeneMarketStore = create<GeneMarketState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== Gene CRUD ==========

      listGenes: async (params = {}) => {
        const requestVersion = nextListRequestVersion('genes');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGenes(params);
          if (isLatestListRequest('genes', requestVersion)) {
            set({
              genes: response.genes,
              geneTotal: response.total,
              isLoading: false,
            });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('genes', requestVersion)) {
            set({ error: getErrorMessage(error, 'Failed to list genes'), isLoading: false });
          }
          throw error;
        }
      },

      getGene: async (id: string, options?: TenantScopedOptions) => {
        const requestVersion = nextDetailRequestVersion('currentGene');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGene(id, options);
          if (isLatestDetailRequest('currentGene', requestVersion)) {
            set({ currentGene: response, isLoading: false });
          }
          return response;
        } catch (error: unknown) {
          if (isLatestDetailRequest('currentGene', requestVersion)) {
            set({ error: getErrorMessage(error, 'Failed to get gene'), isLoading: false });
          }
          throw error;
        }
      },

      createGene: async (data: GeneCreate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createGene(data, options);
          const { genes } = get();
          set({
            genes: [response, ...genes],
            geneTotal: get().geneTotal + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create gene'), isSubmitting: false });
          throw error;
        }
      },

      updateGene: async (id: string, data: GeneUpdate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.updateGene(id, data, options);
          const { genes } = get();
          set({
            genes: genes.map((g) => (g.id === id ? response : g)),
            currentGene: get().currentGene?.id === id ? response : get().currentGene,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to update gene'), isSubmitting: false });
          throw error;
        }
      },

      deleteGene: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGene(id, options);
          const { genes } = get();
          set({
            genes: genes.filter((g) => g.id !== id),
            currentGene: get().currentGene?.id === id ? null : get().currentGene,
            geneTotal: decrementNonNegative(get().geneTotal),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete gene'), isSubmitting: false });
          throw error;
        }
      },

      publishGene: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.publishGene(id, options);
          const { genes, currentGene } = get();
          set({
            genes: genes.map((g) => (g.id === id ? response : g)),
            currentGene: currentGene?.id === id ? response : currentGene,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to publish gene'), isSubmitting: false });
          throw error;
        }
      },

      unpublishGene: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.unpublishGene(id, options);
          const { genes, currentGene } = get();
          set({
            genes: genes.map((g) => (g.id === id ? response : g)),
            currentGene: currentGene?.id === id ? response : currentGene,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to unpublish gene'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Genome CRUD ==========

      listGenomes: async (params = {}) => {
        const requestVersion = nextListRequestVersion('genomes');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGenomes(params);
          if (isLatestListRequest('genomes', requestVersion)) {
            set({
              genomes: response.genomes,
              genomeTotal: response.total,
              isLoading: false,
            });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('genomes', requestVersion)) {
            set({ error: getErrorMessage(error, 'Failed to list genomes'), isLoading: false });
          }
          throw error;
        }
      },

      getGenome: async (id: string, options?: TenantScopedOptions) => {
        const requestVersion = nextDetailRequestVersion('currentGenome');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGenome(id, options);
          if (isLatestDetailRequest('currentGenome', requestVersion)) {
            set({ currentGenome: response, isLoading: false });
          }
          return response;
        } catch (error: unknown) {
          if (isLatestDetailRequest('currentGenome', requestVersion)) {
            set({ error: getErrorMessage(error, 'Failed to get genome'), isLoading: false });
          }
          throw error;
        }
      },

      fetchGenomeGenes: async (slugs: string[], options?: TenantScopedOptions) => {
        const requestVersion = nextDetailRequestVersion('currentGenomeGenes');
        const normalizedSlugs = normalizeSlugs(slugs);
        if (normalizedSlugs.length === 0) {
          if (isLatestDetailRequest('currentGenomeGenes', requestVersion)) {
            set({ currentGenomeGenes: [], currentGenomeGenesLoading: false });
          }
          return [];
        }

        set({ currentGenomeGenesLoading: true, error: null });
        try {
          const responses = await Promise.all(
            Array.from(
              { length: Math.ceil(normalizedSlugs.length / GENE_SLUG_LOOKUP_BATCH_SIZE) },
              (_, index) => {
                const chunk = normalizedSlugs.slice(
                  index * GENE_SLUG_LOOKUP_BATCH_SIZE,
                  (index + 1) * GENE_SLUG_LOOKUP_BATCH_SIZE
                );
                return geneMarketService.listGenes({
                  ...(options?.tenant_id ? { tenant_id: options.tenant_id } : {}),
                  slugs: chunk,
                  page_size: chunk.length,
                });
              }
            )
          );
          const orderedGenes = orderGenesBySlugs(
            responses.flatMap((response) => response.genes),
            normalizedSlugs
          );
          if (isLatestDetailRequest('currentGenomeGenes', requestVersion)) {
            set({ currentGenomeGenes: orderedGenes, currentGenomeGenesLoading: false });
          }
          return orderedGenes;
        } catch (error: unknown) {
          if (isLatestDetailRequest('currentGenomeGenes', requestVersion)) {
            set({
              error: getErrorMessage(error, 'Failed to fetch genome genes'),
              currentGenomeGenesLoading: false,
            });
          }
          throw error;
        }
      },

      createGenome: async (data: GenomeCreate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createGenome(data, options);
          const { genomes } = get();
          set({
            genomes: [response, ...genomes],
            genomeTotal: get().genomeTotal + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create genome'), isSubmitting: false });
          throw error;
        }
      },

      updateGenome: async (id: string, data: GenomeUpdate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.updateGenome(id, data, options);
          const { genomes } = get();
          set({
            genomes: genomes.map((g) => (g.id === id ? response : g)),
            currentGenome: get().currentGenome?.id === id ? response : get().currentGenome,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to update genome'), isSubmitting: false });
          throw error;
        }
      },

      deleteGenome: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGenome(id, options);
          const { genomes } = get();
          set({
            genomes: genomes.filter((g) => g.id !== id),
            currentGenome: get().currentGenome?.id === id ? null : get().currentGenome,
            genomeTotal: decrementNonNegative(get().genomeTotal),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete genome'), isSubmitting: false });
          throw error;
        }
      },

      publishGenome: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.publishGenome(id, options);
          const { genomes, currentGenome } = get();
          set({
            genomes: genomes.map((g) => (g.id === id ? response : g)),
            currentGenome: currentGenome?.id === id ? response : currentGenome,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to publish genome'), isSubmitting: false });
          throw error;
        }
      },

      unpublishGenome: async (id: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.unpublishGenome(id, options);
          const { genomes, currentGenome } = get();
          set({
            genomes: genomes.map((g) => (g.id === id ? response : g)),
            currentGenome: currentGenome?.id === id ? response : currentGenome,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to unpublish genome'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      // ========== Install ==========

      installGene: async (
        instanceId: string,
        data: GeneInstallRequest,
        options?: TenantScopedOptions
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.installGene(instanceId, data, options);
          const { installedGenes } = get();
          set({ installedGenes: [...installedGenes, response], isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to install gene'), isSubmitting: false });
          throw error;
        }
      },

      uninstallGene: async (
        instanceId: string,
        instanceGeneId: string,
        options?: TenantScopedOptions
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.uninstallGene(instanceId, instanceGeneId, options);
          const { installedGenes } = get();
          set({
            installedGenes: installedGenes.filter((ig) => ig.id !== instanceGeneId),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to uninstall gene'), isSubmitting: false });
          throw error;
        }
      },

      listInstalledGenes: async (instanceId: string, options?: TenantScopedOptions) => {
        const requestVersion = nextListRequestVersion('installedGenes');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listInstanceGenes(instanceId, options);
          if (isLatestListRequest('installedGenes', requestVersion)) {
            set({ installedGenes: response.items, isLoading: false });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('installedGenes', requestVersion)) {
            set({
              error: getErrorMessage(error, 'Failed to list installed genes'),
              isLoading: false,
            });
          }
          throw error;
        }
      },

      // ========== Ratings ==========

      fetchGeneReviews: async (
        geneId: string,
        page = 1,
        pageSize = 10,
        options?: TenantScopedOptions
      ) => {
        const requestVersion = nextListRequestVersion('reviews');
        set({ reviewsLoading: true, error: null });
        try {
          const response = await geneMarketService.getGeneReviews(geneId, page, pageSize, options);
          if (isLatestListRequest('reviews', requestVersion)) {
            set({ reviews: response.items, reviewsTotal: response.total, reviewsLoading: false });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('reviews', requestVersion)) {
            set({
              error: getErrorMessage(error, 'Failed to fetch reviews'),
              reviewsLoading: false,
            });
          }
        }
      },

      createGeneReview: async (
        geneId: string,
        data: CreateReviewRequest,
        options?: TenantScopedOptions
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.createGeneReview(geneId, data, options);
          set({ isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create review'), isSubmitting: false });
          throw error;
        }
      },

      deleteGeneReview: async (geneId: string, reviewId: string, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGeneReview(geneId, reviewId, options);
          set({ isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete review'), isSubmitting: false });
          throw error;
        }
      },

      rateGene: async (geneId: string, data: GeneRatingCreate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.rateGene(geneId, data, options);
          const response = await geneMarketService.getGene(geneId, options);
          const { genes, currentGene } = get();
          set({
            genes: genes.map((gene) => (gene.id === geneId ? response : gene)),
            currentGene: currentGene?.id === geneId ? response : currentGene,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to rate gene'), isSubmitting: false });
          throw error;
        }
      },

      rateGenome: async (
        genomeId: string,
        data: GenomeRatingCreate,
        options?: TenantScopedOptions
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.rateGenome(genomeId, data, options);
          const response = await geneMarketService.getGenome(genomeId, options);
          const { genomes, currentGenome } = get();
          set({
            genomes: genomes.map((genome) => (genome.id === genomeId ? response : genome)),
            currentGenome: currentGenome?.id === genomeId ? response : currentGenome,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to rate genome'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Evolution ==========

      listEvolutionEvents: async (instanceId: string, params = {}) => {
        const requestVersion = nextListRequestVersion('evolutionEvents');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listEvolutionEvents(instanceId, params);
          if (isLatestListRequest('evolutionEvents', requestVersion)) {
            set({
              evolutionEvents: response.events,
              evolutionTotal: response.total,
              isLoading: false,
            });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('evolutionEvents', requestVersion)) {
            set({
              error: getErrorMessage(error, 'Failed to list evolution events'),
              isLoading: false,
            });
          }
          throw error;
        }
      },

      listGeneEvolutionEvents: async (geneId: string, params = {}) => {
        const requestVersion = nextListRequestVersion('evolutionEvents');
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGeneEvolutionEvents(geneId, params);
          if (isLatestListRequest('evolutionEvents', requestVersion)) {
            set({
              evolutionEvents: response.events,
              evolutionTotal: response.total,
              isLoading: false,
            });
          }
        } catch (error: unknown) {
          if (isLatestListRequest('evolutionEvents', requestVersion)) {
            set({
              error: getErrorMessage(error, 'Failed to list evolution events'),
              isLoading: false,
            });
          }
          throw error;
        }
      },

      getEvolutionEvent: async (id: string, options?: TenantScopedOptions) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getEvolutionEvent(id, options);
          set({ isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to get evolution event'),
            isLoading: false,
          });
          throw error;
        }
      },

      createEvolutionEvent: async (data: EvolutionEventCreate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createEvolutionEvent(data, options);
          const { evolutionEvents } = get();
          set({
            evolutionEvents: [response, ...evolutionEvents],
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to create evolution event'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      // ========== UI ==========

      setActiveTab: (tab: 'genes' | 'genomes') => {
        set({ activeTab: tab });
      },

      setCurrentGene: (gene: GeneResponse | null) => {
        invalidateDetailRequests('currentGene');
        set({ currentGene: gene, ...(gene ? {} : { isLoading: false }) });
      },

      setCurrentGenome: (genome: GenomeResponse | null) => {
        invalidateDetailRequests('currentGenome', 'currentGenomeGenes');
        set({
          currentGenome: genome,
          ...(genome
            ? {}
            : { currentGenomeGenes: [], currentGenomeGenesLoading: false, isLoading: false }),
        });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        invalidateDetailRequests('currentGene', 'currentGenome', 'currentGenomeGenes');
        invalidateListRequests('genes', 'genomes', 'installedGenes', 'reviews', 'evolutionEvents');
        set(initialState);
      },
    }),
    {
      name: 'GeneMarketStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useGenes = () => useGeneMarketStore((s) => s.genes);
export const useCurrentGene = () => useGeneMarketStore((s) => s.currentGene);
export const useGeneReviews = () => useGeneMarketStore((s) => s.reviews);
export const useGeneReviewsTotal = () => useGeneMarketStore((s) => s.reviewsTotal);
export const useGeneReviewsLoading = () => useGeneMarketStore((s) => s.reviewsLoading);
export const useGenomes = () => useGeneMarketStore((s) => s.genomes);
export const useCurrentGenome = () => useGeneMarketStore((s) => s.currentGenome);
export const useCurrentGenomeGenes = () => useGeneMarketStore((s) => s.currentGenomeGenes);
export const useCurrentGenomeGenesLoading = () =>
  useGeneMarketStore((s) => s.currentGenomeGenesLoading);
export const useInstalledGenes = () => useGeneMarketStore((s) => s.installedGenes);
export const useEvolutionEvents = () => useGeneMarketStore((s) => s.evolutionEvents);
export const useEvolutionTotal = () => useGeneMarketStore((s) => s.evolutionTotal);
export const useGeneMarketLoading = () => useGeneMarketStore((s) => s.isLoading);
export const useGeneMarketError = () => useGeneMarketStore((s) => s.error);
export const useGeneTotal = () => useGeneMarketStore((s) => s.geneTotal);
export const useGenomeTotal = () => useGeneMarketStore((s) => s.genomeTotal);
export const useActiveTab = () => useGeneMarketStore((s) => s.activeTab);

export const useGeneMarketActions = () =>
  useGeneMarketStore(
    useShallow((s) => ({
      listGenes: s.listGenes,
      getGene: s.getGene,
      createGene: s.createGene,
      updateGene: s.updateGene,
      deleteGene: s.deleteGene,
      publishGene: s.publishGene,
      unpublishGene: s.unpublishGene,
      listGenomes: s.listGenomes,
      getGenome: s.getGenome,
      fetchGenomeGenes: s.fetchGenomeGenes,
      createGenome: s.createGenome,
      updateGenome: s.updateGenome,
      deleteGenome: s.deleteGenome,
      publishGenome: s.publishGenome,
      unpublishGenome: s.unpublishGenome,
      installGene: s.installGene,
      uninstallGene: s.uninstallGene,
      listInstalledGenes: s.listInstalledGenes,
      fetchGeneReviews: s.fetchGeneReviews,
      createGeneReview: s.createGeneReview,
      deleteGeneReview: s.deleteGeneReview,
      rateGene: s.rateGene,
      rateGenome: s.rateGenome,
      listEvolutionEvents: s.listEvolutionEvents,
      listGeneEvolutionEvents: s.listGeneEvolutionEvents,
      getEvolutionEvent: s.getEvolutionEvent,
      createEvolutionEvent: s.createEvolutionEvent,
      setActiveTab: s.setActiveTab,
      setCurrentGene: s.setCurrentGene,
      setCurrentGenome: s.setCurrentGenome,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
