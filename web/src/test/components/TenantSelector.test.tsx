import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { TenantSelector } from '@/components/tenant/TenantSelector'

import { useTenantStore } from '../../stores/tenant'

vi.mock('../../stores/tenant', () => ({
    useTenantStore: vi.fn()
}))

describe('TenantSelector', () => {
    const mockSetCurrentTenant = vi.fn()
    const mockOnCreateTenant = vi.fn()
    const mockOnManageTenant = vi.fn()

    beforeEach(() => {
        vi.clearAllMocks()
            ; (useTenantStore as any).mockReturnValue({
                tenants: [],
                currentTenant: null,
                isLoading: false,
                setCurrentTenant: mockSetCurrentTenant
            })
    })

    it('renders loading state', () => {
         (useTenantStore as any).mockReturnValue({ isLoading: true })
        const { container } = render(<TenantSelector />)
        expect(container.querySelector('.animate-spin')).toBeInTheDocument()
    })

    it('renders empty state', () => {
        render(<TenantSelector onCreateTenant={mockOnCreateTenant} />)
        expect(screen.getByText('暂无工作空间')).toBeInTheDocument()

        fireEvent.click(screen.getByText('创建工作空间'))
        expect(mockOnCreateTenant).toHaveBeenCalled()
    })

    it('renders list of tenants', () => {
        const tenants = [
            { id: '1', name: 'Tenant 1', plan: 'free', created_at: '2024-01-01' },
            { id: '2', name: 'Tenant 2', plan: 'premium', created_at: '2024-01-02' }
        ]
            ; (useTenantStore as any).mockReturnValue({
                tenants,
                currentTenant: tenants[0],
                setCurrentTenant: mockSetCurrentTenant
            })

        render(<TenantSelector onManageTenant={mockOnManageTenant} />)

        expect(screen.getByText('Tenant 1')).toBeInTheDocument()
        expect(screen.getByText('Tenant 2')).toBeInTheDocument()

        // Select tenant
        // We can find the element by text and click its parent
        fireEvent.click(screen.getByText('Tenant 2'))
        expect(mockSetCurrentTenant).toHaveBeenCalledWith(tenants[1])
    })
})
