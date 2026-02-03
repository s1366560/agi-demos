/**
 * AppHeader Compound Component Tests
 *
 * TDD tests for the new compound component pattern.
 * These tests define the desired API before implementation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as AppHeaderModule from '@/components/layout/AppHeader'

// Import components after module is created
const { AppHeader } = AppHeaderModule

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'zh-CN', changeLanguage: vi.fn() },
  }),
}))

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

// Mock auth store
const mockLogout = vi.fn()
const mockUser = {
  id: '1',
  email: 'test@example.com',
  name: 'Test User',
  roles: ['admin'],
  is_active: true,
  created_at: '2024-01-01',
  profile: {
    avatar_url: null,
  },
}

vi.mock('@/stores/auth', () => ({
  useUser: vi.fn(() => mockUser),
  useAuthActions: () => ({ logout: mockLogout }),
}))

function renderWithHeader(node: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={['/tenant']}>
      {node}
    </MemoryRouter>
  )
}

describe('AppHeader (Compound Components)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Basic Rendering', () => {
    it('should render header with basePath only', () => {
      renderWithHeader(<AppHeader basePath="/tenant" />)

      expect(screen.getByText('Home')).toBeInTheDocument()
    })

    it('should render header with empty children', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
        </AppHeader>
      )

      expect(screen.getByText('Home')).toBeInTheDocument()
    })
  })

  describe('AppHeader.SidebarToggle', () => {
    it('should render sidebar toggle when child is provided', () => {
      const onToggle = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} onToggle={onToggle} />
        </AppHeader>
      )

      const toggleButton = screen.getByLabelText(/Collapse sidebar|Expand sidebar/)
      expect(toggleButton).toBeInTheDocument()
    })

    it('should call onToggle when clicked', () => {
      const onToggle = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} onToggle={onToggle} />
        </AppHeader>
      )

      const toggleButton = screen.getByLabelText('Collapse sidebar')
      fireEvent.click(toggleButton)
      expect(onToggle).toHaveBeenCalledTimes(1)
    })

    it('should show correct icon based on collapsed state', () => {
      const onToggle = vi.fn()
      const { container: containerExpanded } = renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} onToggle={onToggle} />
        </AppHeader>
      )

      const { container: containerCollapsed } = renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={true} onToggle={onToggle} />
        </AppHeader>
      )
    })

    it('should not render without onToggle callback', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} />
        </AppHeader>
      )

      expect(screen.queryByLabelText(/Collapse sidebar|Expand sidebar/)).not.toBeInTheDocument()
    })
  })

  describe('AppHeader.MobileMenu', () => {
    it('should render mobile menu button', () => {
      const onToggle = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.MobileMenu onToggle={onToggle} />
        </AppHeader>
      )

      const menuButton = screen.getByLabelText('Toggle menu')
      expect(menuButton).toBeInTheDocument()
    })

    it('should call onToggle when clicked', () => {
      const onToggle = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.MobileMenu onToggle={onToggle} />
        </AppHeader>
      )

      const menuButton = screen.getByLabelText('Toggle menu')
      fireEvent.click(menuButton)
      expect(onToggle).toHaveBeenCalledTimes(1)
    })

    it('should not render without onToggle callback', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.MobileMenu />
        </AppHeader>
      )

      expect(screen.queryByLabelText('Toggle menu')).not.toBeInTheDocument()
    })
  })

  describe('AppHeader.Search', () => {
    it('should render search input', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Search />
        </AppHeader>
      )

      const searchInput = screen.queryByPlaceholderText('Search...')
      expect(searchInput).toBeInTheDocument()
    })

    it('should display search value', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Search value="test search" />
        </AppHeader>
      )

      const searchInput = screen.queryByPlaceholderText('Search...') as HTMLInputElement
      expect(searchInput.value).toBe('test search')
    })

    it('should call onChange when typing', () => {
      const onChange = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Search value="" onChange={onChange} />
        </AppHeader>
      )

      const searchInput = screen.queryByPlaceholderText('Search...') as HTMLInputElement
      fireEvent.change(searchInput, { target: { value: 'test' } })
      expect(onChange).toHaveBeenCalledWith('test')
    })

    it('should call onSubmit when Enter key is pressed', () => {
      const onSubmit = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Search value="test" onSubmit={onSubmit} />
        </AppHeader>
      )

      const searchInput = screen.queryByPlaceholderText('Search...') as HTMLInputElement
      fireEvent.keyDown(searchInput, { key: 'Enter' })
      expect(onSubmit).toHaveBeenCalledWith('test')
    })

    it('should not call onSubmit for non-Enter keys', () => {
      const onSubmit = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Search value="test" onSubmit={onSubmit} />
        </AppHeader>
      )

      const searchInput = screen.queryByPlaceholderText('Search...') as HTMLInputElement
      fireEvent.keyDown(searchInput, { key: 'Escape' })
      expect(onSubmit).not.toHaveBeenCalled()
    })
  })

  describe('AppHeader.Notifications', () => {
    it('should render notifications bell', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Notifications />
        </AppHeader>
      )

      const bellButton = screen.queryByLabelText('Notifications')
      expect(bellButton).toBeInTheDocument()
    })

    it('should show badge when count > 0', () => {
      const { container } = renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Notifications count={5} />
        </AppHeader>
      )

      const badge = container.querySelector('.bg-red-500')
      expect(badge).toBeInTheDocument()
    })

    it('should not show badge when count is 0', () => {
      const { container } = renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Notifications count={0} />
        </AppHeader>
      )

      const badge = container.querySelector('.bg-red-500')
      expect(badge).not.toBeInTheDocument()
    })

    it('should call onClick when clicked', () => {
      const onClick = vi.fn()
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Notifications onClick={onClick} />
        </AppHeader>
      )

      const bellButton = screen.queryByLabelText('Notifications') as HTMLElement
      fireEvent.click(bellButton)
      expect(onClick).toHaveBeenCalledTimes(1)
    })
  })

  describe('AppHeader.Tools', () => {
    it('should render children tools', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Tools>
            <button data-testid="custom-tool">Tool</button>
          </AppHeader.Tools>
        </AppHeader>
      )

      expect(screen.getByTestId('custom-tool')).toBeInTheDocument()
    })

    it('should render multiple tools', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Tools>
            <button data-testid="tool-1">Tool 1</button>
            <button data-testid="tool-2">Tool 2</button>
          </AppHeader.Tools>
        </AppHeader>
      )

      expect(screen.getByTestId('tool-1')).toBeInTheDocument()
      expect(screen.getByTestId('tool-2')).toBeInTheDocument()
    })

    it('should render empty when no children', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.Tools />
        </AppHeader>
      )
    })
  })

  describe('AppHeader.ThemeToggle', () => {
    it('should render theme toggle', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.ThemeToggle />
        </AppHeader>
      )

      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
    })
  })

  describe('AppHeader.LanguageSwitcher', () => {
    it('should render language switcher', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.LanguageSwitcher />
        </AppHeader>
      )

      expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
    })
  })

  describe('AppHeader.WorkspaceSwitcher', () => {
    it('should render workspace switcher with tenant mode', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.WorkspaceSwitcher mode="tenant" />
        </AppHeader>
      )

      expect(screen.getByTestId('workspace-tenant')).toBeInTheDocument()
    })

    it('should render workspace switcher with project mode', () => {
      renderWithHeader(
        <AppHeader basePath="/project/1">
          <AppHeader.WorkspaceSwitcher mode="project" />
        </AppHeader>
      )

      expect(screen.getByTestId('workspace-project')).toBeInTheDocument()
    })
  })

  describe('AppHeader.UserMenu', () => {
    it('should render user menu', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.UserMenu />
        </AppHeader>
      )

      expect(screen.getByLabelText('User menu')).toBeInTheDocument()
      expect(screen.getByText((content) => content.includes('Test User'))).toBeInTheDocument()
    })

    it('should show dropdown when clicked', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.UserMenu />
        </AppHeader>
      )

      const userButton = screen.getByLabelText('User menu')
      fireEvent.click(userButton)

      expect(screen.getByText('个人资料')).toBeInTheDocument()
      expect(screen.getByText('设置')).toBeInTheDocument()
      expect(screen.getByText('登出')).toBeInTheDocument()
    })

    it('should call logout when logout clicked', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.UserMenu />
        </AppHeader>
      )

      const userButton = screen.getByLabelText('User menu')
      fireEvent.click(userButton)

      const logoutButton = screen.getByText('登出')
      fireEvent.click(logoutButton)

      expect(mockLogout).toHaveBeenCalledTimes(1)
    })

    it('should use custom profile and settings paths', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.UserMenu profilePath="/custom-profile" settingsPath="/custom-settings" />
        </AppHeader>
      )

      const userButton = screen.getByLabelText('User menu')
      fireEvent.click(userButton)

      const profileLink = screen.getByText('个人资料').closest('a')
      const settingsLink = screen.getByText('设置').closest('a')

      expect(profileLink?.getAttribute('href')).toBe('/custom-profile')
      expect(settingsLink?.getAttribute('href')).toBe('/custom-settings')
    })
  })

  describe('AppHeader.PrimaryAction', () => {
    it('should render primary action button', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.PrimaryAction label="Create" to="/create" />
        </AppHeader>
      )

      expect(screen.getByText('Create')).toBeInTheDocument()
    })

    it('should render primary action with icon', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.PrimaryAction label="Create" to="/create" icon={<span data-testid="icon">+</span>} />
        </AppHeader>
      )

      expect(screen.getByTestId('icon')).toBeInTheDocument()
      expect(screen.getByText('Create')).toBeInTheDocument()
    })

    it('should translate label if it contains dot', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.PrimaryAction label="nav.newMemory" to="/new" />
        </AppHeader>
      )

      expect(screen.getByText('nav.newMemory')).toBeInTheDocument()
    })
  })

  describe('Compound Integration', () => {
    it('should render full header with all components', () => {
      const onToggle = vi.fn()
      const onSearch = vi.fn()

      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} onToggle={onToggle} />
          <AppHeader.Search value="" onChange={vi.fn()} onSubmit={onSearch} />
          <AppHeader.Tools>
            <AppHeader.ThemeToggle />
            <AppHeader.LanguageSwitcher />
          </AppHeader.Tools>
          <AppHeader.Notifications count={3} />
          <AppHeader.WorkspaceSwitcher mode="tenant" />
          <AppHeader.UserMenu />
        </AppHeader>
      )

      expect(screen.getByLabelText('Collapse sidebar')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('workspace-tenant')).toBeInTheDocument()
      expect(screen.getByLabelText('User menu')).toBeInTheDocument()
      expect(screen.getByLabelText('Notifications')).toBeInTheDocument()
    })

    it('should render custom components', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant">
          <AppHeader.SidebarToggle collapsed={false} onToggle={vi.fn()} />
          <AppHeader.Tools>
            <button data-testid="custom-tool">Custom</button>
          </AppHeader.Tools>
          <AppHeader.UserMenu />
        </AppHeader>
      )

      expect(screen.getByTestId('custom-tool')).toBeInTheDocument()
    })
  })

  describe('variant prop', () => {
    it('should render "full" variant with all default components', () => {
      renderWithHeader(<AppHeader basePath="/tenant" variant="full" />)

      // Full variant should include search, theme toggle, language switcher, notifications, workspace, user menu
      expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
      expect(screen.getByLabelText('Notifications')).toBeInTheDocument()
      expect(screen.getByTestId('workspace-tenant')).toBeInTheDocument()
      expect(screen.getByLabelText('User menu')).toBeInTheDocument()
    })

    it('should render "minimal" variant with only breadcrumbs', () => {
      renderWithHeader(<AppHeader basePath="/tenant" variant="minimal" />)

      expect(screen.getByText('Home')).toBeInTheDocument()
      expect(screen.queryByPlaceholderText('Search...')).not.toBeInTheDocument()
    })

    it('should allow overriding variant defaults with children', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant" variant="minimal">
          <AppHeader.Search />
        </AppHeader>
      )

      expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
    })
  })

  describe('Breadcrumbs', () => {
    it('should use custom breadcrumbs when provided', () => {
      renderWithHeader(
        <AppHeader
          basePath="/tenant"
          breadcrumbs={[{ label: 'Custom', path: '/custom' }]}
        />
      )

      expect(screen.getByText('Custom')).toBeInTheDocument()
      expect(screen.queryByText('Home')).not.toBeInTheDocument()
    })

    it('should use breadcrumb options', () => {
      renderWithHeader(
        <AppHeader basePath="/tenant" breadcrumbOptions={{ skipFirst: true }} />
      )
    })
  })

  describe('Context', () => {
    it('should pass context to useBreadcrumbs hook', () => {
      renderWithHeader(<AppHeader basePath="/project/1" context="project" />)

      expect(screen.getByText('Home')).toBeInTheDocument()
    })
  })

  describe('Backward Compatibility', () => {
    it('should support legacy props via LegacyAppHeader', () => {
      const { LegacyAppHeader } = AppHeaderModule

      renderWithHeader(
        <LegacyAppHeader
          basePath="/tenant"
          showSidebarToggle={true}
          sidebarCollapsed={false}
          onSidebarToggle={vi.fn()}
          showSearch={true}
          showThemeToggle={true}
          showLanguageSwitcher={true}
          showNotifications={true}
          notificationCount={3}
          showWorkspaceSwitcher={true}
          workspaceMode="tenant"
          showUserStatus={true}
        />
      )

      expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('lang-toggle')).toBeInTheDocument()
      expect(screen.getByLabelText('Notifications')).toBeInTheDocument()
      expect(screen.getByTestId('workspace-tenant')).toBeInTheDocument()
      expect(screen.getByLabelText('User menu')).toBeInTheDocument()
    })

    it('should support legacy showMobileMenu', () => {
      const { LegacyAppHeader } = AppHeaderModule
      const onToggle = vi.fn()

      renderWithHeader(
        <LegacyAppHeader
          basePath="/tenant"
          showMobileMenu={true}
          onMobileMenuToggle={onToggle}
        />
      )

      const menuButton = screen.getByLabelText('Toggle menu')
      expect(menuButton).toBeInTheDocument()

      fireEvent.click(menuButton)
      expect(onToggle).toHaveBeenCalledTimes(1)
    })

    it('should support legacy primaryAction', () => {
      const { LegacyAppHeader } = AppHeaderModule

      renderWithHeader(
        <LegacyAppHeader
          basePath="/tenant"
          primaryAction={{ label: 'Create', to: '/create' }}
        />
      )

      expect(screen.getByText('Create')).toBeInTheDocument()
    })

    it('should support legacy extraActions', () => {
      const { LegacyAppHeader } = AppHeaderModule

      renderWithHeader(
        <LegacyAppHeader
          basePath="/tenant"
          extraActions={<button data-testid="extra-action">Extra</button>}
        />
      )

      expect(screen.getByTestId('extra-action')).toBeInTheDocument()
    })
  })

  describe('Styling', () => {
    it('should have correct header classes', () => {
      const { container } = renderWithHeader(<AppHeader basePath="/tenant" />)
      const header = container.querySelector('header')

      expect(header).toHaveClass('h-16')
      expect(header).toHaveClass('flex')
      expect(header).toHaveClass('items-center')
    })

    it('should render with border bottom', () => {
      const { container } = renderWithHeader(<AppHeader basePath="/tenant" />)
      const header = container.querySelector('header')

      expect(header?.className).toContain('border-b')
    })
  })

  describe('TypeScript Types', () => {
    // Note: Type exports are verified by TypeScript compiler, not runtime tests
    // These tests are skipped as types are erased during compilation
    it.skip('should export Breadcrumb type', () => {
      expect(AppHeaderModule.Breadcrumb).toBeDefined()
    })

    it.skip('should export AppHeaderProps type', () => {
      expect(AppHeaderModule.AppHeaderProps).toBeDefined()
    })

    it.skip('should export CompoundComponentProps type', () => {
      expect(AppHeaderModule.CompoundComponentProps).toBeDefined()
    })
  })
})
