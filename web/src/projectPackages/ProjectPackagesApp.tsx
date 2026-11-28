import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';
import { useEffect, useState, useSyncExternalStore, type FormEvent } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { cloudIdentity } from '@/services/client/cloudIdentity';
import { kernelHttpClient } from '@/services/client/kernelHttpClient';

import {
  clearAuthState,
  getAuthToken,
  persistCloudIdentity,
  subscribeCloudIdentity,
} from '@/utils/tokenResolver';

import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';

import { matchingPageProjects } from './routeScope';
import { projectSessionClient } from './sessionClient';
import { useWebPackageSession } from './useWebPackageSession';
import { TenantPackagePicker } from './TenantPackagePicker';
import { WebProjectMarket } from './WebProjectMarket';

import type { User } from '@/types/memory';

interface ProjectScope {
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  can_execute: boolean;
  can_manage: boolean;
}

function Credentials({ change, refresh }: { change: boolean; refresh: () => void }) {
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
        await cloudIdentity.changePassword(password, field('newPassword'));
        refresh();
      } else {
        const { token, user } = await cloudIdentity.login(field('email'), password);
        persistCloudIdentity(token, user);
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
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const session = useWebPackageSession(token);
  const [loaded, setLoaded] = useState<{
    projects: ProjectScope[];
  } | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [catalogRevision, setCatalogRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const client = projectSessionClient(token, controller.signal);
    void client
      .get<ProjectScope[]>('/project-packages/projects/')
      .then((projects) => {
        setLoaded({ projects });
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
  const { projects } = loaded;

  const matches = matchingPageProjects(projects, location.pathname, params);
  const selected = matches.length === 1 ? matches[0] : undefined;
  return (
    <>
      <Link to="/plugins?packageScope=tenant">{t('tenant.pluginHub.tenantScope')}</Link>
      <label className="package-project">
        {t('projectPackages.project')}
        <select
          value={selected?.project_id ?? ''}
          onChange={(event) => {
            const next = projects.find((item) => item.project_id === event.target.value);
            if (next)
              void navigate({
                pathname:
                  !selected && matches.length > 1 && matches.includes(next)
                    ? location.pathname
                    : '/',
                search: new URLSearchParams({
                  tenant: next.tenant_id,
                  project: next.project_id,
                }).toString(),
              });
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
          <RichPackagePages
            key={JSON.stringify([selected.tenant_id, selected.project_id])}
            scope={{ tenantId: selected.tenant_id, projectId: selected.project_id }}
            target="web"
            diagnostics={params.has('diagnostics')}
            revision={catalogRevision}
            pathname={location.pathname + location.search + location.hash}
            transport={session.transport}
            openVoiceSocket={session.openVoiceSocket}
        streamCommand={session.stream}
            managementLabel={t('projectPackages.manage')}
            navigate={(path, options) => {
              void navigate(
                scopedPageLocation(path, { tenant: selected.tenant_id, project: selected.project_id }),
                options
              );
            }}
            management={
              <WebProjectMarket
                key={selected.project_id}
                transport={session.transport}
                scopeParams={{ tenant: selected.tenant_id, project: selected.project_id }}
                onChanged={() => {
                  setCatalogRevision((value) => value + 1);
                }}
                tenantId={selected.tenant_id}
                projectId={selected.project_id}
                canManage={selected.can_manage}
                onOpen={(pathname) => {
                  void navigate({
                    pathname,
                    search: new URLSearchParams({
                      tenant: selected.tenant_id,
                      project: selected.project_id,
                    }).toString(),
                  });
                }}
              />
            }
          />
        </>
      ) : matches.length > 1 ? (
        <p role="status">{t('projectPackages.select')}</p>
      ) : (
        <p role="alert">{t('projectPackages.noAccess')}</p>
      )}
    </>
  );
}

export function ProjectPackagesApp() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const token = useSyncExternalStore(subscribeCloudIdentity, getAuthToken);
  const [identity, setIdentity] = useState<{ token: string; user: User } | null>(null);
  const user = identity?.token === token ? identity.user : null;
  const [checkError, setCheckError] = useState<{ token: string; message: string } | null>(null);
  const [attempt, retry] = useState(0);
  useEffect(() => {
    let active = true;
    if (token)
      void cloudIdentity
        .verifyToken(token)
        .then((verified) => {
          if (active && token === getAuthToken()) {
            setIdentity({ token, user: verified });
            if (verified.preferred_language && verified.preferred_language !== i18n.language)
              void i18n.changeLanguage(verified.preferred_language);
            setCheckError(null);
          }
        })
        .catch((reason: unknown) => {
          if (active)
            setCheckError({
              token,
              message: reason instanceof Error ? reason.message : t('common.error'),
            });
        });
    return () => {
      active = false;
    };
  }, [token, attempt, t, i18n]);
  function refreshIdentity() {
    retry((value) => value + 1);
  }
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
        {token && user && (
          <div>
            <span>{user.email}</span>
            <button type="button" onClick={logout}>
              {t('common.logout')}
            </button>
          </div>
        )}
      </header>
      {!token ? (
        <Credentials change={false} refresh={refreshIdentity} />
      ) : checkError?.token === token ? (
        <div role="alert">
          {checkError.message}{' '}
          <button
            onClick={() => {
              setCheckError(null);
              retry((value) => value + 1);
            }}
          >
            {t('common.retry')}
          </button>
        </div>
      ) : !user ? (
        <p role="status">{t('common.loading')}</p>
      ) : user.must_change_password ? (
        <Credentials change refresh={refreshIdentity} />
      ) : (
        params.get('packageScope') === 'tenant' ? <TenantPackagePicker key={token} token={token} /> : <ProjectPicker key={token} token={token} />
      )}
    </main>
  );
}
