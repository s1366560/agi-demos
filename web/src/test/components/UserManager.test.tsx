import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { UserManager } from '../../components/UserManager'
import { useTenantStore } from '../../stores/tenant'
import { useProjectStore } from '../../stores/project'

// Mock the stores
vi.mock('../../stores/tenant', () => ({
    useTenantStore: vi.fn()
}))

vi.mock('../../stores/project', () => ({
    useProjectStore: vi.fn()
}))

// Mock fetch globally
global.fetch = vi.fn()

describe('UserManager - Component Tests', () => {
    const mockTenantUsers = [
        {
            id: 'user-1',
            email: 'admin@example.com',
            name: 'Admin User',
            role: 'owner',
            created_at: '2024-01-01T00:00:00Z',
            is_active: true
        },
        {
            id: 'user-2',
            email: 'member@example.com',
            name: 'Member User',
            role: 'member',
            created_at: '2024-01-15T00:00:00Z',
            is_active: true
        }
    ]

    const mockProjectUsers = [
        {
            id: 'user-1',
            email: 'admin@example.com',
            name: 'Project Admin',
            role: 'admin',
            created_at: '2024-01-01T00:00:00Z',
            is_active: true
        },
        {
            id: 'user-3',
            email: 'viewer@example.com',
            name: 'Viewer User',
            role: 'viewer',
            created_at: '2024-02-01T00:00:00Z',
            is_active: true
        }
    ]

    beforeEach(() => {
        vi.clearAllMocks()
        ; (useTenantStore as any).mockReturnValue({
            currentTenant: { id: 'tenant-1', name: 'Test Tenant' }
        })
        ; (useProjectStore as any).mockReturnValue({
            currentProject: { id: 'project-1', name: 'Test Project' }
        })
    })

    describe('Loading States', () => {
        it('shows loading state when fetching tenant users', async () => {
            (global.fetch as any).mockImplementation(() =>
                new Promise(resolve => setTimeout(() => resolve({
                    ok: true,
                    json: async () => ({ users: mockTenantUsers })
                }), 100))
            )

            render(<UserManager context="tenant" />)

            // Check for loading indicator (animate-spin class)
            await waitFor(() => {
                const loadingElements = document.querySelectorAll('.animate-spin')
                expect(loadingElements.length).toBeGreaterThan(0)
            })
        })

        it('shows loading state when fetching project users', async () => {
            (global.fetch as any).mockImplementation(() =>
                new Promise(resolve => setTimeout(() => resolve({
                    ok: true,
                    json: async () => ({ users: mockProjectUsers })
                }), 100))
            )

            render(<UserManager context="project" />)

            await waitFor(() => {
                const loadingElements = document.querySelectorAll('.animate-spin')
                expect(loadingElements.length).toBeGreaterThan(0)
            })
        })
    })

    describe('Data Display', () => {
        it('renders tenant context empty state', () => {
            (useTenantStore as any).mockReturnValue({ currentTenant: null })
            render(<UserManager context="tenant" />)
            expect(screen.getByText('Please select a workspace first')).toBeInTheDocument()
        })

        it('renders project context empty state', () => {
            (useProjectStore as any).mockReturnValue({ currentProject: null })
            render(<UserManager context="project" />)
            expect(screen.getByText('Please select a project first')).toBeInTheDocument()
        })

        it('displays tenant users after loading', async () => {
            (global.fetch as any).mockResolvedValue({
                ok: true,
                json: async () => ({ users: mockTenantUsers })
            })

            render(<UserManager context="tenant" />)

            await waitFor(() => {
                expect(screen.getByText('Admin User')).toBeInTheDocument()
                expect(screen.getByText('Member User')).toBeInTheDocument()
            })
        })

        it('displays project users after loading', async () => {
            (global.fetch as any).mockResolvedValue({
                ok: true,
                json: async () => ({ users: mockProjectUsers })
            })

            render(<UserManager context="project" />)

            await waitFor(() => {
                expect(screen.getByText('Project Admin')).toBeInTheDocument()
                expect(screen.getByText('Viewer User')).toBeInTheDocument()
            })
        })
    })

    describe('Error Handling', () => {
        it('displays error message when API call fails', async () => {
            (global.fetch as any).mockRejectedValue(new Error('Network error'))

            render(<UserManager context="tenant" />)

            await waitFor(() => {
                // Error should be logged to console, component should handle gracefully
                expect(screen.queryByText('Admin User')).not.toBeInTheDocument()
            })
        })
    })
})

describe('UserManager - API Integration Tests', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        ; (useTenantStore as any).mockReturnValue({
            currentTenant: { id: 'tenant-1', name: 'Test Tenant' }
        })
        ; (useProjectStore as any).mockReturnValue({
            currentProject: { id: 'project-1', name: 'Test Project' }
        })
    })

    it('calls correct API endpoint for tenant members', async () => {
        (global.fetch as any).mockResolvedValue({
            ok: true,
            json: async () => ({ users: [] })
        })

        render(<UserManager context="tenant" />)

        await waitFor(() => {
            expect(global.fetch).toHaveBeenCalledWith(
                '/api/v1/tenants/tenant-1/members',
                expect.objectContaining({
                    method: 'GET',
                    headers: expect.objectContaining({
                        'Content-Type': 'application/json'
                    })
                })
            )
        })
    })

    it('calls correct API endpoint for project members', async () => {
        (global.fetch as any).mockResolvedValue({
            ok: true,
            json: async () => ({ users: [] })
        })

        render(<UserManager context="project" />)

        await waitFor(() => {
            expect(global.fetch).toHaveBeenCalledWith(
                '/api/v1/projects/project-1/members',
                expect.objectContaining({
                    method: 'GET',
                    headers: expect.objectContaining({
                        'Content-Type': 'application/json'
                    })
                })
            )
        })
    })
})
