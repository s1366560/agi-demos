import type {
  InstanceTemplateCreate,
  InstanceTemplateResponse,
  InstanceTemplateListResponse,
  TemplateItemResponse,
} from '../web/services/instanceTemplateService';

function read<T>(view: string, values: Record<string, unknown>, signal?: AbortSignal) {
  return window.memstack.invoke(
    'read-instance-templates',
    { view, ...values },
    { signal },
  ) as Promise<T>;
}
function change<T>(action: string, values: Record<string, unknown>, signal?: AbortSignal) {
  return window.memstack.invoke(
    'change-instance-template',
    { action, ...values },
    { signal },
  ) as Promise<T>;
}
export const instanceTemplateService = {
  list: (params = {}, signal?: AbortSignal) =>
    read<InstanceTemplateListResponse>('list', params, signal),
  getById: (id: string, signal?: AbortSignal) =>
    read<InstanceTemplateResponse>('detail', { id }, signal),
  listItems: async (id: string, signal?: AbortSignal) =>
    (await read<{ items: TemplateItemResponse[] }>('items', { id }, signal)).items,
  names: async (id: string) =>
    (await read<{ items: { id: string; name: string }[] }>('names', { id })).items,
  create: (data: InstanceTemplateCreate, signal?: AbortSignal) =>
    change<InstanceTemplateResponse>('create', { data }, signal),
  publish: (id: string, signal?: AbortSignal) =>
    change<InstanceTemplateResponse>('publish', { id }, signal),
  clone: (id: string, new_name: string, signal?: AbortSignal) =>
    change<InstanceTemplateResponse>('clone', { id, data: { new_name } }, signal),
  delete: (id: string, signal?: AbortSignal) => change<void>('delete', { id }, signal),
};
