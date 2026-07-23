/**
 * Organization Members Page
 *
 * Member management has been consolidated into the tenant Users page
 * (invitation flow, pending invites, inline role editing, pagination).
 * This tab is kept as a link card so existing org-settings navigation
 * continues to work.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { ArrowRight, Users } from 'lucide-react';

export const OrgMembers: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-primary/10 text-primary rounded-lg">
          <Users size={20} aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('tenant.orgSettings.members.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.members.description')}
          </p>
        </div>
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-300 mb-6 max-w-xl">
        {t('tenant.orgSettings.members.movedHint', {
          defaultValue:
            'Member management now lives on the Users page: email invitations, pending invites, inline role editing, and pagination are all handled there.',
        })}
      </p>
      <Link
        to="../../users"
        className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
      >
        {t('tenant.orgSettings.members.openUsersPage', { defaultValue: 'Open Users page' })}
        <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </div>
  );
};

export default OrgMembers;
