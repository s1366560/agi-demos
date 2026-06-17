import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  message,
  Rate,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { ArchiveX, ArrowLeft, UploadCloud } from 'lucide-react';

import {
  useCurrentGenome,
  useGenes,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

const { Title, Text, Paragraph } = Typography;

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
  const genes = useGenes();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const { getGenome, listGenes, clearError, setCurrentGenome, publishGenome, unpublishGenome } =
    useGeneMarketActions();
  const [isPublishSubmitting, setIsPublishSubmitting] = useState(false);

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
    if (!genome || !tenantId || genome.gene_slugs.length === 0) {
      return;
    }
    void listGenes({
      tenant_id: tenantId,
      slugs: genome.gene_slugs,
      page_size: Math.min(Math.max(genome.gene_slugs.length, 1), 100),
    }).catch(() => {});
  }, [genome, listGenes, tenantId]);

  const genomeGenes = genes.filter((g) => genome?.gene_slugs.includes(g.slug));

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
      message.error(
        error ??
          (genome.is_published
            ? t('tenant.genomeDetail.unpublishError', 'Failed to unpublish genome')
            : t('tenant.genomeDetail.publishError', 'Failed to publish genome'))
      );
    } finally {
      setIsPublishSubmitting(false);
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
        {genomeGenes.length === 0 ? (
          <Empty description={t('tenant.genomeDetail.noGenes', 'No genes in this genome')} />
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
    </div>
  );
};
