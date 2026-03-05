/**
 * Cron Zustand Store
 *
 * State management for Cron Job operations and execution history.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { cronAPI } from '../services/cronService';
import { getErrorMessage } from '../types/common';

import type {
  CronJobResponse,
  CronJobCreate,
  CronJobUpdate,
  CronJobRunResponse,
} from '../types/cron';

// ============================================================================
// STATE INTERFACE
// ============================================================================

export interface CronFilters {
  search: string;
  include_disabled: boolean;
  page: number;
  pageSize: number;
}

export interface CronState {
  // Data
  jobs: CronJobResponse[];
  selectedJob: CronJobResponse | null;
  runs: CronJobRunResponse[];

  // Pagination
  total: number;
  runsTotal: number;

  // Filters
  filters: CronFilters;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;

  // Error state
  error: string | null;

  // Actions - Job CRUD
  fetchJobs: (projectId: string) => Promise<void>;
  fetchJob: (projectId: string, jobId: string) => Promise<CronJobResponse>;
  createJob: (projectId: string, data: CronJobCreate) => Promise<CronJobResponse>;
  updateJob: (projectId: string, jobId: string, data: CronJobUpdate) => Promise<CronJobResponse>;
  deleteJob: (projectId: string, jobId: string) => Promise<void>;
  toggleJob: (projectId: string, jobId: string, enabled: boolean) => Promise<CronJobResponse>;

  // Actions - Execution
  triggerRun: (projectId: string, jobId: string) => Promise<void>;
  fetchRuns: (projectId: string, jobId: string, limit?: number, offset?: number) => Promise<void>;

  // Actions - Filters & Utility
  setFilters: (filters: Partial<CronFilters>) => void;
  reset: () => void;
  clearError: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: CronFilters = {
  search: '',
  include_disabled: true,
  page: 1,
  pageSize: 20,
};

const initialState = {
  jobs: [],
  selectedJob: null,
  runs: [],
  total: 0,
  runsTotal: 0,
  filters: initialFilters,
  isLoading: false,
  isSubmitting: false,
  error: null,
};

// ============================================================================
// STORE CREATION
// ============================================================================

export const useCronStore = create<CronState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      fetchJobs: async (projectId: string) => {
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const offset = (filters.page - 1) * filters.pageSize;
          const response = await cronAPI.list(projectId, {
            include_disabled: filters.include_disabled,
            limit: filters.pageSize,
            offset,
          });
          set({
            jobs: response.items,
            total: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to list cron jobs)`, isLoading: false });
          throw error;
        }
      },

      fetchJob: async (projectId: string, jobId: string) => {
        set({ isLoading: true, error: null });
        try {
          const job = await cronAPI.get(projectId, jobId);
          set({ selectedJob: job, isLoading: false });
          return job;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to fetch cron job)`, isLoading: false });
          throw error;
        }
      },

      createJob: async (projectId: string, data: CronJobCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const newJob = await cronAPI.create(projectId, data);
          const { jobs, total } = get();
          set({
            jobs: [newJob, ...jobs],
            total: total + 1,
            isSubmitting: false,
          });
          return newJob;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to create cron job)`, isSubmitting: false });
          throw error;
        }
      },

      updateJob: async (projectId: string, jobId: string, data: CronJobUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const updatedJob = await cronAPI.update(projectId, jobId, data);
          const { jobs, selectedJob } = get();
          set({
            jobs: jobs.map((j) => (j.id === jobId ? updatedJob : j)),
            selectedJob: selectedJob?.id === jobId ? updatedJob : selectedJob,
            isSubmitting: false,
          });
          return updatedJob;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to update cron job)`, isSubmitting: false });
          throw error;
        }
      },

      deleteJob: async (projectId: string, jobId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await cronAPI.delete(projectId, jobId);
          const { jobs, total } = get();
          set({
            jobs: jobs.filter((j) => j.id !== jobId),
            total: Math.max(0, total - 1),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to delete cron job)`, isSubmitting: false });
          throw error;
        }
      },

      toggleJob: async (projectId: string, jobId: string, enabled: boolean) => {
        set({ isSubmitting: true, error: null });
        try {
          const updatedJob = await cronAPI.toggle(projectId, jobId, enabled);
          const { jobs, selectedJob } = get();
          set({
            jobs: jobs.map((j) => (j.id === jobId ? updatedJob : j)),
            selectedJob: selectedJob?.id === jobId ? updatedJob : selectedJob,
            isSubmitting: false,
          });
          return updatedJob;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to toggle cron job)`, isSubmitting: false });
          throw error;
        }
      },

      triggerRun: async (projectId: string, jobId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await cronAPI.run(projectId, jobId);
          set({ isSubmitting: false });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to trigger manual run)`, isSubmitting: false });
          throw error;
        }
      },

      fetchRuns: async (projectId: string, jobId: string, limit = 20, offset = 0) => {
        set({ isLoading: true, error: null });
        try {
          const response = await cronAPI.listRuns(projectId, jobId, { limit, offset });
          set({
            runs: response.items,
            runsTotal: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error);
          set({ error: `${errorMessage} (Failed to fetch run history)`, isLoading: false });
          throw error;
        }
      },

      setFilters: (filters: Partial<CronFilters>) => {
        set((state) => ({
          filters: { ...state.filters, ...filters },
        }));
      },

      reset: () => {
        set(initialState);
      },

      clearError: () => {
        set({ error: null });
      },
    }),
    { name: 'CronStore', enabled: import.meta.env.DEV }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useCronJobs = () => useCronStore((state) => state.jobs);
export const useSelectedCronJob = () => useCronStore((state) => state.selectedJob);
export const useCronJobRuns = () => useCronStore((state) => state.runs);
export const useCronTotal = () => useCronStore((state) => state.total);
export const useCronLoading = () => useCronStore((state) => state.isLoading);
export const useCronSubmitting = () => useCronStore((state) => state.isSubmitting);
export const useCronError = () => useCronStore((state) => state.error);
export const useCronFilters = () => useCronStore((state) => state.filters);

export const useCronActions = () =>
  useCronStore(
    useShallow((state) => ({
      fetchJobs: state.fetchJobs,
      fetchJob: state.fetchJob,
      createJob: state.createJob,
      updateJob: state.updateJob,
      deleteJob: state.deleteJob,
      toggleJob: state.toggleJob,
      triggerRun: state.triggerRun,
      fetchRuns: state.fetchRuns,
      setFilters: state.setFilters,
      reset: state.reset,
      clearError: state.clearError,
    }))
  );
