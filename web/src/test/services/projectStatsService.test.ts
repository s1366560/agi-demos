import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';
import { clearProjectStatsSummaryCache, projectStatsService } from '@/services/projectStatsService';
import { installResourceOperationFixtureV2 } from './webResourceOperationFixtureV2';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/services/client/urlUtils', () => ({ apiFetch: { get: request } }));

const projectStatsPayload = {
  active_nodes: 2,
  conversation_count: 4,
  member_count: 3,
  memory_count: 5,
  node_count: 6,
  storage_limit: 100,
  storage_used: 12,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe('projectStatsService', () => {
  let fixture: ReturnType<typeof installResourceOperationFixtureV2>;
  let load: (url: string) => Promise<unknown>;
  beforeEach(() => {
    clearProjectStatsSummaryCache();
    fixture = installResourceOperationFixtureV2();
    load = async () => projectStatsPayload;
    request.mockImplementation(
      (
        url: string,
        consume: (response: Response, operation: WebOperationContextV2) => Promise<unknown>,
        options: { parent: WebOperationContextV2; signal: AbortSignal }
      ) =>
        runWebOperationV2(async (operation) => {
          const data = await load(url);
          operation.check();
          return consume(new Response(JSON.stringify(data)), operation);
        }, options)
    );
  });
  afterEach(async () => {
    await fixture.close();
    clearProjectStatsSummaryCache();
    request.mockReset();
  });

  it('shares concurrent stats requests for the same project under one owner', async () => {
    const [first, second] = await Promise.all([
      projectStatsService.getStats('project-1'),
      projectStatsService.getStats('project-1'),
    ]);
    expect(first).toEqual(projectStatsPayload);
    expect(second).toEqual(projectStatsPayload);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(
      '/projects/project-1/stats',
      expect.any(Function),
      expect.objectContaining({ parent: expect.any(Object), signal: expect.any(AbortSignal) })
    );
    expect(fixture.acquired()).toBe(3); // Both public calls admitted; only one HTTP child.
    expect(fixture.released()).toBe(3);
  });

  it('keeps the settled TTL cache but still admits each cache hit', async () => {
    await projectStatsService.getStats('project-1');
    await projectStatsService.getStats('project-1');
    expect(request).toHaveBeenCalledTimes(1);
    expect(fixture.acquired()).toBe(3);
    fixture.admission.setEnabled(false);
    await expect(projectStatsService.getStats('project-1')).rejects.toThrow(
      'web_operation_generation_unavailable'
    );
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('keeps resource/project/limit keys distinct', async () => {
    load = async (url) =>
      url.includes('recent-skills')
        ? { skills: [{ name: 'code', last_used: 'now' }] }
        : { entities: [{ name: url.endsWith('8') ? 'A' : 'B', mention_count: 1 }] };
    const [eight, ten, recent] = await Promise.all([
      projectStatsService.getTrending('project-1', 8),
      projectStatsService.getTrending('project-1', 10),
      projectStatsService.getRecentSkills('project-1'),
    ]);
    expect(eight).toEqual([{ name: 'A', mention_count: 1 }]);
    expect(ten).toEqual([{ name: 'B', mention_count: 1 }]);
    expect(recent).toEqual([{ name: 'code', last_used: 'now' }]);
    await projectStatsService.getTrending('project-2', 8);
    expect(request.mock.calls.map(([url]) => url)).toEqual([
      '/projects/project-1/trending?limit=8',
      '/projects/project-1/trending?limit=10',
      '/projects/project-1/recent-skills?limit=5',
      '/projects/project-2/trending?limit=8',
    ]);
  });

  it('does not cache failures so the next request can retry', async () => {
    load = vi
      .fn()
      .mockRejectedValueOnce(new Error('temporary stats failure'))
      .mockResolvedValue(projectStatsPayload);
    await expect(projectStatsService.getStats('project-1')).rejects.toThrow(
      'temporary stats failure'
    );
    await expect(projectStatsService.getStats('project-1')).resolves.toEqual(projectStatsPayload);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('never returns a settled cache entry from a retired identity owner', async () => {
    await projectStatsService.getStats('project-1');
    fixture.admission.invalidate();
    load = async () => ({ ...projectStatsPayload, memory_count: 99 });
    expect((await projectStatsService.getStats('project-1')).memory_count).toBe(99);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('does not share old pending promises or cache late cancelled data', async () => {
    const old = deferred<unknown>();
    load = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue({ ...projectStatsPayload, memory_count: 99 });
    const stale = projectStatsService.getStats('project-1').catch((error: unknown) => error);
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    fixture.admission.invalidate();
    expect((await projectStatsService.getStats('project-1')).memory_count).toBe(99);
    old.resolve(projectStatsPayload);
    expect(await stale).toMatchObject({ name: 'AbortError' });
    expect((await projectStatsService.getStats('project-1')).memory_count).toBe(99);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('expires successful entries after the original ten-second TTL', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1000);
    try {
      await projectStatsService.getStats('project-1');
      now.mockReturnValue(11001);
      await projectStatsService.getStats('project-1');
      expect(request).toHaveBeenCalledTimes(2);
    } finally {
      now.mockRestore();
    }
  });
});
