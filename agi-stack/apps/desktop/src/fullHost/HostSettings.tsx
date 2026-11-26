import { Cross2Icon } from '@radix-ui/react-icons';
import { useEffect, useState } from 'react';
import type { CloudSessionProjection } from '../api/cloudSessionProjectionClient';
import { AccountSettingsPage } from '../features/settings/AccountSettingsPage';
import { useModalDialog } from '../features/settings/useModalDialog';
import { useThemePreference, type ThemePreference } from '../theme';
import { useI18n } from '../i18n';
import { transport } from '../packageHost/transport';
import { messages } from '../packageHost/messages';
import { DEFAULT_CONFIG } from '../types';
import { loadTenantProjects, type CatalogProject } from './projectCatalog';
import '../features/settings/SettingsWindow.css';
import '../features/settings/SettingsForms.css';

export type HostSettingsTab = 'account' | 'workspace' | 'appearance';
type ListedProject = CatalogProject & { tenant_name: string };
export function HostSettings({
  initial,
  session,
  reload,
  close,
  signOut,
  memberships,
  onTenant,
}: {
  memberships: { tenant_id: string; name: string }[];
  onTenant(id: string): void;
  initial: HostSettingsTab;
  session: CloudSessionProjection | null;
  reload(): Promise<void>;
  close(): void;
  signOut(): void;
}) {
  const { locale, setLocale, t } = useI18n();
  const { preference, setPreference } = useThemePreference();
  const [tab, setTab] = useState(initial);
  const [projects, setProjects] = useState<ListedProject[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const dialog = useModalDialog({ onClose: close });
  const labels = {
    account: t('sidebar.accountSettings'),
    workspace: t('settings.switchWorkspace'),
    appearance: t('settings.preferences'),
  };
  useEffect(() => {
    if (tab !== 'workspace') return;
    const controller = new AbortController();
    const scopes = session?.tenants.length
      ? session.tenants.map((item) => ({ id: item.id, name: item.name }))
      : memberships.map((item) => ({ id: item.tenant_id, name: item.name }));
    void Promise.all(
      scopes.map(async (scope) => {
        const listed = await loadTenantProjects(transport, scope.id, controller.signal);
        return listed.map((project) => ({ ...project, tenant_name: scope.name }));
      }),
    )
      .then((groups) => {
        if (!controller.signal.aborted) setProjects(groups.flat());
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(String(cause));
      });
    return () => controller.abort();
  }, [memberships, session, tab]);
  async function switchProject(project: ListedProject) {
    setBusy(true);
    setError('');
    try {
      await transport('/api/v1/workspace-context/switch', {
        method: 'POST',
        body: {
          tenant_id: project.tenant_id,
          project_id: project.id,
          expected_revision: session?.workspaceContext.revision ?? 0,
          idempotency_key: crypto.randomUUID(),
        },
      });
      window.location.hash = '';
      await reload();
      close();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  const user = session?.user;
  return (
    <div className="settings-window-backdrop" onMouseDown={close}>
      <section
        ref={dialog}
        role="dialog"
        className="settings-window-dialog"
        aria-modal="true"
        aria-label={t('settings.title')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings-window-titlebar">
          <strong>{t('settings.title')}</strong>
          <button type="button" aria-label={t('settings.close')} onClick={close}>
            <Cross2Icon />
          </button>
        </header>
        <div className="settings-window-body">
          <aside className="settings-window-rail">
            {(Object.keys(labels) as HostSettingsTab[]).map((item) => (
              <button
                type="button"
                key={item}
                className={tab === item ? 'active' : ''}
                onClick={() => setTab(item)}
              >
                {labels[item]}
              </button>
            ))}
          </aside>
          <div className="settings-window-content">
            {tab === 'account' && (
              <AccountSettingsPage
                auth={{
                  status: 'signed_in',
                  session: null,
                  user: user
                    ? {
                        user_id: user.userId,
                        name: user.name,
                        email: user.email,
                        roles: [...user.roles],
                        is_active: user.active,
                        created_at: user.createdAt,
                        profile: {},
                      }
                    : null,
                }}
                config={{
                  ...DEFAULT_CONFIG,
                  mode: 'cloud',
                  apiBaseUrl: session?.apiBaseUrl ?? DEFAULT_CONFIG.apiBaseUrl,
                }}
                tenant={
                  session?.tenants.find((item) => item.id === session.workspaceContext.tenantId) ??
                  null
                }
                onSignOut={signOut}
              />
            )}
            {tab === 'workspace' && (
              <section className="settings-page">
                <h1>{labels.workspace}</h1>
                {memberships.map((item) => (
                  <button
                    type="button"
                    key={item.tenant_id}
                    className="settings-row"
                    onClick={() => onTenant(item.tenant_id)}
                  >
                    {item.name}
                  </button>
                ))}
                {projects.map((project) => (
                  <button
                    key={project.tenant_id + '/' + project.id}
                    type="button"
                    className="settings-row"
                    disabled={busy}
                    onClick={() => void switchProject(project)}
                  >
                    {project.tenant_name} / {project.name}
                  </button>
                ))}
              </section>
            )}
            {tab === 'appearance' && (
              <section className="settings-page">
                <h1>{labels.appearance}</h1>
                <label className="settings-row">
                  {t('settings.language')}
                  <select
                    value={locale}
                    onChange={(event) => setLocale(event.target.value === 'en' ? 'en' : 'zh-CN')}
                  >
                    <option value="en">{t('settings.english')}</option>
                    <option value="zh-CN">{t('settings.chinese')}</option>
                  </select>
                </label>
                <label className="settings-row">
                  {t('settings.theme')}
                  <select
                    value={preference}
                    onChange={(event) => setPreference(event.target.value as ThemePreference)}
                  >
                    <option value="dark">{t('settings.themeDark')}</option>
                    <option value="light">{t('settings.themeLight')}</option>
                    <option value="system">{t('settings.themeSystem')}</option>
                  </select>
                </label>
              </section>
            )}
            {error && <p role="alert">{error}</p>}
            {!session && tab === 'workspace' && (
              <button onClick={signOut}>{messages.signOut}</button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
