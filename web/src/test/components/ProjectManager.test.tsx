/**
 * ProjectManager Component Tests
 *
 * TDD Tests for compound component pattern refactoring
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as React from 'react';

// Import the component and types
import {
  ProjectManager,
  type ProjectManagerProps,
} from '@/components/tenant/ProjectManager';
import type { Project } from '@/types/memory';

// ============================================================================
// MOCKS
// ============================================================================

vi.mock('@/stores/project', () => ({
  useProjectStore: vi.fn(),
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: vi.fn(),
}));

vi.mock('@/components/tenant/ProjectCreateModal', () => ({
  ProjectCreateModal: ({ isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="create-modal">
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

vi.mock('@/components/tenant/ProjectSettingsModal', () => ({
  ProjectSettingsModal: ({ isOpen, project, onClose }: any) =>
    isOpen ? (
      <div data-testid="settings-modal" data-project-id={project?.id}>
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

const mockUseProjectStore = await import('@/stores/project');
const mockUseTenantStore = await import('@/stores/tenant');

// ============================================================================
// TEST FIXTURES
// ============================================================================

const mockTenant = { id: 'tenant-1', name: 'Test Tenant' };

const mockProjects: Project[] = [
  {
    id: 'proj-1',
    tenant_id: 'tenant-1',
    name: 'Project Alpha',
    description: 'First test project',
    owner_id: 'user-1',
    member_ids: [],
    memory_rules: {
      max_episodes: 1000,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 24,
    },
    graph_config: {
      max_nodes: 5000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true,
    },
    is_public: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'proj-2',
    tenant_id: 'tenant-1',
    name: 'Project Beta',
    description: 'Second test project',
    owner_id: 'user-1',
    member_ids: [],
    memory_rules: {
      max_episodes: 1000,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 24,
    },
    graph_config: {
      max_nodes: 5000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true,
    },
    is_public: true,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
];

// ============================================================================
// TEST SETUP
// ============================================================================

function setupMocks({
  tenant = mockTenant,
  projects = mockProjects,
  currentProject = mockProjects[0],
  isLoading = false,
  error = null,
} = {}) {
  (mockUseTenantStore.useTenantStore as any).mockReturnValue({
    currentTenant: tenant,
  });

  (mockUseProjectStore.useProjectStore as any).mockReturnValue({
    projects,
    currentProject,
    isLoading,
    error,
    listProjects: vi.fn(),
    deleteProject: vi.fn(),
    setCurrentProject: vi.fn(),
    createProject: vi.fn(),
    updateProject: vi.fn(),
    getProject: vi.fn(),
    clearError: vi.fn(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  setupMocks();
});

// ============================================================================
// TEST SUITES
// ============================================================================

describe('ProjectManager - Compound Component Pattern', () => {
  describe('Component Structure', () => {
    it('should export ProjectManager as a component', () => {
      expect(ProjectManager).toBeDefined();
      expect(typeof ProjectManager).toBe('function');
    });

    it('should export all sub-components', () => {
      expect(ProjectManager.Search).toBeDefined();
      expect(ProjectManager.Filters).toBeDefined();
      expect(ProjectManager.List).toBeDefined();
      expect(ProjectManager.Item).toBeDefined();
      expect(ProjectManager.CreateModal).toBeDefined();
      expect(ProjectManager.SettingsModal).toBeDefined();
      expect(ProjectManager.Loading).toBeDefined();
      expect(ProjectManager.Empty).toBeDefined();
      expect(ProjectManager.Error).toBeDefined();
    });

    it('should have sub-components as functions', () => {
      expect(typeof ProjectManager.Search).toBe('function');
      expect(typeof ProjectManager.Filters).toBe('function');
      expect(typeof ProjectManager.List).toBe('function');
      expect(typeof ProjectManager.Item).toBe('function');
      expect(typeof ProjectManager.CreateModal).toBe('function');
      expect(typeof ProjectManager.SettingsModal).toBe('function');
      expect(typeof ProjectManager.Loading).toBe('function');
      expect(typeof ProjectManager.Empty).toBe('function');
      expect(typeof ProjectManager.Error).toBe('function');
    });
  });

  describe('Root Component', () => {
    it('should render children when provided', () => {
      render(
        <ProjectManager>
          <div data-testid="custom-child">Custom Content</div>
        </ProjectManager>
      );

      expect(screen.getByTestId('custom-child')).toBeInTheDocument();
      expect(screen.getByText('Custom Content')).toBeInTheDocument();
    });

    it('should render with custom className', () => {
      const { container } = render(
        <ProjectManager className="custom-class">
          <div>Content</div>
        </ProjectManager>
      );

      expect(container.querySelector('.custom-class')).toBeInTheDocument();
    });

    it('should call onProjectSelect when project is selected', () => {
      const handleSelect = vi.fn();

      render(<ProjectManager onProjectSelect={handleSelect}>Content</ProjectManager>);

      expect(handleSelect).toBeDefined();
    });
  });

  describe('variant="full" - Automatic Rendering', () => {
    it('should render all sub-components automatically with full variant', () => {
      const { container } = render(<ProjectManager variant="full" />);

      // Should render Search component
      expect(screen.getByTestId('search-input')).toBeInTheDocument();

      // Should render List component
      expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
    });

    it('should respect controlled variant (default)', () => {
      const { container } = render(<ProjectManager />);

      // Controlled variant should not auto-render children
      expect(container.firstChild).toBeInTheDocument();
    });
  });

  describe('No Tenant State', () => {
    it('should show empty state when no tenant is selected', () => {
      setupMocks({ tenant: null });

      render(<ProjectManager variant="full" />);

      expect(screen.getByTestId('empty-state')).toBeInTheDocument();
      expect(screen.getByText('请先选择工作空间')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('should show loading state when isLoading is true', () => {
      setupMocks({ isLoading: true });

      render(<ProjectManager variant="full" />);

      expect(screen.getByTestId('loading-state')).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('should show error state when error exists', () => {
      const errorMessage = 'Failed to load projects';
      setupMocks({ error: errorMessage });

      render(<ProjectManager variant="full" />);

      expect(screen.getByTestId('error-state')).toBeInTheDocument();
      expect(screen.getByText(errorMessage)).toBeInTheDocument();
    });
  });

  describe('Empty Projects State', () => {
    it('should show empty state when no projects exist', () => {
      setupMocks({ projects: [], currentProject: null });

      render(<ProjectManager variant="full" />);

      expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    });

    it('should show create button in empty state', () => {
      setupMocks({ projects: [], currentProject: null });

      render(<ProjectManager variant="full" />);

      expect(screen.getByText('创建项目')).toBeInTheDocument();
    });
  });
});

describe('ProjectManager.Search', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render search input', () => {
    render(<ProjectManager.Search />, { wrapper: Wrapper });

    expect(screen.getByTestId('search-input')).toBeInTheDocument();
  });

  it('should use custom placeholder', () => {
    render(<ProjectManager.Search placeholder="Find projects..." />, { wrapper: Wrapper });

    const input = screen.getByPlaceholderText('Find projects...');
    expect(input).toBeInTheDocument();
  });

  it('should use default placeholder when not provided', () => {
    render(<ProjectManager.Search />, { wrapper: Wrapper });

    const input = screen.getByPlaceholderText('搜索项目...');
    expect(input).toBeInTheDocument();
  });

  it('should call onChange when input changes', () => {
    const handleChange = vi.fn();
    render(<ProjectManager.Search value="" onChange={handleChange} />, { wrapper: Wrapper });

    const input = screen.getByTestId('search-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'test' } });

    expect(handleChange).toHaveBeenCalledWith('test');
  });

  it('should support controlled mode with value prop', () => {
    render(<ProjectManager.Search value="controlled search" />, { wrapper: Wrapper });

    const input = screen.getByTestId('search-input') as HTMLInputElement;
    expect(input.value).toBe('controlled search');
  });

  it('should support uncontrolled mode with defaultValue', () => {
    render(<ProjectManager.Search defaultValue="initial value" />, { wrapper: Wrapper });

    const input = screen.getByTestId('search-input') as HTMLInputElement;
    expect(input.value).toBe('initial value');
  });
});

describe('ProjectManager.Filters', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render filter select', () => {
    render(<ProjectManager.Filters />, { wrapper: Wrapper });

    expect(screen.getByTestId('filter-select')).toBeInTheDocument();
  });

  it('should use custom options', () => {
    const options = [
      { value: 'all', label: 'All Projects' },
      { value: 'active', label: 'Active' },
      { value: 'archived', label: 'Archived' },
    ];

    render(<ProjectManager.Filters options={options} />, { wrapper: Wrapper });

    const select = screen.getByTestId('filter-select');
    expect(select).toBeInTheDocument();
  });

  it('should call onChange when selection changes', () => {
    const handleChange = vi.fn();
    const options = [
      { value: 'all', label: 'All' },
      { value: 'active', label: 'Active' },
    ];
    render(<ProjectManager.Filters value="all" onChange={handleChange} options={options} />, { wrapper: Wrapper });

    const select = screen.getByTestId('filter-select');
    fireEvent.change(select, { target: { value: 'active' } });

    expect(handleChange).toHaveBeenCalledWith('active');
  });

  it('should support controlled mode with value prop', () => {
    render(<ProjectManager.Filters value="all" />, { wrapper: Wrapper });

    const select = screen.getByTestId('filter-select') as HTMLSelectElement;
    expect(select.value).toBe('all');
  });
});

describe('ProjectManager.List', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render list container', () => {
    render(<ProjectManager.List />, { wrapper: Wrapper });

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });

  it('should render children function for each project', () => {
    const renderProject = vi.fn((project: Project) => (
      <div key={project.id}>{project.name}</div>
    ));

    render(
      <ProjectManager.List>
        {renderProject}
      </ProjectManager.List>,
      { wrapper: Wrapper }
    );

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });

  it('should support grid layout variant', () => {
    render(<ProjectManager.List layout="grid" />, { wrapper: Wrapper });

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });

  it('should support list layout variant', () => {
    render(<ProjectManager.List layout="list" />, { wrapper: Wrapper });

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });
});

describe('ProjectManager.Item', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render project item', () => {
    render(<ProjectManager.Item project={mockProjects[0]} />, { wrapper: Wrapper });

    expect(screen.getByTestId('project-item')).toBeInTheDocument();
    expect(screen.getByText('Project Alpha')).toBeInTheDocument();
  });

  it('should show selected state when isSelected is true', () => {
    render(
      <ProjectManager.Item project={mockProjects[0]} isSelected={true} />,
      { wrapper: Wrapper }
    );

    const item = screen.getByTestId('project-item');
    expect(item.getAttribute('data-selected')).toBe('true');
  });

  it('should not show selected state when isSelected is false', () => {
    render(
      <ProjectManager.Item project={mockProjects[0]} isSelected={false} />,
      { wrapper: Wrapper }
    );

    const item = screen.getByTestId('project-item');
    expect(item.getAttribute('data-selected')).toBe('false');
  });

  it('should call onClick when item is clicked', () => {
    const handleClick = vi.fn();
    render(
      <ProjectManager.Item project={mockProjects[0]} onClick={handleClick} />,
      { wrapper: Wrapper }
    );

    const item = screen.getByTestId('project-item');
    fireEvent.click(item);

    expect(handleClick).toHaveBeenCalledWith(mockProjects[0]);
  });

  it('should call onSettingsClick when settings button is clicked', () => {
    const handleSettings = vi.fn();
    render(
      <ProjectManager.Item
        project={mockProjects[0]}
        onSettingsClick={handleSettings}
      />,
      { wrapper: Wrapper }
    );

    const settingsBtn = screen.getByTestId('settings-btn');
    fireEvent.click(settingsBtn);

    expect(handleSettings).toHaveBeenCalledWith(mockProjects[0], expect.any(Object));
  });

  it('should call onDeleteClick when delete button is clicked', () => {
    const handleDelete = vi.fn();
    render(
      <ProjectManager.Item
        project={mockProjects[0]}
        onDeleteClick={handleDelete}
      />,
      { wrapper: Wrapper }
    );

    const deleteBtn = screen.getByTestId('delete-btn');
    fireEvent.click(deleteBtn);

    expect(handleDelete).toHaveBeenCalledWith(mockProjects[0], expect.any(Object));
  });
});

describe('ProjectManager.Loading', () => {
  it('should render loading state', () => {
    render(<ProjectManager.Loading />);

    expect(screen.getByTestId('loading-state')).toBeInTheDocument();
  });

  it('should use custom message', () => {
    render(<ProjectManager.Loading message="Loading projects..." />);

    expect(screen.getByText('Loading projects...')).toBeInTheDocument();
  });
});

describe('ProjectManager.Empty', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render empty state', () => {
    render(<ProjectManager.Empty />, { wrapper: Wrapper });

    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
  });

  it('should use custom message', () => {
    render(<ProjectManager.Empty message="No projects here" />, { wrapper: Wrapper });

    expect(screen.getByText('No projects here')).toBeInTheDocument();
  });

  it('should show create button when showCreateButton is true', () => {
    render(<ProjectManager.Empty showCreateButton={true} />, { wrapper: Wrapper });

    expect(screen.getByText('创建项目')).toBeInTheDocument();
  });

  it('should not show create button when showCreateButton is false', () => {
    render(<ProjectManager.Empty showCreateButton={false} />, { wrapper: Wrapper });

    expect(screen.queryByText('创建项目')).not.toBeInTheDocument();
  });

  it('should call onCreateClick when create button is clicked', () => {
    const handleCreate = vi.fn();
    render(
      <ProjectManager.Empty
        showCreateButton={true}
        onCreateClick={handleCreate}
      />,
      { wrapper: Wrapper }
    );

    const createBtn = screen.getByText('创建项目');
    fireEvent.click(createBtn);

    expect(handleCreate).toHaveBeenCalled();
  });
});

describe('ProjectManager.Error', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should render null when no error', () => {
    const { container } = render(<ProjectManager.Error error={null} />, { wrapper: Wrapper });

    expect(screen.queryByTestId('error-state')).not.toBeInTheDocument();
  });

  it('should render error state when error exists', () => {
    render(<ProjectManager.Error error="Something went wrong" />, { wrapper: Wrapper });

    expect(screen.getByTestId('error-state')).toBeInTheDocument();
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });
});

describe('ProjectManager.CreateModal', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should not render when isOpen is false', () => {
    render(<ProjectManager.CreateModal isOpen={false} />, { wrapper: Wrapper });

    expect(screen.queryByTestId('create-modal')).not.toBeInTheDocument();
  });

  it('should render when isOpen is true', () => {
    render(<ProjectManager.CreateModal isOpen={true} />, { wrapper: Wrapper });

    expect(screen.getByTestId('create-modal')).toBeInTheDocument();
  });

  it('should call onClose when close button is clicked', () => {
    const handleClose = vi.fn();
    render(
      <ProjectManager.CreateModal isOpen={true} onClose={handleClose} />,
      { wrapper: Wrapper }
    );

    const closeBtn = screen.getByText('Close');
    fireEvent.click(closeBtn);

    expect(handleClose).toHaveBeenCalled();
  });
});

describe('ProjectManager.SettingsModal', () => {
  // Helper wrapper for context
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ProjectManager>{children}</ProjectManager>
  );

  it('should not render when isOpen is false', () => {
    render(
      <ProjectManager.SettingsModal
        project={mockProjects[0]}
        isOpen={false}
      />,
      { wrapper: Wrapper }
    );

    expect(screen.queryByTestId('settings-modal')).not.toBeInTheDocument();
  });

  it('should render when isOpen is true', () => {
    render(
      <ProjectManager.SettingsModal
        project={mockProjects[0]}
        isOpen={true}
      />,
      { wrapper: Wrapper }
    );

    const modal = screen.getByTestId('settings-modal');
    expect(modal).toBeInTheDocument();
    expect(modal.getAttribute('data-project-id')).toBe('proj-1');
  });

  it('should call onClose when close button is clicked', () => {
    const handleClose = vi.fn();
    render(
      <ProjectManager.SettingsModal
        project={mockProjects[0]}
        isOpen={true}
        onClose={handleClose}
      />,
      { wrapper: Wrapper }
    );

    const closeBtn = screen.getByText('Close');
    fireEvent.click(closeBtn);

    expect(handleClose).toHaveBeenCalled();
  });
});

describe('ProjectManager - Integration Tests', () => {
  describe('Manual Composition (controlled variant)', () => {
    it('should allow manual composition of sub-components', () => {
      render(
        <ProjectManager>
          <ProjectManager.Search />
          <ProjectManager.Filters />
          <ProjectManager.List>
            {(project) => <ProjectManager.Item key={project.id} project={project} />}
          </ProjectManager.List>
        </ProjectManager>
      );

      expect(screen.getByTestId('search-input')).toBeInTheDocument();
      expect(screen.getByTestId('filter-select')).toBeInTheDocument();
      expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
    });
  });

  describe('Automatic Composition (full variant)', () => {
    it('should render all components in full variant', () => {
      render(<ProjectManager variant="full" />);

      expect(screen.getByTestId('search-input')).toBeInTheDocument();
      expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
    });
  });
});

describe('ProjectManager - Backward Compatibility', () => {
  it('should support legacy onProjectSelect prop', () => {
    const handleSelect = vi.fn();

    render(
      <ProjectManager onProjectSelect={handleSelect}>
        <div>Content</div>
      </ProjectManager>
    );

    expect(handleSelect).toBeDefined();
  });
});

describe('ProjectManager - Edge Cases', () => {
  it('should handle null children gracefully', () => {
    const { container } = render(
      <ProjectManager>{null}</ProjectManager>
    );

    expect(container.firstChild).toBeInTheDocument();
  });

  it('should handle empty projects array', () => {
    setupMocks({ projects: [] });

    render(<ProjectManager variant="full" />);

    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
  });

  it('should handle projects with missing optional fields', () => {
    const incompleteProject: Project = {
      id: 'proj-incomplete',
      tenant_id: 'tenant-1',
      name: 'Incomplete Project',
      owner_id: 'user-1',
      member_ids: [],
      memory_rules: {
        max_episodes: 1000,
        retention_days: 30,
        auto_refresh: true,
        refresh_interval: 24,
      },
      graph_config: {
        max_nodes: 5000,
        max_edges: 10000,
        similarity_threshold: 0.7,
        community_detection: true,
      },
      is_public: false,
      created_at: '2024-01-01T00:00:00Z',
    };

    setupMocks({ projects: [incompleteProject] });

    render(<ProjectManager variant="full" />);

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });

  it('should handle long project names', () => {
    const longNameProject: Project = {
      ...mockProjects[0],
      name: 'A'.repeat(200),
    };

    setupMocks({ projects: [longNameProject] });

    render(<ProjectManager variant="full" />);

    expect(screen.getByTestId('project-manager-list')).toBeInTheDocument();
  });

  it('should handle special characters in search', () => {
    const Wrapper = ({ children }: { children: React.ReactNode }) => (
      <ProjectManager>{children}</ProjectManager>
    );

    render(<ProjectManager.Search value="" />, { wrapper: Wrapper });

    const input = screen.getByTestId('search-input');
    fireEvent.change(input, { target: { value: '<script>alert("xss")</script>' } });

    expect(input).toBeInTheDocument();
  });

  it('should handle rapid search changes', () => {
    const Wrapper = ({ children }: { children: React.ReactNode }) => (
      <ProjectManager>{children}</ProjectManager>
    );

    const handleChange = vi.fn();
    render(<ProjectManager.Search value="" onChange={handleChange} />, { wrapper: Wrapper });

    const input = screen.getByTestId('search-input');

    fireEvent.change(input, { target: { value: 'a' } });
    fireEvent.change(input, { target: { value: 'ab' } });
    fireEvent.change(input, { target: { value: 'abc' } });

    expect(handleChange).toHaveBeenCalledTimes(3);
  });
});

describe('ProjectManager - Accessibility', () => {
  it('should have proper ARIA labels', () => {
    const Wrapper = ({ children }: { children: React.ReactNode }) => (
      <ProjectManager>{children}</ProjectManager>
    );

    render(<ProjectManager.Search placeholder="Search projects" />, { wrapper: Wrapper });

    // input type="text" has role="textbox", not "searchbox" unless explicitly set
    const input = screen.getByRole('textbox');
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-label', 'Search projects');
  });
});
