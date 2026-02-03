/**
 * SubAgentListCompound.test.tsx
 *
 * TDD tests for SubAgentList compound component pattern.
 * RED phase: Tests are written before implementation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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

// Mock SubAgentModal
vi.mock('../../../components/subagent/SubAgentModal', () => ({
  SubAgentModal: ({ isOpen, onClose, onCreate, onSuccess }: any) =>
    isOpen ? (
      <div data-testid="subagent-modal">
        <button onClick={onClose}>Close</button>
        <button onClick={onCreate}>Create</button>
        <button onClick={onSuccess}>Success</button>
      </div>
    ) : null,
}));

// Mock custom hooks from stores/subagent
const mockSubAgents = [
  {
    id: '1',
    name: 'test-subagent',
    display_name: 'Test SubAgent',
    description: 'Test description',
    enabled: true,
    model: 'gpt-4',
    color: '#FF5733',
    trigger: {
      type: 'keyword',
      keywords: ['test', 'example'],
    },
    allowed_tools: ['tool1', 'tool2'],
    allowed_skills: ['skill1'],
    system_prompt: 'You are a helpful assistant',
    total_invocations: 100,
    success_rate: 0.85,
    avg_execution_time_ms: 1500,
    tenant_id: 'tenant-1',
    project_id: 'proj-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: '2',
    name: 'disabled-subagent',
    display_name: 'Disabled SubAgent',
    description: 'Disabled subagent',
    enabled: false,
    model: 'gpt-4',
    color: '#3498db',
    trigger: {
      type: 'keyword',
      keywords: ['other'],
    },
    allowed_tools: ['*'],
    allowed_skills: [],
    system_prompt: 'You are a helpful assistant',
    total_invocations: 50,
    success_rate: 0.92,
    avg_execution_time_ms: 2000,
    tenant_id: 'tenant-1',
    project_id: 'proj-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
];

const mockTemplates = [
  {
    id: 'tpl-1',
    name: 'Research Assistant',
    description: 'Template for research tasks',
    model: 'gpt-4',
    system_prompt: 'You are a research assistant',
    trigger: { type: 'keyword', keywords: ['research'] },
    allowed_tools: ['web_search'],
    allowed_skills: [],
    color: '#007AFF',
  },
];

const mockStoreState = {
  subagents: mockSubAgents,
  templates: mockTemplates,
  search: '',
  statusFilter: 'all' as const,
  modelFilter: '',
  isLoadingSubAgents: false,
  isLoadingTemplates: false,
  isToggling: new Set<string>(),
  isDeleting: new Set<string>(),
  error: null,
  listSubAgents: vi.fn(),
  listTemplates: vi.fn(),
  toggleSubAgent: vi.fn(),
  deleteSubAgent: vi.fn(),
  createFromTemplate: vi.fn(),
  setSearch: vi.fn(),
  setStatusFilter: vi.fn(),
  setModelFilter: vi.fn(),
  clearError: vi.fn(),
};

vi.mock('../../../stores/subagent', () => ({
  useSubAgentData: vi.fn(() => mockSubAgents),
  useSubAgentFiltersData: vi.fn(() => ({
    search: '',
    statusFilter: 'all',
    modelFilter: '',
  })),
  filterSubAgents: vi.fn((args) => args?.subagents || mockSubAgents),
  useSubAgentLoading: vi.fn(() => ({
    isLoadingSubAgents: false,
    isLoadingTemplates: false,
    isToggling: new Set(),
    isDeleting: new Set(),
  })),
  useSubAgentTemplates: vi.fn(() => mockTemplates),
  useSubAgentTemplatesLoading: vi.fn(() => false),
  useSubAgentError: vi.fn(() => null),
  useEnabledSubAgentsCount: vi.fn(() => 2),
  useAverageSuccessRate: vi.fn(() => 0.88),
  useTotalInvocations: vi.fn(() => 150),
  useListSubAgents: vi.fn(() => vi.fn()),
  useListTemplates: vi.fn(() => vi.fn()),
  useToggleSubAgent: vi.fn(() => vi.fn()),
  useDeleteSubAgent: vi.fn(() => vi.fn()),
  useCreateFromTemplate: vi.fn(() => vi.fn()),
  useSetSubAgentFilters: vi.fn(() => vi.fn()),
  useClearSubAgentError: vi.fn(() => vi.fn()),
}));

describe('SubAgentList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStoreState.isToggling.clear();
    mockStoreState.isDeleting.clear();
  });

  // ============================================================================
  // Import Tests
  // ============================================================================

  describe('Component Structure', () => {
    it('should export SubAgentList compound component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList).toBeDefined();
    });

    it('should export Header sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Header).toBeDefined();
    });

    it('should export Stats sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Stats).toBeDefined();
    });

    it('should export FilterBar sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.FilterBar).toBeDefined();
    });

    it('should export StatusBadge sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.StatusBadge).toBeDefined();
    });

    it('should export Card sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Card).toBeDefined();
    });

    it('should export Loading sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Loading).toBeDefined();
    });

    it('should export Empty sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Empty).toBeDefined();
    });

    it('should export Grid sub-component', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      expect(SubAgentList.Grid).toBeDefined();
    });
  });

  // ============================================================================
  // Main Component Tests
  // ============================================================================

  describe('Main Component', () => {
    it('should render header with create button', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList />);
      expect(screen.getByText('Create SubAgent')).toBeInTheDocument();
    });

    it('should render stats cards', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList />);
      expect(screen.getByText(/Total SubAgents/)).toBeInTheDocument();
      expect(screen.getAllByText('Enabled').length).toBeGreaterThan(0);
    });

    it('should render filter bar', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList />);
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    it('should render subagent cards', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList />);
      expect(screen.getByText('Test SubAgent')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Header Sub-Component Tests
  // ============================================================================

  describe('Header Sub-Component', () => {
    it('should render title and create button', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(
        <SubAgentList.Header
          onCreate={vi.fn()}
          onCreateFromTemplate={vi.fn()}
          templates={[]}
        />
      );
      expect(screen.getByText('Create SubAgent')).toBeInTheDocument();
    });

    it('should call onCreate when create button clicked', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      const onCreate = vi.fn();
      render(
        <SubAgentList.Header
          onCreate={onCreate}
          onCreateFromTemplate={vi.fn()}
          templates={[]}
        />
      );
      fireEvent.click(screen.getByText('Create SubAgent'));
      expect(onCreate).toHaveBeenCalledTimes(1);
    });
  });

  // ============================================================================
  // Stats Sub-Component Tests
  // ============================================================================

  describe('Stats Sub-Component', () => {
    it('should render all stats', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(
        <SubAgentList.Stats
          total={2}
          enabledCount={1}
          avgSuccessRate={88}
          totalInvocations={150}
        />
      );
      expect(screen.getByText('2')).toBeInTheDocument();
      expect(screen.getByText('1')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // FilterBar Sub-Component Tests
  // ============================================================================

  describe('FilterBar Sub-Component', () => {
    it('should render search input', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(
        <SubAgentList.FilterBar
          search=""
          onSearchChange={vi.fn()}
          statusFilter="all"
          onStatusFilterChange={vi.fn()}
          modelFilter=""
          onModelFilterChange={vi.fn()}
          onRefresh={vi.fn()}
        />
      );
      expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    });

    it('should call onSearchChange when typing', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      const onSearchChange = vi.fn();
      render(
        <SubAgentList.FilterBar
          search=""
          onSearchChange={onSearchChange}
          statusFilter="all"
          onStatusFilterChange={vi.fn()}
          modelFilter=""
          onModelFilterChange={vi.fn()}
          onRefresh={vi.fn()}
        />
      );
      const input = screen.getByPlaceholderText(/search/i);
      fireEvent.change(input, { target: { value: 'test' } });
      expect(onSearchChange).toHaveBeenCalledWith('test');
    });
  });

  // ============================================================================
  // StatusBadge Sub-Component Tests
  // ============================================================================

  describe('StatusBadge Sub-Component', () => {
    it('should render enabled badge', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.StatusBadge enabled={true} />);
      expect(screen.getByText('Enabled')).toBeInTheDocument();
    });

    it('should render disabled badge', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.StatusBadge enabled={false} />);
      expect(screen.getByText('Disabled')).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Card Sub-Component Tests
  // ============================================================================

  describe('Card Sub-Component', () => {
    const defaultProps = {
      subagent: mockSubAgents[0],
      onToggle: vi.fn(),
      onEdit: vi.fn(),
      onDelete: vi.fn(),
    };

    it('should render subagent display name', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Card {...defaultProps} />);
      expect(screen.getByText('Test SubAgent')).toBeInTheDocument();
    });

    it('should render status badge', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Card {...defaultProps} />);
      expect(screen.getByText('Enabled')).toBeInTheDocument();
    });

    it('should render model', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Card {...defaultProps} />);
      expect(screen.getByText('gpt-4')).toBeInTheDocument();
    });

    it('should render trigger keywords', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Card {...defaultProps} />);
      expect(screen.getByText('test')).toBeInTheDocument();
      expect(screen.getByText('example')).toBeInTheDocument();
    });

    it('should render stats', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Card {...defaultProps} />);
      expect(screen.getByText('100')).toBeInTheDocument(); // invocations
      expect(screen.getByText('85%')).toBeInTheDocument(); // success rate
    });

    it('should call onToggle when switch changed', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      const onToggle = vi.fn();
      render(<SubAgentList.Card {...{ ...defaultProps, onToggle }} />);
      const switchElement = document.querySelector('.ant-switch');
      if (switchElement) {
        fireEvent.click(switchElement);
        expect(onToggle).toHaveBeenCalled();
      }
    });
  });

  // ============================================================================
  // Empty Sub-Component Tests
  // ============================================================================

  describe('Empty Sub-Component', () => {
    it('should render empty state message', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Empty />);
      expect(screen.getByText(/no subagents/i)).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Loading Sub-Component Tests
  // ============================================================================

  describe('Loading Sub-Component', () => {
    it('should render loading spinner', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList.Loading />);
      const loadingElement = document.querySelector('.ant-spin');
      expect(loadingElement).toBeInTheDocument();
    });
  });

  // ============================================================================
  // Integration Tests
  // ============================================================================

  describe('Integration', () => {
    it('should filter subagents by search text', async () => {
      const { SubAgentList } = await import('../../../pages/tenant/SubAgentList');
      render(<SubAgentList />);
      const searchInput = screen.getByPlaceholderText(/search/i);
      fireEvent.change(searchInput, { target: { value: 'Disabled' } });
      await waitFor(() => {
        expect(screen.getByText('Disabled SubAgent')).toBeInTheDocument();
      });
    });
  });
});
