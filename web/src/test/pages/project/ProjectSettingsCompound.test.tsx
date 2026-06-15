/**
 * ProjectSettingsCompound.test.tsx
 *
 * TDD tests for ProjectSettings compound component pattern.
 * RED phase: Tests are written before implementation.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Modal } from 'antd';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockNavigate = vi.hoisted(() => vi.fn());
const mockApiPost = vi.hoisted(() => vi.fn(() => Promise.resolve({ data: {} })));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Settings: () => <span data-testid="settings-icon">Settings</span>,
  Save: () => <span data-testid="save-icon">Save</span>,
  Trash2: () => <span data-testid="trash-icon">Trash</span>,
  Download: () => <span data-testid="download-icon">Download</span>,
  RefreshCw: () => <span data-testid="refresh-icon">Refresh</span>,
  AlertCircle: () => <span data-testid="alert-icon">Alert</span>,
  Box: () => <span data-testid="box-icon">Box</span>,
  Database: () => <span data-testid="database-icon">Database</span>,
  Network: () => <span data-testid="network-icon">Network</span>,
  Power: () => <span data-testid="power-icon">Power</span>,
  RotateCcw: () => <span data-testid="rotate-icon">Rotate</span>,
  Server: () => <span data-testid="server-icon">Server</span>,
  ShieldAlert: () => <span data-testid="shield-alert-icon">ShieldAlert</span>,
  SlidersHorizontal: () => <span data-testid="sliders-icon">Sliders</span>,
  Wrench: () => <span data-testid="wrench-icon">Wrench</span>,
}));

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      changeLanguage: () => Promise.resolve(),
      language: 'en-US',
    },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock project store
const mockProject = {
  id: 'proj-1',
  tenant_id: 'tenant-1',
  name: 'Test Project',
  description: 'Test Description',
  is_public: false,
  memory_rules: {
    max_episodes: 100,
    retention_days: 365,
    auto_refresh: true,
    refresh_interval: 24,
  },
  graph_config: {
    max_nodes: 10000,
    max_edges: 50000,
    similarity_threshold: 0.8,
    community_detection: true,
  },
};

// Use a wrapper object for the mock state
const mockState = {
  currentProject: mockProject,
  setCurrentProject: vi.fn(),
  projects: [mockProject],
  fetchProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
};

vi.mock('../../../stores/project', () => ({
  useProjectStore: vi.fn((selector) => {
    return selector ? selector(mockState) : mockState;
  }),
}));

// Mock API
const mockProjectAPI = {
  update: vi.fn(() => Promise.resolve(mockProject)),
  delete: vi.fn(() => Promise.resolve()),
};

vi.mock('../../../services/api', () => ({
  default: {
    post: mockApiPost,
  },
  projectAPI: mockProjectAPI,
}));

vi.mock('../../../services/projectSandboxService', () => ({
  projectSandboxService: {
    getProjectSandbox: vi.fn(() => new Promise(() => {})),
    getStats: vi.fn(() => new Promise(() => {})),
    restartSandbox: vi.fn(() => Promise.resolve()),
    terminateSandbox: vi.fn(() => Promise.resolve()),
  },
}));

describe('ProjectSettings Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockReset();
    // Reset project mock to default
    mockState.currentProject = mockProject;
    mockState.projects = [mockProject];
    // Mock window.confirm and alert
    global.confirm = vi.fn(() => true);
    global.alert = vi.fn();
    global.prompt = vi.fn(() => mockProject.name);
  });

  // ============================================================================
  // Import Tests
  // ============================================================================

  describe('Component Structure', () => {
    it('should export ProjectSettings compound component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings).toBeDefined();
    });

    it('should export Header sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Header).toBeDefined();
    });

    it('should export Message sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Message).toBeDefined();
    });

    it('should export Basic sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Basic).toBeDefined();
    });

    it('should export Memory sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Memory).toBeDefined();
    });

    it('should export Graph sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Graph).toBeDefined();
    });

    it('should export Advanced sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Advanced).toBeDefined();
    });

    it('should export Danger sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.Danger).toBeDefined();
    });

    it('should export NoProject sub-component', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      expect(ProjectSettings.NoProject).toBeDefined();
    });
  });

  // ============================================================================
  // Main Component Tests
  // ============================================================================

  describe('Main Component', () => {
    it('should render header with title', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(screen.getByText('project.settings.title')).toBeInTheDocument();
    });

    it('should render basic settings section', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(
        screen.getByRole('heading', { name: 'project.settings.basicTitle', level: 2 })
      ).toBeInTheDocument();
    });

    it('should render memory rules section', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(
        screen.getByRole('heading', { name: 'project.settings.memoryTitle', level: 2 })
      ).toBeInTheDocument();
    });

    it('should render graph config section', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(
        screen.getByRole('heading', { name: 'project.settings.graphTitle', level: 2 })
      ).toBeInTheDocument();
    });

    it('should render advanced section', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(
        screen.getByRole('heading', { name: 'project.settings.advancedTitle', level: 2 })
      ).toBeInTheDocument();
    });

    it('should render danger zone', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(
        screen.getByRole('heading', { name: 'project.settings.dangerTitle', level: 2 })
      ).toBeInTheDocument();
    });

    it('should show no project state when project is null', async () => {
      mockState.currentProject = null;
      mockState.projects = [];
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      expect(screen.getByText('project.settings.noProject')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Header Sub-Component Tests
  // ============================================================================

  describe('Header Sub-Component', () => {
    it('should render title', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Header title="Test Title" />);
      expect(screen.getByText('Test Title')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Message Sub-Component Tests
  // ============================================================================

  describe('Message Sub-Component', () => {
    it('should render success message', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Message
          message={{ type: 'success', text: 'Success message' }}
          onClose={vi.fn()}
        />
      );
      expect(screen.getByText('Success message')).toBeInTheDocument();
    });

    it('should render error message', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Message
          message={{ type: 'error', text: 'Error message' }}
          onClose={vi.fn()}
        />
      );
      expect(screen.getByText('Error message')).toBeInTheDocument();
    });

    it('should not render when message is null', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Message message={null} onClose={vi.fn()} />);
      expect(screen.queryByTestId('alert-icon')).not.toBeInTheDocument();
    });

    it('should call onClose when close button clicked', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onClose = vi.fn();
      render(
        <ProjectSettings.Message message={{ type: 'success', text: 'Success' }} onClose={onClose} />
      );
      // The message should have a close button
      const closeButton = screen.getByRole('button');
      fireEvent.click(closeButton);
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ============================================================================
  // Basic Settings Sub-Component Tests
  // ============================================================================

  describe('Basic Settings Sub-Component', () => {
    const defaultProps = {
      data: {
        name: 'Test Project',
        description: 'Test Description',
        isPublic: false,
      },
      isSaving: false,
      onNameChange: vi.fn(),
      onDescriptionChange: vi.fn(),
      onIsPublicChange: vi.fn(),
      onSave: vi.fn(() => Promise.resolve()),
    };

    it('should render name input', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Basic {...defaultProps} />);
      expect(screen.getByDisplayValue('Test Project')).toBeInTheDocument();
    });

    it('should render description textarea', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Basic {...defaultProps} />);
      expect(screen.getByDisplayValue('Test Description')).toBeInTheDocument();
    });

    it('should render isPublic checkbox', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Basic {...defaultProps} />);
      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).not.toBeChecked();
    });

    it('should call onNameChange when name input changes', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onNameChange = vi.fn();
      render(<ProjectSettings.Basic {...{ ...defaultProps, onNameChange }} />);
      const input = screen.getByDisplayValue('Test Project');
      fireEvent.change(input, { target: { value: 'New Name' } });
      expect(onNameChange).toHaveBeenCalledWith('New Name');
    });

    it('should call onIsPublicChange when checkbox toggled', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onIsPublicChange = vi.fn();
      render(<ProjectSettings.Basic {...{ ...defaultProps, onIsPublicChange }} />);
      const checkbox = screen.getByRole('checkbox');
      fireEvent.click(checkbox);
      expect(onIsPublicChange).toHaveBeenCalledWith(true);
    });

    it('should disable save button when saving', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Basic {...{ ...defaultProps, isSaving: true }} />);
      const saveButton = screen.getByText('project.settings.basicSaving');
      expect(saveButton).toBeDisabled();
    });
  });

  // ============================================================================
  // Memory Rules Sub-Component Tests
  // ============================================================================

  describe('Memory Rules Sub-Component', () => {
    const defaultProps = {
      data: {
        maxEpisodes: 100,
        retentionDays: 365,
        autoRefresh: true,
        refreshInterval: 24,
      },
      isSaving: false,
      onMaxEpisodesChange: vi.fn(),
      onRetentionDaysChange: vi.fn(),
      onAutoRefreshChange: vi.fn(),
      onRefreshIntervalChange: vi.fn(),
      onSave: vi.fn(() => Promise.resolve()),
    };

    it('should render max episodes input', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Memory {...defaultProps} />);
      expect(screen.getByDisplayValue('100')).toBeInTheDocument();
    });

    it('should render retention days input', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Memory {...defaultProps} />);
      expect(screen.getByDisplayValue('365')).toBeInTheDocument();
    });

    it('should render auto refresh checkbox as checked', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Memory {...defaultProps} />);
      const checkbox = screen.getByLabelText('project.settings.memoryAutoRefresh');
      expect(checkbox).toBeChecked();
    });

    it('should render refresh interval when auto refresh is enabled', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Memory {...defaultProps} />);
      expect(screen.getByDisplayValue('24')).toBeInTheDocument();
    });

    it('should hide refresh interval when auto refresh is disabled', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Memory
          {...{ ...defaultProps, data: { ...defaultProps.data, autoRefresh: false } }}
        />
      );
      expect(screen.queryByDisplayValue('24')).not.toBeInTheDocument();
    });

    it('should call onAutoRefreshChange when checkbox toggled', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onAutoRefreshChange = vi.fn();
      render(<ProjectSettings.Memory {...{ ...defaultProps, onAutoRefreshChange }} />);
      const checkbox = screen.getByLabelText('project.settings.memoryAutoRefresh');
      fireEvent.click(checkbox);
      expect(onAutoRefreshChange).toHaveBeenCalledWith(false);
    });
  });

  // ============================================================================
  // Graph Config Sub-Component Tests
  // ============================================================================

  describe('Graph Config Sub-Component', () => {
    const defaultProps = {
      data: {
        maxNodes: 10000,
        maxEdges: 50000,
        similarityThreshold: 0.8,
        communityDetection: true,
      },
      isSaving: false,
      onMaxNodesChange: vi.fn(),
      onMaxEdgesChange: vi.fn(),
      onSimilarityThresholdChange: vi.fn(),
      onCommunityDetectionChange: vi.fn(),
      onSave: vi.fn(() => Promise.resolve()),
    };

    it('should render max nodes input', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Graph {...defaultProps} />);
      expect(screen.getByDisplayValue('10000')).toBeInTheDocument();
    });

    it('should render max edges input', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Graph {...defaultProps} />);
      expect(screen.getAllByDisplayValue('50000').length).toBeGreaterThan(0);
    });

    it('should render similarity threshold slider', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Graph {...defaultProps} />);
      const slider = screen.getByRole('slider');
      expect(slider).toBeInTheDocument();
      expect(slider).toHaveValue('0.8');
    });

    it('should render community detection checkbox', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Graph {...defaultProps} />);
      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).toBeChecked();
    });

    it('should call onSimilarityThresholdChange when slider changes', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onSimilarityThresholdChange = vi.fn();
      render(<ProjectSettings.Graph {...{ ...defaultProps, onSimilarityThresholdChange }} />);
      const slider = screen.getByRole('slider');
      fireEvent.change(slider, { target: { value: '0.9' } });
      expect(onSimilarityThresholdChange).toHaveBeenCalledWith(0.9);
    });
  });

  // ============================================================================
  // Advanced Sub-Component Tests
  // ============================================================================

  describe('Advanced Sub-Component', () => {
    it('should render export data button', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Advanced
          onExportData={vi.fn()}
          onClearCache={vi.fn()}
          onRebuildCommunities={vi.fn()}
        />
      );
      expect(screen.getByText('project.settings.advancedExport')).toBeInTheDocument();
    });

    it('should render clear cache button', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Advanced
          onExportData={vi.fn()}
          onClearCache={vi.fn()}
          onRebuildCommunities={vi.fn()}
        />
      );
      expect(screen.getByText('project.settings.advancedClearCache')).toBeInTheDocument();
    });

    it('should render rebuild communities button', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(
        <ProjectSettings.Advanced
          onExportData={vi.fn()}
          onClearCache={vi.fn()}
          onRebuildCommunities={vi.fn()}
        />
      );
      expect(screen.getByText('project.settings.advancedRebuild')).toBeInTheDocument();
    });

    it('should call onExportData when export button clicked', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      const onExportData = vi.fn(() => Promise.resolve());
      render(
        <ProjectSettings.Advanced
          onExportData={onExportData}
          onClearCache={vi.fn()}
          onRebuildCommunities={vi.fn()}
        />
      );
      fireEvent.click(screen.getByText('project.settings.advancedExport'));
      await waitFor(() => {
        expect(onExportData).toHaveBeenCalled();
      });
    });

    it('should scope advanced export to the current project', async () => {
      const originalCreateObjectURL = window.URL.createObjectURL;
      const originalRevokeObjectURL = window.URL.revokeObjectURL;
      window.URL.createObjectURL = vi.fn(() => 'blob:project-export');
      window.URL.revokeObjectURL = vi.fn();
      const { ProjectSettings } = await import('../../../pages/project/Settings');

      try {
        render(<ProjectSettings />);
        fireEvent.click(screen.getByText('project.settings.advancedExport'));

        await waitFor(() => {
          expect(mockApiPost).toHaveBeenCalledWith('/data/export', {
            tenant_id: 'tenant-1',
            project_id: 'proj-1',
            include_episodes: true,
            include_entities: true,
            include_relationships: true,
            include_communities: true,
          });
        });
      } finally {
        window.URL.createObjectURL = originalCreateObjectURL;
        window.URL.revokeObjectURL = originalRevokeObjectURL;
      }
    });

    it('should scope clear cache to the current project', async () => {
      vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
        void config.onOk?.();
        return { destroy: vi.fn(), update: vi.fn() } as ReturnType<typeof Modal.confirm>;
      });
      const { ProjectSettings } = await import('../../../pages/project/Settings');

      render(<ProjectSettings />);
      fireEvent.click(screen.getByText('project.settings.advancedClearCache'));

      await waitFor(() => {
        expect(mockApiPost).toHaveBeenCalledWith('/maintenance/refresh/incremental', {
          project_id: 'proj-1',
          rebuild_communities: true,
        });
      });
    });

    it('should scope community rebuild to the current project', async () => {
      vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
        void config.onOk?.();
        return { destroy: vi.fn(), update: vi.fn() } as ReturnType<typeof Modal.confirm>;
      });
      const { ProjectSettings } = await import('../../../pages/project/Settings');

      render(<ProjectSettings />);
      fireEvent.click(screen.getByText('project.settings.advancedRebuild'));

      await waitFor(() => {
        expect(mockApiPost).toHaveBeenCalledWith('/graph/communities/rebuild?project_id=proj-1');
      });
    });
  });

  // ============================================================================
  // Danger Zone Sub-Component Tests
  // ============================================================================

  describe('Danger Zone Sub-Component', () => {
    it('should render danger title', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Danger projectName="Test Project" onDelete={vi.fn()} />);
      expect(screen.getByText('project.settings.dangerTitle')).toBeInTheDocument();
    });

    it('should render delete button', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.Danger projectName="Test Project" onDelete={vi.fn()} />);
      const deleteButton = screen.getByText('project.settings.dangerDelete');
      expect(deleteButton).toBeInTheDocument();
    });
  });

  // ============================================================================
  // NoProject Sub-Component Tests
  // ============================================================================

  describe('NoProject Sub-Component', () => {
    it('should render no project message', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.NoProject />);
      expect(screen.getByText('project.settings.noProject')).toBeInTheDocument();
    });

    it('should render settings icon', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings.NoProject />);
      expect(screen.getByTestId('settings-icon')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Integration Tests
  // ============================================================================

  describe('Integration', () => {
    it('should save basic settings', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      const saveButton = screen.getByText('project.settings.basicSave');
      fireEvent.click(saveButton);
      await waitFor(() => {
        expect(mockState.updateProject).toHaveBeenCalled();
      });
    });

    it('should update project store without reloading the page', async () => {
      const reload = vi.fn();
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload },
      });
      const { ProjectSettings } = await import('../../../pages/project/Settings');

      render(<ProjectSettings />);
      fireEvent.click(screen.getByText('project.settings.basicSave'));

      await waitFor(() => {
        expect(mockState.updateProject).toHaveBeenCalledWith('tenant-1', 'proj-1', {
          name: 'Test Project',
          description: 'Test Description',
          is_public: false,
        });
      });
      expect(reload).not.toHaveBeenCalled();
    });

    it('should navigate to tenant page after deleting project without hard reload', async () => {
      const originalLocation = window.location;
      const hrefSetter = vi.fn();
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: {
          get href() {
            return '';
          },
          set href(value: string) {
            hrefSetter(value);
          },
        },
      });
      const confirmSpy = vi.spyOn(Modal, 'confirm').mockImplementation((config) => {
        const content = config.content as {
          props?: { onChange?: (event: { target: { value: string } }) => void };
        };
        content.props?.onChange?.({ target: { value: mockProject.name } });
        void config.onOk?.();
        return { destroy: vi.fn(), update: vi.fn() } as ReturnType<typeof Modal.confirm>;
      });
      const { ProjectSettings } = await import('../../../pages/project/Settings');

      try {
        render(<ProjectSettings />);
        fireEvent.click(screen.getByText('project.settings.dangerDelete'));

        await waitFor(() => {
          expect(mockProjectAPI.delete).toHaveBeenCalledWith('tenant-1', 'proj-1');
        });
        expect(mockNavigate).toHaveBeenCalledWith('/tenant');
        expect(hrefSetter).not.toHaveBeenCalled();
      } finally {
        confirmSpy.mockRestore();
        Object.defineProperty(window, 'location', {
          configurable: true,
          value: originalLocation,
        });
      }
    });

    it('should save memory rules', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      const saveButton = screen.getByText('project.settings.memorySave');
      fireEvent.click(saveButton);
      await waitFor(() => {
        expect(mockProjectAPI.update).toHaveBeenCalled();
      });
    });

    it('should save graph config', async () => {
      const { ProjectSettings } = await import('../../../pages/project/Settings');
      render(<ProjectSettings />);
      const saveButton = screen.getByText('project.settings.graphSave');
      fireEvent.click(saveButton);
      await waitFor(() => {
        expect(mockProjectAPI.update).toHaveBeenCalled();
      });
    });
  });
});
