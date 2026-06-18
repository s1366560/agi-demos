import { beforeEach, describe, expect, it, vi } from 'vitest';

import { skillAPI, tenantSkillConfigAPI } from '@/services/skillService';
import { useSkillStore } from '@/stores/skill';

vi.mock('@/services/skillService', () => ({
  skillAPI: {
    list: vi.fn(),
    listSystemSkills: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    updateStatus: vi.fn(),
    updateContent: vi.fn(),
  },
  tenantSkillConfigAPI: {
    list: vi.fn(),
    disable: vi.fn(),
    enable: vi.fn(),
    override: vi.fn(),
  },
}));

describe('skill store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSkillStore.getState().reset();
    vi.mocked(skillAPI.list).mockResolvedValue({ skills: [], total: 0 });
  });

  it('converts page state into backend limit and offset', async () => {
    useSkillStore.getState().setFilters({
      search: 'memory',
      status: 'active',
      scope: 'tenant',
    });
    vi.mocked(skillAPI.list).mockResolvedValueOnce({ skills: [], total: 42 });

    await useSkillStore.getState().listSkills({ page: 2, pageSize: 25 });

    expect(skillAPI.list).toHaveBeenCalledWith({
      search: 'memory',
      status: 'active',
      scope: 'tenant',
      project_id: undefined,
      limit: 25,
      offset: 25,
    });
    expect(useSkillStore.getState().total).toBe(42);
    expect(useSkillStore.getState().page).toBe(2);
    expect(useSkillStore.getState().pageSize).toBe(25);
  });

  it('lets explicit list parameters override stored filters', async () => {
    useSkillStore.getState().setFilters({
      search: 'memory',
      status: 'active',
      scope: 'tenant',
    });

    await useSkillStore.getState().listSkills({
      search: '',
      status: null,
      scope: 'project',
      project_id: 'project-1',
      page: 1,
      pageSize: 20,
    });

    expect(skillAPI.list).toHaveBeenCalledWith({
      search: undefined,
      status: undefined,
      scope: 'project',
      project_id: 'project-1',
      limit: 20,
      offset: 0,
    });
  });

  it('passes explicit tenant scope through list requests', async () => {
    await useSkillStore.getState().listSkills({
      tenant_id: 'tenant-2',
      page: 1,
      pageSize: 20,
    });

    expect(skillAPI.list).toHaveBeenCalledWith({
      search: undefined,
      status: undefined,
      scope: undefined,
      project_id: undefined,
      tenant_id: 'tenant-2',
      limit: 20,
      offset: 0,
    });
  });

  it('ignores stale responses from older skill list requests', async () => {
    let resolveFirstList: ((value: any) => void) | null = null;
    const firstListPromise = new Promise((resolve) => {
      resolveFirstList = resolve;
    });

    vi.mocked(skillAPI.list)
      .mockReturnValueOnce(firstListPromise as Promise<any>)
      .mockResolvedValueOnce({
        skills: [{ id: 'skill-new', name: 'New', status: 'active', scope: 'tenant' }],
        total: 1,
      } as any);

    const firstLoad = useSkillStore.getState().listSkills({
      tenant_id: 'tenant-1',
      page: 1,
      pageSize: 20,
    });
    const secondLoad = useSkillStore.getState().listSkills({
      tenant_id: 'tenant-2',
      page: 2,
      pageSize: 25,
    });

    await secondLoad;
    resolveFirstList?.({
      skills: [{ id: 'skill-old', name: 'Old', status: 'active', scope: 'tenant' }],
      total: 1,
    });
    await firstLoad;

    const state = useSkillStore.getState();
    expect(state.skills).toEqual([expect.objectContaining({ id: 'skill-new' })]);
    expect(state.page).toBe(2);
    expect(state.pageSize).toBe(25);
    expect(state.total).toBe(1);
    expect(state.isLoading).toBe(false);
  });

  it('ignores skill list responses that resolve after reset', async () => {
    let resolveList: ((value: any) => void) | null = null;
    const listPromise = new Promise((resolve) => {
      resolveList = resolve;
    });

    vi.mocked(skillAPI.list).mockReturnValueOnce(listPromise as Promise<any>);

    const load = useSkillStore.getState().listSkills({
      tenant_id: 'tenant-1',
      page: 3,
      pageSize: 10,
    });

    useSkillStore.getState().reset();
    resolveList?.({
      skills: [{ id: 'skill-stale', name: 'Stale', status: 'active', scope: 'tenant' }],
      total: 1,
    });
    await load;

    const state = useSkillStore.getState();
    expect(state.skills).toEqual([]);
    expect(state.total).toBe(0);
    expect(state.page).toBe(1);
    expect(state.pageSize).toBe(20);
    expect(state.isLoading).toBe(false);
  });

  it('ignores stale responses from older tenant config requests', async () => {
    let resolveFirstConfigs: ((value: any) => void) | null = null;
    const firstConfigPromise = new Promise((resolve) => {
      resolveFirstConfigs = resolve;
    });

    vi.mocked(tenantSkillConfigAPI.list)
      .mockReturnValueOnce(firstConfigPromise as Promise<any>)
      .mockResolvedValueOnce({
        configs: [{ id: 'config-new', tenant_id: 'tenant-2', system_skill_name: 'new-skill' }],
        total: 1,
      } as any);

    const firstLoad = useSkillStore.getState().listTenantConfigs({ tenant_id: 'tenant-1' });
    const secondLoad = useSkillStore.getState().listTenantConfigs({ tenant_id: 'tenant-2' });

    await secondLoad;
    resolveFirstConfigs?.({
      configs: [{ id: 'config-old', tenant_id: 'tenant-1', system_skill_name: 'old-skill' }],
      total: 1,
    });
    await firstLoad;

    expect(useSkillStore.getState().tenantConfigs).toEqual([
      expect.objectContaining({ id: 'config-new' }),
    ]);
    expect(useSkillStore.getState().isLoading).toBe(false);
  });

  it('ignores tenant config responses that resolve after reset', async () => {
    let resolveConfigs: ((value: any) => void) | null = null;
    const configPromise = new Promise((resolve) => {
      resolveConfigs = resolve;
    });

    vi.mocked(tenantSkillConfigAPI.list).mockReturnValueOnce(configPromise as Promise<any>);

    const load = useSkillStore.getState().listTenantConfigs({ tenant_id: 'tenant-1' });

    useSkillStore.getState().reset();
    resolveConfigs?.({
      configs: [{ id: 'config-stale', tenant_id: 'tenant-1', system_skill_name: 'stale-skill' }],
      total: 1,
    });
    await load;

    expect(useSkillStore.getState().tenantConfigs).toEqual([]);
    expect(useSkillStore.getState().isLoading).toBe(false);
  });
});
