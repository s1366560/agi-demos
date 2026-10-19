import { useEffect } from 'react';

import { render, screen } from '@testing-library/react';
import {
  createRoutesFromElements,
  matchRoutes,
  MemoryRouter,
  Outlet,
  Routes,
} from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const mounted = vi.hoisted(() => ({ shell: 0, skills: 0 }));

vi.mock('../../../routes/v2/webBusinessRouteGuardsV2', () => ({
  TenantConsoleShellV2: () => {
    useEffect(() => {
      mounted.shell += 1;
    }, []);
    return <Outlet />;
  },
  NewTenantRouteV2: () => null,
  LegacyAuditLogsRouteV2: () => null,
  LegacyProjectRouteV2: () => null,
}));

vi.mock('../../../routes/v2/webDefaultRouteComponentsV2', async (original) => ({
  ...(await original<typeof import('../../../routes/v2/webDefaultRouteComponentsV2')>()),
  SkillList: () => {
    useEffect(() => {
      mounted.skills += 1;
    }, []);
    return <div>skills-page</div>;
  },
}));

import {
  composeWebRouteArtifactsV2,
  createWebFeatureArtifactsV2,
  WEB_FEATURE_IDS_V2,
  WEB_CORE_ROUTE_ARTIFACT_ID_V2,
  webFeatureRouteArtifactIdV2,
  webFeatureNavigationArtifactIdV2,
} from '../../../routes/v2/webFeatureCompositionV2';
import {
  resolveWebRendererArtifactsV2,
  type WebRouteArtifactV2,
} from '../../../routes/v2/webRendererArtifactCatalogV2';

function routesWithout(...disabled: string[]): WebRouteArtifactV2[] {
  return createWebFeatureArtifactsV2().filter(
    (artifact): artifact is WebRouteArtifactV2 =>
      artifact.kind === 'route' && !disabled.includes(artifact.featureId ?? '')
  );
}

describe('Web feature composition', () => {
  it('owns every original business route exactly once across core and feature artifacts', () => {
    const granular = routesWithout();
    const [legacy] = resolveWebRendererArtifactsV2([
      {
        id: 'legacy',
        kind: 'route',
        order: 0,
        sourceEntryId: 'legacy',
        payload: { schema_version: 1, artifact_refs: ['web.routes.default-business.v1'] },
      },
    ]);
    if (legacy?.kind !== 'route') throw new Error('Missing default artifact');
    const keys = granular.flatMap((artifact) => artifact.routeKeys);
    expect(new Set(keys).size).toBe(keys.length);
    expect([...keys].sort()).toEqual([...legacy.routeKeys].sort());
    expect(WEB_FEATURE_IDS_V2).toContain('tenant-skills');
    expect(WEB_FEATURE_IDS_V2).toContain('project-graph');
    expect(granular.some(({ id }) => id === WEB_CORE_ROUTE_ARTIFACT_ID_V2)).toBe(true);
  });

  it('removes only the disabled feature and keeps its direct and legacy URLs unavailable', () => {
    const routes = createRoutesFromElements(
      composeWebRouteArtifactsV2(routesWithout('tenant-skills'))
    );
    for (const url of [
      '/tenant/t/skills',
      '/tenant/t/skills/s',
      '/tenant/skills',
      '/tenant/skills/s',
    ]) {
      const leaf = matchRoutes(routes, url)?.at(-1)?.route;
      expect(leaf?.handle?.pluginFeature).toBe('tenant-skills');
      expect((leaf?.element as { type?: { name?: string } })?.type?.name).toBe(
        'WebFeatureUnavailableV2'
      );
    }
    expect(
      matchRoutes(routes, '/tenant/t/project/p/graph')?.at(-1)?.route.handle?.pluginFeature
    ).toBe('project-graph');
  });

  it('keeps page and layout instances mounted when an unrelated feature changes', async () => {
    mounted.skills = mounted.shell = 0;
    const view = (disabled: string[]) => (
      <MemoryRouter initialEntries={['/tenant/t/skills']}>
        <Routes>{composeWebRouteArtifactsV2(routesWithout(...disabled))}</Routes>
      </MemoryRouter>
    );
    const { rerender } = render(view([]));
    await screen.findByText('skills-page');
    rerender(view(['project-graph']));
    expect(screen.getByText('skills-page')).toBeVisible();
    expect(mounted).toEqual({ shell: 1, skills: 1 });
    rerender(view(['project-graph', 'tenant-skills']));
    expect(screen.queryByText('skills-page')).not.toBeInTheDocument();
    expect(screen.getByTestId('plugin-feature-unavailable')).toBeVisible();
    expect(mounted.shell).toBe(1);
  });

  it('resolves independently contributed routes and navigation without overlapping authority', () => {
    const artifacts = resolveWebRendererArtifactsV2(
      WEB_FEATURE_IDS_V2.flatMap((feature, index) => [
        {
          id: `${feature}:route`,
          kind: 'route' as const,
          order: index,
          sourceEntryId: feature,
          payload: { schema_version: 1, artifact_refs: [webFeatureRouteArtifactIdV2(feature)] },
        },
        {
          id: `${feature}:nav`,
          kind: 'navigation' as const,
          order: index,
          sourceEntryId: feature,
          payload: {
            schema_version: 1,
            artifact_refs: [webFeatureNavigationArtifactIdV2(feature)],
          },
        },
      ])
    );
    const skillNavigation = artifacts.find(
      ({ id }) => id === webFeatureNavigationArtifactIdV2('tenant-skills')
    );
    if (skillNavigation?.kind !== 'navigation') throw new Error('Missing skills navigation');
    expect(
      skillNavigation.createTopNavigationItems('tenant', { tenantId: 't' }).map(({ id }) => id)
    ).toEqual(['skills']);
  });

  it('assigns fixed navigation URLs to one owner despite legacy conversation parameters', () => {
    const navigation = createWebFeatureArtifactsV2().flatMap((artifact) =>
      artifact.kind === 'navigation'
        ? artifact.createTopNavigationItems('tenant', { tenantId: 't' })
        : []
    );
    const ids = navigation.map(({ id }) => id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(
      expect.arrayContaining([
        'acp',
        'mcp-servers',
        'plugins',
        'providers',
        'templates',
        'webhooks',
      ])
    );
  });
});
