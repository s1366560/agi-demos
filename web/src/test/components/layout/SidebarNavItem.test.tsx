/**
 * SidebarNavItem Component Tests
 *
 * Tests for the reusable navigation item component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SidebarNavItem } from '@/components/layout/SidebarNavItem'
import type { NavItem } from '@/config/navigation'

// Mock antd Tooltip and Empty (used by lazyAntd which is imported transitively)
vi.mock('antd', () => ({
  Tooltip: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div title={title}>{children}</div>
  ),
  Empty: {
    PRESENTED_IMAGE_SIMPLE: 'simple',
    PRESENTED_IMAGE_DEFAULT: 'default',
  },
}))

function renderItem(
  item: Partial<NavItem>,
  props: {
    collapsed?: boolean
    basePath?: string
    currentPathname?: string
    forceActive?: boolean
  } = {}
) {
  const fullItem: NavItem = {
    id: item.id || 'test-item',
    icon: item.icon || 'home',
    label: item.label || 'Test Item',
    path: item.path !== undefined ? item.path : '/test', // Preserve empty string
    exact: item.exact,
    badge: item.badge,
    hidden: item.hidden,
    disabled: item.disabled,
    permission: item.permission,
  }

  // Use currentPathname for both router entry and prop
  const testPath = props.currentPathname || '/'

  return render(
    <MemoryRouter initialEntries={[testPath]}>
      <SidebarNavItem
        item={fullItem}
        collapsed={props.collapsed ?? false}
        basePath={props.basePath ?? '/tenant'}
        currentPathname={testPath}
        forceActive={props.forceActive}
      />
    </MemoryRouter>
  )
}

describe('SidebarNavItem', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render the navigation item with label and icon', () => {
      renderItem({ label: 'Dashboard', icon: 'dashboard', path: '' })

      expect(screen.getByText('Dashboard')).toBeInTheDocument()
      const icon = document.querySelector('.material-symbols-outlined')
      expect(icon?.textContent).toBe('dashboard')
    })

    it('should render a link with correct href', () => {
      renderItem({ label: 'Test', path: '/test' }, { basePath: '/tenant' })

      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', '/tenant/test')
    })

    it('should render with badge when provided', () => {
      renderItem({ label: 'Messages', path: '/messages', badge: 5 })

      expect(screen.getByText('5')).toBeInTheDocument()
    })

    it('should render badge with "99+" for large numbers', () => {
      renderItem({ label: 'Notifications', path: '/notifications', badge: 150 })

      expect(screen.getByText('99+')).toBeInTheDocument()
    })

    it('should not render badge when zero', () => {
      renderItem({ label: 'Messages', path: '/messages', badge: 0 })

      expect(screen.queryByText('0')).not.toBeInTheDocument()
    })

    it('should not render badge when undefined', () => {
      renderItem({ label: 'Messages', path: '/messages' })

      const badge = document.querySelector('.bg-primary.text-white')
      expect(badge).not.toBeInTheDocument()
    })
  })

  describe('Active State', () => {
    it('should show as active when current path matches exactly', () => {
      renderItem(
        { label: 'Overview', path: '', exact: true },
        { basePath: '/tenant', currentPathname: '/tenant' }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('bg-primary/10')
      expect(link.className).toContain('text-primary')
    })

    it('should show as active for partial path match when not exact', () => {
      renderItem(
        { label: 'Projects', path: '/projects' },
        { basePath: '/tenant', currentPathname: '/tenant/projects' }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('bg-primary/10')
    })

    it('should show as active for nested paths', () => {
      renderItem(
        { label: 'Memories', path: '/memories' },
        { basePath: '/project/123', currentPathname: '/project/123/memories/abc' }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('bg-primary/10')
    })

    it('should not show as active for different path', () => {
      renderItem(
        { label: 'Projects', path: '/projects' },
        { basePath: '/tenant', currentPathname: '/tenant/users' }
      )

      const link = screen.getByRole('link')
      expect(link.className).not.toContain('bg-primary/10')
    })

    it('should not show as active for exact match when on nested path', () => {
      renderItem(
        { label: 'Overview', path: '', exact: true },
        { basePath: '/tenant', currentPathname: '/tenant/users' }
      )

      const link = screen.getByRole('link')
      expect(link.className).not.toContain('bg-primary/10')
    })

    it('should respect forceActive prop', () => {
      renderItem(
        { label: 'Test', path: '/test' },
        { basePath: '/tenant', currentPathname: '/tenant/other', forceActive: true }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('bg-primary/10')
    })

    it('should show active indicator dot when active and not collapsed', () => {
      renderItem(
        { label: 'Active', path: '/active' },
        { basePath: '/tenant', currentPathname: '/tenant/active' }
      )

      // Use a more specific selector that's part of the component structure
      const link = screen.getByRole('link')
      // The indicator is a child div within the active link
      const indicator = link.querySelector('.rounded-full.bg-primary')
      expect(indicator).toBeInTheDocument()
    })

    it('should not show active indicator dot when collapsed', () => {
      renderItem(
        { label: 'Active', path: '/active' },
        { basePath: '/tenant', currentPathname: '/tenant/active', collapsed: true }
      )

      const indicator = document.querySelector('.w-1.5.h-1.5.rounded-full.bg-primary')
      expect(indicator).not.toBeInTheDocument()
    })
  })

  describe('Collapsed State', () => {
    it('should hide label when collapsed', () => {
      renderItem(
        { label: 'Hidden Label', path: '/test' },
        { collapsed: true }
      )

      expect(screen.queryByText('Hidden Label')).not.toBeInTheDocument()
    })

    it('should center content when collapsed', () => {
      renderItem(
        { label: 'Test', path: '/test' },
        { collapsed: true }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('justify-center')
    })

    it('should not show badge when collapsed', () => {
      renderItem(
        { label: 'Messages', path: '/messages', badge: 5 },
        { collapsed: true }
      )

      expect(screen.queryByText('5')).not.toBeInTheDocument()
    })

    it('should wrap in tooltip when collapsed', () => {
      renderItem(
        { label: 'Tooltip Label', path: '/test' },
        { collapsed: true }
      )

      const tooltip = document.querySelector('[title="Tooltip Label"]')
      expect(tooltip).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('should have aria-current="page" when active', () => {
      renderItem(
        { label: 'Current Page', path: '/current' },
        { basePath: '/tenant', currentPathname: '/tenant/current' }
      )

      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('aria-current', 'page')
    })

    it('should not have aria-current when not active', () => {
      renderItem(
        { label: 'Other Page', path: '/other' },
        { basePath: '/tenant', currentPathname: '/tenant/current' }
      )

      const link = screen.getByRole('link')
      expect(link).not.toHaveAttribute('aria-current')
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty path (root navigation)', () => {
      renderItem({ label: 'Root', path: '' }, { basePath: '/tenant' })

      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', '/tenant')
    })

    it('should handle path without leading slash', () => {
      renderItem({ label: 'Test', path: 'test' }, { basePath: '/tenant' })

      const link = screen.getByRole('link')
      // Component should normalize the path
      expect(link).toHaveAttribute('href', '/tenant/test')
    })

    it('should handle trailing slash in current path', () => {
      renderItem(
        { label: 'Overview', path: '', exact: true },
        { basePath: '/tenant', currentPathname: '/tenant/' }
      )

      const link = screen.getByRole('link')
      expect(link.className).toContain('bg-primary/10')
    })
  })
})
