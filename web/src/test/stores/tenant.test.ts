import { describe, it, expect, vi, beforeEach } from 'vitest'

import { tenantAPI } from '../../services/api'
import { useTenantStore } from '../../stores/tenant'

vi.mock('../../services/api', () => ({
    tenantAPI: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
        addMember: vi.fn(),
        removeMember: vi.fn(),
        listMembers: vi.fn(),
    }
}))

describe('TenantStore', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useTenantStore.setState({
            tenants: [],
            currentTenant: null,
            isLoading: false,
            error: null,
            total: 0,
            page: 1,
            pageSize: 20
        })
    })

    it('listTenants should update state on success', async () => {
        const mockResponse = {
            tenants: [{ id: '1', name: 'Tenant 1' }],
            total: 1,
            page: 1,
            page_size: 20
        }
            ; (tenantAPI.list as any).mockResolvedValue(mockResponse)

        await useTenantStore.getState().listTenants()

        expect(tenantAPI.list).toHaveBeenCalledWith({})
        expect(useTenantStore.getState().tenants).toEqual(mockResponse.tenants)
        expect(useTenantStore.getState().total).toBe(1)
        expect(useTenantStore.getState().isLoading).toBe(false)
    })

    it('getTenant should update currentTenant on success', async () => {
        const mockTenant = { id: '1', name: 'Tenant 1' }
            ; (tenantAPI.get as any).mockResolvedValue(mockTenant)

        await useTenantStore.getState().getTenant('1')

        expect(tenantAPI.get).toHaveBeenCalledWith('1')
        expect(useTenantStore.getState().currentTenant).toEqual(mockTenant)
        expect(useTenantStore.getState().isLoading).toBe(false)
    })

    it('createTenant should add tenant to list', async () => {
        const newTenant = { id: '2', name: 'New Tenant' }
            ; (tenantAPI.create as any).mockResolvedValue(newTenant)

        await useTenantStore.getState().createTenant({ name: 'New Tenant' })

        expect(tenantAPI.create).toHaveBeenCalledWith({ name: 'New Tenant' })
        expect(useTenantStore.getState().tenants).toContainEqual(newTenant)
    })

    it('updateTenant should update tenant in list', async () => {
        useTenantStore.setState({ tenants: [{ id: '1', name: 'Old Name' } as any] })
        const updatedTenant = { id: '1', name: 'New Name' }
            ; (tenantAPI.update as any).mockResolvedValue(updatedTenant)

        await useTenantStore.getState().updateTenant('1', { name: 'New Name' })

        expect(tenantAPI.update).toHaveBeenCalledWith('1', { name: 'New Name' })
        expect(useTenantStore.getState().tenants[0]).toEqual(updatedTenant)
    })

    it('deleteTenant should remove tenant from list', async () => {
        useTenantStore.setState({ tenants: [{ id: '1', name: 'Tenant 1' } as any] })
            ; (tenantAPI.delete as any).mockResolvedValue({})

        await useTenantStore.getState().deleteTenant('1')

        expect(tenantAPI.delete).toHaveBeenCalledWith('1')
        expect(useTenantStore.getState().tenants).toHaveLength(0)
    })

    it('setCurrentTenant should update state', () => {
        const tenant = { id: '1', name: 'Tenant 1' } as any
        useTenantStore.getState().setCurrentTenant(tenant)
        expect(useTenantStore.getState().currentTenant).toEqual(tenant)
    })
})
