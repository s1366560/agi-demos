import { useCallback, useEffect, useState, useMemo } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Card, Tag, Form, Input, Typography, Space, Pagination } from 'antd';
import { Copy, Upload, Trash2, Eye, Plus, Search } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

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
  useTemplatePagination,
} from '../../stores/instanceTemplate';

const { Title, Text, Paragraph } = Typography;

interface CreateFormValues {
  name: string;
  description?: string;
  default_config?: string;
}

type TemplateStatusFilter = 'all' | 'published' | 'draft';

interface LoadTemplatesOptions {
  page?: number;
  pageSize?: number;
  status?: TemplateStatusFilter;
}

const slugifyTemplateName = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 255) || 'template';

const templateStatusToPublished = (status: TemplateStatusFilter): boolean | undefined => {
  if (status === 'published') return true;
  if (status === 'draft') return false;
  return undefined;
};

export const InstanceTemplateList: FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const messageApi = useLazyMessage();

  const templates = useTemplates();
  const isLoading = useTemplateLoading();
  const isSubmitting = useTemplateSubmitting();
  const { total, page, pageSize } = useTemplatePagination();
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
  const [statusFilter, setStatusFilter] = useState<TemplateStatusFilter>('all');
  const [isCreateModalVisible, setIsCreateModalVisible] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();

  const loadTemplates = useCallback(
    (options?: LoadTemplatesOptions) => {
      const selectedOptions = options ?? {};
      const isPublished = templateStatusToPublished(selectedOptions.status ?? statusFilter);
      return listTemplates({
        page: selectedOptions.page ?? 1,
        page_size: selectedOptions.pageSize ?? pageSize,
        ...(isPublished === undefined ? {} : { is_published: isPublished }),
      });
    },
    [listTemplates, pageSize, statusFilter]
  );

  useEffect(() => {
    loadTemplates().catch(() => messageApi?.error(t('tenant.templates.fetchError')));
  }, [loadTemplates, messageApi, t]);

  useEffect(() => {
    return () => {
      clearError();
      reset();
    };
  }, [clearError, reset]);

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

      let defaultConfig: Record<string, unknown> = {};
      if (values.default_config) {
        defaultConfig = JSON.parse(values.default_config) as Record<string, unknown>;
      }

      await createTemplate({
        name: values.name,
        slug: slugifyTemplateName(values.name),
        description: values.description ?? null,
        default_config: defaultConfig,
      });

      messageApi?.success(t('tenant.templates.createSuccess'));
      setIsCreateModalVisible(false);
      form.resetFields();
    } catch (err) {
      if (typeof err === 'object' && err !== null && 'errorFields' in err) {
        // antd validation errors are shown inline on the form
        return;
      }
      if (err instanceof SyntaxError) {
        messageApi?.error(t('tenant.templates.invalidJson'));
      } else if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handleStatusFilterChange = (value: TemplateStatusFilter) => {
    setStatusFilter(value);
    loadTemplates({ page: 1, status: value }).catch(() =>
      messageApi?.error(t('tenant.templates.fetchError'))
    );
  };

  const handleClone = async (id: string, name: string) => {
    try {
      const cloneName = t('tenant.templates.cloneName', {
        name,
        defaultValue: 'Copy of {{name}}',
      }).slice(0, 200);
      await cloneTemplate(id, cloneName);
      messageApi?.success(t('tenant.templates.cloneSuccess'));
      void loadTemplates({ page });
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
      void loadTemplates({ page });
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
      void loadTemplates({ page });
    } catch (err) {
      if (err instanceof Error) {
        messageApi?.error(err.message);
      }
    }
  };

  const handleViewDetail = (id: string) => {
    void navigate(`./${id}`);
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
          aria-label={t('tenant.templates.searchPlaceholder')}
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
          aria-label={t('tenant.templates.statusFilterLabel')}
          value={statusFilter}
          onChange={handleStatusFilterChange}
          options={[
            { value: 'all', label: t('tenant.templates.filterAll') },
            { value: 'published', label: t('tenant.templates.filterPublished') },
            { value: 'draft', label: t('tenant.templates.filterDraft') },
          ]}
          style={{ width: 150 }}
        />
        {searchText ? (
          <Text type="secondary" className="text-xs">
            {t('tenant.templates.searchScopeHint', 'Search filters templates on the current page')}
          </Text>
        ) : null}
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
                  aria-label={t('tenant.templates.viewTemplate', { name: template.name })}
                  disabled={isSubmitting}
                  onClick={() => {
                    handleViewDetail(template.id);
                  }}
                />,
                <LazyButton
                  key="clone"
                  type="text"
                  icon={<Copy className="w-4 h-4" />}
                  aria-label={t('tenant.templates.cloneTemplate', { name: template.name })}
                  disabled={isSubmitting}
                  onClick={() => {
                    void handleClone(template.id, template.name);
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
                      aria-label={t('tenant.templates.publishTemplate', { name: template.name })}
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
                    aria-label={t('tenant.templates.deleteTemplate', { name: template.name })}
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
                <div className="flex justify-between items-center text-xs text-text-muted">
                  <span className="flex items-center gap-1">
                    <Copy className="w-3 h-3" /> {template.install_count || 0}
                  </span>
                  <span>{formatDateOnly(template.created_at)}</span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {total > pageSize && (
        <div className="flex justify-end">
          <Pagination
            aria-label={t('common.pagination.label', { defaultValue: 'Pagination' })}
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger
            pageSizeOptions={['12', '20', '50', '100']}
            onChange={(nextPage, nextPageSize) => {
              void loadTemplates({ page: nextPage, pageSize: nextPageSize });
            }}
          />
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
            name="default_config"
            label={t('tenant.templates.baseConfig')}
            rules={[
              {
                validator: (_rule, value: unknown) => {
                  if (typeof value !== 'string' || !value.trim()) {
                    return Promise.resolve();
                  }
                  try {
                    JSON.parse(value);
                    return Promise.resolve();
                  } catch {
                    return Promise.reject(new Error(t('tenant.templates.invalidJson')));
                  }
                },
              },
            ]}
          >
            <Input.TextArea
              rows={4}
              spellCheck={false}
              placeholder={t('tenant.templates.baseConfigPlaceholder')}
              className="font-mono text-sm"
            />
          </Form.Item>
        </Form>
      </LazyModal>
    </div>
  );
};
