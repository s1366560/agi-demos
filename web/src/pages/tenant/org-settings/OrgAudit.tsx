/**
 * Organization Audit Logs Page
 *
 * Audit log viewing has been consolidated into the tenant Audit Logs page
 * (debounced filters, error + retry states, detail drawer, export).
 * This tab is kept as a link card so existing org-settings navigation
 * continues to work.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { ArrowRight, History } from 'lucide-react';

export const OrgAudit: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-primary/10 text-primary rounded-lg">
          <History size={20} aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('tenant.orgSettings.audit.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.audit.description')}
          </p>
        </div>
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-6 max-w-xl">
        {t('tenant.orgSettings.audit.movedHint', {
          defaultValue:
            'Audit logs now live on the Audit Logs page, with full filtering, export, and per-entry details.',
        })}
      </p>
      <Link
        to="../../audit-logs"
        className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
      >
        {t('tenant.orgSettings.audit.openAuditLogsPage', { defaultValue: 'Open Audit Logs' })}
        <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </div>
  );
};

export default OrgAudit;
