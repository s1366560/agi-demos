import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  message,
  Modal,
  Space,
  Tag,
  Typography,
} from 'antd';
import { ArrowLeft, Copy, Rocket, Trash2, Upload } from 'lucide-react';

import { formatDateTime } from '@/utils/date';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';

import { instanceTemplateService } from '../../services/instanceTemplateService';
import { useGeneMarketActions, useGenes } from '../../stores/geneMarket';
import { useCurrentTenant } from '../../stores/tenant';

import type {
  InstanceTemplateResponse,
  TemplateItemResponse,
} from '../../services/instanceTemplateService';

const { Title, Text, Paragraph } = Typography;

export const TemplateDetail: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId, templateId } = useParams<{
    tenantId?: string;
    templateId?: string;
  }>();
  const navigate = useNavigate();
  const currentTenant = useCurrentTenant();
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;

  const [template, setTemplate] = useState<InstanceTemplateResponse | null>(null);
  const [items, setItems] = useState<TemplateItemResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [isCloning, setIsCloning] = useState(false);
  const [isLifecycleSubmitting, setIsLifecycleSubmitting] = useState(false);
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
      const msg =
        err instanceof Error
          ? err.message
          : t('tenant.templateDetail.loadFailed', 'Failed to load template');
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [templateId, t]);

  useEffect(() => {
    void fetchData();
    if (tenantId) {
      void listGenes({ tenant_id: tenantId });
    }
  }, [fetchData, listGenes, tenantId]);

  const handleClone = async () => {
    if (!templateId || !template || isCloning) return;
    setIsCloning(true);
    try {
      const cloned = await instanceTemplateService.clone(
        templateId,
        t('tenant.templates.cloneName', {
          name: template.name,
          defaultValue: 'Copy of {{name}}',
        }).slice(0, 200)
      );
      message.success(t('tenant.templateDetail.cloneSuccess', 'Template cloned successfully'));
      void navigate(`../instance-templates/${cloned.id}`);
    } catch {
      message.error(t('tenant.templateDetail.cloneError', 'Failed to clone template'));
    } finally {
      setIsCloning(false);
    }
  };

  const handlePublish = () => {
    if (!templateId || !template) return;
    Modal.confirm({
      title: t('tenant.templateDetail.publishConfirmTitle', {
        name: template.name,
        defaultValue: 'Publish {{name}}?',
      }),
      content: t(
        'tenant.templateDetail.publishConfirmContent',
        'Publishing makes this template visible in the marketplace.'
      ),
      okText: t('tenant.templateDetail.publishAction', 'Publish'),
      cancelText: t('common.cancel', 'Cancel'),
      onOk: async () => {
        setIsLifecycleSubmitting(true);
        try {
          const updated = await instanceTemplateService.publish(templateId);
          setTemplate(updated);
          message.success(
            t('tenant.templateDetail.publishSuccess', 'Template published successfully')
          );
        } catch {
          message.error(t('tenant.templateDetail.publishError', 'Failed to publish template'));
        } finally {
          setIsLifecycleSubmitting(false);
        }
      },
    });
  };

  const handleDelete = () => {
    if (!templateId || !template) return;
    Modal.confirm({
      title: t('tenant.templateDetail.deleteConfirmTitle', {
        name: template.name,
        defaultValue: 'Delete {{name}}?',
      }),
      content: t(
        'tenant.templateDetail.deleteConfirmContent',
        'This removes the template and cannot be undone.'
      ),
      okText: t('common.delete', 'Delete'),
      okType: 'danger',
      cancelText: t('common.cancel', 'Cancel'),
      onOk: async () => {
        setIsLifecycleSubmitting(true);
        try {
          await instanceTemplateService.delete(templateId);
          message.success(
            t('tenant.templateDetail.deleteSuccess', 'Template deleted successfully')
          );
          setIsLifecycleSubmitting(false);
          void navigate(-1);
        } catch {
          message.error(t('tenant.templateDetail.deleteError', 'Failed to delete template'));
          setIsLifecycleSubmitting(false);
        }
      },
    });
  };

  const getGeneName = (geneId: string): string => {
    const gene = genes.find((g) => g.id === geneId);
    return gene?.name ?? geneId;
  };

  const handleDeploy = () => {
    if (!templateId) return;
    void navigate(`../instances/create?templateId=${encodeURIComponent(templateId)}`);
  };

  if (loading && !template) {
    return (
      <div className="max-w-4xl mx-auto w-full">
        <SkeletonLoader type="form" />
      </div>
    );
  }

  if (!template && !loading) {
    // A load failure shows an error with retry; only genuine 404s get "not found"
    if (error) {
      return (
        <Alert
          type="error"
          title={t('tenant.templateDetail.loadFailed', 'Failed to load template')}
          description={error}
          showIcon
          action={
            <Button
              size="small"
              onClick={() => {
                void fetchData();
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
        title={t('tenant.templateDetail.notFound', 'Template not found')}
        showIcon
      />
    );
  }

  if (!template) return null;

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <Button
          icon={<ArrowLeft size={16} />}
          onClick={() => {
            void navigate(-1);
          }}
        >
          {t('common.back', 'Back')}
        </Button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Title level={1} className="!mb-0">
              {template.name}
            </Title>
            {template.is_published && (
              <Tag color="green">{t('tenant.templateDetail.published', 'Published')}</Tag>
            )}
          </div>
          {template.updated_at ? (
            <Text type="secondary" className="text-xs">
              {t('tenant.genes.lastUpdated', 'Last updated {{time}}', {
                time: formatDateTime(template.updated_at),
              })}
            </Text>
          ) : null}
        </div>
      </div>

      {error && (
        <Alert
          type="error"
          title={error}
          closable={{
            onClose: () => {
              setError(null);
            },
          }}
        />
      )}

      <Card className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
        <Descriptions column={{ xs: 1, sm: 2 }} bordered>
          <Descriptions.Item label={t('tenant.templateDetail.fields.id', 'ID')}>
            <Paragraph copyable className="!mb-0">
              {template.id}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item
            label={t('tenant.templateDetail.fields.installCount', 'Install Count')}
          >
            {template.install_count}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.templateDetail.fields.slug', 'Slug')}>
            {template.slug}
          </Descriptions.Item>
          <Descriptions.Item
            label={t('tenant.templateDetail.fields.description', 'Description')}
            span={2}
          >
            {template.description || '-'}
          </Descriptions.Item>
          <Descriptions.Item
            label={t('tenant.templateDetail.fields.imageVersion', 'Image Version')}
          >
            {template.image_version || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.templateDetail.fields.createdAt', 'Created At')}>
            {formatDateTime(template.created_at)}
          </Descriptions.Item>
          {template.updated_at ? (
            <Descriptions.Item label={t('tenant.templateDetail.fields.updatedAt', 'Updated At')}>
              {formatDateTime(template.updated_at)}
            </Descriptions.Item>
          ) : null}
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
          <div role="list" className="divide-y divide-slate-200 dark:divide-slate-800">
            {items.map((item) => (
              <div key={item.id} role="listitem" className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Text strong>{getGeneName(item.item_slug)}</Text>
                  <Tag>{item.item_type}</Tag>
                  <Tag>#{item.display_order}</Tag>
                </div>
                <Text type="secondary" className="mt-1 block text-sm">
                  {item.item_slug}
                </Text>
              </div>
            ))}
          </div>
        )}
      </Card>

      {Object.keys(template.default_config).length > 0 && (
        <Card
          title={t('tenant.templateDetail.baseConfigTitle', 'Base Configuration')}
          className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
        >
          <pre className="bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto text-xs">
            {JSON.stringify(template.default_config, null, 2)}
          </pre>
        </Card>
      )}

      <Space wrap>
        <Button type="primary" icon={<Rocket size={16} />} onClick={handleDeploy}>
          {t('tenant.templateDetail.deployFromTemplate', 'Deploy from Template')}
        </Button>
        <Button
          icon={<Copy size={16} />}
          loading={isCloning}
          disabled={isCloning}
          onClick={() => {
            void handleClone();
          }}
        >
          {t('tenant.templateDetail.clone', 'Clone Template')}
        </Button>
        {!template.is_published && (
          <Button
            icon={<Upload size={16} />}
            loading={isLifecycleSubmitting}
            onClick={handlePublish}
          >
            {t('tenant.templateDetail.publishAction', 'Publish')}
          </Button>
        )}
        <Button
          danger
          icon={<Trash2 size={16} />}
          loading={isLifecycleSubmitting}
          onClick={handleDelete}
        >
          {t('tenant.templateDetail.deleteAction', 'Delete Template')}
        </Button>
      </Space>
    </div>
  );
};
