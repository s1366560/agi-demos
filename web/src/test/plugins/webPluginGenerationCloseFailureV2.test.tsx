import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

const { getDistribution, cleanupError, logError } = vi.hoisted(() => ({
  getDistribution: vi.fn(),
  cleanupError: new Error('real web generation cleanup failed'),
  logError: vi.fn(),
}));

vi.mock('../../services/client/kernelHttpClient', () => ({
  kernelHttpClient: { get: getDistribution },
}));
vi.mock('../../utils/logger', () => ({
  logger: { error: logError, warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));
vi.mock('@agistack/plugin-runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@agistack/plugin-runtime')>();
  return {
    ...actual,
    createWebRendererDefinitionsV2: (
      ...args: Parameters<typeof actual.createWebRendererDefinitionsV2>
    ) =>
      actual.createWebRendererDefinitionsV2(...args).map((definition) => ({
        ...definition,
        async apply(
          context: Parameters<typeof definition.apply>[0],
          config: Parameters<typeof definition.apply>[1]
        ) {
          await context.effect(
            () => () => {
              throw cleanupError;
            },
            'close-failure-regression'
          );
          return definition.apply(context, config);
        },
      })),
  };
});

import {
  RendererGenerationStatusStoreV2,
  webRendererDefinitionsV2,
  digestV2,
} from '@agistack/plugin-runtime';
import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
  useWebPluginGenerationV2,
} from '../../plugins/webPluginGenerationV2';
import { useAuthStore } from '../../stores/auth';
import bootstrapProfile from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function containsError(value: unknown): boolean {
  return (
    value === cleanupError || (value instanceof AggregateError && value.errors.some(containsError))
  );
}

it('observes scheduled real generation cleanup failure and records it in the status store', async () => {
  useAuthStore.setState({ isAuthenticated: true, token: 'close-owner' });
  const refs = new Set(webRendererDefinitionsV2.map((definition) => definition.moduleRef));
  const snapshot = structuredClone(bootstrapProfile);
  snapshot.profile_id = 'web-public-view-v2';
  snapshot.entries = snapshot.entries.filter((entry) => refs.has(entry.module_ref));
  snapshot.manifests = snapshot.manifests
    .map((manifest) => ({
      ...manifest,
      modules: manifest.modules.filter((module) => refs.has(module.module_ref)),
    }))
    .filter((manifest) => manifest.modules.length);
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
  getDistribution.mockResolvedValue({
    schema_version: 2,
    target: 'web',
    view_id: 'close-public',
    snapshot,
  });
  const fail = vi.spyOn(RendererGenerationStatusStoreV2.prototype, 'fail');
  activateWebPluginGenerationRootV2();
  const rendered = renderHook(({ enabled }) => useWebPluginGenerationV2(enabled), {
    initialProps: { enabled: true },
  });
  try {
    await waitFor(() => expect(rendered.result.current.status).toBe('ready'));
    rendered.unmount();
    await act(async () => {
      await deactivateWebPluginGenerationRootV2();
    });
    await waitFor(() =>
      expect(
        fail.mock.calls.some(
          ([error, hasGeneration]) => containsError(error) && hasGeneration === false
        )
      ).toBe(true)
    );
    expect(
      logError.mock.calls.some(
        ([message, error]) =>
          message === 'Failed to close plugin generation' && containsError(error)
      )
    ).toBe(true);
  } finally {
    rendered.unmount();
    fail.mockRestore();
  }
});
