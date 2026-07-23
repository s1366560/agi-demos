import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  Alert,
  Table,
  Button,
  Space,
  Typography,
  Tag,
  Popconfirm,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  message,
} from 'antd';
import { Copy } from 'lucide-react';

import { useCurrentTenant } from '@/stores/tenant';

import { eventService } from '@/services/eventService';
import { webhookService, type Webhook } from '@/services/webhookService';

import { logger } from '@/utils/logger';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';

const { Title } = Typography;

interface WebhookFormValues {
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
}

const isFormValidationError = (error: unknown): error is { errorFields: unknown[] } =>
  typeof error === 'object' &&
  error !== null &&
  'errorFields' in error &&
  Array.isArray((error as { errorFields?: unknown }).errorFields);

interface WebhookCreatedSecretModalProps {
  secret: string | null;
  onClose: () => void;
  onCopy: () => void;
}

export const WebhookCreatedSecretModal: React.FC<WebhookCreatedSecretModalProps> = ({
  secret,
  onClose,
  onCopy,
}) => {
  const { t } = useTranslation();

  return (
    <Modal
      title={t('webhooks.createdSecretTitle', 'Webhook signing secret')}
      open={Boolean(secret)}
      okText={t('common.done', 'Done')}
      cancelButtonProps={{ style: { display: 'none' } }}
      onOk={onClose}
      onCancel={onClose}
      destroyOnHidden
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          title={t('webhooks.secretOneTimeTitle', 'Copy this secret now')}
          description={t(
            'webhooks.secretOneTimeDescription',
            'For security, this value will not be shown again after you close this dialog.'
          )}
        />
        <Space.Compact style={{ width: '100%' }}>
          <Input.Password value={secret ?? ''} readOnly />
          <Button
            icon={<Copy size={14} />}
            aria-label={t('webhooks.copySecret', 'Copy secret')}
            onClick={onCopy}
          />
        </Space.Compact>
      </Space>
    </Modal>
  );
};

export const Webhooks: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId } = useParams<{ tenantId?: string }>();
  const currentTenant = useCurrentTenant();
  const selectedTenantId = tenantId ?? currentTenant?.id;
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [eventTypesError, setEventTypesError] = useState<string | null>(null);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [form] = Form.useForm<WebhookFormValues>();
  const selectedTenantIdRef = React.useRef(selectedTenantId);
  const webhooksRequestIdRef = React.useRef(0);
  const eventTypesRequestIdRef = React.useRef(0);

  useEffect(() => {
    selectedTenantIdRef.current = selectedTenantId;
  }, [selectedTenantId]);

  const fetchWebhooks = React.useCallback(async () => {
    if (!selectedTenantId) {
      setLoading(false);
      setLoadError(null);
      setWebhooks([]);
      return;
    }
    const requestId = webhooksRequestIdRef.current + 1;
    webhooksRequestIdRef.current = requestId;
    const requestTenantId = selectedTenantId;
    const isCurrentRequest = () =>
      webhooksRequestIdRef.current === requestId && selectedTenantIdRef.current === requestTenantId;

    setLoading(true);
    setLoadError(null);
    try {
      const data = await webhookService.listWebhooks(requestTenantId);
      if (!isCurrentRequest()) return;
      setWebhooks(data);
    } catch (err) {
      if (!isCurrentRequest()) return;
      logger.error('Request failed', err);
      const errorMessage = t('webhooks.fetchError', 'Failed to fetch webhooks');
      setWebhooks([]);
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }, [selectedTenantId, t]);

  useEffect(() => {
    void fetchWebhooks();
  }, [fetchWebhooks]);

  useEffect(() => {
    setCreatedSecret(null);
    setEditingWebhook(null);
    setIsModalVisible(false);
  }, [selectedTenantId]);

  const fetchEventTypes = React.useCallback(() => {
    const requestId = eventTypesRequestIdRef.current + 1;
    eventTypesRequestIdRef.current = requestId;
    const requestTenantId = selectedTenantId;
    const isCurrentRequest = () =>
      eventTypesRequestIdRef.current === requestId &&
      selectedTenantIdRef.current === requestTenantId;

    setEventTypesError(null);
    void eventService
      .getEventTypes(requestTenantId ? { tenant_id: requestTenantId } : undefined)
      .then((types) => {
        if (!isCurrentRequest()) return;
        setEventTypes(types);
      })
      .catch((err: unknown) => {
        if (!isCurrentRequest()) return;
        logger.error('Request failed', err);
        setEventTypes([]);
        setEventTypesError(t('webhooks.eventTypesError', 'Failed to load webhook event types'));
      });
  }, [selectedTenantId, t]);

  useEffect(() => {
    fetchEventTypes();
  }, [fetchEventTypes]);

  const handleDelete = async (id: string) => {
    try {
      await webhookService.deleteWebhook(id);
      message.success(t('webhooks.deleteSuccess', 'Webhook deleted'));
      void fetchWebhooks();
    } catch (err) {
      logger.error('Request failed', err);
      message.error(t('webhooks.deleteError', 'Failed to delete webhook'));
    }
  };

  const handleOpenModal = (webhook?: Webhook) => {
    setEditingWebhook(webhook || null);
    if (webhook) {
      form.setFieldsValue({
        name: webhook.name,
        url: webhook.url,
        events: webhook.events,
        is_active: webhook.is_active,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ is_active: true, events: [] });
    }
    setIsModalVisible(true);
  };

  const handleSave = async () => {
    if (!selectedTenantId) return;
    const requestTenantId = selectedTenantId;
    const isCurrentTenant = () => selectedTenantIdRef.current === requestTenantId;
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editingWebhook) {
        await webhookService.updateWebhook(editingWebhook.id, values);
        if (!isCurrentTenant()) return;
        message.success(t('webhooks.updateSuccess', 'Webhook updated'));
      } else {
        const createdWebhook = await webhookService.createWebhook(requestTenantId, values);
        if (!isCurrentTenant()) return;
        setCreatedSecret(createdWebhook.secret ?? null);
        message.success(t('webhooks.createSuccess', 'Webhook created'));
      }
      setIsModalVisible(false);
      void fetchWebhooks();
    } catch (err) {
      if (isFormValidationError(err)) return;
      logger.error('Request failed', err);
      message.error(
        editingWebhook
          ? t('webhooks.updateError', 'Failed to update webhook')
          : t('webhooks.createError', 'Failed to create webhook')
      );
    } finally {
      setSaving(false);
    }
  };

  const handleCopyCreatedSecret = async () => {
    if (!createdSecret) return;
    try {
      await navigator.clipboard.writeText(createdSecret);
      message.success(t('webhooks.secretCopied', 'Secret copied'));
    } catch (err) {
      logger.error('Request failed', err);
      message.error(t('webhooks.secretCopyError', 'Failed to copy secret'));
    }
  };

  const columns = [
    {
      title: t('webhooks.name', 'Name'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Webhook) => (
        <Space>
          {text}
          {!record.is_active && <Tag color="default">{t('webhooks.inactive', 'Inactive')}</Tag>}
        </Space>
      ),
    },
    {
      title: t('webhooks.url', 'URL'),
      dataIndex: 'url',
      key: 'url',
      ellipsis: true,
    },
    {
      title: t('webhooks.events', 'Events'),
      dataIndex: 'events',
      key: 'events',
      render: (events: string[]) => (
        <Space wrap>
          {events.map((e) => (
            <Tag key={e} color="blue">
              {e}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: t('common.actions.label', 'Actions'),
      key: 'actions',
      render: (_: unknown, record: Webhook) => (
        <Space size="middle">
          <Button
            type="link"
            onClick={() => {
              handleOpenModal(record);
            }}
          >
            {t('common.edit', 'Edit')}
          </Button>
          <Popconfirm
            title={t('webhooks.deleteConfirm', {
              name: record.name,
              defaultValue: 'Delete webhook "{{name}}"?',
            })}
            onConfirm={() => {
              void handleDelete(record.id);
            }}
          >
            <Button type="link" danger>
              {t('common.delete', 'Delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={1}>{t('nav.webhooks')}</Title>
        <Button
          type="primary"
          onClick={() => {
            handleOpenModal();
          }}
        >
          {t('webhooks.create', 'Create Webhook')}
        </Button>
      </div>

      {eventTypesError ? (
        <Alert
          title={eventTypesError}
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" onClick={fetchEventTypes}>
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      ) : null}
      {loadError ? (
        <Alert
          title={loadError}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          action={
            <Button
              size="small"
              onClick={() => {
                void fetchWebhooks();
              }}
            >
              {t('common.retry', 'Retry')}
            </Button>
          }
        />
      ) : null}

      {loading && webhooks.length === 0 ? (
        <SkeletonLoader type="table" rows={5} />
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={webhooks}
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      )}

      <Modal
        title={
          editingWebhook
            ? t('webhooks.edit', 'Edit Webhook')
            : t('webhooks.create', 'Create Webhook')
        }
        open={isModalVisible}
        onOk={() => {
          void handleSave();
        }}
        onCancel={() => {
          setIsModalVisible(false);
        }}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={t('webhooks.name', 'Name')}
            rules={[{ required: true, message: t('webhooks.nameRequired', 'Please enter a name') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="url"
            label={t('webhooks.url', 'URL')}
            rules={[
              { required: true, message: t('webhooks.urlRequired', 'Please enter a URL') },
              { type: 'url', message: t('webhooks.urlInvalid', 'Please enter a valid URL') },
            ]}
          >
            <Input type="url" />
          </Form.Item>
          <Form.Item
            name="events"
            label={t('webhooks.events', 'Events')}
            rules={[
              {
                required: true,
                message: t('webhooks.eventsRequired', 'Please select at least one event'),
              },
            ]}
          >
            <Select
              mode="multiple"
              options={eventTypes.map((e) => ({ label: e, value: e }))}
              placeholder={t('webhooks.selectEvents', 'Select events')}
            />
          </Form.Item>
          <Form.Item
            name="is_active"
            label={t('webhooks.active', 'Active')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          {editingWebhook ? (
            <Alert
              type="info"
              showIcon
              title={t(
                'webhooks.secretHidden',
                'Signing secrets are shown only once when a webhook is created.'
              )}
            />
          ) : null}
        </Form>
      </Modal>

      <WebhookCreatedSecretModal
        secret={createdSecret}
        onClose={() => {
          setCreatedSecret(null);
        }}
        onCopy={() => {
          void handleCopyCreatedSecret();
        }}
      />
    </div>
  );
};
