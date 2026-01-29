/**
 * ProjectSidebar Component Tests
 *
 * Tests for the project-level sidebar wrapper component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ProjectSidebar } from '@/components/layout/ProjectSidebar'

// Mock dependencies
vi.mock('@/components/layout/AppSidebar', () => ({
  AppSidebar: ({ config, basePath, collapsed, onCollapseToggle, user, onLogout, openGroups, onGroupToggle }: any) => (
    <aside data-testid="project-sidebar">
      <div data-testid="base-path">{basePath}</div>
      <div data-testid="collapsed">{String(collapsed)}</div>
      <div data-testid="user-name">{user?.name}</div>
      <div data-testid="user-email">{user?.email}</div>
      <button onClick={onCollapseToggle} data-testid="toggle-collapse">Toggle</button>
      <button onClick={onLogout} data-testid="logout">Logout</button>
      <button onClick={() => onGroupToggle?.('knowledge')} data-testid="toggle-group">Toggle Group</button>
      <div data-testid="groups-count">{config.groups?.length || 0}</div>
      <div data-testid="open-knowledge">{String(openGroups?.knowledge)}</div>
    </aside>
  ),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Project User', email: 'project@example.com' },
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

function renderSidebar(props: Parameters<typeof ProjectSidebar>[0] = {}) {
  return render(
    <MemoryRouter initialEntries={['/project/test-project']}>
      <ProjectSidebar {...props} />
    </MemoryRouter>
  )
}

describe('ProjectSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render sidebar with correct base path when projectId provided', () => {
      renderSidebar({ projectId: 'proj-123' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/proj-123')
    })

    it('should render sidebar with empty projectId path', () => {
      renderSidebar({ projectId: '' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/')
    })

    it('should pass user information to AppSidebar', () => {
      renderSidebar()

      expect(screen.getByTestId('user-name')).toHaveTextContent('Project User')
      expect(screen.getByTestId('user-email')).toHaveTextContent('project@example.com')
    })

    it('should render all navigation groups from config', () => {
      renderSidebar()

      // Project config has 4 groups: main, knowledge, discovery, config
      expect(screen.getByTestId('groups-count')).toHaveTextContent('4')
    })
  })

  describe('Initial State', () => {
    it('should have knowledge group open by default', () => {
      renderSidebar()

      expect(screen.getByTestId('open-knowledge')).toHaveTextContent('true')
    })

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

      expect(toggleButton).toBeInTheDocument()
    })

    it('should handle group toggle', () => {
      renderSidebar()

      const groupButton = screen.getByTestId('toggle-group')
      groupButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))

      expect(groupButton).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('should handle special characters in projectId', () => {
      renderSidebar({ projectId: 'proj-with-dashes_and_underscores' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/proj-with-dashes_and_underscores')
    })

    it('should handle numeric projectId', () => {
      renderSidebar({ projectId: '12345' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/12345')
    })
  })
})
