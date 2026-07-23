/**
 * EdgeTypeListCompound.test.tsx
 *
 * TDD tests for EdgeTypeList compound component pattern.
 * RED phase: Tests are written before implementation.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const antdMessage = vi.hoisted(() => ({
  error: vi.fn(),
}));
const antdModal = vi.hoisted(() => ({
  confirm: vi.fn((options?: { onOk?: () => void | Promise<void> }) => options?.onOk?.()),
}));

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd');
  return {
    ...actual,
    Modal: antdModal,
    message: antdMessage,
  };
});

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ projectId: 'test-project-1' }),
}));

const translationMock = vi.hoisted(() => {
  const t = (key: string, options?: string | Record<string, unknown>) => {
    const defaultValue =
      typeof options === 'string'
        ? options
        : typeof options === 'object' &&
            options !== null &&
            typeof options.defaultValue === 'string'
          ? options.defaultValue
          : key;

    if (typeof options !== 'object' || options === null) {
      return defaultValue;
    }

    return defaultValue.replace(/\{\{(\w+)\}\}/g, (_, token: string) =>
      String(options[token] ?? '')
    );
  };

  return {
    t,
    i18n: {
      changeLanguage: () => Promise.resolve(),
      language: 'en-US',
    },
  };
});

// Mock i18n with stable references, matching react-i18next's render contract.
vi.mock('react-i18next', () => ({
  useTranslation: () => translationMock,
}));

// Mock schemaAPI
const mockEdgeTypes = [
  {
    id: 'edge-type-1',
    name: 'KNOWS',
    description: 'Person knows another person',
    schema: {
      since: { type: 'Integer', description: 'Year when they met' },
      strength: { type: 'Float', description: 'Strength of relationship' },
    },
    status: 'ENABLED',
    source: 'user',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'edge-type-2',
    name: 'WORKS_FOR',
    description: 'Person works for organization',
    schema: {
      title: { type: 'String', description: 'Job title' },
    },
    status: 'ENABLED',
    source: 'generated',
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
];

vi.mock('../../../../services/api', () => ({
  schemaAPI: {
    listEdgeTypes: vi.fn(() => Promise.resolve(mockEdgeTypes)),
    createEdgeType: vi.fn(() => Promise.resolve({ id: 'new-edge-type' })),
    updateEdgeType: vi.fn(() => Promise.resolve({ id: 'edge-type-1' })),
    deleteEdgeType: vi.fn(() => Promise.resolve()),
  },
}));

describe('EdgeTypeList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ============================================================================
  // Import Tests
  // ============================================================================

  describe('Component Structure', () => {
    it('should export EdgeTypeList compound component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList).toBeDefined();
    });

    it('should export Header sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.Header).toBeDefined();
    });

    it('should export Toolbar sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.Toolbar).toBeDefined();
    });

    it('should export MasterPane sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.MasterPane).toBeDefined();
    });

    it('should export DetailPane sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.DetailPane).toBeDefined();
    });

    it('should export StatusBadge sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.StatusBadge).toBeDefined();
    });

    it('should export SourceBadge sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.SourceBadge).toBeDefined();
    });

    it('should export Empty sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.Empty).toBeDefined();
    });

    it('should export Loading sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.Loading).toBeDefined();
    });

    it('should export Modal sub-component', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      expect(EdgeTypeList.Modal).toBeDefined();
    });
  });

  // ============================================================================
  // Main Component Tests
  // ============================================================================

  describe('Main Component', () => {
    it('should render header with title', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Edge Types')).toBeInTheDocument();
      });
    });

    it('should render create button', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Create Edge Type')).toBeInTheDocument();
      });
    });

    it('should render toolbar with search', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getByPlaceholderText('Search edge types…')).toBeInTheDocument();
      });
    });

    it('should render edge types in master pane', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        // KNOWS appears in both master and detail panes, use getAllByText
        expect(screen.getAllByText('KNOWS').length).toBeGreaterThan(0);
        expect(screen.getAllByText('WORKS_FOR').length).toBeGreaterThan(0);
      });
    });

    it('should render schema attributes returned by the API', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getByText('since')).toBeInTheDocument();
        expect(screen.getByText('strength')).toBeInTheDocument();
      });
    });
  });

  // ============================================================================
  // Header Sub-Component Tests
  // ============================================================================

  describe('Header Sub-Component', () => {
    it('should render title', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Header onCreate={vi.fn()} />);
      expect(screen.getAllByText('Edge Types').length).toBeGreaterThan(0);
    });

    it('should render subtitle', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Header onCreate={vi.fn()} />);
      expect(
        screen.getByText('Define the structure of relationships in your knowledge graph')
      ).toBeInTheDocument();
    });

    it('should not render a fake system status badge', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Header onCreate={vi.fn()} />);
      expect(screen.queryByText('System Active')).not.toBeInTheDocument();
    });
  });

  // ============================================================================
  // Toolbar Sub-Component Tests
  // ============================================================================

  describe('Toolbar Sub-Component', () => {
    it('should render search input', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Toolbar search="" onSearchChange={vi.fn()} onCreate={vi.fn()} />);
      expect(screen.getByPlaceholderText('Search edge types…')).toBeInTheDocument();
    });

    it('should call onSearchChange when typing', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      const onSearchChange = vi.fn();
      render(<EdgeTypeList.Toolbar search="" onSearchChange={onSearchChange} onCreate={vi.fn()} />);
      const input = screen.getByPlaceholderText('Search edge types…');
      fireEvent.change(input, { target: { value: 'KNOWS' } });
      expect(onSearchChange).toHaveBeenCalledWith('KNOWS');
    });
  });

  // ============================================================================
  // StatusBadge Sub-Component Tests
  // ============================================================================

  describe('StatusBadge Sub-Component', () => {
    it('should render enabled status', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.StatusBadge status="ENABLED" />);
      expect(screen.getByText('ENABLED')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // SourceBadge Sub-Component Tests
  // ============================================================================

  describe('SourceBadge Sub-Component', () => {
    it('should render user source', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.SourceBadge source="user" />);
      expect(screen.getByText('USER')).toBeInTheDocument();
    });

    it('should render generated source', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.SourceBadge source="generated" />);
      expect(screen.getByText('AUTO')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // MasterPane Sub-Component Tests
  // ============================================================================

  describe('MasterPane Sub-Component', () => {
    const defaultProps = {
      edges: mockEdgeTypes,
      selectedId: 'edge-type-1',
      onSelect: vi.fn(),
      onEdit: vi.fn(),
    };

    it('should render edge names', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.MasterPane {...defaultProps} />);
      expect(screen.getByText('KNOWS')).toBeInTheDocument();
      expect(screen.getByText('WORKS_FOR')).toBeInTheDocument();
    });

    it('should call onSelect when edge clicked', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      const onSelect = vi.fn();
      render(<EdgeTypeList.MasterPane {...{ ...defaultProps, onSelect }} />);
      fireEvent.click(screen.getByText('WORKS_FOR'));
      expect(onSelect).toHaveBeenCalledWith('edge-type-2');
    });
  });

  // ============================================================================
  // DetailPane Sub-Component Tests
  // ============================================================================

  describe('DetailPane Sub-Component', () => {
    const defaultProps = {
      selectedEdgeId: 'edge-type-1',
      edges: mockEdgeTypes,
      onEdit: vi.fn(),
      onDelete: vi.fn(),
    };

    it('should render edge name', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.DetailPane {...defaultProps} />);
      expect(screen.getByText('KNOWS')).toBeInTheDocument();
    });

    it('should render edge description', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.DetailPane {...defaultProps} />);
      expect(screen.getByText('Person knows another person')).toBeInTheDocument();
    });

    it('should render schema attributes', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.DetailPane {...defaultProps} />);
      expect(screen.getByText('since')).toBeInTheDocument();
      expect(screen.getByText('strength')).toBeInTheDocument();
    });

    it('should call onEdit when edit button clicked', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      const onEdit = vi.fn();
      render(<EdgeTypeList.DetailPane {...{ ...defaultProps, onEdit }} />);
      // Find button with text "Edit"
      const editButton = screen.getByText('Edit');
      fireEvent.click(editButton);
      expect(onEdit).toHaveBeenCalled();
    });

    it('should call onDelete when delete button clicked', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      const onDelete = vi.fn();
      global.confirm = vi.fn(() => true);
      render(<EdgeTypeList.DetailPane {...{ ...defaultProps, onDelete }} />);
      // Find button with text "Delete"
      const deleteButton = screen.getByText('Delete');
      fireEvent.click(deleteButton);
      expect(onDelete).toHaveBeenCalled();
    });

    it('should render select prompt when no edge selected', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(
        <EdgeTypeList.DetailPane
          selectedEdgeId={null}
          edges={mockEdgeTypes}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
        />
      );
      expect(screen.getByText(/select an edge type/i)).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Empty Sub-Component Tests
  // ============================================================================

  describe('Empty Sub-Component', () => {
    it('should render empty state message', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Empty />);
      expect(screen.getByText(/No edge types defined yet/i)).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Loading Sub-Component Tests
  // ============================================================================

  describe('Loading Sub-Component', () => {
    it('should render loading message', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList.Loading />);
      expect(screen.getByText('Loading…')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Modal Sub-Component Tests
  // ============================================================================

  describe('Modal Sub-Component', () => {
    it('should render modal when open', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(
        <EdgeTypeList.Modal isOpen={true} onClose={vi.fn()} onSave={vi.fn()} editingEdge={null} />
      );
      expect(screen.getByText('New Edge Type')).toBeInTheDocument();
    });

    it('should render edit mode when editingEdge provided', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(
        <EdgeTypeList.Modal
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          editingEdge={mockEdgeTypes[0]}
        />
      );
      expect(screen.getByText(/KNOWS/)).toBeInTheDocument();
    });

    it('should call onSave when save button clicked', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      const onSave = vi.fn();
      render(
        <EdgeTypeList.Modal isOpen={true} onClose={vi.fn()} onSave={onSave} editingEdge={null} />
      );
      const saveButton = screen.getByText('Save');
      fireEvent.click(saveButton);
      expect(onSave).toHaveBeenCalled();
    });
  });

  // ============================================================================
  // Integration Tests
  // ============================================================================

  describe('Integration', () => {
    it('should open modal when create button clicked', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Create Edge Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Create Edge Type'));
      await waitFor(() => {
        expect(screen.getByText('New Edge Type')).toBeInTheDocument();
      });
    });

    it('shows in-app error feedback when saving fails', async () => {
      const { schemaAPI } = await import('../../../../services/api');
      vi.mocked(schemaAPI.createEdgeType).mockRejectedValueOnce(new Error('save failed'));
      const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);

      await waitFor(() => {
        expect(screen.getByText('Create Edge Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Create Edge Type'));
      await waitFor(() => {
        expect(screen.getByText('New Edge Type')).toBeInTheDocument();
      });
      fireEvent.change(screen.getByPlaceholderText('e.g. KNOWS, WORKS_FOR, LOCATED_IN'), {
        target: { value: 'LIKES' },
      });
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(antdMessage.error).toHaveBeenCalledWith('Failed to save edge type');
      });
      expect(alertSpy).not.toHaveBeenCalled();
      alertSpy.mockRestore();
    });

    it('blocks saving when the name is empty', async () => {
      const { schemaAPI } = await import('../../../../services/api');

      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);

      await waitFor(() => {
        expect(screen.getByText('Create Edge Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Create Edge Type'));
      await waitFor(() => {
        expect(screen.getByText('New Edge Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(antdMessage.error).toHaveBeenCalledWith('Name is required');
      });
      expect(schemaAPI.createEdgeType).not.toHaveBeenCalled();
    });

    it('blocks saving when the name duplicates an existing edge type', async () => {
      const { schemaAPI } = await import('../../../../services/api');

      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);

      await waitFor(() => {
        expect(screen.getByText('Create Edge Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Create Edge Type'));
      await waitFor(() => {
        expect(screen.getByText('New Edge Type')).toBeInTheDocument();
      });
      fireEvent.change(screen.getByPlaceholderText('e.g. KNOWS, WORKS_FOR, LOCATED_IN'), {
        target: { value: 'knows' },
      });
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(antdMessage.error).toHaveBeenCalledWith(
          'An edge type with this name already exists'
        );
      });
      expect(schemaAPI.createEdgeType).not.toHaveBeenCalled();
    });

    it('should select edge and show detail pane', async () => {
      const { EdgeTypeList } = await import('../../../../pages/project/schema/EdgeTypeList');
      render(<EdgeTypeList />);
      await waitFor(() => {
        expect(screen.getAllByText('KNOWS').length).toBeGreaterThan(0);
      });
      // Click the first KNOWS element (in master pane)
      fireEvent.click(screen.getAllByText('KNOWS')[0]);
      await waitFor(() => {
        // Description appears in both master and detail panes
        expect(screen.getAllByText('Person knows another person').length).toBeGreaterThan(0);
      });
    });
  });
});
