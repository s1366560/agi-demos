
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { TenantOverview } from '../../../pages/tenant/TenantOverview'
import { tenantAPI } from '../../../services/api'
import { useTenantStore } from '../../../stores/tenant'
import { screen, render, waitFor } from '../../utils'

vi.mock('../../../stores/tenant')
vi.mock('../../../services/api')

describe('TenantOverview', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('renders tenant information', async () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: {
                id: 't1',
                name: 'Test Corp',
                description: 'A test tenant',
                plan: 'basic',
                created_at: '2023-01-01'
            },
            tenants: [{ id: 't1' }],
            listTenants: vi.fn(),
            setCurrentTenant: vi.fn(),
        } as any)

        vi.mocked(tenantAPI.getStats).mockResolvedValue({
            storage: { used: 100, total: 1000, percentage: 10 },
            projects: { active: 5, new_this_week: 1, list: [] },
            members: { total: 10, new_added: 2 },
            tenant_info: {
                organization_id: 'ORG-123',
                plan: 'basic',
                region: 'US-East',
                next_billing_date: '2023-02-01'
            }
        })

        render(<TenantOverview />)

        await waitFor(() => {
            expect(screen.getByText('Overview')).toBeInTheDocument()
            expect(screen.getByText('ORG-123')).toBeInTheDocument()
            expect(screen.getByText('basic')).toBeInTheDocument()
        })
    })

    it('renders loading state when no tenant', () => {
        vi.mocked(useTenantStore).mockReturnValue({
            currentTenant: null,
            tenants: [],
            listTenants: vi.fn(),
        } as any)

        render(<TenantOverview />)

        expect(screen.getByText('Loading tenant information...')).toBeInTheDocument()
    })
})
