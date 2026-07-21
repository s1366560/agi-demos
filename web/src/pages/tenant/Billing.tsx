import { useCallback, useEffect, useMemo, useState, memo, type FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Empty, Pagination } from 'antd';
import { Check, CreditCard, Download, Receipt } from 'lucide-react';

import { formatStorage } from '../../hooks/useDateFormatter';
import { billingService } from '../../services/billingService';
import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { formatDateTime } from '../../utils/date';

import { LoadingState } from './utils/LoadingState';

import type { BillingInfo, UpgradePlanRequest } from '../../services/billingService';

const INVOICES_PER_PAGE = 10;

export const Billing: FC = memo(() => {
  const { t } = useTranslation();
  const { currentTenant } = useTenantStore();
  const [billingInfo, setBillingInfo] = useState<BillingInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [actionLoading, setActionLoading] = useState<UpgradePlanRequest['plan'] | null>(null);
  const [invoicePage, setInvoicePage] = useState(1);
  const [actionMessage, setActionMessage] = useState<{
    type: 'success' | 'error' | 'info';
    text: string;
  } | null>(null);

  const fetchBillingInfo = useCallback(async () => {
    if (currentTenant) {
      setLoading(true);
      setLoadError(false);
      try {
        const data = await billingService.getBillingInfo(currentTenant.id);
        setBillingInfo(data);
      } catch (error) {
        console.error('Failed to fetch billing info:', error);
        setLoadError(true);
      } finally {
        setLoading(false);
      }
    }
  }, [currentTenant]);

  useEffect(() => {
    void fetchBillingInfo();
  }, [fetchBillingInfo]);

  const currentPlan = billingInfo?.tenant.plan ?? currentTenant?.plan ?? 'free';
  const getNextPlan = useCallback((plan: string): UpgradePlanRequest['plan'] | null => {
    if (plan === 'enterprise') return null;
    if (plan === 'pro' || plan === 'premium') return 'enterprise';
    return 'pro';
  }, []);
  const nextPlan = getNextPlan(currentPlan);
  const formatPlanName = useCallback((plan: string) => {
    if (plan === 'pro') return 'Pro';
    return plan.charAt(0).toUpperCase() + plan.slice(1);
  }, []);

  const handleUpgrade = useCallback(
    async (plan: UpgradePlanRequest['plan']) => {
      if (!currentTenant) return;

      const confirmed = await confirmAction({
        title: t('tenant.billing.confirm_upgrade_title'),
        content: t('tenant.billing.confirm_upgrade_content', { plan: formatPlanName(plan) }),
        okText: t('tenant.billing.confirm_upgrade_ok', { plan: formatPlanName(plan) }),
        cancelText: t('common.cancel'),
      });
      if (!confirmed) return;

      setActionLoading(plan);
      setActionMessage(null);
      try {
        const response = await billingService.upgradePlan(currentTenant.id, plan);
        setActionMessage({
          type: 'success',
          text: response.message || t('tenant.billing.upgrade_success'),
        });
        await fetchBillingInfo();
      } catch (error) {
        console.error('Failed to upgrade plan:', error);
        setActionMessage({ type: 'error', text: t('tenant.billing.upgrade_error') });
      } finally {
        setActionLoading(null);
      }
    },
    [currentTenant, fetchBillingInfo, formatPlanName, t]
  );

  // Format date string
  const formatDate = useMemo(() => {
    return (dateStr: string): string => formatDateTime(dateStr) || dateStr;
  }, []);

  // Format an invoice amount with its ISO currency code
  const formatAmount = useMemo(() => {
    return (amount: number, currency: string): string => {
      try {
        return new Intl.NumberFormat(undefined, {
          style: 'currency',
          currency: currency.toUpperCase(),
        }).format(amount);
      } catch {
        return `$${amount.toFixed(2)} ${currency.toUpperCase()}`;
      }
    };
  }, []);

  const formatInvoiceStatus = useCallback(
    (status: string): string => {
      switch (status) {
        case 'paid':
          return t('tenant.billing.history.paid');
        case 'pending':
          return t('tenant.billing.history.pending');
        case 'failed':
          return t('tenant.billing.history.failed');
        default:
          return status;
      }
    },
    [t]
  );

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
  }, [billingInfo]);

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center p-16">
        <Empty description={t('common.noTenant')} />
      </div>
    );
  }

  if (loading) {
    return <LoadingState message={t('common.loading')} />;
  }

  if (loadError) {
    return (
      <div className="max-w-full mx-auto flex flex-col gap-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.billing.title')}
          </h1>
          <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.billing.subtitle')}</p>
        </div>
        <div
          role="alert"
          className="rounded-[28px] border border-rose-200/80 bg-rose-50 px-6 py-8 dark:border-rose-900/60 dark:bg-rose-950/40"
        >
          <p className="text-lg font-semibold tracking-[-0.02em] text-rose-900 dark:text-rose-100">
            {t('tenant.billing.load_error')}
          </p>
          <button
            type="button"
            onClick={() => {
              void fetchBillingInfo();
            }}
            className="mt-5 inline-flex min-h-11 items-center justify-center rounded-full border border-rose-300 px-5 text-sm font-medium text-rose-800 transition-colors duration-150 hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2 dark:border-rose-800 dark:text-rose-100 dark:hover:bg-rose-900/60"
          >
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  const invoices = billingInfo?.invoices || [];
  const pagedInvoices = invoices.slice(
    (invoicePage - 1) * INVOICES_PER_PAGE,
    invoicePage * INVOICES_PER_PAGE
  );

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.billing.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.billing.subtitle')}</p>
      </div>

      {actionMessage ? (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            actionMessage.type === 'success'
              ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-900/50 dark:bg-green-900/20 dark:text-green-300'
              : actionMessage.type === 'error'
                ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300'
                : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/50 dark:bg-blue-900/20 dark:text-blue-300'
          }`}
          role="status"
        >
          {actionMessage.text}
        </div>
      ) : null}

      {/* Current Subscription Card */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
            <CreditCard size={16} className="text-primary" />
            {t('tenant.billing.current_plan')}
          </h2>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-6 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-100 dark:border-slate-800">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-2xl font-bold text-slate-900 dark:text-white capitalize">
                  {currentPlan}
                </h3>
                <span className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wide">
                  {t('common.status.active')}
                </span>
              </div>
              <p className="text-slate-500 mt-1">
                {t('tenant.billing.plan_description', {
                  plan: currentPlan,
                })}
              </p>
            </div>
            <div className="flex gap-3">
              <button
                className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                disabled={!nextPlan || actionLoading !== null}
                type="button"
                onClick={() => {
                  if (nextPlan) {
                    void handleUpgrade(nextPlan);
                  }
                }}
              >
                {actionLoading === nextPlan
                  ? t('tenant.billing.upgrading')
                  : nextPlan
                    ? t('tenant.billing.upgrade_to', { plan: formatPlanName(nextPlan) })
                    : t('tenant.billing.current_plan_button')}
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
              <div
                className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden"
                role="progressbar"
                aria-valuenow={Math.round(usageStats.storagePercent)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t('tenant.billing.storage_usage')}
              >
                <div
                  className="h-full bg-purple-500 transition-[width]"
                  style={{ width: `${String(usageStats.storagePercent)}%` }}
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
              <div
                className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden"
                role="progressbar"
                aria-valuenow={Math.round(usageStats.projectsPercent)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t('tenant.billing.projects')}
              >
                <div
                  className="h-full bg-blue-500 transition-[width]"
                  style={{ width: `${String(usageStats.projectsPercent)}%` }}
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
              <div
                className="mt-2 h-1.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden"
                role="progressbar"
                aria-valuenow={Math.round(usageStats.usersPercent)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t('tenant.billing.users')}
              >
                <div
                  className="h-full bg-green-500 transition-[width]"
                  style={{ width: `${String(usageStats.usersPercent)}%` }}
                ></div>
              </div>
            </div>
          </div>
        </div>

        {/* Upgrade Promo */}
        <div className="bg-white dark:bg-surface-dark rounded-lg shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8 flex flex-col justify-between">
          <div>
            <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <CreditCard size={18} />
            </div>
            <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-2">
              {t('tenant.billing.enterprise.title')}
            </h3>
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-6">
              {t('tenant.billing.enterprise.description')}
            </p>
            <ul className="space-y-3 mb-8">
              <li className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  <Check size={13} />
                </span>
                {t('tenant.billing.enterprise.features.projects')}
              </li>
              <li className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  <Check size={13} />
                </span>
                {t('tenant.billing.enterprise.features.security')}
              </li>
              <li className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  <Check size={13} />
                </span>
                {t('tenant.billing.enterprise.features.support')}
              </li>
            </ul>
          </div>
          <button
            className="w-full bg-slate-900 text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200 font-bold py-3 rounded-lg transition-colors shadow-sm disabled:cursor-not-allowed disabled:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
            disabled={currentPlan === 'enterprise' || actionLoading !== null}
            type="button"
            onClick={() => {
              void handleUpgrade('enterprise');
            }}
          >
            {actionLoading === 'enterprise'
              ? t('tenant.billing.upgrading')
              : currentPlan === 'enterprise'
                ? t('tenant.billing.current_plan_button')
                : t('tenant.billing.upgrade_to', { plan: formatPlanName('enterprise') })}
          </button>
        </div>
      </div>

      {/* Billing History */}
      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div className="p-6 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Receipt size={16} className="text-primary" />
            {t('tenant.billing.history.title')}
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
            <thead className="bg-slate-50 dark:bg-slate-900">
              <tr>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider"
                >
                  {t('tenant.billing.history.date')}
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider"
                >
                  {t('tenant.billing.history.amount')}
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider"
                >
                  {t('tenant.billing.history.status')}
                </th>
                <th
                  scope="col"
                  className="px-6 py-3 text-right text-xs font-medium text-slate-500 uppercase tracking-wider"
                >
                  {t('tenant.billing.history.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-surface-dark divide-y divide-slate-200 dark:divide-slate-800">
              {pagedInvoices.length > 0 ? (
                pagedInvoices.map((invoice) => (
                  <tr
                    key={invoice.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-white">
                      {formatDate(invoice.created_at)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-white tabular-nums">
                      {formatAmount(invoice.amount, invoice.currency)}
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
                        {formatInvoiceStatus(invoice.status)}
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
                          <Download size={16} />
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
        {invoices.length > INVOICES_PER_PAGE && (
          <div className="flex justify-end border-t border-slate-200 px-6 py-4 dark:border-slate-800">
            <Pagination
              current={invoicePage}
              pageSize={INVOICES_PER_PAGE}
              total={invoices.length}
              showSizeChanger={false}
              onChange={(page) => {
                setInvoicePage(page);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
});
Billing.displayName = 'Billing';
