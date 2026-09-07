import { describe, expect, it } from 'vitest';

import { LoaderV2, webRendererDefinitionsV2, type ContextV2 } from '@agistack/plugin-runtime';

import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('real Loader effect setup ownership', () => {
  it('drains partial asynchronous setup and preserves the original activation failure', async () => {
    const failure = new Error('partial setup failed');
    const disposed: string[] = [];
    const definitions = webRendererDefinitionsV2.map((definition, index) => ({
      ...definition,
      async apply(context: ContextV2, config: Readonly<Record<string, unknown>>) {
        const result = await definition.apply(context, config);
        if (index === 0) {
          await context.effect(async function* () {
            yield () => {
              disposed.push('first');
            };
            yield () => {
              disposed.push('second');
            };
            throw failure;
          }, 'partial-setup');
        }
        return result;
      },
    }));
    await expect(new LoaderV2(definitions, 'web').stage(bootstrapProfile)).rejects.toBe(failure);
    expect(disposed).toEqual(['second', 'first']);
  });

  it('keeps actual generation disposal pending through a synchronously reentrant setup close', async () => {
    let hostContext: ContextV2 | undefined;
    const definitions = webRendererDefinitionsV2.map((definition, index) => ({
      ...definition,
      async apply(context: ContextV2, config: Readonly<Record<string, unknown>>) {
        if (index === 0) hostContext = context;
        return definition.apply(context, config);
      },
    }));
    const generation = await new LoaderV2(definitions, 'web').stage(bootstrapProfile);
    const resume = deferred();
    const disposed: string[] = [];
    let closing: Promise<void> | undefined;
    let settled = false;
    const setup = hostContext!.effect(async () => {
      closing = generation.dispose();
      void closing.then(() => {
        settled = true;
      });
      await resume.promise;
      return () => {
        disposed.push('late-resource');
      };
    }, 'reentrant-generation-close');
    expect(closing).toBeDefined();
    try {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
      expect(settled).toBe(false);
      expect(generation.disposed).toBe(false);
      expect(disposed).toEqual([]);
    } finally {
      resume.resolve();
      await Promise.allSettled([setup, closing]);
    }
    await expect(setup).resolves.toBeUndefined();
    await expect(closing).resolves.toBeUndefined();
    expect(generation.disposed).toBe(true);
    expect(disposed).toEqual(['late-resource']);
    await generation.dispose();
    expect(disposed).toHaveLength(1);
  });
});
