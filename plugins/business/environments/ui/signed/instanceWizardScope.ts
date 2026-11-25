import { create } from 'zustand';
import { useParams } from 'react-router-dom';
import { instanceTemplateService } from './templateService';
import type { InstanceCreate } from '../web/services/instanceService';

export const useCurrentTenant = () => ({ id: useParams().tenantId });
export const useTenantStore = <T>(select: (value: { currentTenant: { id?: string } }) => T) =>
  select({ currentTenant: useCurrentTenant() });
// The tenant-scoped wizard has no project selection or project workspace authority.
export const useProjectStore = <T>(select: (value: { currentProject: null }) => T) =>
  select({ currentProject: null });
const workspaces: readonly never[] = [];
export const useWorkspaces = () => workspaces;
const workspaceScope = {
  loadWorkspaces: async () => {
    throw Error('project_scope_required');
  },
};
export const useWorkspaceStore = <T>(select: (value: typeof workspaceScope) => T) =>
  select(workspaceScope);

const useSubmitting = create(() => ({ busy: false }));
export const useInstanceSubmitting = () => useSubmitting((s) => s.busy);
const actions = {
  async createInstance(data: InstanceCreate) {
    useSubmitting.setState({ busy: true });
    try {
      return await window.memstack.invoke('create-runtime-instance', { ...data });
    } finally {
      useSubmitting.setState({ busy: false });
    }
  },
};
export const useInstanceActions = () => actions;
const useNames = create(() => ({ items: [] as { id: string; name: string }[] }));
export const useGenes = () => useNames((s) => s.items);
const geneActions = {
  async listGenes() {
    const { pathname } = await window.memstack.getContext();
    const id = decodeURIComponent(pathname.split('/').filter(Boolean).at(-1)!);
    const items = await instanceTemplateService.names(id);
    useNames.setState({ items });
  },
};
export const useGeneMarketActions = () => geneActions;
