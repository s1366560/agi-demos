import React, { useEffect } from 'react';

import { useNavigate, useLocation } from 'react-router-dom';

import { useAuthStore } from '@/stores/auth';
import { useTenantStore } from '@/stores/tenant';

export const OrgSetupGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const orgSetupComplete = useAuthStore((state) => state.orgSetupComplete);
  const currentTenant = useTenantStore((state) => state.currentTenant);

  useEffect(() => {
    // Only redirect if setup is incomplete, we are inside a tenant route,
    // and not already on the org-settings page.
    if (!orgSetupComplete && currentTenant && !location.pathname.includes('/org-settings/')) {
      navigate(`/tenant/${currentTenant.id}/org-settings/info`, { replace: true });
    }
  }, [orgSetupComplete, currentTenant, location.pathname, navigate]);

  return <>{children}</>;
};
