import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input, Tag, Button as AntButton } from 'antd';
import { ArrowLeft, BarChart, CheckCircle, Package, Plus, Puzzle, Trash2 } from 'lucide-react';

import { httpClient } from '@/services/client/httpClient';
import type { GeneResponse } from '@/services/geneMarketService';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazyEmpty,
  LazySpin,
  LazyModal,
} from '@/components/ui/lazyAntd';

const { Search } = Input;

// Types based on backend InstanceGeneResponse
interface InstanceGene {
  id: string;
  instance_id: string;
  gene_id: string;
  genome_id: string | null;
  status: string;
  installed_version: string | null;
  config_snapshot: Record<string, unknown>;
  usage_count: number;
  installed_at: string | null;
  created_at: string;
  // Extra fields from gene details
  gene_name?: string;
  gene_description?: string;
  gene_category?: string;
}

interface InstanceGeneListResponse {
  items: InstanceGene[];
  total: number;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'green',
  inactive: 'default',
  pending: 'blue',
  error: 'red',
  disabled: 'gray',
};

export const InstanceGenes: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const message = useLazyMessage();

  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [instanceGenes, setInstanceGenes] = useState<InstanceGene[]>([]);
  const [search, setSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [availableGenes, setAvailableGenes] = useState<GeneResponse[]>([]);
  const [isGenesLoading, setIsGenesLoading] = useState(false);
  const [selectedGeneId, setSelectedGeneId] = useState<string | null>(null);

  const fetchInstanceGenes = useCallback(async () => {
    if (!instanceId) return;
    setIsLoading(true);
    try {
      const response = await httpClient.get<InstanceGeneListResponse>(
        `/genes/instances/${instanceId}/genes`
      );
      setInstanceGenes(response.items);
    } catch (error) {
      console.error('Failed to fetch instance genes:', error);
      message?.error(t('tenant.instances.genes.fetchError'));
    } finally {
      setIsLoading(false);
    }
  }, [instanceId, message, t]);

  const fetchAvailableGenes = useCallback(async () => {
    setIsGenesLoading(true);
    try {
      const response = await httpClient.get<{ genes: GeneResponse[] }>('/genes', {
        params: { is_published: true, page_size: 100 },
      });
      setAvailableGenes(response.genes);
    } catch (error) {
      console.error('Failed to fetch available genes:', error);
    } finally {
      setIsGenesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInstanceGenes();
  }, [fetchInstanceGenes]);

  useEffect(() => {
    if (isAddModalOpen) {
      fetchAvailableGenes();
    }
  }, [isAddModalOpen, fetchAvailableGenes]);

  const filteredGenes = useMemo(() => {
    if (!search) return instanceGenes;
    const q = search.toLowerCase();
    return instanceGenes.filter(
      (g) =>
        g.gene_id.toLowerCase().includes(q) ||
        (g.gene_name && g.gene_name.toLowerCase().includes(q)) ||
        (g.gene_category && g.gene_category.toLowerCase().includes(q))
    );
  }, [instanceGenes, search]);

  const installedGeneIds = useMemo(
    () => new Set(instanceGenes.map((g) => g.gene_id)),
    [instanceGenes]
  );

  const genesNotInstalled = useMemo(
    () => availableGenes.filter((g) => !installedGeneIds.has(g.id)),
    [availableGenes, installedGeneIds]
  );

  const handleInstallGene = useCallback(async () => {
    if (!instanceId || !selectedGeneId) return;
    setIsSubmitting(true);
    try {
      await httpClient.post(`/genes/instances/${instanceId}/install`, {
        gene_id: selectedGeneId,
        config: {},
      });
      message?.success(t('tenant.instances.genes.installSuccess'));
      setIsAddModalOpen(false);
      setSelectedGeneId(null);
      fetchInstanceGenes();
    } catch (error) {
      console.error('Failed to install gene:', error);
      message?.error(t('tenant.instances.genes.installError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [instanceId, selectedGeneId, message, t, fetchInstanceGenes]);

  const handleUninstallGene = useCallback(
    async (instanceGeneId: string) => {
      if (!instanceId) return;
      setIsSubmitting(true);
      try {
        await httpClient.delete(`/genes/instances/${instanceId}/genes/${instanceGeneId}`);
        message?.success(t('tenant.instances.genes.uninstallSuccess'));
        fetchInstanceGenes();
      } catch (error) {
        console.error('Failed to uninstall gene:', error);
        message?.error(t('tenant.instances.genes.uninstallError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [instanceId, message, t, fetchInstanceGenes]
  );

  const handleGoBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

  const handleViewGene = useCallback(
    (geneId: string) => {
      navigate(`/tenant/genes/${geneId}`);
    },
    [navigate]
  );

  if (!instanceId) return null;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={handleGoBack}
          type="button"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 mb-3"
        >
          <ArrowLeft size={16} />
          {t('common.back')}
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
              {t('tenant.instances.genes.title')}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t('tenant.instances.genes.description')}
            </p>
          </div>
          <button
            onClick={() => {
              setIsAddModalOpen(true);
            }}
            type="button"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
          >
            <Plus size={16} />
            {t('tenant.instances.genes.installGene')}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <Puzzle size={16} className="text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {instanceGenes.length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.genes.totalGenes')}
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
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {instanceGenes.filter((g) => g.status === 'active').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.genes.activeGenes')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <BarChart size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {instanceGenes.reduce((sum, g) => sum + g.usage_count, 0)}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.genes.totalUsage')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4">
        <Search
          placeholder={t('tenant.instances.genes.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          allowClear
          className="max-w-sm"
        />
      </div>

      {/* Genes Table */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : filteredGenes.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.genes.noGenes')} />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.genes.colGene')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.genes.colStatus')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.genes.colVersion')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.genes.colUsage')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.genes.colInstalled')}
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('common.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredGenes.map((gene) => (
                <tr
                  key={gene.id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                        <Puzzle size={16} className="text-purple-600 dark:text-purple-400" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {gene.gene_name || gene.gene_id}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {gene.gene_category || '-'}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <Tag color={STATUS_COLORS[gene.status] || 'default'}>
                      {t(`tenant.instances.genes.status.${gene.status}`, gene.status)}
                    </Tag>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                    {gene.installed_version || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                    {gene.usage_count}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                    {gene.installed_at ? new Date(gene.installed_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <AntButton
                        type="link"
                        size="small"
                        onClick={() => {
                          handleViewGene(gene.gene_id);
                        }}
                        className="p-0"
                      >
                        {t('common.view')}
                      </AntButton>
                      <LazyPopconfirm
                        title={t('tenant.instances.genes.uninstallConfirm')}
                        onConfirm={() => handleUninstallGene(gene.id)}
                        okText={t('common.confirm')}
                        cancelText={t('common.cancel')}
                      >
                        <button
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                          type="button"
                          disabled={isSubmitting}
                        >
                          <Trash2 size={16} />
                          {t('common.remove')}
                        </button>
                      </LazyPopconfirm>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Install Gene Modal */}
      <LazyModal
        title={t('tenant.instances.genes.installGene')}
        open={isAddModalOpen}
        onOk={handleInstallGene}
        onCancel={() => {
          setIsAddModalOpen(false);
          setSelectedGeneId(null);
        }}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !selectedGeneId }}
        width={600}
      >
        <div className="space-y-4 py-2">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.instances.genes.selectGeneDescription')}
          </p>
          {isGenesLoading ? (
            <div className="flex justify-center py-8">
              <LazySpin />
            </div>
          ) : genesNotInstalled.length === 0 ? (
            <div className="text-center py-8">
              <Package size={16} className="text-4xl text-slate-300 dark:text-slate-600" />
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                {t('tenant.instances.genes.noAvailableGenes')}
              </p>
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto border border-slate-200 dark:border-slate-600 rounded-lg">
              {genesNotInstalled.map((gene) => (
                <button
                  key={gene.id}
                  type="button"
                  onClick={() => {
                    setSelectedGeneId(gene.id);
                  }}
                  className={`w-full text-left px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-3 transition-colors border-b border-slate-100 dark:border-slate-700 last:border-b-0 ${
                    selectedGeneId === gene.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                  }`}
                >
                  <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center flex-shrink-0">
                    <Puzzle size={16} className="text-purple-600 dark:text-purple-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                      {gene.name}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                      {gene.description || t('tenant.instances.genes.noDescription')}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Tag color="blue">{gene.version}</Tag>
                    {gene.category && <Tag>{gene.category}</Tag>}
                  </div>
                  {selectedGeneId === gene.id && (
                    <CheckCircle size={16} className="text-blue-600 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </LazyModal>
    </div>
  );
};
