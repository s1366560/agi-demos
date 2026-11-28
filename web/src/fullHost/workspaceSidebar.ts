import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import type { SidebarData } from '../components/layout/TenantSidebarView';
import type { LinkItem } from './navigation';
import { ownerFor } from './sidebarSlots';
import { useSidebarSlot } from './useSidebarSlot';

type Surface = Pick<SidebarData, 'workspaces' | 'currentWorkspace' | 'workspaceTasks'>;
const empty: Surface = { workspaces: [], currentWorkspace: null, workspaceTasks: [] };

export function useWorkspaceSidebar(
  tenant: string,
  project: string | null,
  items: LinkItem[],
  transport: MarketplaceTransport
) {
  const owner = ownerFor(items, project, 'groups');
  const command = useSidebarSlot(tenant, project, owner, transport);
  const detailRequest = useRef(0);
  const [snapshot, setSnapshot] = useState<{ owner: typeof command; data: Surface } | null>(null);
  const surface = snapshot?.owner === command ? snapshot.data : empty;
  const publish = useCallback(
    (patch: Partial<Surface>) =>
      setSnapshot((previous) => ({
        owner: command,
        data: { ...(previous?.owner === command ? previous.data : empty), ...patch },
      })),
    [command]
  );
  const list = useCallback(
    async (slot: 'groups' | 'children', id?: string, signal?: AbortSignal) => {
      const items: { id: string; name: string }[] = [];
      for (let offset = 0; ; offset += 100) {
        const { rows, count } = await command(slot, { id, offset, limit: 100 }, signal);
        for (const row of rows)
          if (typeof row.id === 'string' && typeof row.label === 'string')
            items.push({ id: row.id, name: row.label });
        if (
          count < 100 ||
          !owner?.sidebar?.[slot]?.inputs ||
          !Object.values(owner.sidebar[slot].inputs).includes('offset')
        )
          return items;
      }
    },
    [command, owner]
  );
  useEffect(() => {
    const controller = new AbortController();
    if (owner)
      void list('groups', undefined, controller.signal)
        .then((workspaces) => {
          if (!controller.signal.aborted) publish({ workspaces });
        })
        .catch(() => {});
    return () => controller.abort();
  }, [list, owner, publish]);
  const loadWorkspaceSurface = useCallback(
    async (tenantId: string, projectId: string, id: string) => {
      if (!owner?.sidebar?.group || tenantId !== tenant || projectId !== project) return;
      const seq = ++detailRequest.current;
      const [detail, children] = await Promise.all([
        command('group', { id }),
        owner.sidebar.children ? list('children', id) : [],
      ]);
      const row = detail.rows[0];
      if (row?.id !== id || typeof row.label !== 'string')
        throw new Error('invalid_sidebar_result');
      if (seq === detailRequest.current)
        publish({
          currentWorkspace: { id, name: row.label },
          workspaceTasks: children.map((child) => ({
            id: child.id,
            title: child.name,
            workspace_id: id,
          })),
        });
    },
    [owner, tenant, project, command, list, publish]
  );
  return useMemo(() => ({ ...surface, loadWorkspaceSurface }), [surface, loadWorkspaceSurface]);
}
