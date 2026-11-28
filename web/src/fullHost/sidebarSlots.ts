import { generatePath, matchPath, createPath } from 'react-router-dom';
import type { SidebarSlot } from '../../../agi-stack/packages/plugin-slots/src/sidebar';
import { routeRank } from '../../../agi-stack/packages/plugin-slots/src/richPage';
import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';
export { invokeSlot } from '../../../agi-stack/packages/plugin-marketplace-ui/src/invokeSidebarSlot';
import type { LinkItem } from './navigation';

export type SlotOwner = LinkItem & { plugin: string; digest: string };
export function ownerFor(
  items: readonly LinkItem[],
  project: string | null,
  slot: SidebarSlot,
  path?: string
) {
  const eligible = items.filter(
    (item): item is SlotOwner =>
      !!item.plugin &&
      !!item.digest &&
      !!project &&
      item.projectId === project &&
      !!item.sidebar?.[slot] &&
      !!item.commands?.includes(item.sidebar[slot].command)
  );
  return (
    (path && eligible.find((item) => item.routes?.some((route) => matchPath(route, path)))) ||
    eligible[0]
  );
}

export function rowNavigation(
  owner: SlotOwner | undefined,
  tenant: string,
  project: string | null
) {
  const binding = owner?.sidebar?.rows;
  const link = (id?: string, group?: string | null) => {
    const route = id ? binding?.row_route : binding?.route;
    if (!owner || !project || !route || !owner.routes?.includes(route)) return null;
    const path = generatePath(route, {
      tenantId: tenant,
      projectId: project,
      ...(id && binding?.row_param ? { [binding.row_param]: id } : {}),
    });
    if (routeRank(route, path, { tenantId: tenant, projectId: project }) === null) return null;
    const query = new URLSearchParams();
    if (group && binding?.group_query) query.set(binding.group_query, group);
    return createPath(
      scopedPageLocation(path + '?' + query, {
        tenant,
        project,
        projectId: project,
        businessPackage: owner.plugin,
      })
    );
  };
  const match = (path: string) => {
    // Before project selection, the shell still needs to resolve its bookmarked workspace.
    if (!owner) return null;
    const result = owner.routes?.map((route) => matchPath(route, path)).find(Boolean);
    return {
      active: !!result,
      id: binding?.row_param ? (result?.params[binding.row_param] ?? null) : null,
    };
  };
  return { link, match, groupQuery: binding?.group_query };
}
