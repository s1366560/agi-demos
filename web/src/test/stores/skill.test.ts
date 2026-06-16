import { beforeEach, describe, expect, it, vi } from 'vitest';

import { skillAPI } from '@/services/skillService';
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
});
