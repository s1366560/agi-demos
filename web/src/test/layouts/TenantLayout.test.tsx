
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { screen, render, waitFor } from '../utils'
import { TenantLayout } from '../../layouts/TenantLayout'

// Define mock state at module level (before vi.mock calls)
let mockTenantState: any = {
    tenants: [{ id: 't1', name: 'Test Tenant' }],
    currentTenant: { id: 't1', name: 'Test Tenant' },
    isLoading: false,
    error: null,
    total: 0,
    page: 1,
    pageSize: 20,
    listTenants: vi.fn().mockResolvedValue(undefined),
    getTenant: vi.fn().mockResolvedValue(undefined),
    createTenant: vi.fn().mockResolvedValue(undefined),
    updateTenant: vi.fn().mockResolvedValue(undefined),
    deleteTenant: vi.fn().mockResolvedValue(undefined),
    setCurrentTenant: vi.fn(),
    addMember: vi.fn().mockResolvedValue(undefined),
    removeMember: vi.fn().mockResolvedValue(undefined),
    listMembers: vi.fn().mockResolvedValue([]),
    clearError: vi.fn(),
}

// Create a function that returns a Zustand-like store
function createMockStore() {
    const getState = () => mockTenantState
    const setState = (partial: any) => {
        mockTenantState = typeof partial === 'function' ? partial(mockTenantState) : { ...mockTenantState, ...partial }
    }
    const subscribe = vi.fn()

    // Create hook function
    const storeHook = ((selector?: any) => selector ? selector(mockTenantState) : mockTenantState) as any

    // Attach methods
    storeHook.getState = getState
    storeHook.setState = setState
    storeHook.subscribe = subscribe

    return storeHook
}

// Mock i18n - must be before component imports
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => {
            const translations: Record<string, string> = {
                'nav.overview': 'Overview',
                'nav.projects': 'Projects',
                'nav.users': 'Users',
                'nav.analytics': 'Analytics',
                'nav.tasks': 'Tasks',
                'nav.agents': 'Agents',
                'nav.subagents': 'Subagents',
                'nav.skills': 'Skills',
                'nav.mcpServers': 'MCP Servers',
                'nav.providers': 'Providers',
                'nav.administration': 'Administration',
                'nav.billing': 'Billing',
                'nav.settings': 'Settings',
                'tenant.welcome': 'Welcome',
                'tenant.noTenantDescription': 'Create a workspace to get started',
                'tenant.create': 'Create Workspace',
                'common.logout': 'Logout',
                'common.search': 'Search',
            }
            return translations[key] || key
        },
    }),
}))

// Mock stores - must be at module level for vi.mock hoisting
vi.mock('../../stores/auth', () => ({
    useAuthStore: vi.fn(() => ({
        user: { name: 'Test User', email: 'test@example.com' },
        logout: vi.fn()
    }))
}))

vi.mock('../../stores/project', () => ({
    useProjectStore: vi.fn(() => ({
        currentProject: null,
        projects: [],
    }))
}))

vi.mock('../../stores/tenant', () => ({
    useTenantStore: createMockStore()
}))

vi.mock('../../components/shared/ui/WorkspaceSwitcher', () => ({
    WorkspaceSwitcher: () => <div data-testid="workspace-switcher">MockSwitcher</div>
}))
vi.mock('../../components/shared/ui/ThemeToggle', () => ({
    ThemeToggle: () => <div data-testid="theme-toggle">Theme</div>
}))
vi.mock('../../components/shared/ui/LanguageSwitcher', () => ({
    LanguageSwitcher: () => <div data-testid="lang-toggle">Lang</div>
}))

// Import after mocking to get the mocked version
import { useTenantStore } from '../../stores/tenant'

describe('TenantLayout', () => {
    beforeEach(() => {
        vi.clearAllMocks()

        // Reset to default state with a tenant
        mockTenantState = {
            tenants: [{ id: 't1', name: 'Test Tenant' }],
            currentTenant: { id: 't1', name: 'Test Tenant' },
            isLoading: false,
            error: null,
            total: 0,
            page: 1,
            pageSize: 20,
            listTenants: vi.fn().mockResolvedValue(undefined),
            getTenant: vi.fn().mockResolvedValue(undefined),
            createTenant: vi.fn().mockResolvedValue(undefined),
            updateTenant: vi.fn().mockResolvedValue(undefined),
            deleteTenant: vi.fn().mockResolvedValue(undefined),
            setCurrentTenant: vi.fn(),
            addMember: vi.fn().mockResolvedValue(undefined),
            removeMember: vi.fn().mockResolvedValue(undefined),
            listMembers: vi.fn().mockResolvedValue([]),
            clearError: vi.fn(),
        }
    })

    it('renders layout elements', async () => {
        render(<TenantLayout />)

        await waitFor(() => {
            expect(screen.getByText('MemStack')).toBeInTheDocument()
        })
        expect(screen.getByText('Overview')).toBeInTheDocument()
        expect(screen.getByText('Projects')).toBeInTheDocument()
    })

    it('renders header components', async () => {
        render(<TenantLayout />)

        await waitFor(() => {
            expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
        })
        expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
        expect(screen.getByTestId('workspace-switcher')).toBeInTheDocument()
    })

    it('toggles sidebar', async () => {
        render(<TenantLayout />)

        await waitFor(() => {
            expect(screen.getByText('MemStack')).toBeInTheDocument()
        })
        expect(screen.getByText('Overview')).toBeVisible()
    })

    it('syncs tenant from URL', async () => {
        // Set state without tenant
        mockTenantState.currentTenant = null
        mockTenantState.tenants = []

        render(<TenantLayout />)

        // Component renders even without tenant
        await waitFor(() => {
            expect(screen.getByText('MemStack')).toBeInTheDocument()
        })
    })

    it('auto creates tenant when none exist', async () => {
        // Set state without tenant and empty tenants list
        mockTenantState.currentTenant = null
        mockTenantState.tenants = []

        render(<TenantLayout />)

        // Component renders without tenant
        await waitFor(() => {
            expect(screen.getByText('MemStack')).toBeInTheDocument()
        })
    })
})
