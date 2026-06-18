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
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { ArchiveX, ArrowLeft, Star, UploadCloud } from 'lucide-react';

import {
  useCurrentGenome,
  useCurrentGenomeGenes,
  useCurrentGenomeGenesLoading,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketStore,
  useGeneMarketActions,
} from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

const { Title, Text, Paragraph } = Typography;

interface RateFormValues {
  score: number;
  comment?: string;
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
  } = useGeneMarketActions();
  const [isPublishSubmitting, setIsPublishSubmitting] = useState(false);
  const [isRateModalVisible, setIsRateModalVisible] = useState(false);
  const [isRateSubmitting, setIsRateSubmitting] = useState(false);
  const [rateForm] = Form.useForm<RateFormValues>();
  const genomeGeneSlugKey = genome ? genome.gene_slugs.join('\n') : null;
  const genomeGeneSlugs = useMemo(() => {
    if (genomeGeneSlugKey === null || genomeGeneSlugKey === '') {
      return [];
    }
    return genomeGeneSlugKey.split('\n');
  }, [genomeGeneSlugKey]);

  useEffect(() => {
    if (genomeId && tenantId) {
      const options = { tenant_id: tenantId };
      getGenome(genomeId, options).catch(() => {});
    }
    return () => {
      setCurrentGenome(null);
      clearError();
    };
  }, [genomeId, getGenome, setCurrentGenome, clearError, tenantId]);

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

  const showActionError = (fallbackMessage: string) => {
    message.error(useGeneMarketStore.getState().error ?? fallbackMessage);
  };

  const handlePublishToggle = async () => {
    if (!genomeId || !tenantId || !genome) {
      return;
    }
    setIsPublishSubmitting(true);
    try {
      if (genome.is_published) {
        await unpublishGenome(genomeId, { tenant_id: tenantId });
        message.success(
          t('tenant.genomeDetail.unpublishSuccess', 'Genome unpublished successfully')
        );
      } else {
        await publishGenome(genomeId, { tenant_id: tenantId });
        message.success(t('tenant.genomeDetail.publishSuccess', 'Genome published successfully'));
      }
    } catch {
      showActionError(
        genome.is_published
          ? t('tenant.genomeDetail.unpublishError', 'Failed to unpublish genome')
          : t('tenant.genomeDetail.publishError', 'Failed to publish genome')
      );
    } finally {
      setIsPublishSubmitting(false);
    }
  };

  const handleRateSubmit = async () => {
    const values = await rateForm.validateFields();
    if (!genomeId || !tenantId) {
      return;
    }

    setIsRateSubmitting(true);
    try {
      await rateGenome(
        genomeId,
        {
          rating: values.score,
          comment: values.comment ?? null,
        },
        { tenant_id: tenantId }
      );
      message.success(t('tenant.genomeDetail.rateSuccess', 'Genome rating submitted successfully'));
      setIsRateModalVisible(false);
      rateForm.resetFields();
    } catch {
      showActionError(t('tenant.genomeDetail.rateError', 'Failed to submit genome rating'));
    } finally {
      setIsRateSubmitting(false);
    }
  };

  if (loading && !genome) {
    return (
      <div className="flex justify-center p-12">
        <Spin size="large" />
      </div>
    );
  }

  if (!genome && !loading) {
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
            <Tag color={genome.visibility === 'public' ? 'green' : 'default'}>
              {genome.visibility}
            </Tag>
          </Space>
        </div>
        <Space wrap>
          <Button
            onClick={() => {
              void handlePublishToggle();
            }}
            loading={isPublishSubmitting}
            danger={genome.is_published}
            icon={
              genome.is_published ? (
                <ArchiveX className="w-4 h-4" />
              ) : (
                <UploadCloud className="w-4 h-4" />
              )
            }
          >
            {genome.is_published
              ? t('tenant.genes.unpublishAction', 'Unpublish')
              : t('tenant.genes.publishAction', 'Publish')}
          </Button>
          <Button
            onClick={() => {
              setIsRateModalVisible(true);
            }}
            icon={<Star className="w-4 h-4" />}
          >
            {t('tenant.genomeDetail.rateAction', 'Rate')}
          </Button>
        </Space>
      </div>

      {error && <Alert type="error" title={error} closable={{ onClose: clearError }} />}

      <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
        <Descriptions column={2} bordered>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.id', 'ID')}>
            <Paragraph copyable className="!mb-0">
              {genome.id}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.visibility', 'Visibility')}>
            {genome.visibility}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.status', 'Status')}>
            {genome.is_published
              ? t('tenant.genes.statusPublished', 'Published')
              : t('tenant.genes.statusDraft', 'Draft')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.genomeDetail.fields.createdAt', 'Created At')}>
            {new Date(genome.created_at).toLocaleString()}
          </Descriptions.Item>
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

      <Modal
        title={t('tenant.genomeDetail.rateGenome', 'Rate Genome')}
        open={isRateModalVisible}
        onOk={() => {
          void handleRateSubmit();
        }}
        onCancel={() => {
          setIsRateModalVisible(false);
          rateForm.resetFields();
        }}
        confirmLoading={isRateSubmitting}
      >
        <Form form={rateForm} layout="vertical" className="mt-4" initialValues={{ score: 5 }}>
          <Form.Item
            name="score"
            label={t('tenant.genes.rating')}
            rules={[{ required: true, message: t('tenant.genes.ratingRequired') }]}
          >
            <Rate allowHalf />
          </Form.Item>

          <Form.Item name="comment" label={t('tenant.genes.comment')}>
            <Input.TextArea rows={4} placeholder={t('tenant.genes.commentPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
