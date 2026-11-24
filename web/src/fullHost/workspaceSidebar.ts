import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  packageBase,
  packageScope,
} from '../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';
import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import type { SidebarData } from '../components/layout/TenantSidebarView';
import type { LinkItem } from './navigation';

type Surface = Pick<SidebarData, 'workspaces' | 'currentWorkspace' | 'workspaceTasks'>;
const empty: Surface = { workspaces: [], currentWorkspace: null, workspaceTasks: [] };

export function useWorkspaceSidebar(
  tenant: string,
  project: string | null,
  items: LinkItem[],
  transport: MarketplaceTransport
) {
  const release = items.find(
    (item) => item.plugin === 'memstack-workspace' && item.projectId === project
  );
  const digest = release?.digest;
  const canRead = release?.commands?.includes('read-workspace');
  const canList = release?.commands?.includes('list-directory');
  const canReadTasks = release?.commands?.includes('list-tasks');

  const scope = useRef<AbortController | null>(null);
  const detailRequest = useRef(0);
  const command = useCallback(
    (name: string, payload: Record<string, unknown>, signal: AbortSignal) => {
      if (!tenant || !project || !digest) throw new Error('page_scope_expired');
      return transport<Record<string, unknown>>(
        packageBase(project) + '/memstack-workspace/commands',
        {
          method: 'POST',
          signal,
          body: {
            ...packageScope(tenant, project),
            expected_digest: digest,
            command_id: name,
            payload,
          },
        }
      );
    },
    [tenant, project, digest, transport]
  );
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
  useEffect(() => {
    const controller = new AbortController();
    scope.current = controller;
    async function readDirectory() {
      const workspaces: Surface['workspaces'] = [];
      for (let offset = 0; !controller.signal.aborted; offset += 100) {
        const { rows } = await command(
          'list-directory',
          { offset, limit: 100, cards: true },
          controller.signal
        );
        if (!Array.isArray(rows)) throw new Error('invalid_workspace_directory');
        for (const row of rows) {
          if (
            row?.tenant_id === tenant &&
            row.project_id === project &&
            typeof row.id === 'string' &&
            typeof row.name === 'string' &&
            !row.is_archived
          )
            workspaces.push({ id: row.id, name: row.name });
        }
        if (rows.length < 100) break;
      }
      if (!controller.signal.aborted) publish({ workspaces });
    }
    if (canList) void readDirectory().catch(() => {});
    return () => controller.abort();
  }, [canList, command, tenant, project, publish]);
  const loadWorkspaceSurface = useCallback(
    async (owner: string, id: string, workspace: string) => {
      const signal = scope.current?.signal;
      if (!canRead || tenant !== owner || project !== id || !signal || signal.aborted) return;
      const request = ++detailRequest.current;
      const detail = await command('read-workspace', { workspace_id: workspace }, signal);
      if (detail.id !== workspace || typeof detail.name !== 'string')
        throw new Error('invalid_workspace_detail');
      const currentWorkspace = { id: workspace, name: detail.name };
      const workspaceTasks: Surface['workspaceTasks'] = [];
      if (canReadTasks)
        for (let offset = 0; !signal.aborted && request === detailRequest.current; offset += 100) {
          const { items: tasks } = await command(
            'list-tasks',
            { workspace_id: workspace, offset, limit: 100 },
            signal
          );
          if (!Array.isArray(tasks)) throw new Error('invalid_workspace_tasks');
          for (const task of tasks)
            if (
              task?.workspace_id === workspace &&
              typeof task.id === 'string' &&
              typeof task.title === 'string'
            )
              workspaceTasks.push({ id: task.id, workspace_id: workspace, title: task.title });
          if (tasks.length < 100) break;
        }
      if (!signal.aborted && request === detailRequest.current)
        publish({ currentWorkspace, workspaceTasks });
    },
    [canRead, canReadTasks, command, tenant, project, publish]
  );
  return useMemo(() => ({ ...surface, loadWorkspaceSurface }), [surface, loadWorkspaceSurface]);
}
