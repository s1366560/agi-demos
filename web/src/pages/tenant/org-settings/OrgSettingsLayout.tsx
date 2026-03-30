/**
 * Organization Settings Layout
 *
 * Provides a sidebar navigation layout for organization settings sub-pages.
 * Routes: /tenant/org-settings/info, /members, /clusters, /audit, /registry
 */

import React, { useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';

import { Building2, Cloud, Dna, FileText, Mail, Server, Users } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

type SettingsTab = 'info' | 'members' | 'clusters' | 'audit' | 'registry' | 'smtp' | 'genes';

const TABS: { key: SettingsTab; icon: React.ComponentType<{ size?: number }>; labelKey: string }[] = [
  { key: 'info', icon: Building2, labelKey: 'tenant.orgSettings.info.title' },
  { key: 'members', icon: Users, labelKey: 'tenant.orgSettings.members.title' },
  { key: 'clusters', icon: Cloud, labelKey: 'tenant.orgSettings.clusters.title' },
  { key: 'audit', icon: FileText, labelKey: 'tenant.orgSettings.audit.title' },
  { key: 'registry', icon: Server, labelKey: 'tenant.orgSettings.registry.title' },
  { key: 'smtp', icon: Mail, labelKey: 'tenant.orgSettings.smtp.title' },
  { key: 'genes', icon: Dna, labelKey: 'tenant.orgSettings.genes.title' },
];

export const OrgSettingsLayout: React.FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { tenantId } = useParams<{ tenantId: string }>();
  const currentTenant = useTenantStore((s) => s.currentTenant);

  // Extract current tab from URL
  const pathParts = location.pathname.split('/');
  const currentTab = (pathParts[pathParts.length - 1] as SettingsTab) || 'info';

  const handleTabChange = useCallback(
    (tab: SettingsTab) => {
      const basePath = tenantId ? `/tenant/${tenantId}/org-settings` : '/tenant/org-settings';
      void navigate(`${basePath}/${tab}`);
    },
    [navigate, tenantId]
  );

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.orgSettings.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">
          {t('tenant.orgSettings.subtitle')}
        </p>
      </div>

      {/* Main content with sidebar */}
      <div className="flex gap-6">
        {/* Sidebar navigation */}
        <div className="w-56 shrink-0">
          <nav className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            <ul className="divide-y divide-slate-100 dark:divide-slate-700">
              {TABS.map((tab) => {
                const isActive = currentTab === tab.key;
                const TabIcon = tab.icon;
                return (
                  <li key={tab.key}>
                    <button
                      type="button"
                      onClick={() => {
                        handleTabChange(tab.key);
                      }}
                      className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                        isActive
                          ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 border-l-2 border-primary-500'
                          : 'text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50'
                      }`}
                    >
                      <TabIcon size={20} />
                      <span className="text-sm font-medium">{t(tab.labelKey)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>

        {/* Content area */}
        <div className="flex-1 min-w-0">
          <Outlet />
        </div>
      </div>
    </div>
  );
};

export default OrgSettingsLayout;
