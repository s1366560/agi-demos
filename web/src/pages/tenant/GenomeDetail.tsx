import React, { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Rate,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { ArrowLeft, Download, Edit2, Star, Trash2 } from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import { InstallEntityModal } from '@/components/marketplace/InstallEntityModal';
import { PublishToggleButton } from '@/components/marketplace/PublishToggleButton';
import { RateEntityModal } from '@/components/marketplace/RateEntityModal';
import { useDeleteEntityConfirm } from '@/components/marketplace/useDeleteEntityConfirm';

import {
  useCurrentGenome,
  useCurrentGenomeGenes,
  useCurrentGenomeGenesLoading,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

import { visibilityLabel, visibilityOptions, visibilityTagColor } from './geneVisibility';
import {
  isFormValidationError,
  normalizeNullableText,
  showGeneActionError,
  splitCsv,
} from './utils/geneFormUtils';

import type { ContentVisibilityValue, GenomeUpdate } from '../../services/geneMarketService';

const { Title, Text, Paragraph } = Typography;

interface EditGenomeFormValues {
  name: string;
  slug: string;
  short_description?: string;
  description?: string;
  visibility?: ContentVisibilityValue;
  gene_slugs?: string;
  config_override?: string;
}

export const GenomeDetail: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId, genomeId } = useParams<{
    tenantId?: string;
    genomeId?: string;
  }>();
  const navigate = useNavigate();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;

  const genome = useCurrentGenome();
  const genomeGenes = useCurrentGenomeGenes();
  const genomeGenesLoading = useCurrentGenomeGenesLoading();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const {
    getGenome,
    fetchGenomeGenes,
    clearError,
    setCurrentGenome,
    publishGenome,
    unpublishGenome,
    rateGenome,
    deleteGenome,
    updateGenome,
    installGenome,
  } = useGeneMarketActions();
  const [isInstallModalVisible, setIsInstallModalVisible] = useState(false);
  const [isEditModalVisible, setIsEditModalVisible] = useState(false);
  const [isRateModalVisible, setIsRateModalVisible] = useState(false);
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [editForm] = Form.useForm<EditGenomeFormValues>();
  const genomeGeneSlugKey = genome ? genome.gene_slugs.join('\n') : null;
  const genomeGeneSlugs = useMemo(() => {
    if (genomeGeneSlugKey === null || genomeGeneSlugKey === '') {
      return [];
    }
    return genomeGeneSlugKey.split('\n');
  }, [genomeGeneSlugKey]);

  const [reloadKey, setReloadKey] = useState(0);

  const { isDeleting, confirmDelete } = useDeleteEntityConfirm({
    entityKind: 'genome',
    deleteEntity: deleteGenome,
    onDeleted: () => {
      void navigate(-1);
    },
  });

  useEffect(() => {
    if (genomeId && tenantId) {
      const options = { tenant_id: tenantId };
      getGenome(genomeId, options).catch(() => {});
    }
    return () => {
      setCurrentGenome(null);
      clearError();
    };
  }, [genomeId, getGenome, setCurrentGenome, clearError, tenantId, reloadKey]);

  useEffect(() => {
    if (genomeGeneSlugKey === null || !tenantId) {
      return;
    }
    void fetchGenomeGenes(genomeGeneSlugs, { tenant_id: tenantId }).catch(() => {});
  }, [fetchGenomeGenes, genomeGeneSlugKey, genomeGeneSlugs, tenantId]);

  const missingGeneSlugs = useMemo(() => {
    if (genomeGeneSlugKey === null) {
      return [];
    }
    const availableSlugs = new Set(genomeGenes.map((gene) => gene.slug));
    return genomeGeneSlugs.filter((slug) => !availableSlugs.has(slug));
  }, [genomeGeneSlugKey, genomeGeneSlugs, genomeGenes]);

  const handleInstall = async (instanceId: string, config: Record<string, unknown>) => {
    if (!genomeId || !tenantId) {
      return;
    }
    await installGenome(instanceId, genomeId, { config }, { tenant_id: tenantId });
  };

  const openEditModal = () => {
    if (!genome) {
      return;
    }
    editForm.setFieldsValue({
      name: genome.name,
      slug: genome.slug,
      short_description: genome.short_description ?? '',
      description: genome.description ?? '',
      visibility: genome.visibility,
      gene_slugs: genome.gene_slugs.join(', '),
      config_override: JSON.stringify(genome.config_override, null, 2),
    });
    setIsEditModalVisible(true);
  };

  const handleEditSubmit = async () => {
    if (!genomeId || !tenantId) {
      return;
    }

    try {
      const values = await editForm.validateFields();
      let configOverride: Record<string, unknown> = {};
      const configText = values.config_override?.trim();
      if (configText) {
        const parsedConfig = JSON.parse(configText) as unknown;
        if (
          typeof parsedConfig !== 'object' ||
          parsedConfig === null ||
          Array.isArray(parsedConfig)
        ) {
          message.error(t('tenant.genes.invalidJson', 'Invalid JSON format'));
          return;
        }
        configOverride = parsedConfig as Record<string, unknown>;
      }

      const payload: GenomeUpdate = {
        name: values.name.trim(),
        slug: values.slug.trim(),
        short_description: normalizeNullableText(values.short_description),
        description: normalizeNullableText(values.description),
        visibility: values.visibility ?? 'public',
        gene_slugs: splitCsv(values.gene_slugs),
        config_override: configOverride,
      };
      setIsEditSubmitting(true);
      await updateGenome(genomeId, payload, { tenant_id: tenantId });
      message.success(t('tenant.genomeDetail.updateSuccess', 'Genome updated successfully'));
      setIsEditModalVisible(false);
      editForm.resetFields();
    } catch (error) {
      if (error instanceof SyntaxError) {
        message.error(t('tenant.genes.invalidJson', 'Invalid JSON format'));
        return;
      }
      if (!isFormValidationError(error)) {
        showGeneActionError(t('tenant.genomeDetail.updateError', 'Failed to update genome'));
      }
    } finally {
      setIsEditSubmitting(false);
    }
  };

  if (loading && !genome) {
    return (
      <div className="max-w-4xl mx-auto w-full">
        <SkeletonLoader type="form" />
      </div>
    );
  }

  if (!genome && !loading) {
    // A load failure shows an error with retry; only genuine 404s get "not found"
    if (error) {
      return (
        <Alert
          type="error"
          title={t('tenant.genomeDetail.loadFailed', 'Failed to load genome')}
          description={error}
          showIcon
          action={
            <Button
              size="small"
              onClick={() => {
                clearError();
                setReloadKey((key) => key + 1);
              }}
            >
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      );
    }
    return (
      <Alert
        type="warning"
        title={t('tenant.genomeDetail.notFound', 'Genome not found')}
        showIcon
      />
    );
  }

  if (!genome) return null;

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              icon={<ArrowLeft size={16} />}
              onClick={() => {
                void navigate(-1);
              }}
            >
              {t('common.back', 'Back')}
            </Button>
            <Title level={3} className="!mb-0">
              {genome.name}
            </Title>
            <Space size={[4, 4]} wrap>
              <Tag color={genome.is_published ? 'green' : 'default'}>
                {genome.is_published
                  ? t('tenant.genes.statusPublished', 'Published')
                  : t('tenant.genes.statusDraft', 'Draft')}
              </Tag>
              <Tag color={visibilityTagColor(genome.visibility)}>
                {visibilityLabel(genome.visibility, t)}
              </Tag>
            </Space>
          </div>
          {genome.updated_at ? (
            <Text type="secondary" className="text-xs">
              {t('tenant.genes.lastUpdated', 'Last updated {{time}}', {
                time: formatDateTime(genome.updated_at),
              })}
            </Text>
          ) : null}
        </div>
        <Space wrap>
          <Button onClick={openEditModal} icon={<Edit2 className="w-4 h-4" />}>
            {t('tenant.genomeDetail.editAction', 'Edit')}
          </Button>
          <Button
            type="primary"
            onClick={() => {
              setIsInstallModalVisible(true);
            }}
            icon={<Download className="w-4 h-4" />}
          >
            {t('tenant.genomeDetail.installAction', 'Install')}
          </Button>
          <PublishToggleButton
            entityKind="genome"
            entityId={genomeId}
            tenantId={tenantId}
            entityName={genome.name}
            isPublished={genome.is_published}
            actions={{ publish: publishGenome, unpublish: unpublishGenome }}
          />
          <Button
            onClick={() => {
              setIsRateModalVisible(true);
            }}
            icon={<Star className="w-4 h-4" />}
          >
            {t('tenant.genomeDetail.rateAction', 'Rate')}
          </Button>
          <Button
            danger
            loading={isDeleting}
            onClick={() => {
              confirmDelete({ entityId: genomeId, tenantId, entityName: genome.name });
            }}
            icon={<Trash2 className="w-4 h-4" />}
          >
            {t('tenant.genomeDetail.deleteAction', 'Delete')}
          </Button>
        </Space>
      </div>

      {error && <Alert type="error" title={error} closable={{ onClose: clearError }} />}

      <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
        <Descriptions column={{ xs: 1, sm: 2 }} bordered>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.id', 'ID')}>
            <Paragraph copyable className="!mb-0">
              {genome.id}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.visibility', 'Visibility')}>
            {visibilityLabel(genome.visibility, t)}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.status', 'Status')}>
            {genome.is_published
              ? t('tenant.genes.statusPublished', 'Published')
              : t('tenant.genes.statusDraft', 'Draft')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.createdAt', 'Created At')}>
            {formatDateTime(genome.created_at)}
          </Descriptions.Item>
          {genome.updated_at ? (
            <Descriptions.Item label={t('tenant.genomeDetail.fields.updatedAt', 'Updated At')}>
              {formatDateTime(genome.updated_at)}
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item
            label={t('tenant.genomeDetail.fields.description', 'Description')}
            span={2}
          >
            {genome.description || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.rating', 'Rating')}>
            <Rate disabled allowHalf value={genome.avg_rating ?? 0} />
            <Text type="secondary" className="ml-2">
              ({genome.avg_rating?.toFixed(1) ?? '-'})
            </Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={t('tenant.genomeDetail.genesTitle', 'Included Genes')}
        className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
      >
        {genomeGeneSlugs.length === 0 ? (
          <Empty description={t('tenant.genomeDetail.noGenes', 'No genes in this genome')} />
        ) : genomeGenesLoading ? (
          <div className="flex items-center justify-center gap-2 py-6" role="status">
            <Spin size="small" />
            <Text type="secondary">
              {t('tenant.genomeDetail.loadingGenes', 'Loading included genes')}
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {missingGeneSlugs.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={t(
                  'tenant.genomeDetail.missingGenesTitle',
                  'Some referenced genes are unavailable'
                )}
                description={
                  <Space size={[4, 4]} wrap>
                    {missingGeneSlugs.map((slug) => (
                      <Tag key={slug}>{slug}</Tag>
                    ))}
                  </Space>
                }
              />
            )}
            {genomeGenes.length === 0 ? (
              <Empty
                description={t(
                  'tenant.genomeDetail.noAvailableGenes',
                  'No included genes are available'
                )}
              />
            ) : (
              <div role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
                {genomeGenes.map((gene) => (
                  <div key={gene.id} role="listitem" className="py-3 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Text strong>{gene.name}</Text>
                      <Tag>{gene.version}</Tag>
                      {gene.category && <Tag color="blue">{gene.category}</Tag>}
                    </div>
                    <Text type="secondary" className="mt-1 block text-sm">
                      {gene.description || '-'}
                    </Text>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {Object.keys(genome.config_override).length > 0 && (
        <Card
          title={t('tenant.genomeDetail.configTitle', 'Configuration')}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <pre className="bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto text-xs">
            {JSON.stringify(genome.config_override, null, 2)}
          </pre>
        </Card>
      )}

      <InstallEntityModal
        open={isInstallModalVisible}
        onClose={() => {
          setIsInstallModalVisible(false);
        }}
        entityKind="genome"
        installEntity={handleInstall}
      />

      <Modal
        title={t('tenant.genomeDetail.editGenome', 'Edit Genome')}
        open={isEditModalVisible}
        onOk={() => {
          void handleEditSubmit();
        }}
        onCancel={() => {
          setIsEditModalVisible(false);
          editForm.resetFields();
        }}
        confirmLoading={isEditSubmitting}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" className="mt-4">
          <Form.Item
            name="name"
            label={t('tenant.genes.publish.name', 'Name')}
            rules={[{ required: true, message: t('tenant.genes.publish.nameRequired') }]}
          >
            <Input placeholder={t('tenant.genes.publish.namePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="slug"
            label={t('tenant.genes.publish.slug', 'Slug')}
            rules={[{ required: true, message: t('tenant.genes.publish.slugRequired') }]}
          >
            <Input placeholder={t('tenant.genes.publish.slugPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="short_description"
            label={t('tenant.genes.publish.shortDescription', 'Short description')}
          >
            <Input placeholder={t('tenant.genes.publish.shortDescriptionPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('tenant.genomeDetail.fields.description', 'Description')}
          >
            <Input.TextArea
              rows={4}
              placeholder={t('tenant.genes.publish.descriptionPlaceholder')}
            />
          </Form.Item>
          <Form.Item name="visibility" label={t('tenant.genes.publish.visibility', 'Visibility')}>
            <Select options={[...visibilityOptions(t)]} />
          </Form.Item>
          <Form.Item
            name="gene_slugs"
            label={t('tenant.genes.publish.geneSlugs', 'Included gene slugs')}
          >
            <Input placeholder={t('tenant.genes.publish.geneSlugsPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="config_override"
            label={t('tenant.genomeDetail.configOverride', 'Configuration Override (JSON)')}
          >
            <Input.TextArea
              rows={4}
              className="font-mono text-sm"
              placeholder={t('tenant.genomeDetail.configOverridePlaceholder', '{"key": "value"}')}
            />
          </Form.Item>
        </Form>
      </Modal>

      <RateEntityModal
        open={isRateModalVisible}
        onClose={() => {
          setIsRateModalVisible(false);
        }}
        entityKind="genome"
        entityId={genomeId}
        tenantId={tenantId}
        rateEntity={rateGenome}
      />
    </div>
  );
};
