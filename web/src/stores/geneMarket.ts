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

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface GeneMarketState {
  genes: GeneResponse[];
  currentGene: GeneResponse | null;
  genomes: GenomeResponse[];
  currentGenome: GenomeResponse | null;
  installedGenes: InstanceGeneResponse[];
  evolutionEvents: EvolutionEventResponse[];
  evolutionTotal: number;
  geneTotal: number;
  genomeTotal: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isSubmitting: boolean;
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

  // Actions - Genome CRUD
  listGenomes: (params?: GenomeListParams) => Promise<void>;
  getGenome: (id: string, options?: TenantScopedOptions) => Promise<GenomeResponse>;
  createGenome: (data: GenomeCreate, options?: TenantScopedOptions) => Promise<GenomeResponse>;
  updateGenome: (
    id: string,
    data: GenomeUpdate,
    options?: TenantScopedOptions
  ) => Promise<GenomeResponse>;
  deleteGenome: (id: string, options?: TenantScopedOptions) => Promise<void>;

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
  | 'installedGenes'
  | 'evolutionEvents'
  | 'evolutionTotal'
  | 'geneTotal'
  | 'genomeTotal'
  | 'page'
  | 'pageSize'
  | 'isLoading'
  | 'isSubmitting'
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
  installedGenes: [] as InstanceGeneResponse[],
  evolutionEvents: [] as EvolutionEventResponse[],
  evolutionTotal: 0,
  geneTotal: 0,
  genomeTotal: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
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
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGenes(params);
          set({
            genes: response.genes,
            geneTotal: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to list genes'), isLoading: false });
          throw error;
        }
      },

      getGene: async (id: string, options?: TenantScopedOptions) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGene(id, options);
          set({ currentGene: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get gene'), isLoading: false });
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
            geneTotal: get().geneTotal - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete gene'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Genome CRUD ==========

      listGenomes: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGenomes(params);
          set({
            genomes: response.genomes,
            genomeTotal: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to list genomes'), isLoading: false });
          throw error;
        }
      },

      getGenome: async (id: string, options?: TenantScopedOptions) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGenome(id, options);
          set({ currentGenome: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get genome'), isLoading: false });
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
            genomeTotal: get().genomeTotal - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete genome'), isSubmitting: false });
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
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listInstanceGenes(instanceId, options);
          set({ installedGenes: response.items, isLoading: false });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list installed genes'),
            isLoading: false,
          });
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
        set({ reviewsLoading: true, error: null });
        try {
          const response = await geneMarketService.getGeneReviews(geneId, page, pageSize, options);
          set({ reviews: response.items, reviewsTotal: response.total, reviewsLoading: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to fetch reviews'), reviewsLoading: false });
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
          // Fetch again to update list
          void get().fetchGeneReviews(geneId, 1, 10, options);
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
          // Fetch again to update list
          void get().fetchGeneReviews(geneId, 1, 10, options);
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete review'), isSubmitting: false });
          throw error;
        }
      },

      rateGene: async (geneId: string, data: GeneRatingCreate, options?: TenantScopedOptions) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.rateGene(geneId, data, options);
          set({ isSubmitting: false });
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
          set({ isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to rate genome'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Evolution ==========

      listEvolutionEvents: async (instanceId: string, params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listEvolutionEvents(instanceId, params);
          set({
            evolutionEvents: response.events,
            evolutionTotal: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list evolution events'),
            isLoading: false,
          });
          throw error;
        }
      },

      listGeneEvolutionEvents: async (geneId: string, params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listGeneEvolutionEvents(geneId, params);
          set({
            evolutionEvents: response.events,
            evolutionTotal: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list evolution events'),
            isLoading: false,
          });
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
        set({ currentGene: gene });
      },

      setCurrentGenome: (genome: GenomeResponse | null) => {
        set({ currentGenome: genome });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
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
      listGenomes: s.listGenomes,
      getGenome: s.getGenome,
      createGenome: s.createGenome,
      updateGenome: s.updateGenome,
      deleteGenome: s.deleteGenome,
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
