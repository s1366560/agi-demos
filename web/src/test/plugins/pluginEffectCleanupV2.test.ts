import { describe, expect, it, vi } from 'vitest';

import { EffectStackV2 } from '../../../../agi-stack/packages/plugin-runtime/src/context';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('EffectStackV2 cleanup ownership', () => {
  it('drains every effect in reverse order and repeats the same original failures', async () => {
    const stack = new EffectStackV2(() => 'active');
    const calls: string[] = [];
    const firstError = new Error('first cleanup');
    const thirdError = { detail: 'third cleanup' };
    stack.add(() => {
      calls.push('first');
      throw firstError;
    }, 'first');
    stack.add(() => {
      calls.push('second');
    }, 'second');
    stack.add(async () => {
      calls.push('third');
      throw thirdError;
    }, 'third');

    const disposal = stack.dispose();
    const failure = await disposal.catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(AggregateError);
    expect((failure as AggregateError).errors).toEqual([thirdError, firstError]);
    expect((failure as AggregateError).errors[0]).toBe(thirdError);
    expect((failure as AggregateError).errors[1]).toBe(firstError);
    expect(calls).toEqual(['third', 'second', 'first']);
    expect(stack.records[0]?.error).toBe('Error: first cleanup');
    expect(stack.records[2]?.error).toBe('[object Object]');
    expect(stack.dispose()).toBe(disposal);
    await expect(stack.dispose()).rejects.toBe(failure);
    expect(calls).toHaveLength(3);
  });

  it('waits for an individually started cleanup before draining earlier effects', async () => {
    const stack = new EffectStackV2(() => 'active');
    const blocked = deferred();
    const entered = deferred();
    const earlier = vi.fn();
    const original = new Error('blocked cleanup failed');
    stack.add(earlier, 'earlier');
    const cleanup = vi.fn(async () => {
      entered.resolve();
      await blocked.promise;
      throw original;
    });
    const manual = stack.add(cleanup, 'blocked');
    const first = manual();
    const firstOutcome = Promise.resolve(first).catch((error: unknown) => error);
    await entered.promise;
    expect(manual()).toBe(first);
    const drain = stack.dispose();
    const drainOutcome = drain.catch((error: unknown) => error);
    let settled = false;
    void drainOutcome.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    expect(earlier).not.toHaveBeenCalled();
    blocked.resolve();
    expect(await firstOutcome).toBe(original);
    const failure = await drainOutcome;
    expect((failure as AggregateError).errors[0]).toBe(original);
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(earlier).toHaveBeenCalledTimes(1);
    await expect(manual()).rejects.toBe(original);
    await expect(stack.dispose()).rejects.toBe(failure);
  });

  it('shares concurrent successful drains and closes effect registration immediately', async () => {
    const stack = new EffectStackV2(() => 'loading');
    const blocked = deferred();
    const cleanup = vi.fn(() => blocked.promise);
    stack.add(cleanup, 'blocked');
    const first = stack.dispose();
    expect(stack.dispose()).toBe(first);
    expect(() => stack.add(() => {}, 'late')).toThrow('inactive context');
    blocked.resolve();
    await first;
    await stack.dispose();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('preserves a thrown value even if diagnostic string conversion itself fails', async () => {
    const stack = new EffectStackV2(() => 'active');
    const error = {
      toString() {
        throw new Error('bad diagnostic');
      },
    };
    const manual = stack.add(() => {
      throw error;
    }, 'unprintable');
    await expect(manual()).rejects.toBe(error);
    const failure = await stack.dispose().catch((value: unknown) => value);
    expect((failure as AggregateError).errors[0]).toBe(error);
    expect(stack.records[0]?.error).toBe('effect cleanup failed');
  });
});
