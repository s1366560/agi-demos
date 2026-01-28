
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, render } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { WorkspaceSwitcher } from '@/components/shared/ui/WorkspaceSwitcher'
import { useTenantStore } from '../../stores/tenant'
import { useProjectStore } from '../../stores/project'

// Mock stores
vi.mock('../../stores/tenant')
vi.mock('../../stores/project')

describe('WorkspaceSwitcher', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    const renderWithRouter = (ui: React.ReactElement, { route = '/' } = {}) => {
        return render(
            <MemoryRouter initialEntries={[route]}>
                <Routes>
                    <Route path="/project/:projectId" element={ui} />
                    <Route path="*" element={ui} />
                </Routes>
            </MemoryRouter>
        )
    }

    describe('Tenant Mode', () => {
        it('renders current tenant name', () => {
            const mockCurrentTenant = { id: 't1', name: 'Test Tenant', plan: 'free' }
            vi.mocked(useTenantStore).mockReturnValue({
                currentTenant: mockCurrentTenant,
                tenants: [mockCurrentTenant],
                listTenants: vi.fn(),
                setCurrentTenant: vi.fn(),
            } as any)

            vi.mocked(useProjectStore).mockReturnValue({
                projects: [],
                listProjects: vi.fn(),
            } as any)

            renderWithRouter(<WorkspaceSwitcher mode="tenant" />)

            expect(screen.getByText('Test Tenant')).toBeInTheDocument()
        })

        it('opens dropdown on click', () => {
            const mockCurrentTenant = { id: 't1', name: 'Test Tenant' }
            vi.mocked(useTenantStore).mockReturnValue({
                currentTenant: mockCurrentTenant,
                tenants: [mockCurrentTenant, { id: 't2', name: 'Other Tenant' }],
                listTenants: vi.fn(),
            } as any)

            vi.mocked(useProjectStore).mockReturnValue({
                projects: [],
                listProjects: vi.fn(),
            } as any)

            renderWithRouter(<WorkspaceSwitcher mode="tenant" />)

            fireEvent.click(screen.getByText('Test Tenant'))
            expect(screen.getByText('Other Tenant')).toBeInTheDocument()
        })
    })

    describe('Project Mode', () => {
        it('renders current project name', () => {
            const mockCurrentProject = { id: 'p1', name: 'Test Project' }
            vi.mocked(useProjectStore).mockReturnValue({
                projects: [mockCurrentProject],
                currentProject: mockCurrentProject,
                listProjects: vi.fn(),
            } as any)

            // Mock tenant store for "Back to Tenant" check
            vi.mocked(useTenantStore).mockReturnValue({
                currentTenant: { id: 't1', name: 'Test Tenant' },
                tenants: [{ id: 't1', name: 'Test Tenant' }],
                listTenants: vi.fn(),
            } as any)

            renderWithRouter(<WorkspaceSwitcher mode="project" />, { route: '/project/p1' })

            expect(screen.getByText('Test Project')).toBeInTheDocument()
        })
    })
})
