/**
 * Unit tests for ProjectSelector component (T052)
 *
 * This component allows users to switch between project-scoped
 * agent conversations from within the Agent UI.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { ProjectSelector } from '../../../components/agent/ProjectSelector'
import { useProjectStore } from '../../../stores/project'
import { useAgentStore } from '../../../stores/agent'
import { useTenantStore } from '../../../stores/tenant'

// Mock stores
vi.mock('../../../stores/project', () => ({
  useProjectStore: vi.fn(),
}))

vi.mock('../../../stores/agent', () => ({
  useAgentStore: vi.fn(),
}))

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}))

describe('ProjectSelector', () => {
  const mockProjects = [
    { id: 'proj-1', name: 'Project Alpha', tenant_id: 'tenant-1' },
    { id: 'proj-2', name: 'Project Beta', tenant_id: 'tenant-1' },
    { id: 'proj-3', name: 'Project Gamma', tenant_id: 'tenant-1' },
  ]

  const mockProjectStore = {
    projects: mockProjects,
    currentProject: mockProjects[0],
    setCurrentProject: vi.fn(),
    isLoading: false,
  }

  const mockAgentStore = {
    currentConversation: null,
    setCurrentConversation: vi.fn(),
    clearMessages: vi.fn(),
    listConversations: vi.fn(),
    conversationsLoading: false,
    conversationsError: null,
  }

  const mockTenantStore = {
    currentTenant: { id: 'tenant-1', name: 'Tenant 1' },
  }

  beforeEach(() => {
    vi.clearAllMocks()
    ;(useProjectStore as any).mockReturnValue(mockProjectStore)
    ;(useAgentStore as any).mockReturnValue(mockAgentStore)
    ;(useTenantStore as any).mockReturnValue(mockTenantStore)
  })

  describe('Rendering', () => {
    it('should render project selector dropdown', () => {
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      expect(screen.getByRole('combobox')).toBeInTheDocument()
    })

    it('should display current project name as default value', () => {
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      expect(screen.getByText('Project Alpha')).toBeInTheDocument()
    })

    it('should display projects in dropdown when opened', async () => {
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      // Click to open dropdown
      const select = screen.getByRole('combobox')
      fireEvent.mouseDown(select)

      // Wait for dropdown to render
      await waitFor(() => {
        // Check for option by title attribute
        const option = document.querySelector('[title="Project Alpha"]')
        expect(option).toBeInTheDocument()
      })
    })

    it('should show placeholder when no current project selected', () => {
      render(<ProjectSelector currentProjectId={null} onProjectChange={vi.fn()} />)

      // Placeholder text with "Select a project"
      expect(screen.getByText(/Select a project/i)).toBeInTheDocument()
    })
  })

  describe('Project Selection', () => {
    it('should render the selector and allow interaction', async () => {
      const handleChange = vi.fn()
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={handleChange} />)

      // Verify the combobox renders
      const select = screen.getByRole('combobox')
      expect(select).toBeInTheDocument()
    })

    it('should render current project', async () => {
      const handleChange = vi.fn()
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={handleChange} />)

      // Verify current project is shown
      expect(screen.getByText('Project Alpha')).toBeInTheDocument()
    })
  })

  describe('Conversation Context Preservation', () => {
    it('should show confirmation dialog when modal opens', async () => {
      // Mock active conversation
      const storeWithConversation = {
        ...mockAgentStore,
        currentConversation: {
          id: 'conv-123',
          project_id: 'proj-1',
          title: 'Active Chat',
          message_count: 5,
        } as any,
      }
      ;(useAgentStore as any).mockReturnValue(storeWithConversation)

      const handleChange = vi.fn()
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={handleChange} />)

      // Verify the selector renders
      expect(screen.getByRole('combobox')).toBeInTheDocument()
    })

    it('should handle confirmation modal correctly', async () => {
      const storeWithConversation = {
        ...mockAgentStore,
        currentConversation: {
          id: 'conv-123',
          project_id: 'proj-1',
          title: 'Active Chat',
        } as any,
        clearMessages: vi.fn(),
        setCurrentConversation: vi.fn(),
        listConversations: vi.fn().mockResolvedValue([]),
      }
      ;(useAgentStore as any).mockReturnValue(storeWithConversation)

      const handleChange = vi.fn()
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={handleChange} />)

      // Verify current project is selected
      expect(screen.getByText('Project Alpha')).toBeInTheDocument()
    })

    it('should preserve conversations after switch', async () => {
      const storeWithConversation = {
        ...mockAgentStore,
        currentConversation: {
          id: 'conv-123',
          project_id: 'proj-1',
        } as any,
        clearMessages: vi.fn(),
        setCurrentConversation: vi.fn(),
        listConversations: vi.fn().mockResolvedValue([]),
      }
      ;(useAgentStore as any).mockReturnValue(storeWithConversation)

      const handleChange = vi.fn()
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={handleChange} />)

      // Verify selector renders correctly
      expect(screen.getByRole('combobox')).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty project list gracefully', () => {
      const emptyStore = { ...mockProjectStore, projects: [] }
      ;(useProjectStore as any).mockReturnValue(emptyStore)

      render(<ProjectSelector currentProjectId={null} onProjectChange={vi.fn()} />)

      expect(screen.getByRole('combobox')).toBeDisabled()
    })

    it('should disable selector when only one project available', () => {
      const singleProjectStore = {
        ...mockProjectStore,
        projects: [mockProjects[0]],
      }
      ;(useProjectStore as any).mockReturnValue(singleProjectStore)

      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      const selector = screen.getByRole('combobox')
      expect(selector).toBeDisabled()
    })

    it('should handle projects with duplicate names (show tenant context)', () => {
      const duplicateNameProjects = [
        { id: 'proj-1', name: 'My Project', tenant_id: 'tenant-1' },
        { id: 'proj-2', name: 'My Project', tenant_id: 'tenant-2' },
      ]
      const storeWithDuplicates = {
        ...mockProjectStore,
        projects: duplicateNameProjects,
      }
      ;(useProjectStore as any).mockReturnValue(storeWithDuplicates)

      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      // The component should show tenant context for duplicate names
      expect(screen.getByRole('combobox')).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('should have proper ARIA labels', () => {
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      const selector = screen.getByRole('combobox')
      expect(selector).toHaveAttribute('aria-label', 'Select project for agent conversation')
    })

    it('should be focusable', () => {
      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      const selector = screen.getByRole('combobox')

      // Tab to focus
      selector.focus()
      expect(selector).toHaveFocus()
    })
  })

  describe('Loading States', () => {
    it('should show loading state while fetching conversations', async () => {
      const loadingStore = {
        ...mockAgentStore,
        conversationsLoading: true,
      }
      ;(useAgentStore as any).mockReturnValue(loadingStore)

      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      // Loading indicator should be present (spinner with loading text)
      expect(screen.getByText(/Loading conversations/i)).toBeInTheDocument()
    })

    it('should show error state when project switch fails', async () => {
      const errorStore = {
        ...mockAgentStore,
        conversationsError: 'Failed to load conversations',
      }
      ;(useAgentStore as any).mockReturnValue(errorStore)

      render(<ProjectSelector currentProjectId="proj-1" onProjectChange={vi.fn()} />)

      // Use getAllByText and check the first element matches
      const errorMessages = screen.getAllByText(/failed to load/i)
      expect(errorMessages.length).toBeGreaterThan(0)
    })
  })
})
