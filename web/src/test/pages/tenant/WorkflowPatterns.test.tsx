import type { ReactNode } from 'react';

import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkflowPatterns } from '@/pages/tenant/WorkflowPatterns';

const { modalConfirm, listPatterns, deletePattern, successMessage, errorMessage, lazyMessage } =
  vi.hoisted(() => {
    const successMessage = vi.fn();
    const errorMessage = vi.fn();

    return {
      modalConfirm: vi.fn(),
      listPatterns: vi.fn(),
      deletePattern: vi.fn(),
      successMessage,
      errorMessage,
      lazyMessage: {
        success: successMessage,
        error: errorMessage,
      },
    };
  });

const { translate } = vi.hoisted(() => ({
  translate: (key: string) => key,
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useParams: () => ({ tenantId: 'tenant-1' }),
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: translate,
  }),
}));

vi.mock('antd', () => ({
  Modal: {
    confirm: modalConfirm,
  },
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  useLazyMessage: () => lazyMessage,
  LazySkeleton: () => <div data-testid="lazy-skeleton" />,
  Skeleton: {
    Button: ({ active, block, style }: { active?: boolean; block?: boolean; style?: object }) => (
      <div data-active={String(active)} data-block={String(block)} style={style} />
    ),
  },
}));

vi.mock('@/components/agent/patterns/PatternStats', () => ({
  PatternStats: () => <div data-testid="pattern-stats" />,
}));

vi.mock('@/components/agent/patterns/PatternList', () => ({
  PatternList: ({
    patterns,
    onDeprecate,
  }: {
    patterns: Array<{ id: string; name: string }>;
    onDeprecate: (patternId: string) => void;
  }) => (
    <div data-testid="pattern-list">
      {patterns.map((pattern) => (
        <button key={pattern.id} type="button" onClick={() => onDeprecate(pattern.id)}>
          {pattern.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock('@/components/agent/patterns/PatternInspector', () => ({
  PatternInspector: ({ onDeprecate }: { onDeprecate: () => void; children?: ReactNode }) => (
    <button type="button" onClick={onDeprecate}>
      inspect-delete
    </button>
  ),
}));

vi.mock('@/services/patternService', () => ({
  PatternServiceError: class PatternServiceError extends Error {},
  patternService: {
    listPatterns,
    deletePattern,
  },
}));

const mockPattern = {
  id: 'pattern-1',
  tenant_id: 'tenant-1',
  name: 'Research pattern',
  description: 'A learned research workflow',
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
  success_rate: 91.2,
  usage_count: 7,
  created_at: '2026-05-01T00:00:00.000Z',
  updated_at: '2026-05-02T00:00:00.000Z',
  metadata: { avg_runtime: 1200 },
};

describe('WorkflowPatterns', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listPatterns.mockResolvedValue({
      patterns: [mockPattern],
      total: 1,
      page: 1,
      page_size: 50,
    });
    deletePattern.mockResolvedValue(undefined);
  });

  it('renders page controls through translation keys', async () => {
    render(<WorkflowPatterns />);

    expect(await screen.findByText('tenant.workflowPatterns.title')).toBeInTheDocument();
    expect(screen.getByText('tenant.workflowPatterns.description')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('tenant.workflowPatterns.searchPlaceholder')
    ).toBeInTheDocument();
    expect(screen.getByLabelText('tenant.workflowPatterns.sortLabel')).toBeInTheDocument();
    expect(screen.getByText('common.refresh')).toBeInTheDocument();
  });

  it('uses localized copy for destructive pattern deletion', async () => {
    render(<WorkflowPatterns />);

    fireEvent.click(await screen.findByText('Research pattern'));

    expect(modalConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'tenant.workflowPatterns.deleteTitle',
        content: 'tenant.workflowPatterns.deleteConfirm',
        okText: 'common.delete',
        cancelText: 'common.cancel',
        okType: 'danger',
      })
    );

    const [{ onOk }] = modalConfirm.mock.calls[0] as [{ onOk: () => Promise<void> }];
    await act(async () => {
      await onOk();
    });

    expect(deletePattern).toHaveBeenCalledWith('pattern-1', 'tenant-1');
    expect(successMessage).toHaveBeenCalledWith('tenant.workflowPatterns.deleteSuccess');
  });

  it('shows localized fallback copy when pattern loading fails', async () => {
    listPatterns.mockRejectedValue(new Error('network unavailable'));

    render(<WorkflowPatterns />);

    expect(await screen.findByText('tenant.workflowPatterns.loadErrorTitle')).toBeInTheDocument();
    expect(screen.getByText('tenant.workflowPatterns.loadError')).toBeInTheDocument();
    expect(screen.getByText('common.retry')).toBeInTheDocument();
    expect(errorMessage).toHaveBeenCalledWith('tenant.workflowPatterns.loadError');
  });
});
