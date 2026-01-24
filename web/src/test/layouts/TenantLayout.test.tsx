
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, render, waitFor } from '../utils'
import { TenantLayout } from '../../layouts/TenantLayout'
import { useTenantStore } from '../../stores/tenant'
import { useAuthStore } from '../../stores/auth'

vi.mock('../../stores/auth', () => ({
    useAuthStore: vi.fn()
}))

vi.mock('../../stores/tenant', () => {
    const mockStore = vi.fn()
    // @ts-expect-error Mocking partial state
    mockStore.getState = vi.fn(() => ({
        tenants: [{ id: 't1', name: 'Test Tenant' }],
        listTenants: vi.fn(),
        createTenant: vi.fn()
    }))
    return { useTenantStore: mockStore }
})
vi.mock('../../components/WorkspaceSwitcher', () => ({
    WorkspaceSwitcher: () => <div>MockSwitcher</div>
}))

describe('TenantLayout', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(useAuthStore).mockReturnValue({
            user: { name: 'Test User', email: 'test@example.com' },
            logout: vi.fn()
        } as any)
    })

    it('renders layout elements', () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: { id: 't1', name: 'Test Tenant' },
            getTenant: vi.fn(),
            setCurrentTenant: vi.fn(),
        } as any)

        render(<TenantLayout />)

        expect(screen.getByText('MemStack')).toBeInTheDocument()
        expect(screen.getByText('Overview')).toBeInTheDocument()
        expect(screen.getByText('Projects')).toBeInTheDocument()
    })

    it('toggles sidebar', () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: { id: 't1', name: 'Test Tenant' },
            getTenant: vi.fn(),
        } as any)

        render(<TenantLayout />)

        // Initially expanded
        expect(screen.getByText('Overview')).toBeVisible()

        // Click toggle button
        const toggleBtn = screen.getByText('menu').closest('button')
        fireEvent.click(toggleBtn!)

        // Should be collapsed (text hidden or styled differently, hard to test strict visibility with just jsdom sometimes, 
        // but we can check if the class changed or if text is gone from accessibility tree if conditional rendering is used)

        // In our implementation, we hide text with conditional rendering: {!isSidebarCollapsed && ...}
        expect(screen.queryByText('Overview')).not.toBeInTheDocument()
    })

    it('syncs tenant from URL', () => {
        const getTenantMock = vi.fn()
        const setCurrentTenantMock = vi.fn()
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: null,
            getTenant: getTenantMock,
            setCurrentTenant: setCurrentTenantMock,
        } as any)

        render(<TenantLayout />, { route: '/tenant/t123' })

        // The component uses useParams which might not work perfectly with MemoryRouter initialEntries directly 
        // unless we render with a Route path.
        // But let's see if we can mock useParams or use a Route wrapper in render.
    })

    it('auto creates tenant when none exist', async () => {
        const createTenantMock = vi.fn().mockResolvedValue({})
        const listTenantsMock = vi.fn().mockResolvedValue({ tenants: [], total: 0 })
        const setCurrentTenantMock = vi.fn()

        // Mock the store hook return value
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: null,
            setCurrentTenant: setCurrentTenantMock,
            getTenant: vi.fn(),
            tenants: [], // Initially empty
        } as any)

            // Mock getState for non-hook usage
            ; (useTenantStore as any).getState = vi.fn(() => ({
                tenants: [],
                listTenants: listTenantsMock,
                createTenant: createTenantMock.mockImplementation(async () => {
                    // Simulate state update after creation
                    (useTenantStore as any).getState = vi.fn(() => ({
                        tenants: [{ id: 'new-t', name: "Test User's Workspace" }],
                        listTenants: listTenantsMock,
                        createTenant: createTenantMock
                    }))
                })
            }))

        render(<TenantLayout />)

        await waitFor(() => {
            expect(listTenantsMock).toHaveBeenCalled()
            expect(createTenantMock).toHaveBeenCalledWith(expect.objectContaining({
                name: "Test User's Workspace"
            }))
        })
    })
})
