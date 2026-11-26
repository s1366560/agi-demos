import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { CubeIcon, GearIcon, GridIcon } from '@radix-ui/react-icons';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { DesktopTitlebar } from '../features/chrome/DesktopTitlebar';
import { DesktopSidebarFrame } from '../features/navigation/DesktopSidebarFrame';
import {
  CommandPaletteSurface,
  type CommandPaletteItem,
} from '../features/navigation/CommandPaletteSurface';
import { useI18n } from '../i18n';
import { DesktopPackageWorkbench } from '../packageHost/DesktopPackageWorkbench';
import { messages } from '../packageHost/messages';
import { transport } from '../packageHost/transport';
import { HostSettings, type HostSettingsTab } from './HostSettings';
import { HostAdministration } from './HostAdministration';
import { matchPage, useInstalledPages } from './pages';
import { useNavigationRows, type NavigationRow } from './useNavigationRows';
import { WorkbenchHeader } from './WorkbenchHeader';
import {
  assembleWorkbenchHeader,
  headerItemActive,
  hostSection,
  isShellRoot,
  pathnameOf,
  selectWorkbenchSurface,
  shellLanding,
} from './workbenchModel';
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
  const linkedTenant = memberships.find(
    (item) => hash.split('/')[2] === encodeURIComponent(item.tenant_id),
  );
  const tenant =
    session?.workspaceContext.tenantId ??
    linkedTenant?.tenant_id ??
    (chosenTenant || (memberships.length === 1 ? memberships[0]!.tenant_id : ''));
  const project = session?.workspaceContext.projectId ?? null;
  const [settings, setSettings] = useState<HostSettingsTab | null>(null);
  const [directory, setDirectory] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState('');
  const trigger = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { entries, error, loading, refresh } = useInstalledPages(tenant, project);
  const base = '/tenant/' + encodeURIComponent(tenant);
  const market = base + '/plugins';
  const pathname = pathnameOf(hash);
  const root = isShellRoot(pathname, tenant);
  const newTask = entries.find(
    (entry) => entry.enabled && entry.page.navigation_actions?.includes('primary-create') && entry.path,
  )?.path;
  const address = root && tenant ? shellLanding(tenant) : hash;
  const selected = matchPage(entries, tenant, address);
  const surface = tenant ? selectWorkbenchSurface(pathnameOf(address), tenant, Boolean(selected)) : 'empty';
  const header = tenant ? assembleWorkbenchHeader(entries, tenant, project, pathnameOf(address)) : [];
  const rowsOwner = selected?.page.sidebar?.rows ? selected : entries.find(entry => entry.enabled && entry.page.sidebar?.rows);
  const rowsSlot = useNavigationRows(tenant, project, rowsOwner, address);
  const createWorkspace = entries.find(
    (entry) => entry.enabled && entry.page.navigation_actions?.includes('group-create') && entry.path,
  )?.path;
  const tenantName =
    session?.tenants.find((item) => item.id === tenant)?.name ??
    memberships.find((item) => item.tenant_id === tenant)?.name ??
    tenant;
  const projectName =
    session?.projects.find((item) => item.id === project)?.name ?? t('settings.noProjectSelected');
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
  for (const row of rowsSlot.rows) {
    item(JSON.stringify([rowsOwner?.pluginId, row.id]), row.label, rowsOwner!.page.title, () => navigate(row.path));
  }
  const props = { tenant, project, locale, showBack: false as const };
  const activeHeader = header.find((entry) => headerItemActive(entry, pathnameOf(address)));
  const contextTitle =
    surface === 'market'
      ? t('nav.plugins')
      : activeHeader
        ? t(activeHeader.label)
        : (selected?.page.title ?? projectName);
  const administration = tenant ? hostSection(pathnameOf(address), tenant) : null;
  return (
    <div
      className={
        'app-shell hierarchy-shell runtime-mode desktop-window' +
        (collapsed ? ' sidebar-collapsed' : '')
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
            if (newTask) navigate(newTask);
          }}
          onOpenAccountSettings={() => setSettings('account')}
          onSwitchWorkspace={() => setSettings('workspace')}
          onSignOut={signOut}
          workspaceDock={
            <nav className="desktop-design-primary-nav">
              {rowsSlot.error && <p role="alert">{rowsSlot.error}</p>}
              <NavigationGroups key={JSON.stringify([tenant, project, rowsOwner?.pluginId])}
                rows={rowsSlot.rows} address={address}/>
            </nav>
          }
        />
        <section className="workbench">
          {tenant ? (
            <WorkbenchHeader items={header} pathname={pathnameOf(address)} onNavigate={navigate} />
          ) : null}
          <div className="workbench-content">
            {surface === 'market' && tenant ? (
              <DesktopPackageWorkbench
                {...props}
                workbench={{ kind: 'market' }}
                onChanged={refresh}
              />
            ) : surface === 'host' && tenant && administration && administration !== 'plugins' ? (
              <HostAdministration
                section={administration}
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
                <h1>{project ? projectName : tenantName || messages.tenant}</h1>
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
                {!root && !loading && !error && (
                  <p role="status">{t('desktopProductionRouter.unavailable.description')}</p>
                )}
                {error && <p role="alert">{error}</p>}
                {loading ? (
                  <p role="status">{messages.loading}</p>
                ) : tenant ? (
                  <button type="button" onClick={() =>
                    navigate(root ? market : market + '?' + new URLSearchParams({ returnTo: address }))
                  }>
                    {t('nav.plugins')}
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

function NavigationGroups({ rows, address }: { rows: NavigationRow[]; address: string }) {
  const groups = new Map<string | null, NavigationRow[]>();
  for (const row of rows) {
    const siblings = groups.get(row.group);
    if (siblings) siblings.push(row);
    else groups.set(row.group, [row]);
  }
  return Array.from(groups, ([id, entries]) => {
    const buttons = entries.map(row =>
      <button key={row.path} type="button" aria-current={address === row.path ? 'page' : undefined}
        onClick={() => navigate(row.path)}><span>{row.label}</span></button>
    );
    if (id === null) return buttons;
    return <details key={id} open><summary>{entries[0]?.groupLabel || id}</summary>{buttons}</details>;
  });
}
