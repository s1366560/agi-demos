import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import {
  Alert,
  Tabs,
  Input,
  Select,
  Button,
  Form,
  Modal,
  message,
  Tag,
  Space,
  Card,
  Rate,
  Empty,
  Pagination,
} from 'antd';
import { Download, Search as SearchIcon } from 'lucide-react';

import {
  useGenes,
  useGenomes,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneTotal,
  useGenomeTotal,
  useActiveTab,
  useGeneMarketActions,
} from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

import type {
  GeneCreate,
  GeneListParams,
  GeneResponse,
  GenomeCreate,
  GenomeListParams,
  GenomeResponse,
} from '../../services/geneMarketService';

const { Search } = Input;
const { Option } = Select;
type PublishStatusFilter = 'all' | 'published' | 'draft';

interface PublishGeneFormValues {
  name: string;
  slug: string;
  category?: string;
  version?: string;
  short_description?: string;
  description?: string;
  visibility?: 'public' | 'org_private';
  tags?: string;
  gene_slugs?: string;
}

const normalizeOptionalText = (value: string | undefined): string | undefined => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
};

const splitTags = (value: string | undefined): string[] =>
  Array.from(
    new Set(
      (value ?? '')
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean)
    )
  );

const isFormValidationError = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && 'errorFields' in error;

export const GeneMarket: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;

  const genes = useGenes();
  const genomes = useGenomes();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const geneTotal = useGeneTotal();
  const genomeTotal = useGenomeTotal();
  const activeTab = useActiveTab();

  const { listGenes, listGenomes, createGene, createGenome, setActiveTab, clearError, reset } =
    useGeneMarketActions();

  const [geneSearchInput, setGeneSearchInput] = useState('');
  const [genomeSearchInput, setGenomeSearchInput] = useState('');
  const [geneSearch, setGeneSearch] = useState('');
  const [genomeSearch, setGenomeSearch] = useState('');
  const [geneCategory, setGeneCategory] = useState('all');
  const [geneVisibility, setGeneVisibility] = useState('all');
  const [genomeVisibility, setGenomeVisibility] = useState('all');
  const [genePublishStatus, setGenePublishStatus] = useState<PublishStatusFilter>('all');
  const [genomePublishStatus, setGenomePublishStatus] = useState<PublishStatusFilter>('all');
  const [genePage, setGenePage] = useState(1);
  const [genePageSize, setGenePageSize] = useState(20);
  const [genomePage, setGenomePage] = useState(1);
  const [genomePageSize, setGenomePageSize] = useState(20);
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const [isPublishSubmitting, setIsPublishSubmitting] = useState(false);
  const [publishForm] = Form.useForm<PublishGeneFormValues>();

  const geneListParams = useMemo<GeneListParams>(() => {
    const params: GeneListParams = {
      page: genePage,
      page_size: genePageSize,
    };
    if (tenantId) {
      params.tenant_id = tenantId;
    }
    if (geneSearch) {
      params.search = geneSearch;
    }
    if (geneCategory !== 'all') {
      params.category = geneCategory;
    }
    if (geneVisibility !== 'all') {
      params.visibility = geneVisibility;
    }
    if (genePublishStatus !== 'all') {
      params.is_published = genePublishStatus === 'published';
    }
    return params;
  }, [
    geneCategory,
    genePage,
    genePageSize,
    genePublishStatus,
    geneSearch,
    geneVisibility,
    tenantId,
  ]);

  const genomeListParams = useMemo<GenomeListParams>(() => {
    const params: GenomeListParams = {
      page: genomePage,
      page_size: genomePageSize,
      tenant_id: tenantId,
    };
    if (genomePublishStatus !== 'all') {
      params.is_published = genomePublishStatus === 'published';
    }
    if (genomeSearch) {
      params.search = genomeSearch;
    }
    if (genomeVisibility !== 'all') {
      params.visibility = genomeVisibility;
    }
    return params;
  }, [genomePage, genomePageSize, genomePublishStatus, genomeSearch, genomeVisibility, tenantId]);

  const loadActiveTab = useCallback(() => {
    if (!tenantId) {
      return Promise.resolve();
    }
    if (activeTab === 'genes') {
      return listGenes(geneListParams);
    }
    return listGenomes(genomeListParams);
  }, [activeTab, geneListParams, genomeListParams, listGenes, listGenomes, tenantId]);

  useEffect(() => {
    void loadActiveTab().catch(() => undefined);
  }, [loadActiveTab]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

  const handleTabChange = (key: string) => {
    setActiveTab(key as 'genes' | 'genomes');
  };

  const handlePublishGene = () => {
    publishForm.resetFields();
    setIsPublishModalOpen(true);
  };

  const handleCreateMarketplaceDraft = async () => {
    if (!tenantId) {
      return;
    }
    try {
      const values = await publishForm.validateFields();
      setIsPublishSubmitting(true);
      if (activeTab === 'genomes') {
        const payload: GenomeCreate = {
          name: values.name.trim(),
          slug: values.slug.trim(),
          tenant_id: tenantId,
          visibility: values.visibility ?? 'public',
          gene_slugs: splitTags(values.gene_slugs),
        };
        const shortDescription = normalizeOptionalText(values.short_description);
        if (shortDescription) {
          payload.short_description = shortDescription;
        }
        const description = normalizeOptionalText(values.description);
        if (description) {
          payload.description = description;
        }
        const created = await createGenome(payload, { tenant_id: tenantId });
        message.success(t('tenant.genes.publish.createGenomeDraftSuccess'));
        setIsPublishModalOpen(false);
        publishForm.resetFields();
        void navigate(`./genomes/${created.id}`);
        return;
      }

      const payload: GeneCreate = {
        name: values.name.trim(),
        slug: values.slug.trim(),
        tenant_id: tenantId,
        version: normalizeOptionalText(values.version) ?? '1.0.0',
        visibility: values.visibility ?? 'public',
        tags: splitTags(values.tags),
        source: 'manual',
      };
      const category = normalizeOptionalText(values.category);
      if (category) {
        payload.category = category;
      }
      const shortDescription = normalizeOptionalText(values.short_description);
      if (shortDescription) {
        payload.short_description = shortDescription;
      }
      const description = normalizeOptionalText(values.description);
      if (description) {
        payload.description = description;
      }
      const created = await createGene(payload, { tenant_id: tenantId });
      message.success(t('tenant.genes.publish.createDraftSuccess'));
      setIsPublishModalOpen(false);
      publishForm.resetFields();
      void navigate(created.id);
    } catch (error) {
      if (isFormValidationError(error)) {
        return;
      }
      if (error instanceof Error) {
        message.error(error.message);
        return;
      }
      message.error(
        activeTab === 'genomes'
          ? t('tenant.genes.publish.createGenomeDraftError')
          : t('tenant.genes.publish.createDraftError')
      );
    } finally {
      setIsPublishSubmitting(false);
    }
  };

  const handleGeneSearch = useCallback((value: string) => {
    setGeneSearch(value.trim());
    setGenePage(1);
  }, []);

  const handleGenomeSearch = useCallback((value: string) => {
    setGenomeSearch(value.trim());
    setGenomePage(1);
  }, []);

  const handleGenePageChange = useCallback((page: number, pageSize: number) => {
    setGenePage(page);
    setGenePageSize(pageSize);
  }, []);

  const handleGenomePageChange = useCallback((page: number, pageSize: number) => {
    setGenomePage(page);
    setGenomePageSize(pageSize);
  }, []);

  const handleStatusChange = useCallback(
    (value: PublishStatusFilter) => {
      if (activeTab === 'genes') {
        setGenePublishStatus(value);
        setGenePage(1);
        return;
      }
      setGenomePublishStatus(value);
      setGenomePage(1);
    },
    [activeTab]
  );

  const renderStars = (rating: number | null | undefined, count: number = 0) => {
    const val = rating ?? 0;
    return (
      <Space size="small" className="items-center">
        <Rate disabled allowHalf value={val} className="text-sm" />
        <span className="text-sm text-slate-500">
          {val.toFixed(1)} ({count} {t('tenant.genes.ratings')})
        </span>
      </Space>
    );
  };

  const getVisibilityBadge = (visibility: string) => {
    const colors: Record<string, string> = {
      public: 'green',
      org_private: 'red',
      unlisted: 'default',
    };
    return <Tag color={colors[visibility] || 'default'}>{visibility}</Tag>;
  };

  const getPublishStatusBadge = (isPublished: boolean) => (
    <Tag color={isPublished ? 'green' : 'default'}>
      {isPublished
        ? t('tenant.genes.statusPublished', 'Published')
        : t('tenant.genes.statusDraft', 'Draft')}
    </Tag>
  );

  const renderGenesGrid = () => (
    <div className="flex flex-col gap-6">
      {genes.length === 0 ? (
        <Empty description={t('tenant.genes.empty', 'No genes found')} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {genes.map((gene: GeneResponse) => (
            <Card
              key={gene.id}
              className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors cursor-pointer"
              onClick={() => {
                void navigate(gene.id);
              }}
              actions={[
                <Button
                  key="install"
                  type="link"
                  onClick={(e) => {
                    e.stopPropagation();
                    void navigate(`${gene.id}?install=1`);
                  }}
                >
                  {t('tenant.genes.actions.install')}
                </Button>,
                <Button
                  key="rate"
                  type="link"
                  onClick={(e) => {
                    e.stopPropagation();
                    void navigate(`${gene.id}?rate=1`);
                  }}
                >
                  {t('tenant.genes.actions.rate')}
                </Button>,
              ]}
            >
              <div className="flex justify-between items-start gap-2 mb-2">
                <h3 className="min-w-0 flex-1 text-lg font-semibold truncate">{gene.name}</h3>
                <Space size={[4, 4]} wrap className="justify-end">
                  {getPublishStatusBadge(gene.is_published)}
                  {getVisibilityBadge(gene.visibility)}
                </Space>
              </div>

              <div className="mb-2">
                <Tag color="blue">{gene.category}</Tag>
                <span className="text-slate-500 text-sm ml-2">v{gene.version}</span>
              </div>

              <p className="text-slate-600 dark:text-slate-400 text-sm mb-4 line-clamp-2 min-h-10">
                {gene.description}
              </p>

              <div className="mb-4">
                {gene.tags.slice(0, 3).map((tag) => (
                  <Tag key={tag} className="mr-1 mb-1">
                    {tag}
                  </Tag>
                ))}
                {gene.tags.length > 3 && <Tag>...</Tag>}
              </div>

              <div className="flex justify-between items-center text-sm text-slate-500">
                <div>
                  <Download size={14} className="mr-1 align-text-bottom" />
                  {gene.install_count}
                </div>
                {renderStars(gene.avg_rating, 0)}
              </div>
            </Card>
          ))}
        </div>
      )}
      {geneTotal > genePageSize ? (
        <Pagination
          current={genePage}
          pageSize={genePageSize}
          total={geneTotal}
          showSizeChanger
          pageSizeOptions={['20', '50', '100']}
          onChange={handleGenePageChange}
          className="self-end"
        />
      ) : null}
    </div>
  );

  const renderGenomesGrid = () => (
    <div className="flex flex-col gap-6">
      {genomes.length === 0 ? (
        <Empty description={t('tenant.genes.emptyGenomes', 'No genomes found')} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {genomes.map((genome: GenomeResponse) => (
            <Card
              key={genome.id}
              className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary-300 dark:hover:border-primary-600 transition-colors cursor-pointer"
              onClick={() => {
                void navigate(`./genomes/${genome.id}`);
              }}
            >
              <div className="flex justify-between items-start gap-2 mb-2">
                <h3 className="min-w-0 flex-1 text-lg font-semibold truncate">{genome.name}</h3>
                <Space size={[4, 4]} wrap className="justify-end">
                  {getPublishStatusBadge(genome.is_published)}
                  {getVisibilityBadge(genome.visibility)}
                </Space>
              </div>

              <p className="text-slate-600 dark:text-slate-400 text-sm mb-4 line-clamp-2 min-h-10">
                {genome.description}
              </p>

              <div className="mb-4 flex gap-2">
                <Tag color="purple">
                  {genome.gene_slugs.length} {t('tenant.genes.genesCount')}
                </Tag>
              </div>

              <div className="flex justify-end items-center text-sm text-slate-500">
                {renderStars(genome.avg_rating, 0)}
              </div>
            </Card>
          ))}
        </div>
      )}
      {genomeTotal > genomePageSize ? (
        <Pagination
          current={genomePage}
          pageSize={genomePageSize}
          total={genomeTotal}
          showSizeChanger
          pageSizeOptions={['20', '50', '100']}
          onChange={handleGenomePageChange}
          className="self-end"
        />
      ) : null}
    </div>
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('tenant.genes.title')}</h1>
          <p className="text-slate-500">{t('tenant.genes.subtitle')}</p>
        </div>
        <Button type="primary" onClick={handlePublishGene} disabled={!tenantId}>
          {activeTab === 'genomes'
            ? t('tenant.genes.publishGenomeButton')
            : t('tenant.genes.publishButton')}
        </Button>
      </div>

      <div className="flex flex-col gap-4 bg-white dark:bg-slate-800 p-4 rounded-lg border border-slate-200 dark:border-slate-700 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <Search
            aria-label={
              activeTab === 'genes'
                ? t('tenant.genes.searchPlaceholder')
                : t('tenant.genes.searchGenomesPlaceholder')
            }
            placeholder={
              activeTab === 'genes'
                ? t('tenant.genes.searchPlaceholder')
                : t('tenant.genes.searchGenomesPlaceholder')
            }
            allowClear
            value={activeTab === 'genes' ? geneSearchInput : genomeSearchInput}
            onChange={(event) => {
              const nextValue = event.target.value;
              if (activeTab === 'genes') {
                setGeneSearchInput(nextValue);
                if (nextValue === '') {
                  handleGeneSearch('');
                }
                return;
              }
              setGenomeSearchInput(nextValue);
              if (nextValue === '') {
                handleGenomeSearch('');
              }
            }}
            onSearch={activeTab === 'genes' ? handleGeneSearch : handleGenomeSearch}
            enterButton={
              <>
                <span className="sr-only">{t('common.search', 'Search')}</span>
                <SearchIcon size={16} aria-hidden="true" />
              </>
            }
            className="w-full max-w-md"
          />
        </div>
        <Space wrap className="w-full lg:w-auto">
          {activeTab === 'genes' && (
            <>
              <Select
                aria-label={t('tenant.genes.filters.categoryLabel')}
                value={geneCategory}
                onChange={(value) => {
                  setGeneCategory(value);
                  setGenePage(1);
                }}
                className="w-full sm:w-36"
              >
                <Option value="all">{t('tenant.genes.filters.allCategories')}</Option>
                <Option value="ai">{t('tenant.genes.filters.catAi')}</Option>
                <Option value="tool">{t('tenant.genes.filters.catTool')}</Option>
              </Select>
              <Select
                aria-label={t('tenant.genes.filters.visibilityLabel')}
                value={geneVisibility}
                onChange={(value) => {
                  setGeneVisibility(value);
                  setGenePage(1);
                }}
                className="w-full sm:w-36"
              >
                <Option value="all">{t('tenant.genes.filters.allVisibility')}</Option>
                <Option value="public">{t('tenant.genes.filters.visPublic')}</Option>
                <Option value="org_private">{t('tenant.genes.filters.visPrivate')}</Option>
              </Select>
            </>
          )}
          {activeTab === 'genomes' && (
            <Select
              aria-label={t('tenant.genes.filters.genomeVisibilityLabel')}
              value={genomeVisibility}
              onChange={(value) => {
                setGenomeVisibility(value);
                setGenomePage(1);
              }}
              className="w-full sm:w-36"
            >
              <Option value="all">{t('tenant.genes.filters.allVisibility')}</Option>
              <Option value="public">{t('tenant.genes.filters.visPublic')}</Option>
              <Option value="org_private">{t('tenant.genes.filters.visPrivate')}</Option>
            </Select>
          )}
          <Select
            aria-label={t('tenant.genes.filters.statusLabel', 'Filter by publish status')}
            value={activeTab === 'genes' ? genePublishStatus : genomePublishStatus}
            onChange={handleStatusChange}
            className="w-full sm:w-40"
          >
            <Option value="all">{t('tenant.genes.filters.allStatus', 'All Status')}</Option>
            <Option value="published">{t('tenant.genes.statusPublished', 'Published')}</Option>
            <Option value="draft">{t('tenant.genes.statusDraft', 'Draft')}</Option>
          </Select>
        </Space>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          title={t('tenant.genes.listErrorTitle', 'Could not load marketplace data')}
          description={error}
          closable={{ onClose: clearError }}
          action={
            <Button
              size="small"
              onClick={() => {
                void loadActiveTab().catch(() => undefined);
              }}
            >
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      )}

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          {
            key: 'genes',
            label: `${t('tenant.genes.tabs.genes')} (${String(geneTotal)})`,
            children: loading ? <div>{t('tenant.genes.loading')}</div> : renderGenesGrid(),
          },
          {
            key: 'genomes',
            label: `${t('tenant.genes.tabs.genomes')} (${String(genomeTotal)})`,
            children: loading ? <div>{t('tenant.genes.loading')}</div> : renderGenomesGrid(),
          },
        ]}
      />

      <Modal
        title={
          activeTab === 'genomes'
            ? t('tenant.genes.publish.genomeModalTitle')
            : t('tenant.genes.publish.modalTitle')
        }
        open={isPublishModalOpen}
        onOk={() => {
          void handleCreateMarketplaceDraft();
        }}
        onCancel={() => {
          setIsPublishModalOpen(false);
          publishForm.resetFields();
        }}
        okText={
          activeTab === 'genomes'
            ? t('tenant.genes.publish.createGenomeDraft')
            : t('tenant.genes.publish.createDraft')
        }
        confirmLoading={isPublishSubmitting}
        destroyOnHidden
      >
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          {activeTab === 'genomes'
            ? t('tenant.genes.publish.genomeModalDescription')
            : t('tenant.genes.publish.modalDescription')}
        </p>
        <Form
          form={publishForm}
          layout="vertical"
          initialValues={{ version: '1.0.0', visibility: 'public' }}
        >
          <Form.Item
            name="name"
            label={t('tenant.genes.publish.name')}
            rules={[{ required: true, message: t('tenant.genes.publish.nameRequired') }]}
          >
            <Input placeholder={t('tenant.genes.publish.namePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="slug"
            label={t('tenant.genes.publish.slug')}
            rules={[{ required: true, message: t('tenant.genes.publish.slugRequired') }]}
          >
            <Input placeholder={t('tenant.genes.publish.slugPlaceholder')} />
          </Form.Item>
          {activeTab === 'genes' && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Form.Item name="category" label={t('tenant.genes.publish.category')}>
                <Input placeholder={t('tenant.genes.publish.categoryPlaceholder')} />
              </Form.Item>
              <Form.Item name="version" label={t('tenant.genes.publish.version')}>
                <Input placeholder="1.0.0" />
              </Form.Item>
            </div>
          )}
          <Form.Item name="short_description" label={t('tenant.genes.publish.shortDescription')}>
            <Input placeholder={t('tenant.genes.publish.shortDescriptionPlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('tenant.genes.description')}>
            <Input.TextArea
              rows={4}
              placeholder={t('tenant.genes.publish.descriptionPlaceholder')}
            />
          </Form.Item>
          <Form.Item name="visibility" label={t('tenant.genes.publish.visibility')}>
            <Select>
              <Option value="public">{t('tenant.genes.filters.visPublic')}</Option>
              <Option value="org_private">{t('tenant.genes.filters.visPrivate')}</Option>
            </Select>
          </Form.Item>
          {activeTab === 'genomes' ? (
            <Form.Item name="gene_slugs" label={t('tenant.genes.publish.geneSlugs')}>
              <Input placeholder={t('tenant.genes.publish.geneSlugsPlaceholder')} />
            </Form.Item>
          ) : (
            <Form.Item name="tags" label={t('tenant.genes.publish.tags')}>
              <Input placeholder={t('tenant.genes.publish.tagsPlaceholder')} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};
