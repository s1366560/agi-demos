/**
 * TenantSidebar Component (Refactored)
 *
 * Tenant-level sidebar variant component.
 * Explicit variant with embedded configuration and state management.
 */

import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { useAuthStore } from '@/stores/auth';

import { getTenantSidebarConfig } from '@/config/navigation';

import { AppSidebar } from './AppSidebar';

import type { TenantSidebarProps } from './types';
import type { NavUser } from '@/config/navigation';

/**
 * Tenant sidebar component with configuration and state management
 */
export function TenantSidebar({
  tenantId,
  defaultCollapsed = false,
  collapsed: controlledCollapsed,
  onCollapseToggle,
  user: externalUser,
  onLogout: externalLogout,
  openGroups: controlledOpenGroups,
  onGroupToggle,
  t: externalT,
}: TenantSidebarProps & {
  collapsed?: boolean;
  onCollapseToggle?: () => void;
  user?: NavUser;
  onLogout?: () => void;
  openGroups?: Record<string, boolean>;
  onGroupToggle?: (groupId: string) => void;
  t?: (key: string) => string;
}) {
  const { t: useT } = useTranslation();
  const { user: authUser, logout: authLogout } = useAuthStore();
  const navigate = useNavigate();

  // Use external callbacks if provided, otherwise use internal state
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed);
  const [internalOpenGroups, setInternalOpenGroups] = useState<Record<string, boolean>>({});

  const collapsed = controlledCollapsed ?? internalCollapsed;
  const openGroups = controlledOpenGroups ?? internalOpenGroups;
  const handleCollapseToggle = onCollapseToggle ?? (() => setInternalCollapsed(!collapsed));
  const handleGroupToggle =
    onGroupToggle ??
    ((groupId: string) => {
      setInternalOpenGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
    });

  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant';

  const handleLogout =
    externalLogout ??
    (() => {
      authLogout();
      navigate('/login');
    });

  const navUser: NavUser = externalUser ?? {
    name: authUser?.name || 'User',
    email: authUser?.email || 'user@example.com',
  };

  const t = externalT ?? useT;

  return (
    <AppSidebar
      config={getTenantSidebarConfig()}
      basePath={basePath}
      variant="tenant"
      collapsed={collapsed}
      onCollapseToggle={handleCollapseToggle}
      user={navUser}
      onLogout={handleLogout}
      openGroups={openGroups}
      onGroupToggle={handleGroupToggle}
      t={t}
    />
  );
}

export default TenantSidebar;
