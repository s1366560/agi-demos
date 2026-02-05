
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import { screen, fireEvent, render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { WorkspaceSwitcher } from '@/components/shared/ui/WorkspaceSwitcher'

import { useProjectStore } from '../../stores/project'
import { useTenantStore } from '../../stores/tenant'

// Mock stores
vi.mock('../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}))
vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}))

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
            vi.mocked(useTenantStore).mockImplementation((selector) => {
                const state = {
                    currentTenant: mockCurrentTenant,
                    tenants: [mockCurrentTenant],
                    listTenants: vi.fn(),
                    setCurrentTenant: vi.fn(),
                }
                if (typeof selector === 'function') {
                    return selector(state)
                }
                return state
            })

            vi.mocked(useProjectStore).mockReturnValue({
                projects: [],
                listProjects: vi.fn(),
            } as any)

            renderWithRouter(<WorkspaceSwitcher mode="tenant" />)

            expect(screen.getByText('Test Tenant')).toBeInTheDocument()
        })

        it('opens dropdown on click', () => {
            const mockCurrentTenant = { id: 't1', name: 'Test Tenant' }
            vi.mocked(useTenantStore).mockImplementation((selector) => {
                const state = {
                    currentTenant: mockCurrentTenant,
                    tenants: [mockCurrentTenant, { id: 't2', name: 'Other Tenant' }],
                    listTenants: vi.fn(),
                }
                if (typeof selector === 'function') {
                    return selector(state)
                }
                return state
            })

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
            vi.mocked(useProjectStore).mockImplementation((selector) => {
                const state = {
                    projects: [mockCurrentProject],
                    currentProject: mockCurrentProject,
                    listProjects: vi.fn(),
                }
                if (typeof selector === 'function') {
                    return selector(state)
                }
                return state
            })

            // Mock tenant store for "Back to Tenant" check
            vi.mocked(useTenantStore).mockImplementation((selector) => {
                const state = {
                    currentTenant: { id: 't1', name: 'Test Tenant' },
                    tenants: [{ id: 't1', name: 'Test Tenant' }],
                    listTenants: vi.fn(),
                }
                if (typeof selector === 'function') {
                    return selector(state)
                }
                return state
            })

            renderWithRouter(<WorkspaceSwitcher mode="project" />, { route: '/project/p1' })

            expect(screen.getByText('Test Project')).toBeInTheDocument()
        })
    })
})
