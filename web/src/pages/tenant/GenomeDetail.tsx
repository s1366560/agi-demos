import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Button, Card, Typography, Spin, Alert, Tag, Descriptions, Rate, List, Empty } from 'antd';
import { ArrowLeft } from 'lucide-react';

import {
  useCurrentGenome,
  useGenes,
  useGeneMarketLoading,
  useGeneMarketError,
  useGeneMarketActions,
} from '../../stores/geneMarket';

const { Title, Text, Paragraph } = Typography;

export const GenomeDetail: React.FC = () => {
  const { t } = useTranslation();
  const { genomeId } = useParams();
  const navigate = useNavigate();

  const genome = useCurrentGenome();
  const genes = useGenes();
  const loading = useGeneMarketLoading();
  const error = useGeneMarketError();
  const { getGenome, listGenes, clearError, setCurrentGenome } = useGeneMarketActions();

  useEffect(() => {
    if (genomeId) {
      getGenome(genomeId).catch(() => {});
      listGenes().catch(() => {});
    }
    return () => {
      setCurrentGenome(null);
      clearError();
    };
  }, [genomeId, getGenome, listGenes, setCurrentGenome, clearError]);

  const genomeGenes = genes.filter((g) => genome?.gene_ids?.includes(g.id));

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
        message={t('tenant.genomeDetail.notFound', 'Genome not found')}
        showIcon
      />
    );
  }

  if (!genome) return null;

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <Button icon={<ArrowLeft size={16} />} onClick={() => navigate(-1)}>
          {t('common.back', 'Back')}
        </Button>
        <Title level={3} className="!mb-0">
          {genome.name}
        </Title>
        <Tag color={genome.visibility === 'public' ? 'green' : 'default'}>{genome.visibility}</Tag>
      </div>

      {error && <Alert type="error" message={error} closable onClose={clearError} />}

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
          <Descriptions.Item label={t('tenant.genomeDetail.fields.createdAt', 'Created At')}>
            {new Date(genome.created_at).toLocaleString()}
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
          <List
            dataSource={genomeGenes}
            renderItem={(gene) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <div className="flex items-center gap-2">
                      <Text strong>{gene.name}</Text>
                      <Tag>{gene.version}</Tag>
                      {gene.category && <Tag color="blue">{gene.category}</Tag>}
                    </div>
                  }
                  description={gene.description || '-'}
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      {genome.config && Object.keys(genome.config).length > 0 && (
        <Card
          title={t('tenant.genomeDetail.configTitle', 'Configuration')}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <pre className="bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto text-xs">
            {JSON.stringify(genome.config, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
};
