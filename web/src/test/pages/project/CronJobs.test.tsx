import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CronJobs } from '../../../pages/project/CronJobs';
import type { CronJobResponse, CronJobRunResponse } from '../../../types/cron';
import { fireEvent, render, screen } from '../../utils';

const cronState = vi.hoisted(() => ({
  jobs: [] as CronJobResponse[],
  runs: [] as CronJobRunResponse[],
  total: 0,
  runsTotal: 0,
  filters: {
    search: '',
    include_disabled: true,
    page: 1,
    pageSize: 20,
  },
  loading: false,
  submitting: false,
  actions: {
    fetchJobs: vi.fn().mockResolvedValue(undefined),
    createJob: vi.fn().mockResolvedValue(undefined),
    updateJob: vi.fn().mockResolvedValue(undefined),
    deleteJob: vi.fn().mockResolvedValue(undefined),
    toggleJob: vi.fn().mockResolvedValue(undefined),
    triggerRun: vi.fn().mockResolvedValue(undefined),
    fetchRuns: vi.fn().mockResolvedValue(undefined),
    setFilters: vi.fn(),
  },
}));

vi.mock('../../../stores/cron', () => ({
  useCronJobs: () => cronState.jobs,
  useCronJobRuns: () => cronState.runs,
  useCronTotal: () => cronState.total,
  useCronRunsTotal: () => cronState.runsTotal,
  useCronFilters: () => cronState.filters,
  useCronLoading: () => cronState.loading,
  useCronSubmitting: () => cronState.submitting,
  useCronActions: () => cronState.actions,
}));

vi.mock('../../../components/cron/CronJobForm', () => ({
  CronJobForm: () => null,
}));

const buildJob = (overrides: Partial<CronJobResponse> = {}): CronJobResponse => ({
  id: 'job-1',
  project_id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Evolver Heartbeat + Task Earner',
  description: 'Keeps the agent runtime active.',
  enabled: true,
  delete_after_run: false,
  schedule: { kind: 'every', config: {} },
  payload: { kind: 'agent_turn', config: {} },
  delivery: { kind: 'none', config: {} },
  conversation_mode: 'reuse',
  conversation_id: null,
  timezone: 'UTC',
  stagger_seconds: 0,
  timeout_seconds: 30,
  max_retries: 0,
  state: {},
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
  ...overrides,
});

const buildRun = (overrides: Partial<CronJobRunResponse> = {}): CronJobRunResponse => ({
  id: 'run-1',
  job_id: 'job-1',
  project_id: 'project-1',
  status: 'success',
  trigger_type: 'scheduled',
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:00:01Z',
  duration_ms: 1000,
  error_message: null,
  result_summary: {},
  conversation_id: null,
  ...overrides,
});

describe('CronJobs', () => {
  beforeEach(() => {
    cronState.jobs = [buildJob(), buildJob({ id: 'job-2', name: 'EvoMap Node Monitor' })];
    cronState.runs = [];
    cronState.total = cronState.jobs.length;
    cronState.runsTotal = 0;
    cronState.filters = {
      search: '',
      include_disabled: true,
      page: 1,
      pageSize: 20,
    };
    cronState.loading = false;
    cronState.submitting = false;
    vi.clearAllMocks();
  });

  it('constrains the table to horizontal scrolling on narrow viewports', () => {
    const { container } = render(<CronJobs />);

    expect(screen.getByText('Scheduled Tasks')).toBeInTheDocument();
    expect(container.querySelector('.ant-table-content')).toHaveStyle({ overflowX: 'auto' });
    expect(container.querySelector('.ant-pagination')).not.toBeInTheDocument();
  });

  it('labels job toggle switches with the job name', () => {
    render(<CronJobs />);

    expect(
      screen.getByRole('switch', { name: 'Toggle Evolver Heartbeat + Task Earner' })
    ).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Toggle EvoMap Node Monitor' })).toBeInTheDocument();
  });

  it('uses server job totals to render pagination for full current pages', () => {
    cronState.jobs = Array.from({ length: 20 }, (_, index) =>
      buildJob({ id: `job-${index + 1}`, name: `Scheduled Task ${index + 1}` })
    );
    cronState.total = 25;

    const { container } = render(<CronJobs />);

    expect(container.querySelector('.ant-pagination')).toBeInTheDocument();
    expect(screen.getByText('Showing 1-20 of 25 tasks')).toBeInTheDocument();
  });

  it('uses server run totals to render run history pagination', () => {
    cronState.runs = Array.from({ length: 10 }, (_, index) =>
      buildRun({ id: `run-${index + 1}` })
    );
    cronState.runsTotal = 23;

    render(<CronJobs />);
    fireEvent.click(screen.getAllByText('History')[0]);

    expect(screen.getByText('Showing 1-10 of 23 runs')).toBeInTheDocument();
  });
});
