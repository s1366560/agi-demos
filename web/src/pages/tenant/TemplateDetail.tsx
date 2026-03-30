import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import {
  Button,
  Card,
  Typography,
  Spin,
  Alert,
  Tag,
  Descriptions,
  List,
  Empty,
  message,
} from 'antd';
import { ArrowLeft, Rocket, Copy } from 'lucide-react';

import { instanceTemplateService } from '../../services/instanceTemplateService';
import { useGenes, useGeneMarketActions } from '../../stores/geneMarket';

import type {
  InstanceTemplateResponse,
  TemplateItemResponse,
} from '../../services/instanceTemplateService';

const { Title, Text, Paragraph } = Typography;

export const TemplateDetail: React.FC = () => {
  const { t } = useTranslation();
  const { templateId } = useParams();
  const navigate = useNavigate();

  const [template, setTemplate] = useState<InstanceTemplateResponse | null>(null);
  const [items, setItems] = useState<TemplateItemResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const genes = useGenes();
  const { listGenes } = useGeneMarketActions();

  const fetchData = useCallback(async () => {
    if (!templateId) return;
    setLoading(true);
    setError(null);
    try {
      const [templateRes, itemsRes] = await Promise.all([
        instanceTemplateService.getById(templateId),
        instanceTemplateService.listItems(templateId),
      ]);
      setTemplate(templateRes);
      setItems(itemsRes);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load template';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [templateId]);

  useEffect(() => {
    fetchData().catch(() => {});
    listGenes().catch(() => {});
  }, [fetchData, listGenes]);

  const handleClone = async () => {
    if (!templateId) return;
    try {
      const cloned = await instanceTemplateService.clone(templateId);
      message.success(t('tenant.templateDetail.cloneSuccess', 'Template cloned successfully'));
      navigate(`../instance-templates/${cloned.id}`);
    } catch {
      message.error(t('tenant.templateDetail.cloneError', 'Failed to clone template'));
    }
  };

  const getGeneName = (geneId: string): string => {
    const gene = genes.find((g) => g.id === geneId);
    return gene?.name ?? geneId;
  };

  if (loading && !template) {
    return (
      <div className="flex justify-center p-12">
        <Spin size="large" />
      </div>
    );
  }

  if (!template && !loading) {
    return (
      <Alert
        type="warning"
        message={t('tenant.templateDetail.notFound', 'Template not found')}
        showIcon
      />
    );
  }

  if (!template) return null;

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <Button icon={<ArrowLeft size={16} />} onClick={() => navigate(-1)}>
          {t('common.back', 'Back')}
        </Button>
        <Title level={3} className="!mb-0">
          {template.name}
        </Title>
        {template.is_published && (
          <Tag color="green">{t('tenant.templateDetail.published', 'Published')}</Tag>
        )}
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          closable
          onClose={() => {
            setError(null);
          }}
        />
      )}

      <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
        <Descriptions column={2} bordered>
          <Descriptions.Item label={t('tenant.templateDetail.fields.id', 'ID')}>
            <Paragraph copyable className="!mb-0">
              {template.id}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.templateDetail.fields.cloneCount', 'Clone Count')}>
            {template.clone_count}
          </Descriptions.Item>
          <Descriptions.Item
            label={t('tenant.templateDetail.fields.description', 'Description')}
            span={2}
          >
            {template.description || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.templateDetail.fields.tags', 'Tags')}>
            {template.tags.length > 0
              ? template.tags.map((tag) => (
                  <Tag key={tag} color="blue">
                    {tag}
                  </Tag>
                ))
              : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.templateDetail.fields.createdAt', 'Created At')}>
            {new Date(template.created_at).toLocaleString()}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={t('tenant.templateDetail.itemsTitle', 'Gene Assignments')}
        className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
      >
        {items.length === 0 ? (
          <Empty
            description={t('tenant.templateDetail.noItems', 'No genes assigned to this template')}
          />
        ) : (
          <List
            dataSource={items}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <div className="flex items-center gap-2">
                      <Text strong>{getGeneName(item.gene_id)}</Text>
                      <Tag>#{item.order}</Tag>
                    </div>
                  }
                  description={
                    Object.keys(item.config_override).length > 0
                      ? t('tenant.templateDetail.hasConfigOverride', 'Has config override')
                      : t('tenant.templateDetail.defaultConfig', 'Default config')
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      {template.base_config && Object.keys(template.base_config).length > 0 && (
        <Card
          title={t('tenant.templateDetail.baseConfigTitle', 'Base Configuration')}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <pre className="bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto text-xs">
            {JSON.stringify(template.base_config, null, 2)}
          </pre>
        </Card>
      )}

      <div className="flex gap-4">
        <Button type="primary" icon={<Rocket size={16} />} disabled>
          {t('tenant.templateDetail.deployFromTemplate', 'Deploy from Template')}
        </Button>
        <Button icon={<Copy size={16} />} onClick={handleClone}>
          {t('tenant.templateDetail.clone', 'Clone Template')}
        </Button>
      </div>
    </div>
  );
};
