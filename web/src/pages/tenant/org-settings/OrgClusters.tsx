/**
 * Organization Clusters Page
 *
 * Lists all organization clusters with status overview and quick actions.
 */

import React, { useCallback, useEffect, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  AlertCircle,
  CheckCircle,
  Cloud,
  CloudOff,
  Eye,
  Loader2,
  Server,
  Settings,
  Wrench,
} from 'lucide-react';

import { useClusters, useClusterLoading, useClusterActions } from '@/stores/cluster';
import { useTenantStore } from '@/stores/tenant';

import type { ClusterResponse } from '@/services/clusterService';

const getStatusConfig = (status: string): { color: string; bgColor: string; label: string } => {
  switch (status) {
    case 'active':
      return {
        color: 'text-green-600 dark:text-green-400',
        bgColor: 'bg-green-50 dark:bg-green-950/40',
        label: 'Active',
      };
    case 'maintenance':
      return {
        color: 'text-orange-600 dark:text-orange-400',
        bgColor: 'bg-orange-50 dark:bg-orange-950/40',
        label: 'Maintenance',
      };
    case 'error':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-50 dark:bg-red-950/40',
        label: 'Error',
      };
    case 'inactive':
      return {
        color: 'text-slate-600 dark:text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-800',
        label: 'Inactive',
      };
    default:
      return {
        color: 'text-slate-600 dark:text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-800',
        label: 'Unknown',
      };
  }
};

const getProviderIcon = (provider: string) => {
  switch (provider.toLowerCase()) {
    case 'aws':
    case 'gcp':
    case 'azure':
      return Cloud;
    case 'on-prem':
      return Server;
    default:
      return Cloud;
  }
};

interface ClusterCardProps {
  cluster: ClusterResponse;
  onViewDetails: (id: string) => void;
}

const ClusterCard: React.FC<ClusterCardProps> = ({ cluster, onViewDetails }) => {
  const { t } = useTranslation();
  const statusConfig = getStatusConfig(cluster.status);

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-5 transition-shadow hover:shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${statusConfig.bgColor}`}>
            {React.createElement(getProviderIcon(cluster.compute_provider), {
              size: 24,
              className: statusConfig.color,
            })}
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">{cluster.name}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">{cluster.compute_provider}</p>
          </div>
        </div>
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.color}`}
        >
          {statusConfig.label}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="rounded-lg bg-slate-100 p-2 text-center dark:bg-slate-800">
          <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
            {cluster.health_status ?? 'N/A'}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.clusters.health')}
          </p>
        </div>
        <div className="rounded-lg bg-slate-100 p-2 text-center dark:bg-slate-800">
          <p className="text-lg font-bold text-slate-900 dark:text-slate-100">{cluster.status}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.clusters.status')}
          </p>
        </div>
      </div>

      {/* API Endpoint */}
      {cluster.proxy_endpoint && (
        <div className="mt-4">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
            {t('tenant.orgSettings.clusters.endpoint')}
          </p>
          <p className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate">
            {cluster.proxy_endpoint}
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            onViewDetails(cluster.id);
          }}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-md transition-colors"
        >
          <Eye size={16} />
          {t('tenant.orgSettings.clusters.viewDetails')}
        </button>
      </div>
    </div>
  );
};

export const OrgClusters: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const currentTenant = useTenantStore((s) => s.currentTenant);
  const clusters = useClusters();
  const isLoading = useClusterLoading();
  const { listClusters } = useClusterActions();

  useEffect(() => {
    void listClusters();
  }, [listClusters]);

  // Stats
  const stats = useMemo(
    () => ({
      total: clusters.length,
      active: clusters.filter((c) => c.status === 'active').length,
      maintenance: clusters.filter((c) => c.status === 'maintenance').length,
      error: clusters.filter((c) => c.status === 'error').length,
    }),
    [clusters]
  );

  const handleViewDetails = useCallback(
    (clusterId: string) => {
      if (!currentTenant) return;
      void navigate(`/tenant/${currentTenant.id}/clusters?highlight=${clusterId}`);
    },
    [navigate, currentTenant]
  );

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('tenant.orgSettings.clusters.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.clusters.description')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void navigate(`/tenant/${currentTenant.id}/clusters`);
          }}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <Settings size={16} />
          {t('tenant.orgSettings.clusters.manage')}
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-50 p-2 dark:bg-blue-950/40">
              <Cloud size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">{stats.total}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.clusters.stats.total')}
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-green-50 p-2 dark:bg-green-950/40">
              <CheckCircle size={16} className="text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                {stats.active}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.clusters.stats.active')}
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-orange-50 p-2 dark:bg-orange-950/40">
              <Wrench size={16} className="text-orange-600 dark:text-orange-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-orange-600 dark:text-orange-400">
                {stats.maintenance}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.clusters.stats.maintenance')}
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-red-50 p-2 dark:bg-red-950/40">
              <AlertCircle size={16} className="text-red-600 dark:text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-red-600 dark:text-red-400">{stats.error}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.clusters.stats.error')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Clusters grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-primary" />
        </div>
      ) : clusters.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-12 text-center dark:border-slate-700 dark:bg-slate-900">
          <CloudOff size={48} className="mx-auto text-slate-300 dark:text-slate-600" />
          <p className="text-slate-500 dark:text-slate-400 mt-4">
            {t('tenant.orgSettings.clusters.noClusters')}
          </p>
          <button
            type="button"
            onClick={() => {
              void navigate(`/tenant/${currentTenant.id}/clusters`);
            }}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-slate-50 transition-colors hover:bg-primary-dark"
          >
            {t('tenant.orgSettings.clusters.addCluster')}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.id} cluster={cluster} onViewDetails={handleViewDetails} />
          ))}
        </div>
      )}
    </div>
  );
};

export default OrgClusters;
