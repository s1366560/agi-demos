import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input, Pagination, Tag, Table } from 'antd';
import {
  BarChart,
  CheckCircle,
  Package,
  Plus,
  Puzzle,
  Search as SearchIcon,
  Trash2,
} from 'lucide-react';

import { geneMarketService } from '@/services/geneMarketService';
import type { GeneResponse, InstanceGeneResponse } from '@/services/geneMarketService';

import { useDebounce } from '@/hooks/useDebounce';

import {
  useLazyMessage,
  LazyButton,
  LazyPopconfirm,
  LazyEmpty,
  LazySpin,
  LazyModal,
} from '@/components/ui/lazyAntd';

import type { ColumnsType } from 'antd/es/table';

const { Search } = Input;

const STATUS_COLORS: Record<string, string> = {
  failed: 'red',
  forget_failed: 'red',
  forgetting: 'orange',
  installed: 'green',
  installing: 'blue',
  learn_failed: 'red',
  learning: 'blue',
  simplified: 'purple',
  uninstalling: 'orange',
};

const INSTANCE_GENES_PAGE_SIZE = 25;
const AVAILABLE_GENES_PAGE_SIZE = 20;

export const InstanceGenes: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId, instanceId } = useParams<{ tenantId: string; instanceId: string }>();
  const navigate = useNavigate();
  const messageApi = useLazyMessage();

  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [instanceGenes, setInstanceGenes] = useState<InstanceGeneResponse[]>([]);
  const [instanceGenesTotal, setInstanceGenesTotal] = useState(0);
  const [instanceGenesActiveTotal, setInstanceGenesActiveTotal] = useState(0);
  const [instanceGenesUsageTotal, setInstanceGenesUsageTotal] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 250);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [availableGenes, setAvailableGenes] = useState<GeneResponse[]>([]);
  const [availableGenesTotal, setAvailableGenesTotal] = useState(0);
  const [availableGenesPage, setAvailableGenesPage] = useState(1);
  const [availableGeneSearch, setAvailableGeneSearch] = useState('');
  const debouncedAvailableGeneSearch = useDebounce(availableGeneSearch.trim(), 250);
  const [isGenesLoading, setIsGenesLoading] = useState(false);
  const [availableGenesError, setAvailableGenesError] = useState<string | null>(null);
  const [selectedGeneId, setSelectedGeneId] = useState<string | null>(null);
  const instanceGenesRequestId = useRef(0);
  const availableGenesRequestId = useRef(0);

  const fetchInstanceGenes = useCallback(
    async (page: number) => {
      if (!tenantId || !instanceId) return;
      const requestId = instanceGenesRequestId.current + 1;
      instanceGenesRequestId.current = requestId;
      const isLatestRequest = () => instanceGenesRequestId.current === requestId;
      setIsLoading(true);
      try {
        const response = await geneMarketService.listInstanceGenes(instanceId, {
          tenant_id: tenantId,
          limit: INSTANCE_GENES_PAGE_SIZE,
          offset: (page - 1) * INSTANCE_GENES_PAGE_SIZE,
          search: debouncedSearch || undefined,
        });
        if (!isLatestRequest()) return;
        setInstanceGenes(response.items);
        setInstanceGenesTotal(response.total);
        setInstanceGenesActiveTotal(response.active_total);
        setInstanceGenesUsageTotal(response.usage_total);
        setCurrentPage(page);
      } catch (err) {
        if (!isLatestRequest()) return;
        console.error('Failed to fetch instance genes:', err);
        messageApi?.error(t('tenant.instances.genes.fetchError'));
      } finally {
        if (isLatestRequest()) {
          setIsLoading(false);
        }
      }
    },
    [debouncedSearch, instanceId, messageApi, t, tenantId]
  );

  const fetchAvailableGenes = useCallback(
    async (page: number) => {
      if (!tenantId || !instanceId) return;
      const requestId = availableGenesRequestId.current + 1;
      availableGenesRequestId.current = requestId;
      const isLatestRequest = () => availableGenesRequestId.current === requestId;
      setIsGenesLoading(true);
      setSelectedGeneId(null);
      setAvailableGenesError(null);
      try {
        const response = await geneMarketService.listGenes({
          is_published: true,
          page,
          page_size: AVAILABLE_GENES_PAGE_SIZE,
          tenant_id: tenantId,
          exclude_installed_instance_id: instanceId,
          search: debouncedAvailableGeneSearch || undefined,
        });
        if (!isLatestRequest()) return;
        setAvailableGenes(response.genes);
        setAvailableGenesTotal(response.total);
        setAvailableGenesPage(response.page);
      } catch (err) {
        if (!isLatestRequest()) return;
        console.error('Failed to fetch available genes:', err);
        setAvailableGenes([]);
        setAvailableGenesTotal(0);
        setAvailableGenesError(t('tenant.instances.genes.availableGenesError'));
        messageApi?.error(t('tenant.instances.genes.availableGenesError'));
      } finally {
        if (isLatestRequest()) {
          setIsGenesLoading(false);
        }
      }
    },
    [debouncedAvailableGeneSearch, instanceId, messageApi, t, tenantId]
  );

  useEffect(() => {
    void fetchInstanceGenes(1);
  }, [fetchInstanceGenes]);

  useEffect(() => {
    if (isAddModalOpen) {
      setSelectedGeneId(null);
      void fetchAvailableGenes(1);
    }
  }, [isAddModalOpen, fetchAvailableGenes]);

  const handleInstallGene = useCallback(async () => {
    if (!tenantId || !instanceId || !selectedGeneId) return;
    setIsSubmitting(true);
    try {
      await geneMarketService.installGene(
        instanceId,
        {
          gene_id: selectedGeneId,
          config: {},
        },
        { tenant_id: tenantId }
      );
      messageApi?.success(t('tenant.instances.genes.installSuccess'));
      setIsAddModalOpen(false);
      setSelectedGeneId(null);
      void fetchInstanceGenes(1);
    } catch (err) {
      console.error('Failed to install gene:', err);
      messageApi?.error(t('tenant.instances.genes.installError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [instanceId, selectedGeneId, messageApi, t, fetchInstanceGenes, tenantId]);

  const handleUninstallGene = useCallback(
    async (instanceGeneId: string) => {
      if (!tenantId || !instanceId) return;
      setIsSubmitting(true);
      try {
        await geneMarketService.uninstallGene(instanceId, instanceGeneId, {
          tenant_id: tenantId,
        });
        messageApi?.success(t('tenant.instances.genes.uninstallSuccess'));
        const nextPage =
          instanceGenes.length === 1 && currentPage > 1 ? currentPage - 1 : currentPage;
        void fetchInstanceGenes(nextPage);
      } catch (err) {
        console.error('Failed to uninstall gene:', err);
        messageApi?.error(t('tenant.instances.genes.uninstallError'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [currentPage, instanceGenes.length, instanceId, messageApi, t, fetchInstanceGenes, tenantId]
  );

  const handleViewGene = useCallback(
    (geneId: string) => {
      if (!tenantId) return;
      void navigate(`/tenant/${tenantId}/genes/${geneId}`);
    },
    [navigate, tenantId]
  );

  const columns: ColumnsType<InstanceGeneResponse> = useMemo(
    () => [
      {
        title: t('tenant.instances.genes.colGene'),
        key: 'gene',
        ellipsis: true,
        render: (_, gene) => (
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-lg bg-purple-bg dark:bg-purple-bg-dark flex items-center justify-center shrink-0">
              <Puzzle size={16} className="text-purple-dark dark:text-purple-light" />
            </div>
            <div className="min-w-0 truncate">
              <p className="text-sm font-medium text-text-primary dark:text-text-inverse truncate">
                {gene.gene_name || gene.gene_id}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted truncate">
                {gene.gene_category || '-'}
              </p>
            </div>
          </div>
        ),
      },
      {
        title: t('tenant.instances.genes.colStatus'),
        key: 'status',
        render: (_, gene) => (
          <Tag color={STATUS_COLORS[gene.status] || 'default'}>
            {t(`tenant.instances.genes.status.${gene.status}`, gene.status)}
          </Tag>
        ),
      },
      {
        title: t('tenant.instances.genes.colVersion'),
        key: 'version',
        render: (_, gene) => (
          <span className="text-sm text-text-muted dark:text-text-muted">
            {gene.installed_version || '-'}
          </span>
        ),
      },
      {
        title: t('tenant.instances.genes.colUsage'),
        dataIndex: 'usage_count',
        key: 'usage_count',
        render: (count: number) => (
          <span className="text-sm text-text-muted dark:text-text-muted">{count}</span>
        ),
      },
      {
        title: t('tenant.instances.genes.colInstalled'),
        key: 'installed',
        render: (_, gene) => (
          <span className="text-sm text-text-muted dark:text-text-muted">
            {gene.installed_at ? new Date(gene.installed_at).toLocaleDateString() : '-'}
          </span>
        ),
      },
      {
        title: t('common.actions.label'),
        key: 'actions',
        align: 'right',
        render: (_, gene) => (
          <div className="flex items-center justify-end gap-2">
            <LazyButton
              type="link"
              size="small"
              onClick={() => {
                handleViewGene(gene.gene_id);
              }}
              className="p-0"
            >
              {t('common.view')}
            </LazyButton>
            <LazyPopconfirm
              title={t('tenant.instances.genes.uninstallConfirm')}
              onConfirm={() => {
                void handleUninstallGene(gene.id);
              }}
              okText={t('common.confirm')}
              cancelText={t('common.cancel')}
            >
              <LazyButton
                danger
                type="text"
                size="small"
                icon={<Trash2 size={16} />}
                disabled={isSubmitting}
              >
                {t('common.remove')}
              </LazyButton>
            </LazyPopconfirm>
          </div>
        ),
      },
    ],
    [t, isSubmitting, handleViewGene, handleUninstallGene]
  );

  if (!instanceId) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* Toolbar */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('tenant.instances.genes.title')}
          </h2>
          <p className="text-sm text-text-muted">{t('tenant.instances.genes.description')}</p>
        </div>
        <LazyButton
          type="primary"
          icon={<Plus size={16} />}
          onClick={() => {
            setIsAddModalOpen(true);
          }}
        >
          {t('tenant.instances.genes.installGene')}
        </LazyButton>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-bg dark:bg-purple-bg-dark rounded-lg">
              <Puzzle size={16} className="text-purple-dark dark:text-purple-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {instanceGenesTotal}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.genes.totalGenes')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-success-bg dark:bg-success-bg-dark rounded-lg">
              <CheckCircle size={16} className="text-success-dark dark:text-success-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {instanceGenesActiveTotal}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.genes.activeGenes')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-info-bg dark:bg-info-bg-dark rounded-lg">
              <BarChart size={16} className="text-info-dark dark:text-info-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {instanceGenesUsageTotal}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
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
          enterButton={
            <>
              <span className="sr-only">{t('common.search', 'Search')}</span>
              <SearchIcon size={16} aria-hidden="true" />
            </>
          }
          className="w-full max-w-sm"
        />
      </div>

      {/* Genes Table */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : instanceGenes.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.genes.noGenes')} />
          </div>
        ) : (
          <Table<InstanceGeneResponse>
            columns={columns}
            dataSource={instanceGenes}
            rowKey="id"
            pagination={{
              current: currentPage,
              pageSize: INSTANCE_GENES_PAGE_SIZE,
              total: instanceGenesTotal,
              showSizeChanger: false,
              showTotal: (total, range) =>
                t('tenant.instances.genes.paginationTotal', {
                  from: range[0],
                  to: range[1],
                  total,
                }),
              onChange: (page) => {
                void fetchInstanceGenes(page);
              },
              disabled: isLoading,
            }}
            scroll={{ x: 'max-content' }}
            className="max-w-full"
          />
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
          <p className="text-sm text-text-muted dark:text-text-muted">
            {t('tenant.instances.genes.selectGeneDescription')}
          </p>
          <Search
            placeholder={t('tenant.instances.genes.availableSearchPlaceholder')}
            value={availableGeneSearch}
            onChange={(event) => {
              setAvailableGeneSearch(event.target.value);
            }}
            allowClear
            enterButton={
              <>
                <span className="sr-only">{t('common.search', 'Search')}</span>
                <SearchIcon size={16} aria-hidden="true" />
              </>
            }
          />
          {isGenesLoading ? (
            <div className="flex justify-center py-8">
              <LazySpin />
            </div>
          ) : availableGenesError ? (
            <div className="text-center py-8">
              <p className="text-sm text-danger dark:text-danger-light">{availableGenesError}</p>
              <LazyButton
                type="link"
                onClick={() => {
                  void fetchAvailableGenes(availableGenesPage);
                }}
              >
                {t('common.retry')}
              </LazyButton>
            </div>
          ) : availableGenes.length === 0 ? (
            <div className="text-center py-8">
              <Package
                size={16}
                className="text-4xl text-text-muted-light dark:text-text-secondary"
              />
              <p className="mt-2 text-sm text-text-muted dark:text-text-muted">
                {t('tenant.instances.genes.noAvailableGenes')}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="max-h-80 overflow-y-auto border border-border-light dark:border-border-separator rounded-lg">
                {availableGenes.map((gene) => (
                  <LazyButton
                    key={gene.id}
                    type="text"
                    block
                    onClick={() => {
                      setSelectedGeneId(gene.id);
                    }}
                    className={`h-auto w-full text-left px-4 py-3 hover:bg-surface-alt dark:hover:bg-surface-elevated flex items-center justify-start gap-3 transition-colors border-0 border-b border-solid border-border-subtle dark:border-border-dark last:border-b-0 rounded-none ${
                      selectedGeneId === gene.id ? 'bg-info-bg dark:bg-info-bg-dark' : ''
                    }`}
                  >
                    <div className="w-10 h-10 rounded-lg bg-purple-bg dark:bg-purple-bg-dark flex items-center justify-center flex-shrink-0">
                      <Puzzle size={16} className="text-purple-dark dark:text-purple-light" />
                    </div>
                    <div className="flex-1 min-w-0 text-left">
                      <p className="text-sm font-medium text-text-primary dark:text-text-inverse truncate m-0">
                        {gene.name}
                      </p>
                      <p className="text-xs text-text-muted dark:text-text-muted truncate m-0 mt-0.5">
                        {gene.description || t('tenant.instances.genes.noDescription')}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-auto">
                      <Tag color="blue" className="m-0">
                        {gene.version}
                      </Tag>
                      {gene.category && <Tag className="m-0">{gene.category}</Tag>}
                    </div>
                    {selectedGeneId === gene.id && (
                      <CheckCircle size={16} className="text-info-dark flex-shrink-0 ml-2" />
                    )}
                  </LazyButton>
                ))}
              </div>
              {availableGenesTotal > AVAILABLE_GENES_PAGE_SIZE ? (
                <Pagination
                  current={availableGenesPage}
                  pageSize={AVAILABLE_GENES_PAGE_SIZE}
                  total={availableGenesTotal}
                  showSizeChanger={false}
                  size="small"
                  onChange={(page) => {
                    void fetchAvailableGenes(page);
                  }}
                  className="text-right"
                />
              ) : null}
            </div>
          )}
        </div>
      </LazyModal>
    </div>
  );
};
