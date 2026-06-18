import { beforeEach, describe, expect, it, vi } from 'vitest';

import { instanceTemplateService } from '@/services/instanceTemplateService';
import { useInstanceTemplateStore } from '@/stores/instanceTemplate';

import type {
  InstanceTemplateResponse,
  TemplateItemResponse,
} from '@/services/instanceTemplateService';

vi.mock('@/services/instanceTemplateService', () => ({
  instanceTemplateService: {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    publish: vi.fn(),
    clone: vi.fn(),
    listItems: vi.fn(),
    addItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

const template = (id: string): InstanceTemplateResponse => ({
  id,
  name: id,
  slug: id,
  tenant_id: 'tenant-1',
  description: null,
  icon: null,
  image_version: null,
  default_config: {},
  is_published: false,
  is_featured: false,
  install_count: 0,
  created_by: 'user-1',
  created_at: '2026-06-18T00:00:00Z',
  updated_at: null,
});

const item = (id: string): TemplateItemResponse => ({
  id,
  template_id: 'template-1',
  item_type: 'gene',
  item_slug: id,
  display_order: 0,
  created_at: '2026-06-18T00:00:00Z',
});

describe('instance template store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useInstanceTemplateStore.getState().reset();
  });

  it('ignores list responses that resolve after reset', async () => {
    const request = deferred<Awaited<ReturnType<typeof instanceTemplateService.list>>>();
    vi.mocked(instanceTemplateService.list).mockReturnValueOnce(request.promise);

    const load = useInstanceTemplateStore.getState().listTemplates({ page: 1 });
    useInstanceTemplateStore.getState().reset();

    request.resolve({
      templates: [template('stale-template')],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await load;

    const state = useInstanceTemplateStore.getState();
    expect(state.templates).toEqual([]);
    expect(state.total).toBe(0);
    expect(state.isLoading).toBe(false);
  });

  it('ignores detail responses that resolve after reset', async () => {
    const request = deferred<InstanceTemplateResponse>();
    vi.mocked(instanceTemplateService.getById).mockReturnValueOnce(request.promise);

    const load = useInstanceTemplateStore.getState().getTemplate('stale-template');
    useInstanceTemplateStore.getState().reset();

    request.resolve(template('stale-template'));
    await load;

    expect(useInstanceTemplateStore.getState().currentTemplate).toBeNull();
    expect(useInstanceTemplateStore.getState().isLoading).toBe(false);
  });

  it('ignores item responses that resolve after reset', async () => {
    const request = deferred<TemplateItemResponse[]>();
    vi.mocked(instanceTemplateService.listItems).mockReturnValueOnce(request.promise);

    const load = useInstanceTemplateStore.getState().listTemplateItems('stale-template');
    useInstanceTemplateStore.getState().reset();

    request.resolve([item('stale-item')]);
    await load;

    expect(useInstanceTemplateStore.getState().templateItems).toEqual([]);
    expect(useInstanceTemplateStore.getState().isLoading).toBe(false);
  });
});
