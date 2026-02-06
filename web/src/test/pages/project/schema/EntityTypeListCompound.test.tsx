/**
 * EntityTypeListCompound.test.tsx
 *
 * TDD tests for EntityTypeList compound component pattern.
 * RED phase: Tests are written before implementation.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ projectId: 'test-project-1' }),
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

// Mock schemaAPI
const mockEntityTypes = [
  {
    id: 'entity-type-1',
    name: 'Person',
    description: 'A human being',
    schema: {
      name: { type: 'String', description: 'Full name', required: true },
      age: { type: 'Integer', description: 'Age in years', required: false },
      email: { type: 'String', description: 'Email address', required: true },
    },
    status: 'ENABLED',
    source: 'user',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'entity-type-2',
    name: 'Organization',
    description: 'A company or organization',
    schema: {
      name: { type: 'String', description: 'Organization name', required: true },
      founded: { type: 'Integer', description: 'Year founded', required: false },
    },
    status: 'ENABLED',
    source: 'generated',
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
];

vi.mock('../../../../services/api', () => ({
  schemaAPI: {
    listEntityTypes: vi.fn(() => Promise.resolve(mockEntityTypes)),
    createEntityType: vi.fn(() => Promise.resolve({ id: 'new-entity-type' })),
    updateEntityType: vi.fn(() => Promise.resolve({ id: 'entity-type-1' })),
    deleteEntityType: vi.fn(() => Promise.resolve()),
  },
}));

describe('EntityTypeList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ============================================================================
  // Import Tests
  // ============================================================================

  describe('Component Structure', () => {
    it('should export EntityTypeList compound component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList).toBeDefined();
    });

    it('should export Header sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Header).toBeDefined();
    });

    it('should export Toolbar sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Toolbar).toBeDefined();
    });

    it('should export Table sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Table).toBeDefined();
    });

    it('should export TableHeader sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.TableHeader).toBeDefined();
    });

    it('should export TableRow sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.TableRow).toBeDefined();
    });

    it('should export StatusBadge sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.StatusBadge).toBeDefined();
    });

    it('should export SourceBadge sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.SourceBadge).toBeDefined();
    });

    it('should export Empty sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Empty).toBeDefined();
    });

    it('should export Loading sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Loading).toBeDefined();
    });

    it('should export Modal sub-component', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      expect(EntityTypeList.Modal).toBeDefined();
    });
  });

  // ============================================================================
  // Main Component Tests
  // ============================================================================

  describe('Main Component', () => {
    it('should render header with title', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Entity Types')).toBeInTheDocument();
      });
    });

    it('should render create button', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Create Entity Type')).toBeInTheDocument();
      });
    });

    it('should render toolbar with search', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList />);
      await waitFor(() => {
        expect(screen.getByPlaceholderText('Search entity types...')).toBeInTheDocument();
      });
    });

    it('should render entity types in table', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Person')).toBeInTheDocument();
        expect(screen.getByText('Organization')).toBeInTheDocument();
      });
    });
  });

  // ============================================================================
  // Header Sub-Component Tests
  // ============================================================================

  describe('Header Sub-Component', () => {
    it('should render title and create button', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.Header onCreate={vi.fn()} />);
      expect(screen.getByText('Entity Types')).toBeInTheDocument();
      expect(screen.getByText('Create Entity Type')).toBeInTheDocument();
    });

    it('should call onCreate when create button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onCreate = vi.fn();
      render(<EntityTypeList.Header onCreate={onCreate} />);
      fireEvent.click(screen.getByText('Create Entity Type'));
      expect(onCreate).toHaveBeenCalledTimes(1);
    });
  });

  // ============================================================================
  // Toolbar Sub-Component Tests
  // ============================================================================

  describe('Toolbar Sub-Component', () => {
    it('should render search input', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(
        <EntityTypeList.Toolbar
          search=""
          onSearchChange={vi.fn()}
          viewMode="list"
          onViewModeChange={vi.fn()}
        />
      );
      expect(screen.getByPlaceholderText('Search entity types...')).toBeInTheDocument();
    });

    it('should call onSearchChange when typing', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onSearchChange = vi.fn();
      render(
        <EntityTypeList.Toolbar
          search=""
          onSearchChange={onSearchChange}
          viewMode="list"
          onViewModeChange={vi.fn()}
        />
      );
      const input = screen.getByPlaceholderText('Search entity types...');
      fireEvent.change(input, { target: { value: 'Person' } });
      expect(onSearchChange).toHaveBeenCalledWith('Person');
    });

    it('should call onViewModeChange when grid view clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onViewModeChange = vi.fn();
      render(
        <EntityTypeList.Toolbar
          search=""
          onSearchChange={vi.fn()}
          viewMode="list"
          onViewModeChange={onViewModeChange}
        />
      );
      const gridButton = screen.getByTitle('Grid View');
      fireEvent.click(gridButton);
      expect(onViewModeChange).toHaveBeenCalledWith('grid');
    });
  });

  // ============================================================================
  // StatusBadge Sub-Component Tests
  // ============================================================================

  describe('StatusBadge Sub-Component', () => {
    it('should render enabled status', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.StatusBadge status="ENABLED" />);
      expect(screen.getByText('ENABLED')).toBeInTheDocument();
    });

    it('should render disabled status', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.StatusBadge status="DISABLED" />);
      expect(screen.getByText('DISABLED')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // SourceBadge Sub-Component Tests
  // ============================================================================

  describe('SourceBadge Sub-Component', () => {
    it('should render user source', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.SourceBadge source="user" />);
      expect(screen.getByText('user')).toBeInTheDocument();
    });

    it('should render generated source', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.SourceBadge source="generated" />);
      expect(screen.getByText('generated')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // TableRow Sub-Component Tests
  // ============================================================================

  describe('TableRow Sub-Component', () => {
    const defaultProps = {
      entity: mockEntityTypes[0],
      onEdit: vi.fn(),
      onDelete: vi.fn(),
    };

    it('should render entity name', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.TableRow {...defaultProps} />);
      expect(screen.getByText('Person')).toBeInTheDocument();
    });

    it('should render entity description', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.TableRow {...defaultProps} />);
      expect(screen.getByText('A human being')).toBeInTheDocument();
    });

    it('should render schema attributes', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.TableRow {...defaultProps} />);
      expect(screen.getByText('name')).toBeInTheDocument();
      expect(screen.getByText('age')).toBeInTheDocument();
      expect(screen.getByText('email')).toBeInTheDocument();
    });

    it('should call onEdit when edit button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onEdit = vi.fn();
      render(<EntityTypeList.TableRow {...{ ...defaultProps, onEdit }} />);
      const editButton = screen.getByTitle('Edit');
      fireEvent.click(editButton);
      expect(onEdit).toHaveBeenCalledWith(mockEntityTypes[0]);
    });

    it('should call onDelete when delete button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onDelete = vi.fn();
      // Mock window.confirm
      global.confirm = vi.fn(() => true);
      render(<EntityTypeList.TableRow {...{ ...defaultProps, onDelete }} />);
      const deleteButton = screen.getByTitle('Delete');
      fireEvent.click(deleteButton);
      expect(onDelete).toHaveBeenCalledWith('entity-type-1');
    });
  });

  // ============================================================================
  // Empty Sub-Component Tests
  // ============================================================================

  describe('Empty Sub-Component', () => {
    it('should render empty state message', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.Empty />);
      expect(screen.getByText(/No entity types defined yet/)).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Loading Sub-Component Tests
  // ============================================================================

  describe('Loading Sub-Component', () => {
    it('should render loading message', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList.Loading />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Modal Sub-Component Tests
  // ============================================================================

  describe('Modal Sub-Component', () => {
    it('should render modal when open', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(
        <EntityTypeList.Modal
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          editingEntity={null}
        />
      );
      expect(screen.getByText('New Entity Type')).toBeInTheDocument();
    });

    it('should render edit mode when editingEntity provided', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(
        <EntityTypeList.Modal
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          editingEntity={mockEntityTypes[0]}
        />
      );
      expect(screen.getByText(/Person/)).toBeInTheDocument();
    });

    it('should call onClose when close button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onClose = vi.fn();
      render(
        <EntityTypeList.Modal
          isOpen={true}
          onClose={onClose}
          onSave={vi.fn()}
          editingEntity={null}
        />
      );
      // Find the X button by looking for a button containing an SVG
      const buttons = screen.getAllByRole('button');
      const closeButton = buttons.find((btn) => btn.querySelector('svg'));
      if (closeButton) {
        fireEvent.click(closeButton);
        expect(onClose).toHaveBeenCalled();
      }
    });

    it('should call onSave when save button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      const onSave = vi.fn();
      render(
        <EntityTypeList.Modal
          isOpen={true}
          onClose={vi.fn()}
          onSave={onSave}
          editingEntity={null}
        />
      );
      const saveButton = screen.getByText('Save');
      fireEvent.click(saveButton);
      expect(onSave).toHaveBeenCalled();
    });

    it('should render tab buttons', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(
        <EntityTypeList.Modal
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          editingEntity={null}
        />
      );
      expect(screen.getByText('General Settings')).toBeInTheDocument();
      expect(screen.getByText('Attributes & Schema')).toBeInTheDocument();
      expect(screen.getByText('Relationships')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Integration Tests
  // ============================================================================

  describe('Integration', () => {
    it('should open modal when create button clicked', async () => {
      const { EntityTypeList } = await import('../../../../pages/project/schema/EntityTypeList');
      render(<EntityTypeList />);
      await waitFor(() => {
        expect(screen.getByText('Create Entity Type')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Create Entity Type'));
      await waitFor(() => {
        expect(screen.getByText('New Entity Type')).toBeInTheDocument();
      });
    });
  });
});
