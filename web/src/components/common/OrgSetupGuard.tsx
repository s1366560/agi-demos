import React, { useEffect } from 'react';

import { useNavigate, useLocation } from 'react-router-dom';

import { Spin } from 'antd';

import { useAuthStore } from '@/stores/auth';
import { useTenantStore } from '@/stores/tenant';

export const OrgSetupGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const orgSetupComplete = useAuthStore((state) => state.orgSetupComplete);
  const currentTenant = useTenantStore((state) => state.currentTenant);

  const redirectTarget =
    !orgSetupComplete && currentTenant && !location.pathname.includes('/org-settings/')
      ? `/tenant/${currentTenant.id}/org-settings/info`
      : null;

  useEffect(() => {
    // Only redirect if setup is incomplete, we are inside a tenant route,
    // and not already on the org-settings page.
    if (redirectTarget) {
      void navigate(redirectTarget, { replace: true });
    }
  }, [redirectTarget, navigate]);

  // Show a loading indicator (not a blank flash) while the redirect is pending.
  if (redirectTarget) {
    return (
      <div
        role="status"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: 200,
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  return <>{children}</>;
};
