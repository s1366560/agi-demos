import { useEffect, useState, type FormEvent } from 'react';

import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { useAuthStore } from '@/stores/auth';

import { authAPI } from '@/services/api';
import { kernelHttpClient } from '@/services/client/kernelHttpClient';
import { createOptionalBusinessService } from '@/services/projectPackageClient';

import { clearAuthState, getAuthToken } from '@/utils/tokenResolver';

import { OptionalBusinessPanel } from '@/components/plugins/OptionalBusinessPanel';

import { projectSessionClient } from './sessionClient';

interface ProjectScope {
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  can_execute: boolean;
  can_manage: boolean;
}

function Credentials({ change }: { change: boolean }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const field = (name: string) => {
      const value = data.get(name);
      return typeof value === 'string' ? value : '';
    };
    const password = field('password');
    setPending(true);
    setError('');
    try {
      if (change) {
        await authAPI.changePassword(password, field('newPassword'));
        await useAuthStore.getState().checkAuth('project-packages');
      } else {
        await useAuthStore.getState().login(field('email'), password, 'project-packages');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('common.error'));
    } finally {
      setPending(false);
    }
  }
  return (
    <form
      className="package-login"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <h2>{t(change ? 'forceChangePassword.title' : 'login.subtitle')}</h2>
      {!change && (
        <label>
          {t('login.email')}
          <input name="email" type="email" required autoComplete="username" />
        </label>
      )}
      <label>
        {t(change ? 'forceChangePassword.currentPassword' : 'login.password')}
        <input name="password" type="password" required autoComplete="current-password" />
      </label>
      {change && (
        <label>
          {t('forceChangePassword.newPassword')}
          <input name="newPassword" type="password" required autoComplete="new-password" />
        </label>
      )}
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={pending}>
        {t(change ? 'common.save' : 'login.submit')}
      </button>
    </form>
  );
}

function ProjectPicker({ token }: { token: string }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [loaded, setLoaded] = useState<{
    projects: ProjectScope[];
    service: ReturnType<typeof createOptionalBusinessService>;
  } | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const client = projectSessionClient(token, controller.signal);
    void client
      .get<ProjectScope[]>('/project-packages/projects/')
      .then((projects) => {
        setLoaded({ projects, service: createOptionalBusinessService(client) });
        setError('');
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : t('common.error'));
      });
    return () => {
      controller.abort();
    };
  }, [revision, token, t]);

  if (error)
    return (
      <div role="alert">
        {error}{' '}
        <button
          onClick={() => {
            setError('');
            setLoaded(null);
            setRevision(revision + 1);
          }}
        >
          {t('common.retry')}
        </button>
      </div>
    );
  if (!loaded) return <p role="status">{t('common.loading')}</p>;
  const { projects, service } = loaded;
  if (!projects.length) return <p role="status">{t('projectPackages.noAccess')}</p>;
  const tenant = params.get('tenant');
  const project = params.get('project');
  const selected =
    tenant || project
      ? projects.find((item) => item.tenant_id === tenant && item.project_id === project)
      : projects[0];
  return (
    <>
      <label className="package-project">
        {t('projectPackages.project')}
        <select
          value={selected?.project_id ?? ''}
          onChange={(event) => {
            const next = projects.find((item) => item.project_id === event.target.value);
            if (next) setParams({ tenant: next.tenant_id, project: next.project_id });
          }}
        >
          {!selected && <option value="">{t('projectPackages.select')}</option>}
          {projects.map((item) => (
            <option key={item.project_id} value={item.project_id}>
              {item.tenant_name} / {item.project_name}
            </option>
          ))}
        </select>
      </label>
      {selected ? (
        <>
          {!selected.can_manage && (
            <p>{t(selected.can_execute ? 'projectPackages.member' : 'projectPackages.viewer')}</p>
          )}
          <OptionalBusinessPanel
            key={selected.project_id}
            service={service}
            tenantId={selected.tenant_id}
            projectId={selected.project_id}
            canManage={selected.can_manage}
            canExecute={selected.can_execute}
          />
        </>
      ) : (
        <p role="alert">{t('projectPackages.noAccess')}</p>
      )}
    </>
  );
}

export function ProjectPackagesApp() {
  const { t } = useTranslation();
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const [verified, setVerified] = useState<string | null>(null);
  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key !== null && event.key !== 'memstack-auth-storage') return;
      if (getAuthToken() === useAuthStore.getState().token) return;
      setVerified(null);
      if (getAuthToken()) void useAuthStore.persist.rehydrate();
      else clearAuthState();
    }
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  useEffect(() => {
    let active = true;
    if (token)
      void useAuthStore
        .getState()
        .checkAuth('project-packages')
        .then(() => {
          if (active && token === getAuthToken()) setVerified(token);
        });
    return () => {
      active = false;
    };
  }, [token]);
  function logout() {
    if (token)
      void kernelHttpClient
        .post('/auth/signout', {}, { headers: { Authorization: `Bearer ${token}` } })
        .catch(() => undefined);
    clearAuthState();
  }
  return (
    <main className="package-shell">
      <header>
        <h1>{t('projectPackages.title')}</h1>
        {token && verified === token && user && (
          <div>
            <span>{user.email}</span>
            <button type="button" onClick={logout}>
              {t('common.logout')}
            </button>
          </div>
        )}
      </header>
      {!token ? (
        <Credentials change={false} />
      ) : !user || verified !== token ? (
        <p role="status">{t('common.loading')}</p>
      ) : user.must_change_password ? (
        <Credentials change />
      ) : (
        <ProjectPicker key={token} token={token} />
      )}
    </main>
  );
}
