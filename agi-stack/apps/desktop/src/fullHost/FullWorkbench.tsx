import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react';
import { CubeIcon, GearIcon, GridIcon } from '@radix-ui/react-icons';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { DesktopTitlebar } from '../features/chrome/DesktopTitlebar';
import { ResizeHandle, useResizablePanelWidth } from '../components/ResizeHandle';
import { SIDEBAR_WIDTH_STORAGE_KEY } from '../sidebarWidth';
import { DesktopSidebarFrame } from '../features/navigation/DesktopSidebarFrame';
import {
  CommandPaletteSurface,
  type CommandPaletteItem,
} from '../features/navigation/CommandPaletteSurface';
import { useI18n } from '../i18n';
import { DesktopPackageWorkbench } from '../packageHost/DesktopPackageWorkbench';
import { messages } from '../packageHost/messages';
import { transport } from '../packageHost/transport';
import { WorkspaceDock } from '../features/workspace/WorkspaceDock';
import { HostSettings, type HostSettingsTab } from './HostSettings';
import { HostAdministration } from './HostAdministration';
import { matchPage, useInstalledPages } from './pages';
import { NARROW_SHELL_QUERY } from './headerPresentation';
import { useSignedSidebar } from './useSignedSidebar';
import { WorkbenchHeader } from './WorkbenchHeader';
import {
  assembleWorkbenchHeader,
  explicitWorkbenchProject,
  FULL_HOST_SIDEBAR_CONSTRAINTS,
  headerItemActive,
  pendingWorkspaceSelection,
  hostSection,
  isShellRoot,
  pathnameOf,
  resolveWorkbenchScope,
  selectWorkbenchSurface,
  shellLanding,
} from './workbenchModel';
import { signedSidebarLoadPhase, signedSidebarRetryTarget } from './signedSidebarModel';
import './style.css';

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  return () => window.removeEventListener('hashchange', listener);
}
const readHash = () => window.location.hash.slice(1);
function navigate(path: string) {
  window.location.hash = path;
}

export function FullWorkbench({
  session,
  reload,
  signOut,
}: {
  session: CloudSessionProjection | null;
  reload(): Promise<void>;
  signOut(): void;
}) {
  const { locale, t } = useI18n();
  const hash = useSyncExternalStore(subscribe, readHash);
  const [memberships, setMemberships] = useState<{ tenant_id: string; name: string }[]>([]);
  const [tenantError, setTenantError] = useState('');
  const [chosenTenant, setChosenTenant] = useState('');
  useEffect(() => {
    if (session) return;
    const controller = new AbortController();
    void transport<{ items: { tenant_id: string; name: string }[] }>(
      '/api/v1/tenant-packages/tenants',
      { signal: controller.signal },
    )
      .then((result) => setMemberships(result.items))
      .catch((cause) => {
        if (!controller.signal.aborted) setTenantError(String(cause));
      });
    return () => controller.abort();
  }, [session]);
  const sessionScope = session
    ? {
        tenantId: session.workspaceContext.tenantId,
        projectId: session.workspaceContext.projectId,
      }
    : null;
  const routed = resolveWorkbenchScope(hash, sessionScope);
  const tenant =
    routed.tenantId ||
    (chosenTenant || (memberships.length === 1 ? memberships[0]!.tenant_id : ''));
  const project = routed.tenantId === tenant ? routed.projectId : null;
  const explicitProject = explicitWorkbenchProject(hash);
  const pendingSelection = session
    ? pendingWorkspaceSelection(session.workspaceContext, explicitProject)
    : null;
  const [settings, setSettings] = useState<HostSettingsTab | null>(null);
  const [switchFailure, setSwitchFailure] = useState('');
  const [switchAttempt, setSwitchAttempt] = useState(0);
  const sidebarWidth = useResizablePanelWidth(
    SIDEBAR_WIDTH_STORAGE_KEY,
    FULL_HOST_SIDEBAR_CONSTRAINTS,
  );
  const scopeSwitchError = pendingSelection ? switchFailure : '';
  const scopeReady = !pendingSelection;
  useEffect(() => {
    if (!session || !pendingSelection) return;
    let cancelled = false;
    setSwitchFailure('');
    void transport('/api/v1/workspace-context/switch', {
      method: 'POST',
      body: {
        tenant_id: pendingSelection.tenantId,
        project_id: pendingSelection.projectId,
        expected_revision: session.workspaceContext.revision,
        idempotency_key: crypto.randomUUID(),
      },
    })
      .then(() => {
        if (!cancelled) return reload();
        return undefined;
      })
      .catch((cause: unknown) => {
        if (!cancelled) setSwitchFailure(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [
    pendingSelection?.tenantId,
    pendingSelection?.projectId,
    session?.workspaceContext.tenantId,
    session?.workspaceContext.projectId,
    session?.workspaceContext.revision,
    reload,
    switchAttempt,
  ]);
  const [directory, setDirectory] = useState(false);
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(NARROW_SHELL_QUERY).matches,
  );
  const [query, setQuery] = useState('');
  const trigger = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { entries, error, loading, refresh } = useInstalledPages(
    tenant,
    scopeReady ? project : null,
  );
  const base = '/tenant/' + encodeURIComponent(tenant);
  const market = base + '/plugins';
  const pathname = pathnameOf(hash);
  const root = isShellRoot(pathname, tenant);
  const address = root && tenant ? shellLanding(tenant) : hash;
  const section = tenant ? hostSection(pathnameOf(address), tenant) : null;
  const waitingForPage = Boolean(tenant) && (!scopeReady || loading) && !section;
  const selected = scopeReady && !loading ? matchPage(entries, tenant, address) : null;
  const surface = tenant ? selectWorkbenchSurface(pathnameOf(address), tenant, Boolean(selected)) : 'empty';
  const header = tenant ? assembleWorkbenchHeader(entries, tenant, project, pathnameOf(address)) : [];
  const sidebarGate = signedSidebarLoadPhase({
    project,
    scopeBlocked: !scopeReady,
    pagesLoading: loading,
    switchFailed: Boolean(scopeSwitchError),
  });
  const sidebar = useSignedSidebar(
    tenant,
    project,
    entries,
    address,
    sidebarGate,
    scopeSwitchError,
  );
  const retrySidebar = () => {
    if (signedSidebarRetryTarget(Boolean(scopeSwitchError)) === 'scope-switch') {
      setSwitchAttempt((attempt) => attempt + 1);
      return;
    }
    sidebar.reload();
  };
  const newTask = sidebar.canCreate || sidebar.openChatPath;
  const createWorkspace = sidebar.createWorkspacePath;
  const tenantName =
    session?.tenants.find((item) => item.id === tenant)?.name ??
    memberships.find((item) => item.tenant_id === tenant)?.name ??
    tenant;
  const projectName =
    session?.projects.find((item) => item.id === project)?.name ??
    project ??
    t('settings.noProjectSelected');
  const openDirectory = useCallback((button?: HTMLElement) => {
    trigger.current =
      button ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setQuery('');
    setDirectory(true);
  }, []);
  useEffect(() => {
    function keydown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openDirectory();
      }
    }
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [openDirectory]);
  useEffect(() => {
    if (directory) input.current?.focus();
  }, [directory]);
  useEffect(() => {
    if (tenant && root) navigate(shellLanding(tenant));
  }, [tenant, root]);
  useEffect(() => {
    const media = window.matchMedia(NARROW_SHELL_QUERY);
    const onChange = () => setCollapsed(media.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);
  const previousHash = useRef(hash);
  useEffect(() => {
    if (previousHash.current.startsWith(market) && !hash.startsWith(market)) refresh();
    previousHash.current = hash;
  }, [hash, market, refresh]);
  const items: CommandPaletteItem[] = [];
  function item(
    id: string,
    label: string,
    groupLabel: string,
    action: () => void,
    icon = <CubeIcon />,
  ) {
    items.push({
      id,
      kind: 'route',
      groupId: groupLabel,
      groupLabel,
      label,
      description: '',
      icon,
      searchText: label + ' ' + groupLabel,
      onSelect: action,
    });
  }
  item(
    'host-market',
    t('nav.plugins'),
    t('featureDirectory.open'),
    () => navigate(market),
    <GridIcon />,
  );
  item(
    'host-settings',
    t('sidebar.accountSettings'),
    t('settings.title'),
    () => setSettings('account'),
    <GearIcon />,
  );
  for (const entry of header)
    item(entry.id, t(entry.label), t(entry.groupLabel ?? 'featureDirectory.open'), () =>
      navigate(entry.path),
    );
  for (const row of sidebar.palette) {
    if (!row.path) continue;
    item(row.id, row.label, row.groupLabel, () => navigate(row.path));
  }
  const props = { tenant, project, locale, showBack: false as const };
  const activeHeader = header.find((entry) => headerItemActive(entry, pathnameOf(address)));
  const contextTitle =
    surface === 'market'
      ? t('nav.plugins')
      : activeHeader
        ? t(activeHeader.label)
        : (selected?.page.title ?? projectName);
  return (
    <div
      className={
        'app-shell hierarchy-shell runtime-mode desktop-window' +
        (collapsed ? ' sidebar-collapsed' : '')
      }
      style={
        {
          '--desktop-sidebar-preferred-width': `${Math.round(sidebarWidth.width)}px`,
        } as CSSProperties
      }
    >
      <DesktopTitlebar
        contextTitle={contextTitle}
        sidebarCollapsed={collapsed}
        rightSidebarOpen={false}
        rightSidebarAvailable={false}
        onToggleSidebar={() => setCollapsed((value) => !value)}
        onToggleRightSidebar={() => {}}
      />
      <section className="desktop-body">
        <DesktopSidebarFrame
          tenantName={tenantName}
          projectName={projectName}
          user={session?.user ?? null}
          onNavigate={() => navigate('')}
          onOpenFeatureDirectory={openDirectory}
          onOpenSearch={() => openDirectory()}
          onCreateWorkspace={createWorkspace ? () => navigate(createWorkspace) : undefined}
          newTaskDisabledReason={newTask ? null : t('desktopProductionRouter.unavailable.title')}
          onNewTask={() => {
            if (sidebar.canCreate) {
              void sidebar.create().then((path) => {
                if (path) navigate(path);
              }).catch(() => undefined);
              return;
            }
            if (sidebar.openChatPath) navigate(sidebar.openChatPath);
          }}
          onOpenAccountSettings={() => setSettings('account')}
          onSwitchWorkspace={() => setSettings('workspace')}
          onSignOut={signOut}
          resizeHandle={
            collapsed ? null : (
              <ResizeHandle
                side="trailing"
                width={sidebarWidth.width}
                constraints={FULL_HOST_SIDEBAR_CONSTRAINTS}
                label={t('layout.resizeSidebar')}
                onResize={sidebarWidth.resize}
                onReset={sidebarWidth.reset}
              />
            )
          }
          workspaceDock={
            <WorkspaceDock
              workspaces={sidebar.workspaces}
              conversationsByWorkspace={sidebar.conversationsByWorkspace}
              nodeState={sidebar.nodeState}
              currentProjectId={project ?? ''}
              currentWorkspaceId={sidebar.currentWorkspaceId}
              currentConversationId={sidebar.currentConversationId}
              selectionMode={sidebar.selectionMode}
              expandedWorkspaceIds={sidebar.expandedWorkspaceIds}
              onToggleWorkspace={sidebar.toggleWorkspace}
              onRetryProject={retrySidebar}
              onRetryWorkspace={sidebar.reload}
              workspaceHref={(workspaceId) => sidebar.workspacePath(workspaceId)}
              conversationHref={(conversation, workspaceId) =>
                sidebar.conversationPath(conversation.id, workspaceId)
              }
              onSelectWorkspace={(_projectId, workspaceId) => {
                const path = sidebar.workspacePath(workspaceId);
                if (path) navigate(path);
              }}
              onSelectConversation={(_projectId, workspaceId, conversation) => {
                const path = sidebar.conversationPath(conversation.id, workspaceId);
                if (path) navigate(path);
              }}
              onRenameConversation={
                sidebar.canRename
                  ? async (_projectId, _workspaceId, conversation, title) => {
                      await sidebar.rename(conversation.id, title);
                    }
                  : undefined
              }
              onCreateWorkspace={createWorkspace ? () => navigate(createWorkspace) : undefined}
              executionTarget={sidebar.filter}
              onExecutionTargetChange={sidebar.setFilter}
            />
          }
        />
        <section className="workbench">
          {tenant ? (
            <WorkbenchHeader items={header} pathname={pathnameOf(address)} onNavigate={navigate} />
          ) : null}
          <div className="workbench-content">
            {scopeSwitchError ? (
              <main className="desktop-package-workbench">
                <h1>{project ? projectName : tenantName}</h1>
                <p role="alert">{scopeSwitchError}</p>
                <button type="button" onClick={retrySidebar}>
                  {t('workspaceTree.retry')}
                </button>
              </main>
            ) : waitingForPage ? (
              <main className="desktop-package-workbench">
                <h1>{project ? projectName : tenantName}</h1>
                <p role="status">{messages.loading}</p>
              </main>
            ) : surface === 'market' && tenant ? (
              <DesktopPackageWorkbench
                {...props}
                workbench={{ kind: 'market' }}
                onChanged={refresh}
              />
            ) : surface === 'host' && tenant && section && section !== 'plugins' ? (
              <HostAdministration
                section={section}
                tenant={tenant}
                project={project}
                session={session}
                reload={reload}
              />
            ) : surface === 'page' && selected ? (
              <DesktopPackageWorkbench
                {...props}
                workbench={{
                  kind: 'page',
                  address,
                  route: {
                    projectId: selected.projectId,
                    pluginId: selected.pluginId,
                    rank: '',
                  },
                }}
              />
            ) : (
              <main className="desktop-package-workbench">
                <h1>
                  {!root && !loading && !error
                    ? t('fullHost.unavailable')
                    : project
                      ? projectName
                      : tenantName || messages.tenant}
                </h1>
                {!session && memberships.length > 0 && (
                  <label>
                    {messages.tenant}
                    <select
                      value={tenant}
                      onChange={(event) => {
                        setChosenTenant(event.target.value);
                        navigate(
                          '/tenant/' +
                            encodeURIComponent(event.target.value) +
                            '/plugins?marketScope=tenant',
                        );
                      }}
                    >
                      {!tenant && <option value="">{messages.tenant}</option>}
                      {memberships.map((item) => (
                        <option key={item.tenant_id} value={item.tenant_id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {tenantError && <p role="alert">{tenantError}</p>}
                {error && <p role="alert">{error}</p>}
                {loading ? (
                  <p role="status">{messages.loading}</p>
                ) : tenant ? (
                  <button type="button" onClick={() =>
                    navigate(root ? market : market + '?' + new URLSearchParams({ returnTo: address }))
                  }>
                    {t('fullHost.backToMarket')}
                  </button>
                ) : (
                  <button type="button" onClick={() => setSettings('workspace')}>
                    {t('settings.switchWorkspace')}
                  </button>
                )}
              </main>
            )}
          </div>
        </section>
      </section>
      {directory && (
        <CommandPaletteSurface
          inputRef={input}
          query={query}
          items={items.filter((entry) =>
            entry.searchText.toLowerCase().includes(query.trim().toLowerCase()),
          )}
          shortcutIds={['palette-move', 'palette-jump', 'palette-run']}
          onQueryChange={setQuery}
          onClose={(restore = true) => {
            setDirectory(false);
            if (restore) trigger.current?.focus();
          }}
        />
      )}
      {settings && (
        <HostSettings
          initial={settings}
          session={session}
          reload={reload}
          signOut={signOut}
          memberships={memberships}
          onTenant={(id) => {
            setChosenTenant(id);
            navigate('/tenant/' + encodeURIComponent(id) + '/plugins?marketScope=tenant');
            setSettings(null);
          }}
          close={() => setSettings(null)}
        />
      )}
    </div>
  );
}

