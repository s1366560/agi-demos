import { splitPageLocation } from '../../plugin-slots/src/pageLocation';
import { routeRank, type PageScope, type PageTarget } from '../../plugin-slots/src/richPage';
import type { Installation } from './pluginMarketTypes';

export function installationDestination(
  bookmark: string | null,
  scope: PageScope,
  installed: Installation,
  target: PageTarget
) {
  if (!bookmark || !installed.actual_digest) return null;
  const { pathname, search } = splitPageLocation(bookmark);
  const query = new URLSearchParams(search);
  for (const [key, expected] of [
    ['tenant', scope.tenantId],
    ['project', scope.projectId],
    ['businessPackage', installed.plugin_id],
  ] as const) {
    if (query.getAll(key).some((value) => value !== expected)) return null;
  }
  return installed.pages?.some(
    (page) =>
      page.targets.includes(target) &&
      page.routes.some((route) => routeRank(route, pathname, scope) !== null)
  )
    ? bookmark
    : null;
}
