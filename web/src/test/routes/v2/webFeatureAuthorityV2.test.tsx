import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
  type RuntimeGenerationV2,
} from '@agistack/plugin-runtime';
import {
  WebRouteAuthorityContextV2,
  projectWebRouteAuthorityV2,
} from '../../../routes/v2/webRouteAuthorityStateV2';
import { useWebFeatureEnabledV2 } from '../../../routes/v2/webFeatureAuthorityV2';
import '../../../routes/v2/webFeatureCompositionV2';
import { validateWebRendererContributionsV2 } from '../../../routes/v2/webRendererArtifactCatalogV2';
import bootstrap from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';
import type { ReactNode } from 'react';

let current: RuntimeGenerationV2 | undefined;
vi.mock('../../../plugins/WebPluginGenerationHostV2', () => ({
  useCurrentWebPluginGenerationV2: () => current,
}));

describe('Web feature UI authority', () => {
  it('ties command and settings consumers to their exact active feature contribution', async () => {
    const runtime = new RendererPluginRuntimeV2(
      'web',
      createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
    );
    await runtime.bootstrap(bootstrap);
    current = runtime.getSnapshot();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <WebRouteAuthorityContextV2.Provider value={projectWebRouteAuthorityV2(current!)}>
        {children}
      </WebRouteAuthorityContextV2.Provider>
    );
    const { result, rerender, unmount } = renderHook(
      () => ({
        graph: useWebFeatureEnabledV2('project-graph', 'settings-page'),
        skills: useWebFeatureEnabledV2('tenant-skills', 'command'),
        skillsPage: useWebFeatureEnabledV2('tenant-skills'),
      }),
      { wrapper }
    );
    expect(result.current).toEqual({ graph: true, skills: true, skillsPage: true });
    const snapshot = structuredClone(bootstrap);
    snapshot.entries.find(
      ({ entry_id }) => entry_id === 'builtin-web-feature-project-graph'
    )!.enabled = false;
    const skill = snapshot.entries.find(
      ({ entry_id }) => entry_id === 'builtin-web-feature-tenant-skills'
    )!;
    skill.config.contributions = skill.config.contributions.filter(
      (contribution: { kind: string }) => contribution.kind !== 'command'
    );
    snapshot.generation += 1;
    const { digest: _digest, ...unsigned } = snapshot;
    snapshot.digest = await digestV2(unsigned);
    await runtime.replaceBaseline(snapshot);
    current = runtime.getSnapshot();
    rerender();
    expect(result.current).toEqual({ graph: false, skills: false, skillsPage: true });
    unmount();
    await runtime.close();
    current = undefined;
  });

  it('keeps core features available without enabling an unknown plugin feature', () => {
    current = undefined;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <WebRouteAuthorityContextV2.Provider
        value={{
          routeArtifacts: [],
          routeArtifactIds: ['web.routes.default-business.v1'],
          routeKeys: [],
          status: 'ready',
        }}
      >
        {children}
      </WebRouteAuthorityContextV2.Provider>
    );
    const { result } = renderHook(
      () => ({
        core: useWebFeatureEnabledV2('tenant-skills'),
        plugin: useWebFeatureEnabledV2('optional-business-sample'),
      }),
      { wrapper }
    );
    expect(result.current).toEqual({ core: true, plugin: false });
  });
});
