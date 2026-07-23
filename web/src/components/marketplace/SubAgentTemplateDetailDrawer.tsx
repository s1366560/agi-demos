/**
 * SubAgentTemplateDetailDrawer - detail preview for a marketplace template.
 *
 * The marketplace grid only exposes list-item fields; this drawer fetches the
 * full template definition (system prompt, trigger config, model params) so
 * users can inspect a template before installing it.
 */

import { useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Button, Descriptions, Drawer, Tag, Typography } from 'antd';
import { Download } from 'lucide-react';

import { subagentTemplateService } from '@/services/subagentTemplateService';
import type { SubAgentTemplateDetail } from '@/services/subagentTemplateService';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';

const { Title, Text, Paragraph } = Typography;

interface SubAgentTemplateDetailDrawerProps {
  templateId: string | null;
  onClose: () => void;
  onInstall: (templateId: string) => void;
  installing: boolean;
}

export const SubAgentTemplateDetailDrawer: FC<SubAgentTemplateDetailDrawerProps> = ({
  templateId,
  onClose,
  onInstall,
  installing,
}) => {
  const { t } = useTranslation();
  const [result, setResult] = useState<{
    id: string;
    detail?: SubAgentTemplateDetail;
    error?: boolean;
  } | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!templateId) {
      return;
    }
    let cancelled = false;
    subagentTemplateService
      .get(templateId)
      .then((detail) => {
        if (!cancelled) {
          setResult({ id: templateId, detail });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResult({ id: templateId, error: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [templateId, retryToken]);

  // Only trust a result that matches the currently requested template
  const current = templateId !== null && result?.id === templateId ? result : null;
  const loading = templateId !== null && current === null;
  const loadError = current?.error === true;
  const detail = current?.detail ?? null;

  const handleRetry = () => {
    setResult(null);
    setRetryToken((token) => token + 1);
  };

  return (
    <Drawer
      title={
        detail?.display_name || detail?.name || t('agent.templates.detailTitle', 'Template Details')
      }
      size={520}
      open={templateId !== null}
      onClose={onClose}
      footer={
        detail ? (
          <Button
            type="primary"
            icon={<Download size={14} />}
            loading={installing}
            onClick={() => {
              onInstall(detail.id);
            }}
          >
            {t('agent.templates.install', 'Install')}
          </Button>
        ) : null
      }
    >
      {loading ? (
        <SkeletonLoader type="form" />
      ) : loadError ? (
        <Alert
          type="error"
          showIcon
          title={t('agent.templates.loadError', 'Failed to load templates')}
          action={
            <Button size="small" onClick={handleRetry}>
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      ) : detail ? (
        <div className="flex flex-col gap-5">
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label={t('agent.templates.detailFields.version', 'Version')}>
              {detail.version}
            </Descriptions.Item>
            <Descriptions.Item label={t('agent.templates.detailFields.category', 'Category')}>
              <Tag>{detail.category}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('agent.templates.detailFields.author', 'Author')}>
              {detail.author || '-'}
            </Descriptions.Item>
            <Descriptions.Item label={t('agent.templates.detailFields.installCount', 'Installs')}>
              {detail.install_count}
            </Descriptions.Item>
            <Descriptions.Item label={t('agent.templates.detailFields.model', 'Model')}>
              {detail.model || '-'}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Title level={5}>{t('agent.templates.detailFields.description', 'Description')}</Title>
            <Paragraph className="whitespace-pre-wrap break-words">
              {detail.description || t('agent.templates.noDescription', 'No description')}
            </Paragraph>
          </div>

          <div>
            <Title level={5}>
              {t('agent.templates.detailFields.systemPrompt', 'System Prompt')}
            </Title>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-700 dark:bg-slate-900">
              {detail.system_prompt || '-'}
            </pre>
          </div>

          {detail.trigger_description ? (
            <div>
              <Title level={5}>
                {t('agent.templates.detailFields.triggerDescription', 'Trigger Description')}
              </Title>
              <Paragraph className="whitespace-pre-wrap break-words">
                {detail.trigger_description}
              </Paragraph>
            </div>
          ) : null}

          {detail.trigger_keywords.length > 0 ? (
            <div>
              <Title level={5}>
                {t('agent.templates.detailFields.triggerKeywords', 'Trigger Keywords')}
              </Title>
              <div className="flex flex-wrap gap-1">
                {detail.trigger_keywords.map((keyword) => (
                  <Tag key={keyword}>{keyword}</Tag>
                ))}
              </div>
            </div>
          ) : null}

          {detail.allowed_tools.length > 0 ? (
            <div>
              <Title level={5}>
                {t('agent.templates.detailFields.allowedTools', 'Allowed Tools')}
              </Title>
              <div className="flex flex-wrap gap-1">
                {detail.allowed_tools.map((tool) => (
                  <Tag key={tool}>{tool}</Tag>
                ))}
              </div>
            </div>
          ) : null}

          {detail.tags.length > 0 ? (
            <div>
              <Title level={5}>{t('agent.templates.detailFields.tags', 'Tags')}</Title>
              <div className="flex flex-wrap gap-1">
                {detail.tags.map((tag) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </div>
            </div>
          ) : null}

          <Text type="secondary" className="text-xs">
            {t('agent.templates.detailFields.templateId', 'Template ID')}: {detail.id}
          </Text>
        </div>
      ) : null}
    </Drawer>
  );
};
