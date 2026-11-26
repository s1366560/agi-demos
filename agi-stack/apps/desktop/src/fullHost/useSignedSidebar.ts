import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { invokeSlot } from '../../../../packages/plugin-marketplace-ui/src/invokeSidebarSlot';
import { useI18n } from '../i18n';
import { transport } from '../packageHost/transport';
import type { RuntimeNodeLoadState } from '../types';
import type { InstalledPage } from './pages';
import { installedWorkbenchLinks } from './workbenchModel';
import {
  activeConversationId,
  activeWorkspaceId,
  buildSidebarTree,
  chatDeepLink,
  findSidebarOwner,
  linkForAction,
  readConversationSources,
  readGroupSources,
  settledWorkspaceNodes,
  workspacePagePath,
  type ConversationSource,
  type ExecutionTargetFilter,
} from './signedSidebarModel';

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function collect(
  page: InstalledPage,
  tenant: string,
  project: string,
  slot: 'rows' | 'groups',
  signal: AbortSignal,
): Promise<Record<string, unknown>[]> {
  const binding = page.page.sidebar?.[slot];
  const owner = {
    plugin: page.pluginId,
    digest: page.digest,
    projectId: project,
    commands: page.commands,
    sidebar: page.page.sidebar,
  };
  const rows: Record<string, unknown>[] = [];
  for (let offset = 0; ; offset += 100) {
    const result = await invokeSlot(transport, tenant, project, owner, slot, { offset, limit: 100 }, signal);
    rows.push(...result.rows);
    const acceptsOffset = Object.values(binding?.inputs ?? {}).includes('offset');
    if (!acceptsOffset || result.count < 100 || offset >= 5000) return rows;
  }
}

export function useSignedSidebar(tenant: string, project: string | null, entries: readonly InstalledPage[], address: string) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<ExecutionTargetFilter>('all');
  const [sources, setSources] = useState<ConversationSource[]>([]);
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState<Set<string>>(() => new Set());
  const knownWorkspaces = useRef(new Set<string>());
  const hasData = useRef(false);
  const lifetime = useRef<AbortController | null>(null);
  const rowsOwner = findSidebarOwner(entries, tenant, project, 'rows', address);
  const groupsOwner = findSidebarOwner(entries, tenant, project, 'groups', address);
  const loadKey = JSON.stringify([
    tenant,
    project,
    rowsOwner?.pluginId,
    rowsOwner?.digest,
    groupsOwner?.pluginId,
    groupsOwner?.digest,
    revision,
  ]);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    knownWorkspaces.current = new Set();
    hasData.current = false;
    setExpandedWorkspaceIds(new Set());
  }, [project]);

  useEffect(() => {
    const controller = new AbortController();
    const rowsPage = rowsOwner;
    const groupsPage = groupsOwner;
    if (!project || (!rowsPage && !groupsPage)) {
      setSources([]);
      setGroups([]);
      setLoading(false);
      setError('');
      return () => controller.abort();
    }
    if (!hasData.current) setLoading(true);
    void (async () => {
      const [listed, directories] = await Promise.allSettled([
        rowsPage ? collect(rowsPage, tenant, project, 'rows', controller.signal) : [],
        groupsPage ? collect(groupsPage, tenant, project, 'groups', controller.signal) : [],
      ]);
      if (controller.signal.aborted) return;
      const failure = [listed, directories].find((result) => result.status === 'rejected');
      if (listed.status === 'fulfilled') setSources(readConversationSources(listed.value));
      if (directories.status === 'fulfilled') setGroups(readGroupSources(directories.value));
      if (listed.status === 'fulfilled' || directories.status === 'fulfilled') hasData.current = true;
      else if (!hasData.current) {
        setSources([]);
        setGroups([]);
      }
      setError(failure && failure.status === 'rejected' ? message(failure.reason) : '');
      setLoading(false);
    })();
    return () => controller.abort();
  }, [loadKey, groupsOwner, project, rowsOwner, tenant]);

  const reload = useCallback(() => setRevision((current) => current + 1), []);
  useEffect(() => {
    const onFocus = () => {
      if (!document.hidden) reload();
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [reload]);

  const tree = useMemo(
    () => buildSidebarTree(sources, groups, filter, tenant, project ?? ''),
    [sources, groups, filter, tenant, project],
  );
  useEffect(() => {
    setExpandedWorkspaceIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const workspace of tree.workspaces) {
        if (knownWorkspaces.current.has(workspace.id)) continue;
        knownWorkspaces.current.add(workspace.id);
        next.add(workspace.id);
        changed = true;
      }
      return changed ? next : current;
    });
  }, [tree.workspaces]);

  const conversationId = activeConversationId(rowsOwner, address);
  const conversation = sources.find((source) => source.id === conversationId) ?? null;
  const currentWorkspaceId = activeWorkspaceId(
    rowsOwner,
    entries,
    address,
    conversation?.workspaceId ?? null,
  );
  const links = useMemo(() => installedWorkbenchLinks(entries, tenant), [entries, tenant]);
  const canCall = (slot: 'create' | 'rename' | 'delete') => {
    const binding = rowsOwner?.page.sidebar?.[slot];
    return !!rowsOwner && !!project && !!binding && rowsOwner.commands.includes(binding.command);
  };

  async function mutate(slot: 'create' | 'rename' | 'delete', values: Record<string, unknown>) {
    const page = rowsOwner;
    const signal = lifetime.current?.signal;
    if (!page || !project || !signal) throw new Error('page_scope_expired');
    const result = await invokeSlot(
      transport,
      tenant,
      project,
      {
        plugin: page.pluginId,
        digest: page.digest,
        projectId: project,
        commands: page.commands,
        sidebar: page.page.sidebar,
      },
      slot,
      values,
      signal,
    );
    reload();
    return result;
  }

  const nodeState: RuntimeNodeLoadState = {
    projects: project ? { [project]: { loading, error: error || null } } : {},
    workspaces: settledWorkspaceNodes(
      tree.workspaces.map((workspace) => workspace.id),
      { loading, error },
    ),
  };

  return {
    workspaces: tree.workspaces,
    conversationsByWorkspace: tree.conversationsByWorkspace,
    nodeState,
    currentWorkspaceId,
    currentConversationId: conversationId,
    selectionMode: conversationId
      ? ('conversation' as const)
      : currentWorkspaceId
        ? ('overview' as const)
        : ('none' as const),
    filter,
    setFilter,
    expandedWorkspaceIds,
    toggleWorkspace(id: string) {
      setExpandedWorkspaceIds((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    reload,
    canRename: canCall('rename'),
    canCreate: canCall('create'),
    createWorkspacePath: linkForAction(entries, links, tenant, 'group-create'),
    openChatPath: linkForAction(entries, links, tenant, 'primary-create'),
    workspacePath(workspaceId: string) {
      if (!project) return null;
      return (
        workspacePagePath(entries, tenant, project, workspaceId) ??
        chatDeepLink(rowsOwner, tenant, project, null, workspaceId)
      );
    },
    conversationPath(id: string, workspaceId: string) {
      if (!project || !rowsOwner) return null;
      return chatDeepLink(rowsOwner, tenant, project, id, workspaceId || null);
    },
    async create() {
      try {
        const result = await mutate('create', {
          label: t('overview.newTask'),
          ...(currentWorkspaceId ? { group: currentWorkspaceId } : {}),
        });
        const created = result.rows[0];
        const id = created && typeof created.id === 'string' ? created.id : null;
        if (!id || !project) throw new Error('invalid_sidebar_result');
        return chatDeepLink(rowsOwner, tenant, project, id, currentWorkspaceId || null);
      } catch (cause) {
        setError(message(cause));
        throw cause;
      }
    },
    async rename(id: string, title: string) {
      await mutate('rename', { id, label: title });
    },
    palette: sources.map((source) => ({
      id: `conversation:${source.id}`,
      label: source.title,
      groupLabel: source.workspaceName || t('workspaceTree.tasks'),
      path:
        project && rowsOwner
          ? chatDeepLink(rowsOwner, tenant, project, source.id, source.workspaceId) ?? ''
          : '',
    })),
  };
}
