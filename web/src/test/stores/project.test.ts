import { describe, it, expect, vi, beforeEach } from 'vitest'

import { projectAPI } from '../../services/api'
import { useProjectStore } from '../../stores/project'

vi.mock('../../services/api', () => ({
    projectAPI: {
        list: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
        get: vi.fn(),
    }
}))

describe('ProjectStore', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useProjectStore.setState({
            projects: [],
            currentProject: null,
            isLoading: false,
            error: null,
            total: 0,
            page: 1,
            pageSize: 20
        })
    })

    it('listProjects should update state on success', async () => {
        const mockResponse = {
            projects: [{ id: '1', name: 'Project 1' }],
            total: 1,
            page: 1,
            page_size: 20
        }
            ; (projectAPI.list as any).mockResolvedValue(mockResponse)

        await useProjectStore.getState().listProjects('tenant-1')

        expect(projectAPI.list).toHaveBeenCalledWith('tenant-1', {})
        expect(useProjectStore.getState().projects).toEqual(mockResponse.projects)
        expect(useProjectStore.getState().total).toBe(1)
    })

    it('createProject should add project to list', async () => {
        const newProject = { id: '2', name: 'New Project' }
            ; (projectAPI.create as any).mockResolvedValue(newProject)

        await useProjectStore.getState().createProject('tenant-1', { name: 'New Project' } as any)

        expect(projectAPI.create).toHaveBeenCalledWith('tenant-1', { name: 'New Project' })
        expect(useProjectStore.getState().projects).toContainEqual(newProject)
    })

    it('updateProject should update project in list', async () => {
        useProjectStore.setState({ projects: [{ id: '1', name: 'Old Name' } as any] })
        const updatedProject = { id: '1', name: 'New Name' }
            ; (projectAPI.update as any).mockResolvedValue(updatedProject)

        await useProjectStore.getState().updateProject('tenant-1', '1', { name: 'New Name' } as any)

        expect(projectAPI.update).toHaveBeenCalledWith('tenant-1', '1', { name: 'New Name' })
        expect(useProjectStore.getState().projects[0]).toEqual(updatedProject)
    })

    it('deleteProject should remove project from list', async () => {
        useProjectStore.setState({ projects: [{ id: '1', name: 'Project 1' } as any] })
            ; (projectAPI.delete as any).mockResolvedValue({})

        await useProjectStore.getState().deleteProject('tenant-1', '1')

        expect(projectAPI.delete).toHaveBeenCalledWith('tenant-1', '1')
        expect(useProjectStore.getState().projects).toHaveLength(0)
    })

    it('setCurrentProject should update state', () => {
        const project = { id: '1', name: 'Project 1' } as any
        useProjectStore.getState().setCurrentProject(project)
        expect(useProjectStore.getState().currentProject).toEqual(project)
    })
})
