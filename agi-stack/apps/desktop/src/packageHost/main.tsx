import { openVoiceSocket } from './voiceSocket';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';

import { RichPackagePages } from './DesktopRichPackagePages';
import { desktopNativeCloudAuthClient } from '../api/nativeCloudAuthClient';
import {
  desktopCloudSessionProjectionClient,
  type CloudSessionProjection,
} from '../api/cloudSessionProjectionClient';
import { devicePageCall } from './device';
import { PackageManagement } from './PackageManagement';
import { messages as t } from './messages';
import { transport, streamCommand } from './transport';
import './style.css';

type Project = {
  project_id: string;
  tenant_id: string;
  project_name: string;
  tenant_name: string;
  can_manage: boolean;
};
function ProjectHost({
  session,
  reload,
}: {
  session: CloudSessionProjection | null;
  reload(): Promise<void>;
}) {
  const { tenantId: selectedTenant, projectId, revision } = session?.workspaceContext ?? {
    tenantId: '',
    projectId: null,
    revision: 0,
  };
  const [tenants, setTenants] = useState<{tenant_id:string; name:string}[]>([]);
  const [chosenTenant, setChosenTenant] = useState('');
  const tenantId = selectedTenant || chosenTenant || (tenants.length === 1 ? tenants[0]!.tenant_id : '');
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [version, bump] = useState(0);
  const [path, setPath] = useState(location.hash.slice(1) || '/');
  useEffect(() => {
    const update = () => setPath(location.hash.slice(1) || '/');
    window.addEventListener('hashchange', update);
    const stop = new AbortController();
    if (!selectedTenant) {
      transport<{items:{tenant_id:string;name:string}[]}>('/api/v1/tenant-packages/tenants', { signal: stop.signal })
        .then(result => setTenants(result.items))
        .catch(cause => { if (!stop.signal.aborted) setError(String(cause)); });
    }
    transport<Project[]>('/api/v1/project-packages/projects/', {
      signal: stop.signal,
    })
      .then(setProjects)
      .catch((cause) => {
        if (!stop.signal.aborted) setError(String(cause));
      });
    return () => {
      stop.abort();
      window.removeEventListener('hashchange', update);
    };
  }, [selectedTenant]);
  async function switchProject(id: string) {
    const requested = projects.find((item) => item.project_id === id);
    if (!requested) return;
    setPending(true);
    setError('');
    try {
      await transport('/api/v1/workspace-context/switch', {
        method: 'POST',
        body: {
          tenant_id: requested.tenant_id,
          project_id: id,
          expected_revision: revision,
          idempotency_key: crypto.randomUUID(),
        },
      });
      location.hash = '';
      await reload();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setPending(false);
    }
  }
  const device = useMemo(
    () => (projectId ? devicePageCall(tenantId, projectId) : undefined),
    [tenantId, projectId],
  );
  return (
    <>
      <label>
        {t.project}
        <select
          value={projectId ?? ''}
          disabled={pending}
          onChange={(e) => void switchProject(e.target.value)}
        >
          {!projectId && <option value="">{t.project}</option>}
          {projects.map((item) => (
            <option value={item.project_id} key={item.project_id}>
              {item.tenant_name} / {item.project_name}
            </option>
          ))}
        </select>
      </label>
      {!selectedTenant && tenants.length > 0 && (
        <label>{t.tenant}
          <select value={tenantId} onChange={event => { setChosenTenant(event.target.value); location.hash = '/plugins?marketScope=tenant'; }}>
            {!tenantId && <option value="">{t.tenant}</option>}
            {tenants.map(item => <option key={item.tenant_id} value={item.tenant_id}>{item.name}</option>)}
          </select>
        </label>
      )}
      {error && <p role="alert">{error}</p>}
      {tenantId && !projectId && !pending && <PackageManagement tenant={tenantId} project={null} canManage />}
      {projectId && !pending && (
        <>
          <RichPackagePages
            scope={{ tenantId, projectId }}
            target="desktop-renderer"
            pathname={path}
            navigate={(next, options) => {
              if (options?.replace) location.replace('#' + next);
              else location.hash = next;
            }}
            transport={transport}
            openVoiceSocket={openVoiceSocket}
          streamCommand={streamCommand}
            managementLabel={t.packages}
            management={
              <PackageManagement
                tenant={tenantId}
                project={projectId}
                canManage={projects.some((item) => item.project_id === projectId && item.can_manage)}
                refresh={() => bump((value) => value + 1)}
              />
            }
            invokeDevice={device}
            revision={version}
          />
        </>
      )}
    </>
  );
}

function DesktopHost() {
  const [session, setSession] = useState<CloudSessionProjection | null>(null);
  const [busy, setBusy] = useState(true);
  const [change, setChange] = useState(false);
  const [chooseProject, setChooseProject] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    const client = desktopCloudSessionProjectionClient();
    if (!client) throw new Error('native_cloud_session_unavailable');
    try {
      setSession(await client.load());
      setChooseProject(false);
    } catch (cause) {
      if (!String(cause).includes('cloud_project_selection_required')) throw cause;
      setSession(null);
      setChooseProject(true);
    }
  }, []);
  useEffect(() => {
    const client = desktopNativeCloudAuthClient();
    void (async () => {
      if (!client) throw new Error('native_authentication_unavailable');
      const status = await client.getStatus();
      if (status.status === 'authenticated') await load();
      setChange(status.status === 'password_change_required');
    })()
      .catch((cause) => setError(String(cause)))
      .finally(() => setBusy(false));
  }, [load]);
  useEffect(
    () =>
      window.__MEMSTACK_DESKTOP__?.events?.onCloudSessionInvalidated?.(() => {
        setSession(null);
        setChooseProject(false);
        setError('cloud_session_expired');
      }),
    [],
  );
  async function authenticate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const fields = new FormData(e.currentTarget);
    const field = (key: string) => String(fields.get(key) ?? '');
    try {
      const auth = desktopNativeCloudAuthClient();
      if (!auth) throw new Error('native_authentication_unavailable');
      const result = change
        ? await auth.forceChangePassword({
            currentPassword: field('password'),
            newPassword: field('newPassword'),
          })
        : await auth.loginWithPassword({
            apiBaseUrl: field('origin'),
            username: field('email'),
            password: field('password'),
            trustedDevice: fields.has('trusted'),
          });
      setChange(result.status === 'password_change_required');
      if (result.status === 'authenticated') await load();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    setSession(null);
    setChooseProject(false);
    setBusy(true);
    setError('');
    try {
      await desktopNativeCloudAuthClient()?.signOut();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main>
      <header>
        <h1>MemStack</h1>
        {(session || chooseProject) && (
          <>
            <span>{session?.user.email}</span>
            <button onClick={() => void signOut()}>{t.signOut}</button>
          </>
        )}
      </header>
      {error && <p role="alert">{error}</p>}
      {session || chooseProject ? (
        <ProjectHost
          key={JSON.stringify([session?.user.userId, session?.workspaceContext])}
          session={session}
          reload={load}
        />
      ) : (
        <form onSubmit={(e) => void authenticate(e)}>
          <h2>{change ? t.change : t.signIn}</h2>
          {!change && (
            <>
              <label>
                {t.origin}
                <input name="origin" type="url" required defaultValue="http://127.0.0.1:8000" />
              </label>
              <label>
                {t.email}
                <input name="email" type="email" autoComplete="username" required />
              </label>
            </>
          )}
          <label>
            {t.password}
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          {change ? (
            <label>
              {t.newPassword}
              <input name="newPassword" type="password" autoComplete="new-password" required />
            </label>
          ) : (
            <label>
              <input name="trusted" type="checkbox" defaultChecked />
              {t.trusted}
            </label>
          )}
          <button disabled={busy}>{busy ? t.loading : change ? t.change : t.signIn}</button>
        </form>
      )}
    </main>
  );
}
document.documentElement.lang = navigator.language;
createRoot(document.getElementById('root')!).render(<DesktopHost />);
