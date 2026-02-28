/**
 * Zustand store for prompt template management.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import {
  templateService,
  type PromptTemplateData,
  type CreateTemplateRequest,
} from '@/services/templateService';

interface TemplateState {
  templates: PromptTemplateData[];
  loading: boolean;
  error: string | null;

  fetchTemplates: (tenantId: string, category?: string) => Promise<void>;
  createTemplate: (
    tenantId: string,
    data: CreateTemplateRequest
  ) => Promise<PromptTemplateData | null>;
  deleteTemplate: (templateId: string) => Promise<void>;
  reset: () => void;
}

export const useTemplateStore = create<TemplateState>()(
  devtools(
    (set) => ({
      templates: [],
      loading: false,
      error: null,

      fetchTemplates: async (tenantId, category) => {
        set({ loading: true, error: null });
        try {
          const templates = await templateService.list(tenantId, category);
          set({ templates, loading: false });
        } catch (err) {
          set({ error: String(err), loading: false });
        }
      },

      createTemplate: async (tenantId, data) => {
        try {
          const template = await templateService.create(tenantId, data);
          set((state) => ({ templates: [template, ...state.templates] }));
          return template;
        } catch (err) {
          set({ error: String(err) });
          return null;
        }
      },

      deleteTemplate: async (templateId) => {
        try {
          await templateService.delete(templateId);
          set((state) => ({ templates: state.templates.filter((t) => t.id !== templateId) }));
        } catch (err) {
          set({ error: String(err) });
        }
      },

      reset: () => {
        set({ templates: [], loading: false, error: null });
      },
    }),
    { name: 'template-store' }
  )
);

export const useTemplates = () => useTemplateStore((state) => state.templates);
export const useTemplateLoading = () => useTemplateStore((state) => state.loading);

export const useTemplateActions = () =>
  useTemplateStore(
    useShallow((s) => ({
      fetchTemplates: s.fetchTemplates,
      createTemplate: s.createTemplate,
      deleteTemplate: s.deleteTemplate,
    }))
  );
