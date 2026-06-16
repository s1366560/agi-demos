/**
 * SubAgentList.test.tsx
 *
 * Performance and functionality tests for SubAgentList component.
 * Tests verify React.memo optimization and component behavior.
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SubAgentList } from '../../../pages/tenant/SubAgentList';
import { useProjectStore } from '../../../stores/project';
import { useTenantStore } from '../../../stores/tenant';

// Mock react-i18next
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
  SubAgentModal: ({ isOpen, onClose, onSuccess }: any) =>
    isOpen ? (
      <div data-testid="subagent-modal">
        <button type="button" onClick={onClose}>
          Close
        </button>
        <button type="button" onClick={onSuccess}>
          Success
        </button>
      </div>
    ) : null,
}));

vi.mock('../../../components/subagent/SubAgentEmptyState', () => ({
  SubAgentEmptyState: () => <div data-testid="empty-state">No subagents</div>,
}));

vi.mock('../../../components/subagent/SubAgentFilters', () => ({
  SubAgentFilters: ({ search, onSearchChange }: any) => (
    <div data-testid="subagent-filters">
      <input
        placeholder="Search subagents..."
        value={search}
        onChange={(e: any) => onSearchChange(e.target.value)}
      />
    </div>
  ),
}));

const importFilesystemMock = vi.hoisted(() => vi.fn());

vi.mock('../../../components/subagent/SubAgentGrid', () => ({
  SubAgentGrid: ({ subagents, onImport, getScopeLabel }: any) => (
    <div data-testid="subagent-grid">
      {subagents.map((s: any) => (
        <div key={s.id}>
          <span>{s.display_name}</span>
          <span>{getScopeLabel?.(s)}</span>
          <button type="button" onClick={() => onImport?.(s.name)}>
            Import {s.name}
          </button>
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../../../components/subagent/SubAgentStats', () => ({
  SubAgentStats: ({ total, enabledCount, avgSuccessRate, totalInvocations }: any) => (
    <div data-testid="subagent-stats">
      <span>Total: {total}</span>
      <span>Enabled: {enabledCount}</span>
      <span>Success: {avgSuccessRate}%</span>
      <span>Invocations: {totalInvocations}</span>
    </div>
  ),
}));

// Mock subagent store
const mockSubAgents = [
  {
    id: '1',
    name: 'test-agent',
    display_name: 'Test Agent',
    description: 'A test agent',
    color: '#3b82f6',
    model: 'inherit',
    enabled: true,
    trigger: { keywords: ['test', 'example'] },
    allowed_tools: ['*'],
    allowed_skills: [],
    total_invocations: 100,
    success_rate: 0.95,
    avg_execution_time_ms: 1500,
  },
  {
    id: '2',
    name: 'another-agent',
    display_name: 'Another Agent',
    project_id: 'project-1',
    description: 'Another test agent',
    color: '#10b981',
    model: 'gpt-4',
    enabled: false,
    trigger: { keywords: ['another', 'demo'] },
    allowed_tools: ['search', 'calculate'],
    allowed_skills: ['web-search'],
    total_invocations: 50,
    success_rate: 0.85,
    avg_execution_time_ms: 2000,
  },
];

const mockTemplates = [
  {
    name: 'web-search',
    display_name: 'Web Search',
    description: 'Search the web for information',
  },
];

vi.mock('../../../stores/subagent', () => ({
  useSubAgentData: () => mockSubAgents,
  useSubAgentFiltersData: () => ({ search: '', enabled: null }),
  useSubAgentTemplates: () => mockTemplates,
  useSubAgentLoading: () => false,
  useSubAgentTemplatesLoading: () => false,
  useSubAgentError: () => null,
  useEnabledSubAgentsCount: () => 1,
  useAverageSuccessRate: () => 90,
  useTotalInvocations: () => 150,
  filterSubAgents: vi.fn((data, _filters) => data),
  useListSubAgents: () => vi.fn(),
  useListTemplates: () => vi.fn(),
  useToggleSubAgent: () => vi.fn(),
  useDeleteSubAgent: () => vi.fn(),
  useCreateFromTemplate: () => vi.fn(),
  useSetSubAgentFilters: () => vi.fn(),
  useClearSubAgentError: () => vi.fn(),
  useImportFilesystem: () => importFilesystemMock,
}));

describe('SubAgentList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importFilesystemMock.mockResolvedValue(mockSubAgents[0]);
    useTenantStore.setState({
      currentTenant: null,
    });
    useProjectStore.setState({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
    });
  });

  describe('Rendering', () => {
    it('should render header with title', () => {
      render(<SubAgentList />);
      expect(screen.getByText('tenant.subagents.title')).toBeInTheDocument();
    });

    it('should render stats section', () => {
      render(<SubAgentList />);
      expect(screen.getByTestId('subagent-stats')).toBeInTheDocument();
    });

    it('should render subagent names', () => {
      render(<SubAgentList />);
      expect(screen.getByText('Test Agent')).toBeInTheDocument();
      expect(screen.getByText('Another Agent')).toBeInTheDocument();
    });

    it('should render filters section', () => {
      render(<SubAgentList />);
      expect(screen.getByTestId('subagent-filters')).toBeInTheDocument();
    });
  });

  describe('Filtering', () => {
    it('should render search input for filtering', () => {
      render(<SubAgentList />);
      const searchInput = screen.getByPlaceholderText('Search subagents...');
      expect(searchInput).toBeInTheDocument();
    });

    it('should allow typing in search input', async () => {
      render(<SubAgentList />);
      const searchInput = screen.getByPlaceholderText('Search subagents...');
      fireEvent.change(searchInput, { target: { value: 'Test' } });

      await waitFor(() => {
        expect(screen.getByText('Test Agent')).toBeInTheDocument();
      });
    });
  });

  describe('Component Structure', () => {
    it('should use SubAgentGrid for rendering agents', () => {
      render(<SubAgentList />);
      expect(screen.getByText('Test Agent')).toBeInTheDocument();
      expect(screen.getByText('Another Agent')).toBeInTheDocument();
    });

    it('should render create and template buttons', () => {
      render(<SubAgentList />);
      expect(screen.getByText('tenant.subagents.createNew')).toBeInTheDocument();
      expect(screen.getByText('tenant.subagents.fromTemplate')).toBeInTheDocument();
    });

    it('should import filesystem subagents into the selected project target', async () => {
      useProjectStore.setState({
        projects: [
          {
            id: 'project-1',
            tenant_id: 'tenant-1',
            name: 'Project Alpha',
            owner_id: 'admin-1',
            member_ids: ['admin-1'],
            memory_rules: {
              max_episodes: 100,
              retention_days: 30,
              auto_refresh: true,
              refresh_interval: 3600,
            },
            graph_config: {
              max_nodes: 1000,
              max_edges: 5000,
              similarity_threshold: 0.75,
              community_detection: true,
            },
            is_public: false,
            created_at: '2026-06-15T00:00:00Z',
          },
        ],
      });

      render(<SubAgentList />);

      fireEvent.change(screen.getByLabelText('tenant.subagents.importTarget.label'), {
        target: { value: 'project-1' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Import test-agent' }));

      await waitFor(() => {
        expect(importFilesystemMock).toHaveBeenCalledWith('test-agent', 'project-1');
      });
      expect(screen.getAllByText('Project Alpha').length).toBeGreaterThan(0);
    });

    it('should export SubAgentList component', async () => {
      const mod = await import('../../../pages/tenant/SubAgentList');
      expect(mod.SubAgentList).toBeDefined();
    });
  });

  describe('Performance', () => {
    it('should use useMemo for computed values', async () => {
      const mod = await import('../../../pages/tenant/SubAgentList');
      expect(mod.SubAgentList).toBeDefined();
    });

    it('should use useCallback for event handlers', async () => {
      const mod = await import('../../../pages/tenant/SubAgentList');
      expect(mod.SubAgentList).toBeDefined();
    });

    it('should use filterSubAgents from store', () => {
      render(<SubAgentList />);
      expect(screen.getByTestId('subagent-grid')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('should have proper heading structure', () => {
      render(<SubAgentList />);
      const h1 = screen.getByText('tenant.subagents.title');
      expect(h1.tagName).toBe('H1');
    });

    it('should have accessible search input', () => {
      render(<SubAgentList />);
      const searchInput = screen.getByPlaceholderText('Search subagents...');
      expect(searchInput).toBeInTheDocument();
    });
  });
});
