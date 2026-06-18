import { describe, it, expect, vi, beforeEach } from 'vitest';

import { projectAPI } from '../../services/api';
import { useProjectStore } from '../../stores/project';

vi.mock('../../services/api', () => ({
  projectAPI: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    get: vi.fn(),
  },
}));

describe('ProjectStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectStore.getState().clearProjects();
    useProjectStore.setState({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
      ownerIds: [],
    });
  });

  it('listProjects should update state on success', async () => {
    const mockResponse = {
      projects: [{ id: '1', name: 'Project 1' }],
      total: 1,
      page: 1,
      page_size: 20,
    };
    (projectAPI.list as any).mockResolvedValue(mockResponse);

    await useProjectStore.getState().listProjects('tenant-1');

    expect(projectAPI.list).toHaveBeenCalledWith('tenant-1', {});
    expect(useProjectStore.getState().projects).toEqual(mockResponse.projects);
    expect(useProjectStore.getState().total).toBe(1);
  });

  it('listProjects should ignore stale responses', async () => {
    let resolveFirst: (value: any) => void = () => {};
    let resolveSecond: (value: any) => void = () => {};
    const firstRequest = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    const secondRequest = new Promise((resolve) => {
      resolveSecond = resolve;
    });
    (projectAPI.list as any).mockReturnValueOnce(firstRequest).mockReturnValueOnce(secondRequest);

    const firstList = useProjectStore.getState().listProjects('tenant-1', { search: 'old' });
    const secondList = useProjectStore.getState().listProjects('tenant-1', { search: 'new' });

    resolveSecond({
      projects: [{ id: 'new', name: 'New Result' }],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await secondList;
    expect(useProjectStore.getState().projects).toEqual([{ id: 'new', name: 'New Result' }]);

    resolveFirst({
      projects: [{ id: 'old', name: 'Old Result' }],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await firstList;
    expect(useProjectStore.getState().projects).toEqual([{ id: 'new', name: 'New Result' }]);
  });

  it('createProject should add project to list', async () => {
    const newProject = { id: '2', name: 'New Project' };
    (projectAPI.create as any).mockResolvedValue(newProject);

    await useProjectStore.getState().createProject('tenant-1', { name: 'New Project' } as any);

    expect(projectAPI.create).toHaveBeenCalledWith('tenant-1', { name: 'New Project' });
    expect(useProjectStore.getState().projects).toContainEqual(newProject);
  });

  it('updateProject should update project in list', async () => {
    useProjectStore.setState({ projects: [{ id: '1', name: 'Old Name' } as any] });
    const updatedProject = { id: '1', name: 'New Name' };
    (projectAPI.update as any).mockResolvedValue(updatedProject);

    await useProjectStore.getState().updateProject('tenant-1', '1', { name: 'New Name' } as any);

    expect(projectAPI.update).toHaveBeenCalledWith('tenant-1', '1', { name: 'New Name' });
    expect(useProjectStore.getState().projects[0]).toEqual(updatedProject);
  });

  it('deleteProject should remove project from list', async () => {
    useProjectStore.setState({ projects: [{ id: '1', name: 'Project 1' } as any] });
    (projectAPI.delete as any).mockResolvedValue({});

    await useProjectStore.getState().deleteProject('tenant-1', '1');

    expect(projectAPI.delete).toHaveBeenCalledWith('tenant-1', '1');
    expect(useProjectStore.getState().projects).toHaveLength(0);
  });

  it('getProject should return the current project without fetching', async () => {
    const currentProject = {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Current Project',
    } as any;
    useProjectStore.setState({ currentProject });

    const result = await useProjectStore.getState().getProject('tenant-1', 'project-1');

    expect(result).toBe(currentProject);
    expect(projectAPI.get).not.toHaveBeenCalled();
  });

  it('getProject should not return a matching current project from another tenant', async () => {
    const currentProject = {
      id: 'project-1',
      tenant_id: 'tenant-2',
      name: 'Other Tenant Project',
    } as any;
    const fetchedProject = {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Fetched Project',
    } as any;
    useProjectStore.setState({ currentProject });
    (projectAPI.get as any).mockResolvedValue(fetchedProject);

    const result = await useProjectStore.getState().getProject('tenant-1', 'project-1');

    expect(result).toBe(fetchedProject);
    expect(projectAPI.get).toHaveBeenCalledWith('tenant-1', 'project-1');
  });

  it('getProject should return an existing list project without fetching', async () => {
    const existingProject = {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Listed Project',
    } as any;
    useProjectStore.setState({ projects: [existingProject] });

    const result = await useProjectStore.getState().getProject('tenant-1', 'project-1');

    expect(result).toBe(existingProject);
    expect(projectAPI.get).not.toHaveBeenCalled();
  });

  it('getProject should not return a matching list project from another tenant', async () => {
    const existingProject = {
      id: 'project-1',
      tenant_id: 'tenant-2',
      name: 'Other Tenant Listed Project',
    } as any;
    const fetchedProject = {
      id: 'project-1',
      tenant_id: 'tenant-1',
      name: 'Fetched Project',
    } as any;
    useProjectStore.setState({ projects: [existingProject] });
    (projectAPI.get as any).mockResolvedValue(fetchedProject);

    const result = await useProjectStore.getState().getProject('tenant-1', 'project-1');

    expect(result).toBe(fetchedProject);
    expect(projectAPI.get).toHaveBeenCalledWith('tenant-1', 'project-1');
  });

  it('getProject should dedupe concurrent identical requests and merge the result', async () => {
    let resolveGet: (value: any) => void = () => {};
    const projectRequest = new Promise((resolve) => {
      resolveGet = resolve;
    });
    const fetchedProject = { id: 'project-1', name: 'Fetched Project' } as any;
    (projectAPI.get as any).mockReturnValue(projectRequest);

    const firstRequest = useProjectStore.getState().getProject('tenant-1', 'project-1');
    const secondRequest = useProjectStore.getState().getProject('tenant-1', 'project-1');

    expect(projectAPI.get).toHaveBeenCalledTimes(1);
    expect(projectAPI.get).toHaveBeenCalledWith('tenant-1', 'project-1');

    resolveGet(fetchedProject);

    await expect(firstRequest).resolves.toBe(fetchedProject);
    await expect(secondRequest).resolves.toBe(fetchedProject);
    expect(useProjectStore.getState().projects).toEqual([fetchedProject]);
  });

  it('getProject should reuse a recent fetched detail without a second fetch', async () => {
    const fetchedProject = { id: 'project-1', name: 'Fetched Project' } as any;
    (projectAPI.get as any).mockResolvedValue(fetchedProject);

    await expect(useProjectStore.getState().getProject('tenant-1', 'project-1')).resolves.toBe(
      fetchedProject
    );
    useProjectStore.setState({ projects: [], currentProject: null });

    await expect(useProjectStore.getState().getProject('tenant-1', 'project-1')).resolves.toBe(
      fetchedProject
    );
    expect(projectAPI.get).toHaveBeenCalledTimes(1);
  });

  it('setCurrentProject should update state', () => {
    const project = { id: '1', name: 'Project 1' } as any;
    useProjectStore.getState().setCurrentProject(project);
    expect(useProjectStore.getState().currentProject).toEqual(project);
  });

  it('clearProjects should reset tenant-scoped state', () => {
    useProjectStore.setState({
      projects: [{ id: '1', name: 'Project 1' } as any],
      currentProject: { id: '1', name: 'Project 1' } as any,
      isLoading: true,
      error: 'failed',
      total: 1,
      page: 3,
      pageSize: 50,
      ownerIds: ['owner-1'],
    });

    useProjectStore.getState().clearProjects();

    expect(useProjectStore.getState()).toMatchObject({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
      ownerIds: [],
    });
  });

  it('clearProjects should ignore stale list responses', async () => {
    let resolveList: (value: any) => void = () => {};
    const listRequest = new Promise((resolve) => {
      resolveList = resolve;
    });
    (projectAPI.list as any).mockReturnValue(listRequest);

    const listProjects = useProjectStore.getState().listProjects('tenant-1');
    useProjectStore.getState().clearProjects();

    resolveList({
      projects: [{ id: 'old', name: 'Old Tenant Project' }],
      total: 1,
      page: 1,
      page_size: 20,
      owner_ids: ['owner-1'],
    });
    await listProjects;

    expect(useProjectStore.getState().projects).toEqual([]);
    expect(useProjectStore.getState().ownerIds).toEqual([]);
  });
});
