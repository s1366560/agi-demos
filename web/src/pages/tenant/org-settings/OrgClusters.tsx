/**
 * Organization Clusters Page
 *
 * Lists all organization clusters with status overview and quick actions.
 */

import React, { useCallback, useEffect, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { AlertCircle, CheckCircle, Cloud, CloudOff, Eye, Loader2, Server, Settings, Wrench } from 'lucide-react';

import { useClusters, useClusterLoading, useClusterActions } from '@/stores/cluster';
import { useTenantStore } from '@/stores/tenant';

import type { ClusterResponse } from '@/services/clusterService';

const getStatusConfig = (status: string): { color: string; bgColor: string; label: string } => {
  switch (status) {
    case 'active':
      return {
        color: 'text-green-600 dark:text-green-400',
        bgColor: 'bg-green-100 dark:bg-green-900/30',
        label: 'Active',
      };
    case 'maintenance':
      return {
        color: 'text-orange-600 dark:text-orange-400',
        bgColor: 'bg-orange-100 dark:bg-orange-900/30',
        label: 'Maintenance',
      };
    case 'error':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-100 dark:bg-red-900/30',
        label: 'Error',
      };
    case 'inactive':
      return {
        color: 'text-slate-600 dark:text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-700',
        label: 'Inactive',
      };
    default:
      return {
        color: 'text-slate-600 dark:text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-700',
        label: 'Unknown',
      };
  }
};

const getProviderIcon = (provider: string) => {
  switch (provider?.toLowerCase()) {
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
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${statusConfig.bgColor}`}>
            {/* eslint-disable-next-line react-hooks/static-components */}
            {(() => { const Icon = getProviderIcon(cluster.compute_provider); return <Icon size={24} className={statusConfig.color} />; })()}
          </div>
          <div>
            <h3 className="font-semibold text-slate-900 dark:text-white">{cluster.name}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">{cluster.compute_provider}</p>
          </div>
        </div>
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.color}`}
        >
          {statusConfig.label}
        </span>
      </div>

      {/* Cluster metrics placeholder */}
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="text-center p-2 bg-slate-50 dark:bg-slate-700/50 rounded-lg">
          <p className="text-lg font-bold text-slate-900 dark:text-white">
            {cluster.health_status ?? 'N/A'}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.clusters.health')}
          </p>
        </div>
        <div className="text-center p-2 bg-slate-50 dark:bg-slate-700/50 rounded-lg">
          <p className="text-lg font-bold text-slate-900 dark:text-white">{cluster.status}</p>
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
    listClusters();
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
      navigate(`/tenant/${currentTenant?.id}/clusters?highlight=${clusterId}`);
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
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('tenant.orgSettings.clusters.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.clusters.description')}
          </p>
        </div>
        <button
          onClick={() => navigate(`/tenant/${currentTenant.id}/clusters`)}
          type="button"
          className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors text-sm font-medium"
        >
          <Settings size={16} />
          {t('tenant.orgSettings.clusters.manage')}
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Cloud size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{stats.total}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.clusters.stats.total')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
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
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
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
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
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
          <Loader2 size={16} className="animate-spin text-primary text-3xl" />
        </div>
      ) : clusters.length === 0 ? (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-12 text-center">
          <CloudOff size={16} className="text-slate-300 dark:text-slate-600 text-5xl" />
          <p className="text-slate-500 dark:text-slate-400 mt-4">
            {t('tenant.orgSettings.clusters.noClusters')}
          </p>
          <button
            onClick={() => navigate(`/tenant/${currentTenant.id}/clusters`)}
            type="button"
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
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
