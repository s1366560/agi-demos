import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { useTranslation } from 'react-i18next';
import { useWorkspaceSidebar } from './workspaceSidebar';
import { useAuthStore } from '../stores/auth';
import { useWebPackageSession } from '../projectPackages/useWebPackageSession';
import { useFullNavigation } from './navigation';
import type { SidebarConversation, SidebarData } from '../components/layout/TenantSidebarView';
import {
  packageBase,
  packageScope,
} from '../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';

const Sidebar = createContext<SidebarData | null>(null);
export function useSignedSidebar() {
  const state = useContext(Sidebar);
  if (!state) throw new Error('Missing workbench sidebar');
  return state;
}

function unavailable(): Promise<never> {
  return Promise.reject(new Error('package_command_unavailable'));
}

function row(value: unknown, project: string): SidebarConversation | null {
  if (
    typeof value !== 'object' ||
    !value ||
    !('id' in value) ||
    typeof value.id !== 'string' ||
    !('title' in value) ||
    typeof value.title !== 'string'
  )
    return null;
  return {
    id: value.id,
    title: value.title,
    project_id: project,
    ...('execution_target' in value &&
    (value.execution_target === 'cloud' || value.execution_target === 'local')
      ? { execution_target: value.execution_target }
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
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const revision = useRef(0);
  const release = items.find(
    (i) =>
      i.plugin === 'memstack-agent' && i.projectId === project && i.commands?.includes('chat-list')
  );
  const plugin = release?.plugin,
    digest = release?.digest;
  const reset = useCallback(() => {
    revision.current++;
    setConversations([]);
    setBusy(false);
  }, []);
  const command = useCallback(
    async (id: string, name: string, payload: Record<string, unknown>, signal?: AbortSignal) => {
      if (!token || !tenant || project !== id || !plugin || !digest)
        throw new Error('package_command_unavailable');
      return transport<Record<string, unknown>>(
        packageBase(id) + '/' + encodeURIComponent(plugin) + '/commands',
        {
          method: 'POST',
          body: { ...packageScope(tenant, id), expected_digest: digest, command_id: name, payload },
          ...(signal ? { signal } : {}),
        }
      );
    },
    [token, tenant, project, plugin, digest, transport]
  );
  const load = useCallback<SidebarData['loadConversations']>(
    async (id, options) => {
      const seq = ++revision.current;
      if (!plugin || !digest || project !== id) {
        setConversations([]);
        setBusy(false);
        return;
      }
      setBusy(true);
      try {
        const { items: rows } = await command(id, 'chat-list', {}, options?.signal);
        if (seq !== revision.current || options?.signal?.aborted) return;
        const visible = (Array.isArray(rows) ? rows : [])
          .map((v) => row(v, id))
          .filter((v): v is SidebarConversation => v !== null);
        setConversations(
          visible.filter(
            (v) =>
              !options?.executionTarget ||
              options.executionTarget === 'all' ||
              options.executionTarget === v.execution_target
          )
        );
      } finally {
        if (seq === revision.current) setBusy(false);
      }
    },
    [command, project, plugin, digest]
  );
  useEffect(() => {
    reset();
    setActive(null);
    const controller = new AbortController();
    if (project && digest) void load(project, { signal: controller.signal }).catch(() => {});
    return () => {
      revision.current++;
      controller.abort();
    };
  }, [tenant, project, digest, load, reset]);
  const state = useMemo<SidebarData>(
    () => ({
      conversations,
      conversationsLoading: busy,
      activeConversationId: active,
      setActiveConversation: setActive,
      loadConversations: load,
      resetConversations: reset,
      hasMoreConversations: false,
      loadMoreConversations: async () => {},
      ...workspace,
      removeConversationLocal: () => {},
      restoreConversationLocal: () => {},
      canCreate: release?.commands?.includes('chat-create') ?? false,
      canRename: release?.commands?.includes('chat-rename') ?? false,
      canDelete: false,
      createNewConversation: async (id) => {
        const result = await command(id, 'chat-create', {
          title: t('commandPalette.actions.newConversation', 'New conversation'),
        });
        const created = row(result, id);
        if (!created) throw new Error('invalid_conversation');
        await load(id);
        setActive(created.id);
        return created.id;
      },
      renameConversation: async (conversation, id, title) => {
        await command(id, 'chat-rename', { conversation_id: conversation, title });
        await load(id);
      },
      deleteConversation: unavailable,
    }),
    [conversations, busy, active, load, reset, release, command, workspace, t]
  );
  return <Sidebar.Provider value={state}>{children}</Sidebar.Provider>;
}
