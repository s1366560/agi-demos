/**
 * AgentLayout Tests
 *
 * Tests for the Agent layout component.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter, Route, Routes, MemoryRouter } from 'react-router-dom'
import { AgentLayout } from '@/layouts/AgentLayout'

// Mock stores
vi.mock('@/stores/project', () => ({
  useProjectStore: () => ({
    currentProject: { id: 'proj-123', name: 'Test Project' },
    projects: [],
    setCurrentProject: vi.fn(),
    getProject: vi.fn(),
  }),
}))

vi.mock('@/stores/tenant', () => ({
  useTenantStore: () => ({
    currentTenant: { id: 'tenant-123', name: 'Test Tenant' },
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  }),
}))

vi.mock('@/components/common/RouteErrorBoundary', () => ({
  RouteErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function renderWithRouter(ui: React.ReactElement, initialEntries = ['/project/proj-123/agent']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      {ui}
    </MemoryRouter>
  )
}

describe('AgentLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('Rendering', () => {
    it('should render the layout with sidebar and main content', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Agent Content</div>} />
          </Route>
        </Routes>,
      )

      // Check that the main layout structure exists
      expect(screen.getByText('Agent Content')).toBeInTheDocument()
    })

    it('should render the brand header', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
      )

      // Check for brand indicator
      const brandIcon = document.querySelector('.material-symbols-outlined')
      expect(brandIcon).toBeTruthy()
    })

    it('should render navigation items', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
        ['/project/proj-123/agent']
      )

      // Check for navigation items
      expect(screen.getByText('Back to Project')).toBeInTheDocument()
      expect(screen.getByText('Project Overview')).toBeInTheDocument()
      expect(screen.getByText('Memories')).toBeInTheDocument()
      expect(screen.getByText('Entities')).toBeInTheDocument()
    })

    it('should render the top tabs', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
      )

      expect(screen.getByText('Dashboard')).toBeInTheDocument()
      expect(screen.getByText('Activity Logs')).toBeInTheDocument()
      expect(screen.getByText('Patterns')).toBeInTheDocument()
    })
  })

  describe('Sidebar Collapse', () => {
    it('should render expandable sidebar', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
      )

      // Should have collapse toggle button
      const collapseButton = document.querySelector('button[title*="sidebar" i]')
      expect(collapseButton).toBeTruthy()
    })
  })

  describe('User Profile', () => {
    it('should display user information', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
      )

      expect(screen.getByText('Test User')).toBeInTheDocument()
    })
  })

  describe('Agent Status', () => {
    it('should display online status badge', () => {
      renderWithRouter(
        <Routes>
          <Route path="/project/:projectId/agent" element={<AgentLayout />}>
            <Route path="" element={<div>Content</div>} />
          </Route>
        </Routes>,
      )

      expect(screen.getByText('Agent Online')).toBeInTheDocument()
    })
  })
})
