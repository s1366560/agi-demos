import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectAgentPatterns } from '@/pages/project/ProjectAgentPatterns';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import { ProjectAgentContractError } from '@/services/projectAgentService';

const { listSharedPatterns } = vi.hoisted(() => ({
  listSharedPatterns: vi.fn(),
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useParams: () => ({ tenantId: 'tenant-1', projectId: 'project-1' }),
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/services/projectAgentService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/projectAgentService')>();
  return {
    ...actual,
    projectAgentService: {
      ...actual.projectAgentService,
      listSharedPatterns,
    },
  };
});

vi.mock('@/components/agent/patterns/PatternList', () => ({
  PatternList: (props: Record<string, unknown>) => {
    const patterns = props.patterns as Array<{
      id: string;
      name: string;
      status: string;
      successRate: number;
    }>;
    const destructiveCallbacks = ['onDelete', 'onDeprecate', 'onReset'].filter(
      (name) => typeof props[name] === 'function'
    );
    return (
      <div data-testid="pattern-list">
        {patterns.map((pattern) => (
          <span key={pattern.id}>
            {pattern.name}:{pattern.status}:{pattern.successRate}
          </span>
        ))}
        {destructiveCallbacks.map((name) => (
          <button key={name} type="button" data-testid={`destructive-${name}`}>
            {name}
          </button>
        ))}
      </div>
    );
  },
}));

vi.mock('@/components/agent/patterns/PatternInspector', () => ({
  PatternInspector: (props: Record<string, unknown>) => {
    const destructiveCallbacks = ['onDelete', 'onDeprecate', 'onReset'].filter(
      (name) => typeof props[name] === 'function'
    );
    return (
      <div data-testid="pattern-inspector">
        {destructiveCallbacks.map((name) => (
          <button key={name} type="button" data-testid={`inspector-destructive-${name}`}>
            {name}
          </button>
        ))}
      </div>
    );
  },
}));

const sharedPattern = {
  id: 'pattern-1',
  tenant_id: 'tenant-1',
  name: 'Research pattern',
  description: 'A tenant-shared workflow pattern',
  steps: [
    {
      step_number: 1,
      description: 'Search',
      tool_name: 'web_search',
      expected_output_format: 'json',
      similarity_threshold: 0.8,
      tool_parameters: {},
    },
  ],
  success_rate: 0.912,
  usage_count: 7,
  created_at: '2026-08-05T00:00:00.000Z',
  updated_at: '2026-08-05T01:00:00.000Z',
  metadata: { avg_runtime: 1200 },
};

describe('ProjectAgentPatterns', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('moves from loading to a tenant-shared read-only projection', async () => {
    let resolveResponse: (value: unknown) => void = () => {};
    listSharedPatterns.mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve;
      })
    );

    render(<ProjectAgentPatterns />);

    expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
      'data-availability',
      'loading'
    );

    resolveResponse({
      project_id: 'project-1',
      tenant_id: 'tenant-1',
      scope_kind: 'tenant_shared',
      patterns: [sharedPattern],
      total: 1,
      page: 1,
      page_size: 50,
    });

    await waitFor(() => {
      expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
        'data-availability',
        'available'
      );
    });
    expect(listSharedPatterns).toHaveBeenCalledWith('project-1');
    expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
      'data-scope-kind',
      'tenant_shared'
    );
    expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
      'data-tenant-id',
      'tenant-1'
    );
    expect(screen.getByText('Research pattern:unclassified:91.2')).toBeInTheDocument();
    expect(screen.queryByTestId(/^destructive-/)).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^inspector-destructive-/)).not.toBeInTheDocument();
  });

  it('fails closed when project membership is forbidden', async () => {
    listSharedPatterns.mockRejectedValue(
      new ApiError(ApiErrorType.AUTHORIZATION, 'FORBIDDEN', 'Forbidden', 403)
    );

    render(<ProjectAgentPatterns />);

    await waitFor(() => {
      expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
        'data-reason-code',
        'project_agent_patterns_forbidden'
      );
    });
    expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
      'data-availability',
      'unavailable'
    );
  });

  it('surfaces a fail-closed project or tenant scope conflict without data', async () => {
    listSharedPatterns.mockRejectedValue(
      new ProjectAgentContractError('project_agent_patterns_scope_conflict')
    );

    render(<ProjectAgentPatterns />);

    await waitFor(() => {
      expect(screen.getByTestId('project-agent-patterns')).toHaveAttribute(
        'data-reason-code',
        'project_agent_patterns_scope_conflict'
      );
    });
    expect(screen.queryByTestId('pattern-list')).not.toBeInTheDocument();
  });
});
