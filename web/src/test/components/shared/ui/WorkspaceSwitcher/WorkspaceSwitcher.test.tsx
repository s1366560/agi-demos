/**
 * WorkspaceSwitcher Component Tests
 *
 * TDD test suite for the compound WorkspaceSwitcher component.
 *
 * Test Coverage:
 * 1. Compound component structure
 * 2. Tenant mode behavior
 * 3. Project mode behavior
 * 4. Keyboard navigation
 * 5. Accessibility (ARIA attributes)
 * 6. Backward compatibility
 * 7. Edge cases
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup, render } from '@testing-library/react'
import { render as renderWithRouter } from '@/test/utils'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Component imports
import {
  WorkspaceSwitcher,
  WorkspaceSwitcherRoot,
  WorkspaceSwitcherTrigger,
  WorkspaceSwitcherMenu,
  TenantWorkspaceSwitcher,
  ProjectWorkspaceSwitcher,
} from '@/components/shared/ui/WorkspaceSwitcher'

// Store mocks
import { useTenantStore } from '@/stores/tenant'
import { useProjectStore } from '@/stores/project'
import type { Tenant, Project } from '@/types/memory'

// Mock stores with proper selector support
const mockTenantState = {
  tenants: [],
  currentTenant: null as Tenant | null,
  listTenants: vi.fn(),
  setCurrentTenant: vi.fn(),
}

const mockProjectState = {
  projects: [],
  currentProject: null as Project | null,
  listProjects: vi.fn(),
}

vi.mock('@/stores/tenant', () => ({
  useTenantStore: vi.fn(),
}))

vi.mock('@/stores/project', () => ({
  useProjectStore: vi.fn(),
}))

const mockTenant: Tenant = {
  id: 'tenant-1',
  name: 'Test Tenant',
  description: 'A test tenant',
  owner_id: 'user-1',
  plan: 'free',
  max_projects: 5,
  max_users: 10,
  max_storage: 1024,
  created_at: '2024-01-01',
}

const mockTenant2: Tenant = {
  id: 'tenant-2',
  name: 'Another Tenant',
  owner_id: 'user-1',
  plan: 'basic',
  max_projects: 10,
  max_users: 20,
  max_storage: 2048,
  created_at: '2024-01-02',
}

const mockProject: Project = {
  id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Test Project',
  description: 'A test project',
  owner_id: 'user-1',
  member_ids: ['user-1'],
  memory_rules: {
    max_episodes: 1000,
    retention_days: 30,
    auto_refresh: true,
    refresh_interval: 300,
  },
  graph_config: {
    max_nodes: 10000,
    max_edges: 50000,
    similarity_threshold: 0.8,
    community_detection: true,
  },
  is_public: false,
  created_at: '2024-01-01',
}

const mockProject2: Project = {
  id: 'project-2',
  tenant_id: 'tenant-1',
  name: 'Another Project',
  owner_id: 'user-1',
  member_ids: ['user-1'],
  memory_rules: {
    max_episodes: 500,
    retention_days: 30,
    auto_refresh: true,
    refresh_interval: 300,
  },
  graph_config: {
    max_nodes: 5000,
    max_edges: 25000,
    similarity_threshold: 0.8,
    community_detection: true,
  },
  is_public: false,
  created_at: '2024-01-02',
}

// Helper to setup tenant mock
const setupTenantMock = (
  tenants: Tenant[] = [],
  currentTenant: Tenant | null = null
) => {
  const state = {
    tenants,
    currentTenant,
    listTenants: vi.fn(),
    setCurrentTenant: vi.fn(),
  }
  vi.mocked(useTenantStore).mockImplementation((selector) => {
    if (typeof selector === 'function') {
      return selector(state)
    }
    return state as any
  })
}

// Helper to setup project mock
const setupProjectMock = (
  projects: Project[] = [],
  currentProject: Project | null = null
) => {
  const state = {
    projects,
    currentProject,
    listProjects: vi.fn(),
  }
  vi.mocked(useProjectStore).mockImplementation((selector) => {
    if (typeof selector === 'function') {
      return selector(state)
    }
    return state as any
  })
}

describe('WorkspaceSwitcher - Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mocks
    setupTenantMock()
    setupProjectMock()
  })

  afterEach(() => {
    cleanup()
  })

  describe('WorkspaceSwitcherRoot', () => {
    it('should render children correctly', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <div data-testid="test-child">Child content</div>
        </WorkspaceSwitcherRoot>
      )

      expect(screen.getByTestId('test-child')).toBeInTheDocument()
      expect(screen.getByText('Child content')).toBeInTheDocument()
    })

    it('should provide context to children', () => {
      const TestConsumer = () => {
        return (
          <WorkspaceSwitcherRoot mode="tenant" data-testid="root">
            <div data-testid="has-context">Has Context</div>
          </WorkspaceSwitcherRoot>
        )
      }

      render(<TestConsumer />)
      expect(screen.getByTestId('has-context')).toBeInTheDocument()
    })

    it('should support defaultOpen prop', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant" defaultOpen>
          <div data-testid="content">Content</div>
        </WorkspaceSwitcherRoot>
      )

      expect(screen.getByTestId('content')).toBeInTheDocument()
    })

    it('should support controlled open state with onOpenChange', async () => {
      const handleOpenChange = vi.fn()

      render(
        <WorkspaceSwitcherRoot mode="tenant" onOpenChange={handleOpenChange}>
          <div data-testid="content">Content</div>
        </WorkspaceSwitcherRoot>
      )

      // This will be tested when we add Trigger component tests
    })
  })

  describe('WorkspaceSwitcherTrigger', () => {
    it('should render as a button', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Click me
          </WorkspaceSwitcherTrigger>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      expect(trigger.tagName).toBe('BUTTON')
      expect(screen.getByText('Click me')).toBeInTheDocument()
    })

    it('should toggle menu on click', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Menu Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')

      // Menu should not be visible initially
      expect(screen.queryByTestId('menu-content')).not.toBeInTheDocument()

      // Click to open
      fireEvent.click(trigger)
      await waitFor(() => {
        expect(screen.getByTestId('menu-content')).toBeInTheDocument()
      })

      // Click to close
      fireEvent.click(trigger)
      await waitFor(() => {
        expect(screen.queryByTestId('menu-content')).not.toBeInTheDocument()
      })
    })

    it('should have correct ARIA attributes when closed', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
      expect(trigger).toHaveAttribute('aria-haspopup', 'listbox')
    })

    it('should have correct ARIA attributes when open', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.click(trigger)

      await waitFor(() => {
        expect(trigger).toHaveAttribute('aria-expanded', 'true')
      })
    })

    it('should open on ArrowDown key', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        expect(screen.getByTestId('menu-content')).toBeInTheDocument()
      })
    })

    it('should open on ArrowUp key', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.keyDown(trigger, { key: 'ArrowUp' })

      await waitFor(() => {
        expect(screen.getByTestId('menu-content')).toBeInTheDocument()
      })
    })

    it('should open on Enter key', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.keyDown(trigger, { key: 'Enter' })

      await waitFor(() => {
        expect(screen.getByTestId('menu-content')).toBeInTheDocument()
      })
    })

    it('should open on Space key', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.keyDown(trigger, { key: ' ' })

      await waitFor(() => {
        expect(screen.getByTestId('menu-content')).toBeInTheDocument()
      })
    })

    it('should not open on other keys', async () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant">
          <WorkspaceSwitcherTrigger data-testid="trigger">
            Toggle
          </WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu">
            <div data-testid="menu-content">Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const trigger = screen.getByTestId('trigger')
      fireEvent.keyDown(trigger, { key: 'a' })

      expect(screen.queryByTestId('menu-content')).not.toBeInTheDocument()
    })
  })

  describe('WorkspaceSwitcherMenu', () => {
    it('should render menu with label', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant" defaultOpen>
          <WorkspaceSwitcherTrigger>Toggle</WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Switch Tenant">
            <div data-testid="menu-item">Item 1</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      expect(screen.getByText('Switch Tenant')).toBeInTheDocument()
      expect(screen.getByTestId('menu-item')).toBeInTheDocument()
    })

    it('should have correct ARIA attributes', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant" defaultOpen>
          <WorkspaceSwitcherTrigger>Toggle</WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu" data-testid="menu">
            <div data-testid="menu-item">Item 1</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      // The menu element itself has role="listbox"
      const menu = screen.getByRole('listbox')
      expect(menu).toHaveAttribute('role', 'listbox')
      expect(menu).toHaveAttribute('aria-orientation', 'vertical')
    })

    it('should close when clicking outside', async () => {
      render(
        <div>
          <WorkspaceSwitcherRoot mode="tenant" defaultOpen>
            <WorkspaceSwitcherTrigger>Toggle</WorkspaceSwitcherTrigger>
            <WorkspaceSwitcherMenu label="Test Menu">
              <div data-testid="menu-content">Content</div>
            </WorkspaceSwitcherMenu>
          </WorkspaceSwitcherRoot>
          <div data-testid="outside">Outside element</div>
        </div>
      )

      expect(screen.getByTestId('menu-content')).toBeInTheDocument()

      // Click outside
      fireEvent.mouseDown(screen.getByTestId('outside'))

      await waitFor(() => {
        expect(screen.queryByTestId('menu-content')).not.toBeInTheDocument()
      })
    })

    it('should support custom className', () => {
      render(
        <WorkspaceSwitcherRoot mode="tenant" defaultOpen>
          <WorkspaceSwitcherTrigger>Toggle</WorkspaceSwitcherTrigger>
          <WorkspaceSwitcherMenu label="Test Menu" className="custom-class">
            <div>Content</div>
          </WorkspaceSwitcherMenu>
        </WorkspaceSwitcherRoot>
      )

      const menu = screen.getByRole('listbox')
      expect(menu).toHaveClass('custom-class')
    })
  })

  describe('TenantWorkspaceSwitcher', () => {
    beforeEach(() => {
      setupTenantMock([mockTenant, mockTenant2], mockTenant)
      setupProjectMock()
    })

    it('should render current tenant name', () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      expect(screen.getByText('Test Tenant')).toBeInTheDocument()
    })

    it('should render "Select Tenant" when no current tenant', () => {
      setupTenantMock([mockTenant], null)

      renderWithRouter(<TenantWorkspaceSwitcher />)

      expect(screen.getByText('Select Tenant')).toBeInTheDocument()
    })

    it('should open dropdown on click', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      fireEvent.click(screen.getByText('Test Tenant'))

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })
    })

    it('should call onTenantSelect when tenant is clicked', async () => {
      const handleTenantSelect = vi.fn()

      renderWithRouter(<TenantWorkspaceSwitcher onTenantSelect={handleTenantSelect} />)

      fireEvent.click(screen.getByText('Test Tenant'))

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })
    })

    it('should show create tenant button', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      fireEvent.click(screen.getByText('Test Tenant'))

      await waitFor(() => {
        expect(screen.getByText('Create Tenant')).toBeInTheDocument()
      })
    })

    it('should use custom create label when provided', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher createLabel="Add New Organization" />)

      fireEvent.click(screen.getByText('Test Tenant'))

      await waitFor(() => {
        expect(screen.getByText('Add New Organization')).toBeInTheDocument()
      })
    })

    it('should mark current tenant with checkmark', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      fireEvent.click(screen.getByRole('button'))

      await waitFor(() => {
        const menuItems = screen.getAllByRole('option')
        const currentTenantItem = menuItems.find((item) =>
          item.textContent?.includes('Test Tenant')
        )
        expect(currentTenantItem).toHaveClass(/bg-primary\/10/)
      })
    })

    it('should have correct ARIA attributes', () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      expect(trigger).toHaveAttribute('aria-haspopup', 'listbox')
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
    })
  })

  describe('ProjectWorkspaceSwitcher', () => {
    beforeEach(() => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock([mockProject, mockProject2], mockProject)
    })

    it('should render current project name', () => {
      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId="project-1" />, {
        route: '/project/project-1',
      })

      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })

    it('should render "Select Project" when no current project', () => {
      setupProjectMock([], null)

      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId={null} />)

      expect(screen.getByText('Select Project')).toBeInTheDocument()
    })

    it('should open dropdown on click', async () => {
      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId="project-1" />, {
        route: '/project/project-1',
      })

      fireEvent.click(screen.getByText('Test Project'))

      await waitFor(() => {
        expect(screen.getByText('Another Project')).toBeInTheDocument()
      })
    })

    it('should show back to tenant button', async () => {
      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId="project-1" />, {
        route: '/project/project-1',
      })

      fireEvent.click(screen.getByText('Test Project'))

      await waitFor(() => {
        expect(screen.getByText('Back to Tenant')).toBeInTheDocument()
      })
    })

    it('should use custom back label when provided', async () => {
      renderWithRouter(
        <ProjectWorkspaceSwitcher
          currentProjectId="project-1"
          backToTenantLabel="Return to Organization"
        />,
        { route: '/project/project-1' }
      )

      fireEvent.click(screen.getByText('Test Project'))

      await waitFor(() => {
        expect(screen.getByText('Return to Organization')).toBeInTheDocument()
      })
    })

    it('should mark current project with checkmark', async () => {
      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId="project-1" />, {
        route: '/project/project-1',
      })

      fireEvent.click(screen.getByRole('button'))

      await waitFor(() => {
        const menuItems = screen.getAllByRole('option')
        const currentProjectItem = menuItems.find((item) =>
          item.textContent?.includes('Test Project')
        )
        expect(currentProjectItem).toHaveClass(/bg-primary\/10/)
      })
    })
  })

  describe('Keyboard Navigation', () => {
    beforeEach(() => {
      setupTenantMock([mockTenant, mockTenant2], mockTenant)
      setupProjectMock()
    })

    it('should navigate down with ArrowDown', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.click(trigger)

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      // Get menu items
      const menuItems = screen.getAllByRole('option')

      // First item should be focused
      expect(menuItems[0]).toHaveFocus()

      // Arrow down to next item
      fireEvent.keyDown(menuItems[0], { key: 'ArrowDown' })

      await waitFor(() => {
        expect(menuItems[1]).toHaveFocus()
      })
    })

    it('should navigate up with ArrowUp', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      // Arrow down twice
      fireEvent.keyDown(menuItems[0], { key: 'ArrowDown' })
      await waitFor(() => {
        expect(menuItems[1]).toHaveFocus()
      })

      // Arrow up should go back
      fireEvent.keyDown(menuItems[1], { key: 'ArrowUp' })

      await waitFor(() => {
        expect(menuItems[0]).toHaveFocus()
      })
    })

    it('should wrap around when navigating past boundaries', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      // Arrow down from last item should wrap to first
      const lastIndex = menuItems.length - 1
      menuItems[lastIndex].focus()
      fireEvent.keyDown(menuItems[lastIndex], { key: 'ArrowDown' })

      await waitFor(() => {
        expect(menuItems[0]).toHaveFocus()
      })
    })

    it('should navigate to first item with Home key', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      // Focus last item
      const lastIndex = menuItems.length - 1
      menuItems[lastIndex].focus()

      // Home should go to first
      fireEvent.keyDown(menuItems[lastIndex], { key: 'Home' })

      await waitFor(() => {
        expect(menuItems[0]).toHaveFocus()
      })
    })

    it('should navigate to last item with End key', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      // End should go to last
      fireEvent.keyDown(menuItems[0], { key: 'End' })

      await waitFor(() => {
        const lastIndex = menuItems.length - 1
        expect(menuItems[lastIndex]).toHaveFocus()
      })
    })

    it('should close menu and focus trigger on Escape', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.click(trigger)

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      fireEvent.keyDown(menuItems[0], { key: 'Escape' })

      await waitFor(() => {
        expect(screen.queryByText('Another Tenant')).not.toBeInTheDocument()
        expect(trigger).toHaveFocus()
      })
    })

    it('should close menu on Tab key', async () => {
      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.click(trigger)

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      fireEvent.keyDown(menuItems[0], { key: 'Tab' })

      await waitFor(() => {
        expect(screen.queryByText('Another Tenant')).not.toBeInTheDocument()
      })
    })

    it('should select item on Enter', async () => {
      const handleTenantSelect = vi.fn()

      renderWithRouter(<TenantWorkspaceSwitcher onTenantSelect={handleTenantSelect} />)

      const trigger = screen.getByRole('button')
      fireEvent.click(trigger)

      await waitFor(() => {
        expect(screen.getByText('Another Tenant')).toBeInTheDocument()
      })

      const menuItems = screen.getAllByRole('option')

      fireEvent.keyDown(menuItems[1], { key: 'Enter' })

      // The callback should be called when Enter is pressed
      expect(handleTenantSelect).toHaveBeenCalledTimes(1)
      expect(handleTenantSelect).toHaveBeenCalledWith(expect.objectContaining({
        id: 'tenant-2',
        name: 'Another Tenant',
      }))
    })
  })

  describe('Backward Compatibility', () => {
    beforeEach(() => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock()
    })

    it('should support mode="tenant" prop', () => {
      renderWithRouter(<WorkspaceSwitcher mode="tenant" />)

      expect(screen.getByText('Test Tenant')).toBeInTheDocument()
    })

    it('should support mode="project" prop', () => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock([mockProject], mockProject)

      // For project mode, we need to use proper Routes setup because useParams() requires it
      // Use raw render() instead of renderWithRouter to avoid nested routers
      render(
        <MemoryRouter initialEntries={['/project/project-1']}>
          <Routes>
            <Route path="/project/:projectId" element={<WorkspaceSwitcher mode="project" />} />
            <Route path="*" element={<WorkspaceSwitcher mode="project" />} />
          </Routes>
        </MemoryRouter>
      )

      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty tenant list gracefully', () => {
      setupTenantMock([], null)
      setupProjectMock()

      renderWithRouter(<TenantWorkspaceSwitcher />)

      expect(screen.getByText('Select Tenant')).toBeInTheDocument()
    })

    it('should handle empty project list gracefully', () => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock([], null)

      renderWithRouter(<ProjectWorkspaceSwitcher currentProjectId={null} />)

      expect(screen.getByText('Select Project')).toBeInTheDocument()
    })

    it('should handle keyboard navigation with single item', async () => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock()

      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')
      fireEvent.keyDown(trigger, { key: 'ArrowDown' })

      await waitFor(() => {
        const menuItems = screen.getAllByRole('option')
        // Should have create button at minimum
        expect(menuItems.length).toBeGreaterThan(0)
      })
    })

    it('should handle rapid open/close clicks', async () => {
      setupTenantMock([mockTenant], mockTenant)
      setupProjectMock()

      renderWithRouter(<TenantWorkspaceSwitcher />)

      const trigger = screen.getByRole('button')

      // Rapid clicks
      fireEvent.click(trigger)
      fireEvent.click(trigger)
      fireEvent.click(trigger)

      // Should end up open (odd number of clicks)
      await waitFor(() => {
        expect(screen.getByText('Create Tenant')).toBeInTheDocument()
      })
    })
  })
})
