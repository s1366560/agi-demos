import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ownerFor, rowNavigation } from './sidebarSlots';
import { useSidebarSlot } from './useSidebarSlot';
import { useWorkspaceSidebar } from './workspaceSidebar';
import { useAuthStore } from '../stores/auth';
import { useWebPackageSession } from '../projectPackages/useWebPackageSession';
import { useFullNavigation } from './navigation';
import type { ExecutionTargetFilter } from '../components/execution-target/executionTargetModel';
import type { SidebarConversation, SidebarData } from '../components/layout/TenantSidebarView';
const Sidebar = createContext<SidebarData | null>(null);
// Where the rows a package returned end, when the package pages its rows.
interface RowTail {
  hasMore: boolean;
  cursor: string | null;
}
const NO_TAIL: RowTail = { hasMore: false, cursor: null };

function shown(target: ExecutionTargetFilter | undefined, row: SidebarConversation) {
  return !target || target === 'all' || target === row.execution_target;
}
export function useSignedSidebar() {
  const state = useContext(Sidebar);
  if (!state) throw new Error('Missing workbench sidebar');
  return state;
}

function row(value: unknown, project: string): SidebarConversation | null {
  if (
    typeof value !== 'object' ||
    !value ||
    !('id' in value) ||
    typeof value.id !== 'string' ||
    !('label' in value) ||
    typeof value.label !== 'string'
  )
    return null;
  return {
    id: value.id,
    title: value.label,
    project_id: project,
    // A derived conversation stays in the list, counted as the original workbench
    // counts it; the view leaves such rows out of what it shows.
    slot: {
      active: 'active' in value && value.active === true,
      hidden: 'hidden' in value && value.hidden === true,
      ...('role' in value && typeof value.role === 'string' ? { role: value.role } : {}),
    },
    ...('updatedAt' in value && typeof value.updatedAt === 'string'
      ? { updated_at: value.updatedAt }
      : {}),
    ...('createdAt' in value && typeof value.createdAt === 'string'
      ? { created_at: value.createdAt }
      : {}),
    ...('group' in value && typeof value.group === 'string' ? { workspace_id: value.group } : {}),
    ...('groupLabel' in value && typeof value.groupLabel === 'string'
      ? { workspace_name: value.groupLabel }
      : {}),
    ...('child' in value && typeof value.child === 'string'
      ? { linked_workspace_task_id: value.child }
      : {}),
    ...('target' in value && (value.target === 'cloud' || value.target === 'local')
      ? { execution_target: value.target }
      : {}),
  };
}

export function SignedSidebarProvider({ children }: { children: ReactNode }) {
  const { tenant, project, items } = useFullNavigation();
  const { t } = useTranslation();
  const token = useAuthStore((s) => s.token);
  const { transport } = useWebPackageSession(token);
  const workspace = useWorkspaceSidebar(tenant, project, items, transport);
  const [conversations, setConversations] = useState<SidebarConversation[]>([]);
  const [tail, setTail] = useState<RowTail>(NO_TAIL);
  const [busy, setBusy] = useState(false);
  const loadingMore = useRef(false);
  const loading = useRef(false);
  const target = useRef<ExecutionTargetFilter | undefined>(undefined);
  const [active, setActive] = useState<string | null>(null);
  const revision = useRef(0);
  const { pathname } = useLocation();
  const release = ownerFor(items, project, 'rows', pathname);
  const command = useSidebarSlot(tenant, project, release, transport);
  const activeScope = useRef<typeof command | null>(null);
  useLayoutEffect(() => {
    activeScope.current = command;
    return () => {
      activeScope.current = null;
    };
  }, [command]);
  const navigation = useMemo(
    () => rowNavigation(release, tenant, project),
    [release, tenant, project]
  );
  const reset = useCallback(() => {
    revision.current++;
    setConversations([]);
    setTail(NO_TAIL);
    setBusy(false);
  }, []);
  const load = useCallback<SidebarData['loadConversations']>(
    async (id, options) => {
      if (activeScope.current !== command) throw new Error('page_scope_expired');
      // Rows that are being read are not read again on the side.
      if (options?.silent && loading.current) return;
      const seq = ++revision.current;
      if (!release || project !== id) {
        setConversations([]);
        setTail(NO_TAIL);
        setBusy(false);
        return;
      }
      loading.current = true;
      if (!options?.silent) setBusy(true);
      try {
        const { rows, hasMore, cursor } = await command('rows', {}, options?.signal);
        if (seq !== revision.current || options?.signal?.aborted) return;
        const visible = (Array.isArray(rows) ? rows : [])
          .map((v) => row(v, id))
          .filter((v): v is SidebarConversation => v !== null);
        setConversations(visible.filter((v) => shown(options?.executionTarget, v)));
        target.current = options?.executionTarget;
        // Rows that cannot be found again are all there is.
        setTail({ hasMore: hasMore && !!cursor, cursor });
      } finally {
        loading.current = false;
        if (seq === revision.current && !options?.silent) setBusy(false);
      }
    },
    [command, project, release]
  );
  // A conversation the page opened by its address, as one it has just created, is
  // listed: the rows are read once more for it, without showing that they are read.
  const addressed = navigation.match(pathname)?.id;
  const listedFor = useRef<string | null>(null);
  useEffect(() => {
    if (
      !addressed ||
      !project ||
      loading.current ||
      listedFor.current === addressed ||
      conversations.some((row) => row.id === addressed)
    )
      return;
    listedFor.current = addressed;
    void load(project, { silent: true }).catch(() => {});
  }, [addressed, conversations, load, project]);
  const loadMore = useCallback<SidebarData['loadMoreConversations']>(
    async (id) => {
      if (activeScope.current !== command || id !== project) return;
      if (loadingMore.current || !tail.cursor) return;
      loadingMore.current = true;
      const seq = revision.current;
      try {
        const { rows, hasMore, cursor } = await command('rows', { cursor: tail.cursor });
        if (seq !== revision.current) return;
        const loaded = (Array.isArray(rows) ? rows : [])
          .map((v) => row(v, id))
          .filter((v): v is SidebarConversation => v !== null)
          .filter((v) => shown(target.current, v));
        setConversations((previous) => [
          ...previous,
          ...loaded.filter((v) => !previous.some((item) => item.id === v.id)),
        ]);
        setTail({ hasMore: hasMore && !!cursor, cursor });
      } finally {
        loadingMore.current = false;
      }
    },
    [command, project, tail]
  );
  useLayoutEffect(() => {
    reset();
    setActive(null);
    const controller = new AbortController();
    if (project && release) void load(project, { signal: controller.signal }).catch(() => {});
    return () => {
      revision.current++;
      controller.abort();
    };
  }, [tenant, project, release, load, reset]);
  const state = useMemo<SidebarData>(
    () => ({
      navigation,
      conversations,
      conversationsLoading: busy,
      activeConversationId: active,
      setActiveConversation: setActive,
      loadConversations: load,
      resetConversations: reset,
      hasMoreConversations: tail.hasMore,
      loadMoreConversations: loadMore,
      ...workspace,
      removeConversationLocal: (id) => {
        if (activeScope.current === command)
          setConversations((previous) => previous.filter((row) => row.id !== id));
      },
      restoreConversationLocal: (row) => {
        if (activeScope.current === command)
          setConversations((previous) =>
            previous.some((item) => item.id === row.id) ? previous : [row, ...previous]
          );
      },
      canCreate: !!release?.commands?.includes(release.sidebar?.create?.command ?? ''),
      canRename: !!release?.commands?.includes(release.sidebar?.rename?.command ?? ''),
      canDelete: !!release?.commands?.includes(release.sidebar?.delete?.command ?? ''),
      createNewConversation: async (id, group) => {
        if (id !== project) throw new Error('page_scope_expired');
        const result = await command('create', {
          ...(group ? { group } : {}),
          label: t('commandPalette.actions.newConversation', 'New conversation'),
        });
        const created = result.rows[0];
        if (!created || typeof created.id !== 'string') throw new Error('invalid_conversation');
        await load(id);
        if (activeScope.current !== command) throw new Error('page_scope_expired');
        setActive(created.id);
        return created.id;
      },
      renameConversation: async (conversation, id, title) => {
        if (id !== project) throw new Error('page_scope_expired');
        await command('rename', { id: conversation, label: title });
        await load(id);
      },
      deleteConversation: async (id, projectId) => {
        if (projectId !== project) throw new Error('page_scope_expired');
        await command('delete', { id });
        await load(projectId);
      },
    }),
    [
      conversations,
      tail,
      busy,
      active,
      load,
      loadMore,
      reset,
      release,
      command,
      workspace,
      navigation,
      project,
      t,
    ]
  );
  return <Sidebar.Provider value={state}>{children}</Sidebar.Provider>;
}
