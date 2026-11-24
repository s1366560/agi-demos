import { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { WebRoutePageLoaderV2 } from '../routes/v2/WebRoutePageLoaderV2';
import { tenantAPI } from '../services/api';
import { useAuthStore } from '../stores/auth';
import { useTenantStore } from '../stores/tenant';

export function TenantPackageBookmark() {
  const { pathname, search, hash } = useLocation();
  const active = useTenantStore((state) => state.currentTenant?.id);
  const account = useAuthStore((state) => state.user?.tenant_id);
  const requested = new URLSearchParams(search).getAll('tenant');
  const tenant = requested.length === 1 ? requested[0] : undefined;
  const [first, setFirst] = useState<string | null | undefined>();
  const owner = tenant || active || account || first;

  useEffect(() => {
    if (tenant || active || account) return;
    let live = true;
    void tenantAPI.list({ page: 1, page_size: 1 })
      .then(({ tenants }) => {
        if (live) setFirst(tenants[0]?.id ?? null);
      })
      .catch(() => {
        if (live) setFirst(null);
      });
    return () => {
      live = false;
    };
  }, [account, active, tenant]);

  if (!owner && first === undefined) return <WebRoutePageLoaderV2 />;
  return (
    <Navigate
      replace
      to={
        owner
          ? {
              pathname: '/tenant/' + encodeURIComponent(owner) + pathname.slice('/tenant'.length),
              search,
              hash,
            }
          : '/tenant'
      }
    />
  );
}
