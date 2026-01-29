/**
 * AgentSidebar Component Tests
 *
 * Tests for the agent-level sidebar wrapper component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AgentSidebar } from '@/components/layout/AgentSidebar'

// Mock dependencies
vi.mock('@/components/layout/AppSidebar', () => ({
  AppSidebar: ({ config, basePath, collapsed, onCollapseToggle, user, onLogout }: any) => (
    <aside data-testid="agent-sidebar">
      <div data-testid="base-path">{basePath}</div>
      <div data-testid="collapsed">{String(collapsed)}</div>
      <div data-testid="user-name">{user?.name}</div>
      <div data-testid="user-email">{user?.email}</div>
      <button onClick={onCollapseToggle} data-testid="toggle-collapse">Toggle</button>
      <button onClick={onLogout} data-testid="logout">Logout</button>
      <div data-testid="groups-count">{config.groups?.length || 0}</div>
      <div data-testid="bottom-count">{config.bottom?.length || 0}</div>
    </aside>
  ),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Agent User', email: 'agent@example.com' },
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

function renderSidebar(props: Parameters<typeof AgentSidebar>[0] = {}) {
  return render(
    <MemoryRouter initialEntries={['/project/test-project/agent/conv-123']}>
      <AgentSidebar {...props} />
    </MemoryRouter>
  )
}

describe('AgentSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Rendering', () => {
    it('should render sidebar with correct base path when projectId provided', () => {
      renderSidebar({ projectId: 'proj-123', conversationId: 'conv-456' })

      // basePath is now /project/{projectId} without /agent/{conversationId}
      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/proj-123')
    })

    it('should render sidebar with fallback path when no ids provided', () => {
      renderSidebar()

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project')
    })

    it('should pass user information to AppSidebar', () => {
      renderSidebar()

      expect(screen.getByTestId('user-name')).toHaveTextContent('Agent User')
      expect(screen.getByTestId('user-email')).toHaveTextContent('agent@example.com')
    })

    it('should render navigation groups from agent config', () => {
      renderSidebar()

      // Agent config has 1 group: main
      expect(screen.getByTestId('groups-count')).toHaveTextContent('1')
    })

    it('should render bottom navigation items', () => {
      renderSidebar()

      // Agent config has 2 bottom items: settings, support
      expect(screen.getByTestId('bottom-count')).toHaveTextContent('2')
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

    it('should respect controlled collapsed prop', () => {
      renderSidebar({ collapsed: true })

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
  })

  describe('Edge Cases', () => {
    it('should handle special characters in ids', () => {
      renderSidebar({
        projectId: 'proj-with-dashes',
        conversationId: 'conv_with_underscores-123',
      })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/proj-with-dashes')
    })

    it('should handle only projectId provided', () => {
      renderSidebar({ projectId: 'proj-123' })

      expect(screen.getByTestId('base-path')).toHaveTextContent('/project/proj-123')
    })

    it('should handle only conversationId provided', () => {
      renderSidebar({ conversationId: 'conv-123' })

      // conversationId is ignored in basePath now
      expect(screen.getByTestId('base-path')).toHaveTextContent('/project')
    })
  })
})
