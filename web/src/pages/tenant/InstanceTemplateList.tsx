import { useEffect, useState, useMemo } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Card, Tag, Form, Input, Typography, Space } from 'antd';
import { Copy, Upload, Trash2, Eye, Plus, Search } from 'lucide-react';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazyEmpty,
  LazySpin,
  LazyModal,
  LazyButton,
  LazySelect,
} from '@/components/ui/lazyAntd';

import {
  useTemplates,
  useTemplateLoading,
  useTemplateSubmitting,
  useTemplateActions,
} from '../../stores/instanceTemplate';

const { Title, Text, Paragraph } = Typography;

interface CreateFormValues {
  name: string;
  description?: string;
  tags?: string;
  base_config?: string;
}

export const InstanceTemplateList: FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const messageApi = useLazyMessage();

  const templates = useTemplates();
  const isLoading = useTemplateLoading();
  const isSubmitting = useTemplateSubmitting();
  const {
    listTemplates,
    createTemplate,
    deleteTemplate,
    publishTemplate,
    cloneTemplate,
    clearError,
    reset,
  } = useTemplateActions();

  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'published' | 'draft'>('all');
  const [isCreateModalVisible, setIsCreateModalVisible] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();

  useEffect(() => {
    listTemplates().catch(() => messageApi?.error(t('tenant.templates.fetchError')));
    return () => {
      clearError();
      reset();
    };
  }, [listTemplates, clearError, reset, t, messageApi]);

  const filteredTemplates = useMemo(() => {
    return templates.filter((template) => {
      const matchesSearch =
        template.name.toLowerCase().includes(searchText.toLowerCase()) ||
        template.description?.toLowerCase().includes(searchText.toLowerCase());
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'published' && template.is_published) ||
        (statusFilter === 'draft' && !template.is_published);

      return matchesSearch && matchesStatus;
    });
  }, [templates, searchText, statusFilter]);

  const handleCreateSubmit = async () => {
    try {
      const values = await form.validateFields();
      let tagsArray: string[] = [];
      if (values.tags) {
        tagsArray = values.tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean);
      }

      let baseConfig: Record<string, unknown> = {};
      if (values.base_config) {
        baseConfig = JSON.parse(values.base_config) as Record<string, unknown>;
      }

      await createTemplate({
        name: values.name,
        description: values.description ?? null,
        tags: tagsArray,
        base_config: baseConfig,
      });

      messageApi?.success(t('tenant.templates.createSuccess'));
      setIsCreateModalVisible(false);
      form.resetFields();
    } catch (err) {
      if (err instanceof Error && err.message.includes('Unexpected token')) {
        messageApi?.error(t('tenant.templates.invalidJson'));
      } else if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handleClone = async (id: string) => {
    try {
      await cloneTemplate(id);
      messageApi?.success(t('tenant.templates.cloneSuccess'));
      void listTemplates();
    } catch (err) {
      if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handlePublish = async (id: string) => {
    try {
      await publishTemplate(id);
      messageApi?.success(t('tenant.templates.publishSuccess'));
      void listTemplates();
    } catch (err) {
      if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteTemplate(id);
      messageApi?.success(t('tenant.templates.deleteSuccess'));
    } catch (err) {
      if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handleViewDetail = (id: string) => {
    void navigate(`./templates/${id}`);
  };

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex justify-between items-center">
        <Space orientation="vertical" size="small">
          <Title level={2} className="!mb-0">
            {t('tenant.templates.title')}
          </Title>
          <Text type="secondary">{t('tenant.templates.subtitle')}</Text>
        </Space>
        <LazyButton
          type="primary"
          icon={<Plus className="w-4 h-4" />}
          onClick={() => {
            setIsCreateModalVisible(true);
          }}
        >
          {t('tenant.templates.createTemplate')}
        </LazyButton>
      </div>

      <div className="flex items-center gap-4 bg-surface-light dark:bg-surface-dark p-4 rounded-lg border border-border-light dark:border-border-dark">
        <Input
          placeholder={t('tenant.templates.searchPlaceholder')}
          prefix={<Search className="w-4 h-4 text-text-muted" />}
          value={searchText}
          onChange={(e) => {
            setSearchText(e.target.value);
          }}
          className="max-w-md"
          allowClear
        />
        <LazySelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'all', label: t('tenant.templates.filterAll') },
            { value: 'published', label: t('tenant.templates.filterPublished') },
            { value: 'draft', label: t('tenant.templates.filterDraft') },
          ]}
          style={{ width: 150 }}
        />
      </div>

      {isLoading && templates.length === 0 ? (
        <div className="flex justify-center items-center h-64">
          <LazySpin size="large" />
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="bg-surface-light dark:bg-surface-dark p-12 rounded-lg border border-border-light dark:border-border-dark">
          <LazyEmpty description={t('tenant.templates.empty')} />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredTemplates.map((template) => (
            <Card
              key={template.id}
              className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark hover:border-primary-300 dark:hover:border-primary-600 transition-colors flex flex-col h-full"
              styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column' } }}
              actions={[
                <LazyButton
                  key="view"
                  type="text"
                  icon={<Eye className="w-4 h-4" />}
                  aria-label={t('common.view', 'View')}
                  disabled={isSubmitting}
                  onClick={() => {
                    handleViewDetail(template.id);
                  }}
                />,
                <LazyButton
                  key="clone"
                  type="text"
                  icon={<Copy className="w-4 h-4" />}
                  aria-label={t('common.clone', 'Clone')}
                  disabled={isSubmitting}
                  onClick={() => {
                    void handleClone(template.id);
                  }}
                />,
                !template.is_published ? (
                  <LazyPopconfirm
                    key="publish"
                    title={t('tenant.templates.publishConfirm')}
                    onConfirm={() => handlePublish(template.id)}
                  >
                    <LazyButton
                      type="text"
                      icon={<Upload className="w-4 h-4" />}
                      aria-label={t('common.publish', 'Publish')}
                      disabled={isSubmitting}
                    />
                  </LazyPopconfirm>
                ) : (
                  <span key="empty"></span>
                ),
                <LazyPopconfirm
                  key="delete"
                  title={t('tenant.templates.deleteConfirm')}
                  onConfirm={() => handleDelete(template.id)}
                >
                  <LazyButton
                    type="text"
                    danger
                    icon={<Trash2 className="w-4 h-4" />}
                    aria-label={t('common.delete', 'Delete')}
                    disabled={isSubmitting}
                  />
                </LazyPopconfirm>,
              ]}
            >
              <div className="flex justify-between items-start mb-2">
                <Text strong className="text-lg truncate pr-2">
                  {template.name}
                </Text>
                <Tag color={template.is_published ? 'green' : 'default'} className="m-0">
                  {template.is_published
                    ? t('tenant.templates.statusPublished')
                    : t('tenant.templates.statusDraft')}
                </Tag>
              </div>

              <Paragraph
                className="text-text-muted dark:text-text-muted flex-1 overflow-hidden"
                ellipsis={{ rows: 2 }}
              >
                {template.description || t('tenant.templates.noDescription')}
              </Paragraph>

              <div className="mt-auto pt-4 flex flex-col gap-3">
                {template.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {template.tags.map((tag) => (
                      <Tag key={tag} className="text-xs">
                        {tag}
                      </Tag>
                    ))}
                  </div>
                )}

                <div className="flex justify-between items-center text-xs text-text-muted">
                  <span className="flex items-center gap-1">
                    <Copy className="w-3 h-3" /> {template.clone_count || 0}
                  </span>
                  <span>{new Date(template.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <LazyModal
        title={t('tenant.templates.createTemplate')}
        open={isCreateModalVisible}
        onOk={handleCreateSubmit}
        onCancel={() => {
          setIsCreateModalVisible(false);
          form.resetFields();
        }}
        confirmLoading={isSubmitting}
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="name"
            label={t('tenant.templates.name')}
            rules={[{ required: true, message: t('tenant.templates.nameRequired') }]}
          >
            <Input placeholder={t('tenant.templates.namePlaceholder')} />
          </Form.Item>

          <Form.Item name="description" label={t('tenant.templates.description')}>
            <Input.TextArea rows={3} placeholder={t('tenant.templates.descriptionPlaceholder')} />
          </Form.Item>

          <Form.Item
            name="tags"
            label={t('tenant.templates.tags')}
            tooltip={t('tenant.templates.tagsTooltip')}
          >
            <Input placeholder={t('tenant.templates.tagsPlaceholder')} />
          </Form.Item>

          <Form.Item name="base_config" label={t('tenant.templates.baseConfig')}>
            <Input.TextArea rows={4} placeholder='{"key": "value"}' className="font-mono text-sm" />
          </Form.Item>
        </Form>
      </LazyModal>
    </div>
  );
};
