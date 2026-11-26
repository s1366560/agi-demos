import { describe, expect, it, vi } from 'vitest';
import { groupTenantTopNavItems } from '@/components/layout/tenantNavigation';
import {
  deriveTopNavigationItems,
  type DerivedNavigationItem,
  type NavigationRuntimeContext,
  type TopNavigationContext,
} from '@/config/navigation';
import { layoutHeaderItems, type LinkItem } from '@/fullHost/navigation';
import type { WebNavigationArtifactV2 } from '@/routes/v2/webRendererArtifactCatalogV2';

// The console shell pulls in the renderer generation host, which reads the feature
// list back from the composition module. Only route metadata is needed here.
vi.mock('@/routes/v2/webBusinessRouteGuardsV2', () => ({
  TenantConsoleShellV2: () => null,
  NewTenantRouteV2: () => null,
  LegacyAuditLogsRouteV2: () => null,
  LegacyProjectRouteV2: () => null,
}));

import { createWebFeatureArtifactsV2 } from '@/routes/v2/webFeatureCompositionV2';

const scope = (context: TopNavigationContext): NavigationRuntimeContext => ({
  tenantId: 't',
  ...(context === 'project' ? { projectId: 'p' } : {}),
});

/** The original workbench applies navigation features in identity order. */
function originalHeader(context: TopNavigationContext): readonly DerivedNavigationItem[] {
  return createWebFeatureArtifactsV2()
    .filter((artifact): artifact is WebNavigationArtifactV2 => artifact.kind === 'navigation')
    .flatMap((artifact) => artifact.createTopNavigationItems(context, scope(context)));
}

describe.each(['tenant', 'project'] as const)('%s workbench header order', (context) => {
  it('equals the header of the original workbench', () => {
    const expected = originalHeader(context);
    const installed: LinkItem[] = expected.map((item) => ({
      id: item.id,
      label: item.label,
      path: item.path,
      ...(context === 'project' ? { projectId: 'p' } : {}),
    }));

    const header = layoutHeaderItems(
      installed,
      deriveTopNavigationItems(context, scope(context)),
      context
    );
    const menus = (items: readonly DerivedNavigationItem[]) =>
      groupTenantTopNavItems(items).map((group) => [group.id, group.items.map((item) => item.id)]);

    expect(menus(header)).toEqual(menus(originalHeader(context)));
  });

  it('keeps the original group order when the leading sections are not installed', () => {
    const sections =
      context === 'tenant' ? ['users', 'plugins', 'billing'] : ['settings', 'blackboard', 'search'];
    const installed: LinkItem[] = sections.map((id) => ({
      id,
      label: id,
      path: originalHeader(context).find((item) => item.id === id)!.path,
      ...(context === 'project' ? { projectId: 'p' } : {}),
    }));

    const header = layoutHeaderItems(
      installed,
      deriveTopNavigationItems(context, scope(context)),
      context
    );
    const shown = groupTenantTopNavItems(header).map((group) => group.id);

    expect(shown).toEqual(
      groupTenantTopNavItems(originalHeader(context))
        .map((group) => group.id)
        .filter((id) => shown.includes(id))
    );
  });
});
