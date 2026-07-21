import React, { useEffect } from 'react';

import { useNavigate, useLocation } from 'react-router-dom';

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

  // Render nothing while the redirect is pending to avoid flashing gated content.
  if (redirectTarget) {
    return null;
  }

  return <>{children}</>;
};
