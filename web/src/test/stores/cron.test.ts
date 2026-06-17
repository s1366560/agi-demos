import { beforeEach, describe, expect, it, vi } from 'vitest';

import { cronAPI } from '@/services/cronService';
import { useCronStore } from '@/stores/cron';

import type {
  CronJobListResponse,
  CronJobResponse,
  CronJobRunListResponse,
  CronJobRunResponse,
} from '@/types/cron';

vi.mock('@/services/cronService', () => ({
  cronAPI: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    toggle: vi.fn(),
    run: vi.fn(),
    listRuns: vi.fn(),
  },
}));

const deferred = <T>() => {
  let resolve: (value: T | PromiseLike<T>) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
};

const job = (overrides: Partial<CronJobResponse> = {}): CronJobResponse => ({
  id: 'job-1',
  project_id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Scheduled Task',
  description: null,
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
  created_at: '2026-06-17T00:00:00Z',
  updated_at: null,
  ...overrides,
});

const jobList = (items: CronJobResponse[]): CronJobListResponse => ({
  items,
  total: items.length,
});

const run = (overrides: Partial<CronJobRunResponse> = {}): CronJobRunResponse => ({
  id: 'run-1',
  job_id: 'job-1',
  project_id: 'project-1',
  status: 'success',
  trigger_type: 'scheduled',
  started_at: '2026-06-17T00:00:00Z',
  finished_at: '2026-06-17T00:00:01Z',
  duration_ms: 1000,
  error_message: null,
  result_summary: {},
  conversation_id: null,
  ...overrides,
});

const runList = (items: CronJobRunResponse[]): CronJobRunListResponse => ({
  items,
  total: items.length,
});

describe('cron store', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCronStore.getState().reset();
  });

  it('ignores stale project job list responses', async () => {
    const oldRequest = deferred<CronJobListResponse>();
    const newRequest = deferred<CronJobListResponse>();
    vi.mocked(cronAPI.list)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useCronStore.getState().fetchJobs('old-project');
    const secondLoad = useCronStore.getState().fetchJobs('new-project');

    newRequest.resolve(jobList([job({ id: 'new-job', project_id: 'new-project' })]));
    await secondLoad;

    expect(useCronStore.getState().jobs.map((item) => item.id)).toEqual(['new-job']);
    expect(useCronStore.getState().isLoading).toBe(false);

    oldRequest.resolve(jobList([job({ id: 'old-job', project_id: 'old-project' })]));
    await firstLoad;

    expect(useCronStore.getState().jobs.map((item) => item.id)).toEqual(['new-job']);
    expect(useCronStore.getState().total).toBe(1);
  });

  it('ignores stale job detail responses', async () => {
    const oldRequest = deferred<CronJobResponse>();
    const newRequest = deferred<CronJobResponse>();
    vi.mocked(cronAPI.get)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useCronStore.getState().fetchJob('project-1', 'old-job');
    const secondLoad = useCronStore.getState().fetchJob('project-2', 'new-job');

    newRequest.resolve(job({ id: 'new-job', project_id: 'project-2' }));
    await secondLoad;

    expect(useCronStore.getState().selectedJob?.id).toBe('new-job');
    expect(useCronStore.getState().isLoading).toBe(false);

    oldRequest.resolve(job({ id: 'old-job', project_id: 'project-1' }));
    await firstLoad;

    expect(useCronStore.getState().selectedJob?.id).toBe('new-job');
  });

  it('ignores stale run history responses', async () => {
    const oldRequest = deferred<CronJobRunListResponse>();
    const newRequest = deferred<CronJobRunListResponse>();
    vi.mocked(cronAPI.listRuns)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const firstLoad = useCronStore.getState().fetchRuns('project-1', 'old-job');
    const secondLoad = useCronStore.getState().fetchRuns('project-2', 'new-job');

    newRequest.resolve(runList([run({ id: 'new-run', project_id: 'project-2' })]));
    await secondLoad;

    expect(useCronStore.getState().runs.map((item) => item.id)).toEqual(['new-run']);
    expect(useCronStore.getState().isLoading).toBe(false);

    oldRequest.resolve(runList([run({ id: 'old-run', project_id: 'project-1' })]));
    await firstLoad;

    expect(useCronStore.getState().runs.map((item) => item.id)).toEqual(['new-run']);
    expect(useCronStore.getState().runsTotal).toBe(1);
  });
});
