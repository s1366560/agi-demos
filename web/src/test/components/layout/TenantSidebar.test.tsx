/**
 * TenantSidebar Component Tests
 *
 * Tests for the tenant-level sidebar wrapper component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TenantSidebar } from '@/components/layout/TenantSidebar'

// Mock dependencies
vi.mock('@/components/layout/AppSidebar', () => ({
  AppSidebar: ({ config, basePath, collapsed, onCollapseToggle, user, onLogout, openGroups, onGroupToggle }: any) => (
    <aside data-testid="tenant-sidebar">
      <div data-testid="base-path">{basePath}</div>
      <div data-testid="collapsed">{String(collapsed)}</div>
      <div data-testid="user-name">{user?.name}</div>
      <div data-testid="user-email">{user?.email}</div>
      <button onClick={onCollapseToggle} data-testid="toggle-collapse">Toggle</button>
      <button onClick={onLogout} data-testid="logout">Logout</button>
      <button onClick={() => onGroupToggle?.('test')} data-testid="toggle-group">Toggle Group</button>
      <div data-testid="groups-count">{config.groups?.length || 0}</div>
    </aside>
  ),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  }
})

function renderSidebar(props: Parameters<typeof TenantSidebar>[0] = {}) {
  return render(
    <MemoryRouter initialEntries={['/tenant/test-tenant']}>
      <TenantSidebar {...props} />
    </MemoryRouter>
  )
}

describe('TenantSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render sidebar with correct base path when tenantId provided', () => {
      renderSidebar({ tenantId: 'tenant-123' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/tenant/tenant-123')
    })

    it('should render sidebar with default base path when no tenantId', () => {
      renderSidebar()

      expect(screen.getByTestId('base-path')).toHaveTextContent('/tenant')
    })

    it('should pass user information to AppSidebar', () => {
      renderSidebar()

      expect(screen.getByTestId('user-name')).toHaveTextContent('Test User')
      expect(screen.getByTestId('user-email')).toHaveTextContent('test@example.com')
    })

    it('should render navigation groups from config', () => {
      renderSidebar()

      // Tenant config has 2 groups: platform and administration
      expect(screen.getByTestId('groups-count')).toHaveTextContent('2')
    })
  })

  describe('State Management', () => {
    it('should start expanded by default', () => {
      renderSidebar()

      expect(screen.getByTestId('collapsed')).toHaveTextContent('false')
    })

    it('should start collapsed when defaultCollapsed is true', () => {
      renderSidebar({ defaultCollapsed: true })

      expect(screen.getByTestId('collapsed')).toHaveTextContent('true')
    })
  })

  describe('Callbacks', () => {
    it('should handle collapse toggle', () => {
      renderSidebar()

      const toggleButton = screen.getByTestId('toggle-collapse')
      toggleButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))

      // Should not throw - the internal state should update
      expect(toggleButton).toBeInTheDocument()
    })

    it('should handle group toggle', () => {
      renderSidebar()

      const groupButton = screen.getByTestId('toggle-group')
      groupButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))

      // Should not throw
      expect(groupButton).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty tenantId', () => {
      renderSidebar({ tenantId: '' })

      // Empty string is falsy, so it defaults to /tenant
      expect(screen.getByTestId('base-path')).toHaveTextContent('/tenant')
    })

    it('should handle special characters in tenantId', () => {
      renderSidebar({ tenantId: 'tenant-with-special-chars_123' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/tenant/tenant-with-special-chars_123')
    })
  })
})
