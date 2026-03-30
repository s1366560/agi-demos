import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { instanceTemplateService } from '../services/instanceTemplateService';

import type {
  InstanceTemplateResponse,
  InstanceTemplateCreate,
  InstanceTemplateUpdate,
  TemplateItemResponse,
  TemplateItemCreate,
} from '../services/instanceTemplateService';

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

interface InstanceTemplateState {
  templates: InstanceTemplateResponse[];
  currentTemplate: InstanceTemplateResponse | null;
  templateItems: TemplateItemResponse[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;

  // Actions - Template CRUD
  listTemplates: (params?: Record<string, unknown>) => Promise<void>;
  getTemplate: (id: string) => Promise<InstanceTemplateResponse>;
  createTemplate: (data: InstanceTemplateCreate) => Promise<InstanceTemplateResponse>;
  updateTemplate: (id: string, data: InstanceTemplateUpdate) => Promise<InstanceTemplateResponse>;
  deleteTemplate: (id: string) => Promise<void>;

  // Actions - Lifecycle
  publishTemplate: (id: string) => Promise<InstanceTemplateResponse>;
  cloneTemplate: (id: string) => Promise<InstanceTemplateResponse>;

  // Actions - Items
  listTemplateItems: (id: string) => Promise<void>;
  addTemplateItem: (id: string, data: TemplateItemCreate) => Promise<TemplateItemResponse>;
  removeTemplateItem: (id: string, itemId: string) => Promise<void>;

  // Actions - UI
  setCurrentTemplate: (template: InstanceTemplateResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState = {
  templates: [] as InstanceTemplateResponse[],
  currentTemplate: null as InstanceTemplateResponse | null,
  templateItems: [] as TemplateItemResponse[],
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null as string | null,
};

// ============================================================================
// STORE
// ============================================================================

export const useInstanceTemplateStore = create<InstanceTemplateState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== Template CRUD ==========

      listTemplates: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceTemplateService.list(params);
          set({
            templates: response.templates,
            total: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to list templates'), isLoading: false });
          throw error;
        }
      },

      getTemplate: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceTemplateService.getById(id);
          set({ currentTemplate: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get template'), isLoading: false });
          throw error;
        }
      },

      createTemplate: async (data: InstanceTemplateCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceTemplateService.create(data);
          const { templates } = get();
          set({
            templates: [response, ...templates],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create template'), isSubmitting: false });
          throw error;
        }
      },

      updateTemplate: async (id: string, data: InstanceTemplateUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceTemplateService.update(id, data);
          const { templates } = get();
          set({
            templates: templates.map((t) => (t.id === id ? response : t)),
            currentTemplate: get().currentTemplate?.id === id ? response : get().currentTemplate,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to update template'), isSubmitting: false });
          throw error;
        }
      },

      deleteTemplate: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await instanceTemplateService.delete(id);
          const { templates } = get();
          set({
            templates: templates.filter((t) => t.id !== id),
            currentTemplate: get().currentTemplate?.id === id ? null : get().currentTemplate,
            total: get().total - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete template'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Lifecycle ==========

      publishTemplate: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceTemplateService.publish(id);
          const { templates } = get();
          set({
            templates: templates.map((t) => (t.id === id ? response : t)),
            currentTemplate: get().currentTemplate?.id === id ? response : get().currentTemplate,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to publish template'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      cloneTemplate: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceTemplateService.clone(id);
          const { templates } = get();
          set({
            templates: [response, ...templates],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to clone template'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Items ==========

      listTemplateItems: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceTemplateService.listItems(id);
          set({ templateItems: response, isLoading: false });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list template items'),
            isLoading: false,
          });
          throw error;
        }
      },

      addTemplateItem: async (id: string, data: TemplateItemCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceTemplateService.addItem(id, data);
          const { templateItems } = get();
          set({ templateItems: [...templateItems, response], isSubmitting: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to add template item'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      removeTemplateItem: async (id: string, itemId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await instanceTemplateService.removeItem(id, itemId);
          const { templateItems } = get();
          set({
            templateItems: templateItems.filter((item) => item.id !== itemId),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to remove template item'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      // ========== UI ==========

      setCurrentTemplate: (template: InstanceTemplateResponse | null) => {
        set({ currentTemplate: template });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'InstanceTemplateStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useTemplates = () => useInstanceTemplateStore((s) => s.templates);
export const useCurrentTemplate = () => useInstanceTemplateStore((s) => s.currentTemplate);
export const useTemplateItems = () => useInstanceTemplateStore((s) => s.templateItems);
export const useTemplateLoading = () => useInstanceTemplateStore((s) => s.isLoading);
export const useTemplateSubmitting = () => useInstanceTemplateStore((s) => s.isSubmitting);
export const useTemplateError = () => useInstanceTemplateStore((s) => s.error);
export const useTemplateTotal = () => useInstanceTemplateStore((s) => s.total);

export const useTemplateActions = () =>
  useInstanceTemplateStore(
    useShallow((s) => ({
      listTemplates: s.listTemplates,
      getTemplate: s.getTemplate,
      createTemplate: s.createTemplate,
      updateTemplate: s.updateTemplate,
      deleteTemplate: s.deleteTemplate,
      publishTemplate: s.publishTemplate,
      cloneTemplate: s.cloneTemplate,
      listTemplateItems: s.listTemplateItems,
      addTemplateItem: s.addTemplateItem,
      removeTemplateItem: s.removeTemplateItem,
      setCurrentTemplate: s.setCurrentTemplate,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
