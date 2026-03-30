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
  GeneReview,
  CreateReviewRequest,
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
  listGenes: (params?: Record<string, unknown>) => Promise<void>;
  getGene: (id: string) => Promise<GeneResponse>;
  createGene: (data: GeneCreate) => Promise<GeneResponse>;
  updateGene: (id: string, data: GeneUpdate) => Promise<GeneResponse>;
  deleteGene: (id: string) => Promise<void>;

  // Actions - Genome CRUD
  listGenomes: (params?: Record<string, unknown>) => Promise<void>;
  getGenome: (id: string) => Promise<GenomeResponse>;
  createGenome: (data: GenomeCreate) => Promise<GenomeResponse>;
  updateGenome: (id: string, data: GenomeUpdate) => Promise<GenomeResponse>;
  deleteGenome: (id: string) => Promise<void>;

  // Actions - Install
  installGene: (instanceId: string, data: GeneInstallRequest) => Promise<void>;
  uninstallGene: (instanceId: string, instanceGeneId: string) => Promise<void>;
  listInstalledGenes: (instanceId: string) => Promise<void>;

  // Actions - Reviews
  fetchGeneReviews: (geneId: string, page?: number, pageSize?: number) => Promise<void>;
  createGeneReview: (geneId: string, data: CreateReviewRequest) => Promise<void>;
  deleteGeneReview: (geneId: string, reviewId: string) => Promise<void>;

  // Actions - Ratings
  rateGene: (geneId: string, data: GeneRatingCreate) => Promise<void>;
  rateGenome: (genomeId: string, data: GenomeRatingCreate) => Promise<void>;

  // Actions - Evolution
  listEvolutionEvents: (instanceId: string, params?: Record<string, unknown>) => Promise<void>;
  getEvolutionEvent: (id: string) => Promise<EvolutionEventResponse>;
  createEvolutionEvent: (data: EvolutionEventCreate) => Promise<EvolutionEventResponse>;

  // Actions - UI
  setActiveTab: (tab: 'genes' | 'genomes') => void;
  setCurrentGene: (gene: GeneResponse | null) => void;
  setCurrentGenome: (genome: GenomeResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState = {
  genes: [] as GeneResponse[],
  currentGene: null as GeneResponse | null,
  genomes: [] as GenomeResponse[],
  currentGenome: null as GenomeResponse | null,
  installedGenes: [] as InstanceGeneResponse[],
  evolutionEvents: [] as EvolutionEventResponse[],
  geneTotal: 0,
  genomeTotal: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null as string | null,
  activeTab: 'genes' as const,
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

      getGene: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGene(id);
          set({ currentGene: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get gene'), isLoading: false });
          throw error;
        }
      },

      createGene: async (data: GeneCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createGene(data);
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

      updateGene: async (id: string, data: GeneUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.updateGene(id, data);
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

      deleteGene: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGene(id);
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

      getGenome: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getGenome(id);
          set({ currentGenome: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get genome'), isLoading: false });
          throw error;
        }
      },

      createGenome: async (data: GenomeCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createGenome(data);
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

      updateGenome: async (id: string, data: GenomeUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.updateGenome(id, data);
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

      deleteGenome: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGenome(id);
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

      installGene: async (instanceId: string, data: GeneInstallRequest) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.installGene(instanceId, data);
          const { installedGenes } = get();
          set({ installedGenes: [...installedGenes, response], isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to install gene'), isSubmitting: false });
          throw error;
        }
      },

      uninstallGene: async (instanceId: string, instanceGeneId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.uninstallGene(instanceId, instanceGeneId);
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

      listInstalledGenes: async (instanceId: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.listInstanceGenes(instanceId);
          set({ installedGenes: response, isLoading: false });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list installed genes'),
            isLoading: false,
          });
          throw error;
        }
      },

      // ========== Ratings ==========

      fetchGeneReviews: async (geneId: string, page = 1, pageSize = 10) => {
        set({ reviewsLoading: true, error: null });
        try {
          const response = await geneMarketService.getGeneReviews(geneId, page, pageSize);
          set({ reviews: response.items, reviewsTotal: response.total, reviewsLoading: false });
        } catch (error: any) {
          set({ error: error.message, reviewsLoading: false });
        }
      },

      createGeneReview: async (geneId: string, data: CreateReviewRequest) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.createGeneReview(geneId, data);
          set({ isSubmitting: false });
          // Fetch again to update list
          get().fetchGeneReviews(geneId);
        } catch (error: any) {
          set({ error: error.message, isSubmitting: false });
          throw error;
        }
      },

      deleteGeneReview: async (geneId: string, reviewId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.deleteGeneReview(geneId, reviewId);
          set({ isSubmitting: false });
          // Fetch again to update list
          get().fetchGeneReviews(geneId);
        } catch (error: any) {
          set({ error: error.message, isSubmitting: false });
          throw error;
        }
      },

      rateGene: async (geneId: string, data: GeneRatingCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.rateGene(geneId, data);
          set({ isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to rate gene'), isSubmitting: false });
          throw error;
        }
      },

      rateGenome: async (genomeId: string, data: GenomeRatingCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          await geneMarketService.rateGenome(genomeId, data);
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
          set({ evolutionEvents: response.events, isLoading: false });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list evolution events'),
            isLoading: false,
          });
          throw error;
        }
      },

      getEvolutionEvent: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await geneMarketService.getEvolutionEvent(id);
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

      createEvolutionEvent: async (data: EvolutionEventCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await geneMarketService.createEvolutionEvent(data);
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
      createEvolutionEvent: s.createEvolutionEvent,
      setActiveTab: s.setActiveTab,
      setCurrentGene: s.setCurrentGene,
      setCurrentGenome: s.setCurrentGenome,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
