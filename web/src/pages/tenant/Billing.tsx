import { useCallback, useEffect, useMemo, useState, memo, type FC } from 'react';

import { useTranslation } from 'react-i18next';

import { billingService } from '../../services/billingService';
import { useTenantStore } from '../../stores/tenant';

import type { BillingInfo } from '../../services/billingService';

// Loading state component
const LoadingState = memo<{ message: string }>(({ message }) => (
  <div className="p-8 text-center text-slate-500">
    <span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>
    {message}
  </div>
));
LoadingState.displayName = 'LoadingState';

export const Billing: FC = memo(() => {
  const { t } = useTranslation();
  const { currentTenant } = useTenantStore();
  const [billingInfo, setBillingInfo] = useState<BillingInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchBillingInfo = useCallback(async () => {
    if (currentTenant) {
      try {
        const data = await billingService.getBillingInfo(currentTenant.id);
        setBillingInfo(data);
      } catch (error) {
        console.error('Failed to fetch billing info:', error);
      } finally {
        setLoading(false);
      }
    }
  }, [currentTenant]);

  useEffect(() => {
    fetchBillingInfo();
  }, [fetchBillingInfo]);

  // Format storage bytes to human-readable
  const formatStorage = useMemo(() => {
    return (bytes: number): string => {
      const gb = bytes / (1024 * 1024 * 1024);
      return `${gb.toFixed(0)} GB`;
    };
  }, []);

  // Format date string
  const formatDate = useMemo(() => {
    return (dateStr: string): string => {
      try {
        return new Date(dateStr).toLocaleDateString();
      } catch {
        return dateStr;
      }
    };
  }, []);

  // Calculate usage percentages
  const usageStats = useMemo(() => {
    if (!billingInfo) {
      return {
        storagePercent: 0,
        storageUsed: '0 GB',
        storageLimit: '10 GB',
        projectsPercent: 0,
        projectsUsed: 0,
        projectsLimit: 10,
        usersPercent: 0,
        usersUsed: 0,
        usersLimit: 20,
      };
    }

    const { usage, tenant } = billingInfo;
    const storagePercent =
      tenant.storage_limit > 0 ? (usage.storage / tenant.storage_limit) * 100 : 0;

    // Get limits based on plan
    let projectsLimit = 10;
    let usersLimit = 20;
    if (tenant.plan === 'pro') {
      projectsLimit = 50;
      usersLimit = 100;
    } else if (tenant.plan === 'enterprise') {
      projectsLimit = 999;
      usersLimit = 999;
    }

    return {
      storagePercent: Math.min(storagePercent, 100),
      storageUsed: formatStorage(usage.storage),
      storageLimit: formatStorage(tenant.storage_limit),
      projectsPercent: Math.min((usage.projects / projectsLimit) * 100, 100),
      projectsUsed: usage.projects,
      projectsLimit,
      usersPercent: Math.min((usage.users / usersLimit) * 100, 100),
      usersUsed: usage.users,
      usersLimit,
    };
  }, [billingInfo, formatStorage]);

  if (!currentTenant) return null;

  if (loading) {
    return <LoadingState message={t('common.loading')} />;
  }

  const invoices = billingInfo?.invoices || [];

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.billing.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.billing.subtitle')}</p>
      </div>

      {/* Current Subscription Card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">credit_card</span>
            {t('tenant.billing.current_plan')}
          </h2>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-6 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-100 dark:border-slate-800">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-2xl font-bold text-slate-900 dark:text-white capitalize">
                  {billingInfo?.tenant.plan ?? currentTenant.plan}
                </h3>
                <span className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wide">
                  Active
                </span>
              </div>
              <p className="text-slate-500 mt-1">
                {t('tenant.billing.plan_description', {
                  plan: billingInfo?.tenant.plan ?? currentTenant.plan,
                })}
              </p>
            </div>
            <div className="flex gap-3">
              <button className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white font-medium text-sm transition-colors">
                {t('tenant.billing.contact_sales')}
              </button>
              <button className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm">
                {t('tenant.billing.upgrade_options')}
              </button>
            </div>
          </div>

          <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div className="p-4 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
              <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">
                {t('tenant.billing.storage_usage')}
              </p>
              <p className="text-xl font-semibold text-slate-900 dark:text-white">
                {usageStats.storageUsed}{' '}
                <span className="text-sm font-normal text-slate-400">
                  / {usageStats.storageLimit}
                </span>
              </p>
              <div className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-500 transition-all"
                  style={{ width: `${usageStats.storagePercent}%` }}
                ></div>
              </div>
            </div>
            <div className="p-4 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
              <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">
                {t('tenant.billing.projects')}
              </p>
              <p className="text-xl font-semibold text-slate-900 dark:text-white">
                {usageStats.projectsUsed}{' '}
                <span className="text-sm font-normal text-slate-400">
                  / {usageStats.projectsLimit}
                </span>
              </p>
              <div className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${usageStats.projectsPercent}%` }}
                ></div>
              </div>
            </div>
            <div className="p-4 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
              <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-1">
                {t('tenant.billing.users')}
              </p>
              <p className="text-xl font-semibold text-slate-900 dark:text-white">
                {usageStats.usersUsed}{' '}
                <span className="text-sm font-normal text-slate-400">
                  / {usageStats.usersLimit}
                </span>
              </p>
              <div className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 transition-all"
                  style={{ width: `${usageStats.usersPercent}%` }}
                ></div>
              </div>
            </div>
          </div>
        </div>

        {/* Upgrade Promo */}
        <div className="bg-gradient-to-br from-indigo-600 to-purple-700 rounded-xl shadow-lg p-6 md:p-8 text-white flex flex-col justify-between">
          <div>
            <h3 className="text-xl font-bold mb-2">Enterprise Plan</h3>
            <p className="text-indigo-100 text-sm mb-6">
              Get unlimited storage, advanced security features, and dedicated support.
            </p>
            <ul className="space-y-3 mb-8">
              <li className="flex items-center gap-2 text-sm text-indigo-50">
                <span className="material-symbols-outlined text-[18px]">check</span> Unlimited
                Projects
              </li>
              <li className="flex items-center gap-2 text-sm text-indigo-50">
                <span className="material-symbols-outlined text-[18px]">check</span> SSO & Audit
                Logs
              </li>
              <li className="flex items-center gap-2 text-sm text-indigo-50">
                <span className="material-symbols-outlined text-[18px]">check</span> Priority
                Support
              </li>
            </ul>
          </div>
          <button className="w-full bg-white text-indigo-600 hover:bg-indigo-50 font-bold py-3 rounded-lg transition-colors shadow-sm">
            {t('tenant.billing.contact_sales')}
          </button>
        </div>
      </div>

      {/* Billing History */}
      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">receipt_long</span>
            {t('tenant.billing.history.title')}
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-50 dark:bg-slate-900">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {t('tenant.billing.history.date')}
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {t('tenant.billing.history.amount')}
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {t('tenant.billing.history.status')}
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">
                  {t('tenant.billing.history.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-surface-dark divide-y divide-slate-200 dark:divide-slate-800">
              {invoices.length > 0 ? (
                invoices.map((invoice) => (
                  <tr
                    key={invoice.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-white">
                      {formatDate(invoice.created_at)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-white">
                      ${invoice.amount.toFixed(2)} {invoice.currency.toUpperCase()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                          invoice.status === 'paid'
                            ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                            : invoice.status === 'pending'
                              ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                              : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                        }`}
                      >
                        {invoice.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      {invoice.invoice_url ? (
                        <a
                          href={invoice.invoice_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:text-primary-dark hover:underline flex items-center justify-end gap-1"
                        >
                          <span className="material-symbols-outlined text-[16px]">download</span>
                          {t('tenant.billing.history.download')}
                        </a>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                    {t('tenant.billing.history.no_history')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
});
Billing.displayName = 'Billing';
