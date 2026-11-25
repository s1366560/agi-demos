import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { RichPackagePages } from '../../../agi-stack/packages/plugin-marketplace-ui/src/RichPackagePages';
import { scopedPageLocation } from '../../../agi-stack/packages/plugin-slots/src/pageLocation';

import { useWebPackageSession } from './useWebPackageSession';
import { WebProjectMarket } from './WebProjectMarket';

type Tenant = { tenant_id: string; name: string; can_manage: boolean; can_execute: boolean };

export function TenantPackagePicker({ token }: { token: string }) {
  const session = useWebPackageSession(token);
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [revision, setRevision] = useState(0);
  const [tenants, setTenants] = useState<Tenant[]>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void session
      .transport<{ items: Tenant[] }>('/api/v1/tenant-packages/tenants', {
        signal: controller.signal,
      })
      .then((result) => {
        if (!controller.signal.aborted) setTenants(result.items);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(String(reason));
      });
    return () => { controller.abort(); };
  }, [session]);
  const tenantId = params.get('tenant') || (tenants?.length === 1 ? tenants[0]?.tenant_id : null);
  const tenant = tenants?.find((entry) => entry.tenant_id === tenantId);
  const bindings = { tenant: tenant?.tenant_id ?? '', packageScope: 'tenant' };
  return (
    <>
      <Link to="/plugins">{t('projectPackages.project')}</Link>
      <label className="package-project">
        {t('tenant.pluginHub.tenantScope')}
        <select
          value={tenant?.tenant_id ?? ''}
          onChange={(event) => {
            void navigate(
              scopedPageLocation('/plugins', { ...bindings, tenant: event.target.value })
            );
          }}
        >
          <option value="">{t('projectPackages.selectTenant')}</option>
          {tenants?.map((item) => (
            <option key={item.tenant_id} value={item.tenant_id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      {error && <p role="alert">{error}</p>}
      {tenants && !tenants.length && <p role="status">{t('projectPackages.noAccess')}</p>}
      {tenant && (
        <RichPackagePages
          key={tenant.tenant_id}
          scope={{ tenantId: tenant.tenant_id, projectId: null }}
          target="web"
          locale={i18n.language}
          revision={revision}
          pathname={location.pathname + location.search + location.hash}
          transport={session.transport}
          openVoiceSocket={session.openVoiceSocket}
        streamCommand={session.stream}
          managementLabel={t('projectPackages.manage')}
          navigate={(path, options) => void navigate(scopedPageLocation(path, bindings), options)}
          management={
            <WebProjectMarket
              tenantId={tenant.tenant_id}
              projectId={null}
              canManage={tenant.can_manage}
              transport={session.transport}
              scopeParams={bindings}
              onChanged={() => { setRevision((v) => v + 1); }}
              onOpen={(path) => void navigate(scopedPageLocation(path, bindings))}
            />
          }
        />
      )}
    </>
  );
}
