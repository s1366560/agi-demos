import { describe, expect, it, vi } from 'vitest';
import {
  ContextV2,
  EffectStackV2,
} from '../../../../agi-stack/packages/plugin-runtime/src/context';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function runtime() {
  const stack = new EffectStackV2(() => 'active');
  const context = new ContextV2(
    'owner',
    { kind: 'root' },
    [],
    [],
    stack,
    {
      services: { provides: [], requires: [] },
      events: { emits: [], handles: [] },
      config_schema: {},
    },
    new Map(),
    {},
    {}
  );
  return { stack, context };
}
async function flush() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
}

describe('pending effect setup ownership', () => {
  it('waits for pending setup and shares a drain reclaiming its disposer once', async () => {
    const { stack, context } = runtime();
    const resume = deferred();
    const cleanup = vi.fn();
    const acquiring = context.effect(async () => {
      await resume.promise;
      return cleanup;
    }, 'blocked');
    const outcome = acquiring.catch((error: unknown) => error);
    const closing = stack.dispose();
    let settled = false;
    void closing.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      }
    );
    try {
      expect(stack.dispose()).toBe(closing);
      await flush();
      expect(settled).toBe(false);
      expect(cleanup).not.toHaveBeenCalled();
    } finally {
      resume.resolve();
      await Promise.allSettled([outcome, closing]);
    }
    expect(await outcome).toBeUndefined();
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(stack.dispose()).toBe(closing);
    await closing;
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('drains interleaved setups by actual registration order', async () => {
    const { stack, context } = runtime();
    const first = deferred();
    const second = deferred();
    const calls: string[] = [];
    const one = context.effect(async () => {
      await first.promise;
      return () => {
        calls.push('first');
      };
    }, 'first');
    const two = context.effect(async () => {
      await second.promise;
      return () => {
        calls.push('second');
      };
    }, 'second');
    try {
      second.resolve();
      await two;
      first.resolve();
      await one;
      await stack.dispose();
      expect(calls).toEqual(['first', 'second']);
    } finally {
      first.resolve();
      second.resolve();
      await Promise.allSettled([one, two, stack.dispose()]);
    }
  });

  it('reclaims late async iterable yields even when iteration then rejects', async () => {
    const { stack, context } = runtime();
    const entered = deferred();
    const resume = deferred();
    const calls: string[] = [];
    const failure = new Error('late iteration failed');
    async function* resources() {
      yield () => {
        calls.push('first');
      };
      entered.resolve();
      await resume.promise;
      yield () => {
        calls.push('late');
      };
      throw failure;
    }
    const outcome = context.effect(resources, 'iterable').catch((error: unknown) => error);
    await entered.promise;
    const closing = stack.dispose();
    let settled = false;
    void closing.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      }
    );
    try {
      await flush();
      expect(settled).toBe(false);
    } finally {
      resume.resolve();
      await Promise.allSettled([outcome, closing]);
    }
    expect(await outcome).toBe(failure);
    await closing;
    expect(calls).toEqual(['late', 'first']);
    await stack.dispose();
    expect(calls).toEqual(['late', 'first']);
  });

  it('invokes setup synchronously and owns its result across reentrant close', async () => {
    const { stack, context } = runtime();
    const cleanup = vi.fn();
    let closing: Promise<void> | undefined;
    const setup = vi.fn(() => {
      closing = stack.dispose();
      return cleanup;
    });
    const outcome = context.effect(setup, 'reentrant').catch((error: unknown) => error);
    expect(setup).toHaveBeenCalledTimes(1);
    expect(closing).toBeDefined();
    await Promise.allSettled([outcome, closing]);
    expect(await outcome).toBeUndefined();
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(stack.dispose()).toBe(closing);
  });

  it('owns a synchronous result when close follows effect in the same call stack', async () => {
    const { stack, context } = runtime();
    const cleanup = vi.fn();
    const setup = vi.fn(() => cleanup);
    const outcome = context.effect(setup, 'synchronous').catch((error: unknown) => error);
    expect(setup).toHaveBeenCalledTimes(1);
    await stack.dispose();
    expect(await outcome).toBeUndefined();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('returns setup errors through effect while dispose reclaims partial resources', async () => {
    const { stack, context } = runtime();
    const cleanup = vi.fn();
    const failure = new Error('iteration failed');
    async function* resources() {
      yield cleanup;
      throw failure;
    }
    await expect(context.effect(resources, 'partial')).rejects.toBe(failure);
    await expect(stack.dispose()).resolves.toBeUndefined();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('never calls new setup after closing begins', async () => {
    const { stack, context } = runtime();
    const closing = stack.dispose();
    const setup = vi.fn();
    await expect(context.effect(setup, 'inactive')).rejects.toMatchObject({
      code: 'inactive_effect',
    });
    await closing;
    await expect(context.effect(setup, 'disposed')).rejects.toMatchObject({
      code: 'inactive_effect',
    });
    expect(setup).not.toHaveBeenCalled();
  });
});
