import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ProjectManager } from '@/components/tenant/ProjectManager'
import { useProjectStore } from '../../stores/project'
import { useTenantStore } from '../../stores/tenant'

vi.mock('../../stores/project', () => ({
    useProjectStore: vi.fn()
}))

vi.mock('../../stores/tenant', () => ({
    useTenantStore: vi.fn()
}))

// Mock ProjectCreateModal
vi.mock('../../components/tenant/ProjectCreateModal', () => ({
    ProjectCreateModal: ({ isOpen, onClose, onSuccess }: any) => isOpen ? (
        <div data-testid="project-create-modal">
            <button onClick={onClose}>Close</button>
            <button onClick={onSuccess}>Create</button>
        </div>
    ) : null
}))

describe('ProjectManager', () => {
    const mockListProjects = vi.fn()
    const mockDeleteProject = vi.fn()
    const mockSetCurrentProject = vi.fn()
    const mockOnProjectSelect = vi.fn()

    beforeEach(() => {
        vi.clearAllMocks()
            ; (useTenantStore as any).mockReturnValue({
                currentTenant: { id: 'tenant-1', name: 'Tenant 1' }
            })
            ; (useProjectStore as any).mockReturnValue({
                projects: [],
                currentProject: null,
                listProjects: mockListProjects,
                deleteProject: mockDeleteProject,
                setCurrentProject: mockSetCurrentProject,
                isLoading: false,
                error: null
            })
    })

    it('renders loading state', () => {
         (useProjectStore as any).mockReturnValue({
            isLoading: true,
            projects: [],
            listProjects: mockListProjects
        })
        const { container } = render(<ProjectManager />)
        expect(container.querySelector('.animate-spin')).toBeInTheDocument()
    })

    it('renders empty state when no tenant selected', () => {
         (useTenantStore as any).mockReturnValue({ currentTenant: null })
        render(<ProjectManager />)
        expect(screen.getByText('请先选择工作空间')).toBeInTheDocument()
    })

    it('renders list of projects', () => {
        const projects = [
            { id: '1', name: 'Project 1', status: 'active', created_at: '2024-01-01' },
            { id: '2', name: 'Project 2', status: 'paused', created_at: '2024-01-02' }
        ]
            ; (useProjectStore as any).mockReturnValue({
                projects,
                currentProject: projects[0],
                listProjects: mockListProjects,
                setCurrentProject: mockSetCurrentProject,
                deleteProject: mockDeleteProject,
                isLoading: false
            })

        render(<ProjectManager onProjectSelect={mockOnProjectSelect} />)

        expect(screen.getByText('Project 1')).toBeInTheDocument()
        expect(screen.getByText('Project 2')).toBeInTheDocument()

        // Select project - find parent div with onClick
        const project2 = screen.getByText('Project 2')
        fireEvent.click(project2)

        expect(mockSetCurrentProject).toHaveBeenCalledWith(projects[1])
        expect(mockOnProjectSelect).toHaveBeenCalledWith(projects[1])
    })

    it('opens create modal', () => {
        render(<ProjectManager />)
        fireEvent.click(screen.getByText('新建项目'))
        expect(screen.getAllByTestId('project-create-modal').length).toBeGreaterThan(0)
    })
})
