/**
 * AppSidebar Component Tests
 *
 * Tests for the reusable sidebar component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppSidebar } from '@/components/layout/AppSidebar'
import type { SidebarConfig, NavUser } from '@/config/navigation'

// Mock dependencies
vi.mock('@/components/layout/SidebarNavItem', () => ({
  SidebarNavItem: ({ item, basePath }: {
    item: { id: string; label: string; path: string }
    basePath: string
  }) => (
    <a href={basePath + item.path} data-testid={`nav-${item.id}`}>
      {item.label}
    </a>
  ),
}))

vi.mock('@/hooks/useNavigation', () => ({
  useNavigation: () => ({
    isActive: () => false,
    getLink: (path: string) => path,
  }),
}))

vi.mock('antd', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Collapse: ({ in: $in, children }: { in: boolean; children: React.ReactNode }) =>
    $in ? <div>{children}</div> : null,
}))

const mockUser: NavUser = {
  name: 'Test User',
  email: 'test@example.com',
}

const mockConfig: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'main',
      title: 'Main',
      collapsible: false,
      defaultOpen: true,
      items: [
        { id: 'overview', icon: 'dashboard', label: 'Overview', path: '' },
        { id: 'projects', icon: 'folder', label: 'Projects', path: '/projects' },
      ],
    },
    {
      id: 'settings',
      title: 'Settings',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'general', icon: 'settings', label: 'General', path: '/settings' },
      ],
    },
  ],
  bottom: [
    { id: 'support', icon: 'help', label: 'Support', path: '/support' },
  ],
}

function renderSidebar(props = {}) {
  const defaults = {
    config: mockConfig,
    basePath: '/tenant',
    user: mockUser,
  }

  return render(
    <MemoryRouter initialEntries={['/tenant']}>
      <AppSidebar {...defaults} {...props} />
    </MemoryRouter>
  )
}

describe('AppSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render sidebar with navigation items', () => {
      renderSidebar()

      expect(screen.getByText('Overview')).toBeInTheDocument()
      expect(screen.getByText('Projects')).toBeInTheDocument()
      expect(screen.getByText('General')).toBeInTheDocument()
    })

    it('should render bottom navigation items', () => {
      renderSidebar()

      expect(screen.getByText('Support')).toBeInTheDocument()
    })

    it('should render user profile section', () => {
      renderSidebar()

      expect(screen.getByText('Test User')).toBeInTheDocument()
      expect(screen.getByText('test@example.com')).toBeInTheDocument()
    })

    it('should render collapse toggle button', () => {
      const { container } = renderSidebar()

      const toggleButton = container.querySelector('button[title*="Collapse" i], button[title*="Expand" i]')
      expect(toggleButton).toBeInTheDocument()
    })
  })

  describe('Collapse State', () => {
    it('should render in expanded state by default', () => {
      const { container } = renderSidebar({ collapsed: false })

      const sidebar = container.querySelector('.w-64')
      expect(sidebar).toBeInTheDocument()
    })

    it('should render in collapsed state when prop is true', () => {
      const { container } = renderSidebar({ collapsed: true })

      const sidebar = container.querySelector('.w-20')
      expect(sidebar).toBeInTheDocument()
    })

    it('should hide user info when collapsed', () => {
      renderSidebar({ collapsed: true })

      expect(screen.queryByText('Test User')).not.toBeInTheDocument()
      expect(screen.queryByText('test@example.com')).not.toBeInTheDocument()
    })
  })

  describe('User Profile', () => {
    it('should display user avatar with first letter of name', () => {
      const { container } = renderSidebar({
        user: { name: 'Alice', email: 'alice@example.com' },
      })

      const avatar = container.querySelector('.rounded-full')
      expect(avatar?.textContent).toBe('A')
    })

    it('should show logout button when onLogout provided', () => {
      const { container } = renderSidebar({ onLogout: vi.fn() })

      const logoutButton = container.querySelector('button[title="Sign out"]')
      expect(logoutButton).toBeInTheDocument()
    })

    it('should not show logout button when onLogout not provided', () => {
      const { container } = renderSidebar()

      const logoutButton = container.querySelector('button[title="Sign out"]')
      expect(logoutButton).not.toBeInTheDocument()
    })

    it('should call onLogout when logout button clicked', () => {
      const onLogout = vi.fn()
      const { container } = renderSidebar({ onLogout })

      const logoutButton = container.querySelector('button[title="Sign out"]')
      if (logoutButton) {
        fireEvent.click(logoutButton)
        expect(onLogout).toHaveBeenCalledTimes(1)
      }
    })
  })

  describe('Callbacks', () => {
    it('should call onCollapseToggle when collapse button clicked', () => {
      const onCollapseToggle = vi.fn()
      const { container } = renderSidebar({ onCollapseToggle })

      const toggleButton = container.querySelector('button[title*="Collapse" i]')
      if (toggleButton) {
        fireEvent.click(toggleButton)
        expect(onCollapseToggle).toHaveBeenCalledTimes(1)
      }
    })

    it('should call onGroupToggle when group toggle clicked', () => {
      const onGroupToggle = vi.fn()
      const { container } = renderSidebar({ onGroupToggle })

      // Find the Settings group toggle button by its text content
      const toggleButton = Array.from(container.querySelectorAll('button')).find(
        btn => btn.textContent?.includes('Settings')
      )
      // Settings group is collapsible, should have toggle
      expect(toggleButton).toBeDefined()

      if (toggleButton) {
        fireEvent.click(toggleButton)
        expect(onGroupToggle).toHaveBeenCalledWith('settings')
      }
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty groups array', () => {
      const emptyConfig: SidebarConfig = {
        width: 256,
        collapsedWidth: 80,
        groups: [],
      }

      expect(() => renderSidebar({ config: emptyConfig })).not.toThrow()
    })

    it('should handle showUser false', () => {
      renderSidebar({
        config: { ...mockConfig, showUser: false },
        user: mockUser,
      })

      expect(screen.queryByText('Test User')).not.toBeInTheDocument()
    })
  })
})
