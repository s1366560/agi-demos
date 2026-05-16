import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CronJobs } from '../../../pages/project/CronJobs';
import type { CronJobResponse } from '../../../types/cron';
import { render, screen } from '../../utils';

const cronState = vi.hoisted(() => ({
  jobs: [] as CronJobResponse[],
  runs: [],
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
  },
}));

vi.mock('../../../stores/cron', () => ({
  useCronJobs: () => cronState.jobs,
  useCronJobRuns: () => cronState.runs,
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

describe('CronJobs', () => {
  beforeEach(() => {
    cronState.jobs = [buildJob(), buildJob({ id: 'job-2', name: 'EvoMap Node Monitor' })];
    cronState.runs = [];
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
});
