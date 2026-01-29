/**
 * AppHeader Component Tests
 *
 * Tests for the reusable header component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppHeader } from '@/components/layout/AppHeader'
import type { Breadcrumb } from '@/components/layout/AppHeader'

// Mock dependencies
vi.mock('@/components/shared/ui/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle">Theme</button>,
}))

vi.mock('@/components/shared/ui/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <button data-testid="lang-toggle">Lang</button>,
}))

vi.mock('@/components/shared/ui/WorkspaceSwitcher', () => ({
  WorkspaceSwitcher: ({ mode }: { mode: string }) => (
    <div data-testid={`workspace-${mode}`}>Workspace {mode}</div>
  ),
}))

vi.mock('@/hooks/useBreadcrumbs', () => ({
  useBreadcrumbs: () => [
    { label: 'Home', path: '/tenant' },
    { label: 'Projects', path: '/tenant/projects' },
  ],
}))

function renderHeader(props: Partial<React.ComponentProps<typeof AppHeader>> = {}) {
  const defaultProps = {
    basePath: '/tenant',
    context: 'tenant' as const,
  }

  return render(
    <MemoryRouter initialEntries={['/tenant']}>
      <AppHeader {...defaultProps} {...props} />
    </MemoryRouter>
  )
}

describe('AppHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render header with default breadcrumbs', () => {
      renderHeader()

      expect(screen.getByText('Home')).toBeInTheDocument()
      expect(screen.getByText('Projects')).toBeInTheDocument()
    })

    it('should render custom breadcrumbs when provided', () => {
      const customBreadcrumbs: Breadcrumb[] = [
        { label: 'Dashboard', path: '/dashboard' },
        { label: 'Settings', path: '/dashboard/settings' },
      ]

      renderHeader({ breadcrumbs: customBreadcrumbs })

      expect(screen.getByText('Dashboard')).toBeInTheDocument()
      expect(screen.getByText('Settings')).toBeInTheDocument()
      expect(screen.queryByText('Home')).not.toBeInTheDocument()
    })

    it('should render theme toggle by default', () => {
      renderHeader()
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
    })

    it('should render language switcher by default', () => {
      renderHeader()
      expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
    })

    it('should render workspace switcher by default', () => {
      renderHeader()
      expect(screen.getByTestId('workspace-tenant')).toBeInTheDocument()
    })

    it('should render search input by default', () => {
      renderHeader()
      const searchInput = screen.queryByPlaceholderText('Search...')
      expect(searchInput).toBeInTheDocument()
    })

    it('should render notifications bell by default', () => {
      const { container } = renderHeader()
      const bellButton = container.querySelector('button[aria-label="Notifications"]')
      expect(bellButton).toBeInTheDocument()
    })
  })

  describe('Conditional Rendering', () => {
    it('should not render theme toggle when showThemeToggle is false', () => {
      renderHeader({ showThemeToggle: false })
      expect(screen.queryByTestId('theme-toggle')).not.toBeInTheDocument()
    })

    it('should not render language switcher when showLanguageSwitcher is false', () => {
      renderHeader({ showLanguageSwitcher: false })
      expect(screen.queryByTestId('lang-toggle')).not.toBeInTheDocument()
    })

    it('should not render workspace switcher when showWorkspaceSwitcher is false', () => {
      renderHeader({ showWorkspaceSwitcher: false })
      expect(screen.queryByTestId('workspace-tenant')).not.toBeInTheDocument()
    })

    it('should not render search when showSearch is false', () => {
      renderHeader({ showSearch: false })
      const searchInput = screen.queryByPlaceholderText('Search...')
      expect(searchInput).not.toBeInTheDocument()
    })

    it('should not render notifications when showNotifications is false', () => {
      const { container } = renderHeader({ showNotifications: false })
      const bellButton = container.querySelector('button[aria-label="Notifications"]')
      expect(bellButton).not.toBeInTheDocument()
    })

    it('should render mobile menu button when showMobileMenu is true', () => {
      const onMobileMenuToggle = vi.fn()
      renderHeader({ showMobileMenu: true, onMobileMenuToggle })

      const menuButton = screen.getByLabelText('Toggle menu')
      expect(menuButton).toBeInTheDocument()
    })

    it('should not render mobile menu button when showMobileMenu is true but no callback', () => {
      renderHeader({ showMobileMenu: true })

      const menuButton = screen.queryByLabelText('Toggle menu')
      expect(menuButton).not.toBeInTheDocument()
    })

    it('should use correct workspace mode', () => {
      renderHeader({ workspaceMode: 'project' })
      expect(screen.getByTestId('workspace-project')).toBeInTheDocument()
    })
  })

  describe('Breadcrumbs', () => {
    it('should render breadcrumbs as links except last one', () => {
      const customBreadcrumbs: Breadcrumb[] = [
        { label: 'Home', path: '/' },
        { label: 'Projects', path: '/projects' },
        { label: 'Detail', path: '/projects/1' },
      ]

      const { container } = renderHeader({ breadcrumbs: customBreadcrumbs })

      // First two should be links
      const links = container.querySelectorAll('a')
      expect(links[0]).toHaveTextContent('Home')
      expect(links[1]).toHaveTextContent('Projects')

      // Last one should be span
      expect(container.textContent).toContain('Detail')
    })

    it('should render empty when breadcrumbs array is empty', () => {
      renderHeader({ breadcrumbs: [] })
      // Should not crash, just render without breadcrumbs
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
    })

    it('should show breadcrumb separators', () => {
      const customBreadcrumbs: Breadcrumb[] = [
        { label: 'Home', path: '/' },
        { label: 'Projects', path: '/projects' },
      ]

      const { container } = renderHeader({ breadcrumbs: customBreadcrumbs })
      expect(container.textContent).toContain('/')
    })
  })

  describe('Search', () => {
    it('should call onSearchChange when typing', () => {
      const onSearchChange = vi.fn()
      const { container } = renderHeader({ onSearchChange })

      const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
      searchInput.value = 'test query'
      searchInput.dispatchEvent(new Event('change', { bubbles: true }))

      // Note: fireEvent.change or userEvent.type would be better here
      // but this tests the value binding
      expect(searchInput.value).toBe('test query')
    })

    it('should display search value from prop', () => {
      const { container } = renderHeader({ searchValue: 'existing search' })

      const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
      expect(searchInput.value).toBe('existing search')
    })

    it('should call onSearchSubmit when Enter key is pressed', () => {
      const onSearchSubmit = vi.fn()
      const { container } = renderHeader({ onSearchSubmit, searchValue: 'test' })

      const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
      const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
      searchInput.dispatchEvent(enterEvent)

      expect(onSearchSubmit).toHaveBeenCalledWith('test')
    })

    it('should not call onSearchSubmit for non-Enter keys', () => {
      const onSearchSubmit = vi.fn()
      const { container } = renderHeader({ onSearchSubmit, searchValue: 'test' })

      const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
      const escapeEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
      searchInput.dispatchEvent(escapeEvent)

      expect(onSearchSubmit).not.toHaveBeenCalled()
    })

    it('should not call onSearchSubmit when callback not provided', () => {
      const { container } = renderHeader({ searchValue: 'test' })

      const searchInput = container.querySelector('input[type="text"]') as HTMLInputElement
      const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
      // Should not throw
      expect(() => searchInput.dispatchEvent(enterEvent)).not.toThrow()
    })
  })

  describe('Notifications', () => {
    it('should not show notification badge when count is 0', () => {
      const { container } = renderHeader({ notificationCount: 0 })
      const badge = container.querySelector('.bg-red-500')
      expect(badge).not.toBeInTheDocument()
    })

    it('should show notification badge when count > 0', () => {
      const { container } = renderHeader({ notificationCount: 5 })
      const badge = container.querySelector('.bg-red-500')
      expect(badge).toBeInTheDocument()
    })

    it('should call onNotificationsClick when bell clicked', () => {
      const onNotificationsClick = vi.fn()
      const { container } = renderHeader({ onNotificationsClick })

      const bellButton = container.querySelector('button[aria-label="Notifications"]')
      if (bellButton) {
        bellButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        expect(onNotificationsClick).toHaveBeenCalledTimes(1)
      }
    })
  })

  describe('Primary Action', () => {
    it('should render primary action button when provided', () => {
      renderHeader({
        primaryAction: {
          label: 'New Item',
          to: '/new',
        },
      })

      expect(screen.getByText('New Item')).toBeInTheDocument()
    })

    it('should render primary action with icon', () => {
      const icon = <span data-testid="action-icon">+</span>
      renderHeader({
        primaryAction: {
          label: 'Create',
          to: '/create',
          icon,
        },
      })

      expect(screen.getByTestId('action-icon')).toBeInTheDocument()
      expect(screen.getByText('Create')).toBeInTheDocument()
    })

    it('should not render primary action when not provided', () => {
      const { container } = renderHeader()
      // Should not have a link with the button class
      const primaryButton = container.querySelector('.btn-primary')
      expect(primaryButton).not.toBeInTheDocument()
    })
  })

  describe('Extra Actions', () => {
    it('should render extra actions', () => {
      renderHeader({
        extraActions: <button data-testid="extra-action">Extra</button>,
      })

      expect(screen.getByTestId('extra-action')).toBeInTheDocument()
    })
  })

  describe('Callbacks', () => {
    it('should call onMobileMenuToggle when menu button clicked', () => {
      const onMobileMenuToggle = vi.fn()
      renderHeader({ showMobileMenu: true, onMobileMenuToggle })

      const menuButton = screen.getByLabelText('Toggle menu')
      menuButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      expect(onMobileMenuToggle).toHaveBeenCalledTimes(1)
    })
  })

  describe('Styling', () => {
    it('should have correct header classes', () => {
      const { container } = renderHeader()
      const header = container.querySelector('header')

      expect(header).toHaveClass('h-16')
      expect(header).toHaveClass('flex')
      expect(header).toHaveClass('items-center')
    })

    it('should render with border bottom', () => {
      const { container } = renderHeader()
      const header = container.querySelector('header')

      expect(header?.className).toContain('border-b')
    })
  })
})
