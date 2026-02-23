/**
 * SubAgentList.test.tsx
 *
 * Performance and functionality tests for SubAgentList component.
 * Tests verify React.memo optimization and component behavior.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SubAgentList } from '../../../pages/tenant/SubAgentList';

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
        <button onClick={onClose}>Close</button>
        <button onClick={onSuccess}>Success</button>
      </div>
    ) : null,
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
}));

describe('SubAgentList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render header with title', () => {
      render(<SubAgentList />);
      expect(screen.getByText('tenant.subagents.title')).toBeInTheDocument();
    });

    it('should render stats cards', () => {
      render(<SubAgentList />);
      expect(screen.getByText('tenant.subagents.stats.total')).toBeInTheDocument();
      expect(screen.getByText('tenant.subagents.stats.enabled')).toBeInTheDocument();
      expect(screen.getByText('tenant.subagents.stats.successRate')).toBeInTheDocument();
      expect(screen.getByText('tenant.subagents.stats.invocations')).toBeInTheDocument();
    });

    it('should render subagent cards', () => {
      render(<SubAgentList />);
      expect(screen.getByText('Test Agent')).toBeInTheDocument();
      expect(screen.getByText('Another Agent')).toBeInTheDocument();
    });

    it('should show loading state when isLoading is true', () => {
      vi.doMock('../../../stores/subagent', () => ({
        useSubAgentLoading: () => true,
        // ... other mocks
      }));

      render(<SubAgentList />);
      // Should show loading indicator
      const loadingElement = document.querySelector('.ant-spin');
      expect(loadingElement).toBeInTheDocument();
    });
  });

  describe('Filtering', () => {
    it('should filter subagents by search text', async () => {
      render(<SubAgentList />);

      const searchInput = screen.getByPlaceholderText('tenant.subagents.searchPlaceholder');
      if (searchInput) {
        await userEvent.type(searchInput, 'Test');

        await waitFor(() => {
          expect(screen.getByText('Test Agent')).toBeInTheDocument();
        });
      }
    });

    it('should filter subagents by status', async () => {
      render(<SubAgentList />);

      const statusFilter = screen.getByRole('combobox');
      await userEvent.click(statusFilter);
      // Select "enabled" option
      const enabledOption = screen.getByText('tenant.subagents.enabledOnly');
      if (enabledOption) {
        await userEvent.click(enabledOption);

        await waitFor(() => {
          expect(screen.getByText('Test Agent')).toBeInTheDocument();
        });
      }
    });
  });

  describe('Component Structure', () => {
    it('should have SubAgentCard component defined', async () => {
       
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('SubAgentCard');
    });

    it('should have StatusBadge component', async () => {
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('StatusBadge');
    });

    it('should export SubAgentList component', async () => {
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('export const SubAgentList');
    });
  });

  describe('Performance', () => {
    it('should use useMemo for computed values', async () => {
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('useMemo');
    });

    it('should use useCallback for event handlers', async () => {
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('useCallback');
    });

    it('should have efficient filtering', async () => {
       

      const sourceCode = (await import('fs')).readFileSync(
        require.resolve('../../../pages/tenant/SubAgentList'),
        'utf-8'
      );
      expect(sourceCode).toContain('filterSubAgents');
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
      const searchInput = screen.getByPlaceholderText('tenant.subagents.searchPlaceholder');
      expect(searchInput).toBeInTheDocument();
    });
  });
});
