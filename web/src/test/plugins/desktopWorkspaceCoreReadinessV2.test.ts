import { afterEach, describe, expect, it, vi } from 'vitest';
import { waitForDesktopWorkspaceCoreReadyV2 } from '../../../../agi-stack/apps/desktop/src/hooks/desktopWorkspaceCoreReadinessV2';
const running = { state: 'running', cutoverState: 'core-authoritative' };
describe('Workspace Core readiness', () => {
  afterEach(() => vi.useRealTimers());
  it('waits through starting and restartScheduled before business admission', async () => {
    vi.useFakeTimers();
    const readStatus = vi
      .fn()
      .mockResolvedValueOnce({ state: 'starting' })
      .mockResolvedValueOnce({ state: 'restartScheduled' })
      .mockResolvedValueOnce(running);
    const business = vi.fn();
    const wait = waitForDesktopWorkspaceCoreReadyV2({ readStatus, isCurrent: () => true }).then(
      (ready) => {
        if (ready) business();
      }
    );
    await vi.advanceTimersByTimeAsync(499);
    expect(business).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await wait;
    expect(readStatus).toHaveBeenCalledTimes(3);
    expect(business).toHaveBeenCalledTimes(1);
  });
  it.each(['failed', 'stopped'])('rejects terminal %s', async (state) => {
    const readStatus = vi.fn().mockResolvedValue({ state });
    await expect(
      waitForDesktopWorkspaceCoreReadyV2({ readStatus, isCurrent: () => true })
    ).rejects.toThrow(`workspace_core_${state}`);
    expect(readStatus).toHaveBeenCalledTimes(1);
  });
  it.each([null, [], {}, { state: 'unknown' }, { state: 'running', cutoverState: 'importing' }])(
    'rejects invalid protocol %j',
    async (status) => {
      await expect(
        waitForDesktopWorkspaceCoreReadyV2({
          readStatus: async () => status,
          isCurrent: () => true,
        })
      ).rejects.toThrow('workspace_core_status_invalid');
    }
  );
  it('does not poll already retired contexts', async () => {
    const readStatus = vi.fn();
    expect(await waitForDesktopWorkspaceCoreReadyV2({ readStatus, isCurrent: () => false })).toBe(
      false
    );
    expect(readStatus).not.toHaveBeenCalled();
  });
  it('stops waiting when admission or the captured context is retired', async () => {
    vi.useFakeTimers();
    let current = true;
    const readStatus = vi.fn().mockResolvedValue({ state: 'starting' });
    const wait = waitForDesktopWorkspaceCoreReadyV2({ readStatus, isCurrent: () => current });
    await vi.advanceTimersByTimeAsync(0);
    current = false;
    await vi.advanceTimersByTimeAsync(250);
    expect(await wait).toBe(false);
    expect(readStatus).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('discards a late running result after retirement', async () => {
    let current = true;
    let settle!: (value: unknown) => void;
    const wait = waitForDesktopWorkspaceCoreReadyV2({
      readStatus: () =>
        new Promise((resolve) => {
          settle = resolve;
        }),
      isCurrent: () => current,
    });
    current = false;
    settle(running);
    expect(await wait).toBe(false);
  });
  it('discards retired transport errors and preserves current errors', async () => {
    let current = true;
    let reject!: (error: unknown) => void;
    const error = new Error('transport failure');
    const wait = waitForDesktopWorkspaceCoreReadyV2({
      readStatus: () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
      isCurrent: () => current,
    });
    current = false;
    reject(error);
    expect(await wait).toBe(false);
    await expect(
      waitForDesktopWorkspaceCoreReadyV2({
        readStatus: async () => {
          throw error;
        },
        isCurrent: () => true,
      })
    ).rejects.toBe(error);
  });
});
