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

import { useCurrentTenant } from '@/stores/tenant';

import { eventService } from '@/services/eventService';
import { webhookService, type Webhook } from '@/services/webhookService';

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

export const Webhooks: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId } = useParams<{ tenantId?: string }>();
  const currentTenant = useCurrentTenant();
  const selectedTenantId = tenantId ?? currentTenant?.id;
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [eventTypesError, setEventTypesError] = useState<string | null>(null);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null);
  const [form] = Form.useForm<WebhookFormValues>();

  const fetchWebhooks = React.useCallback(async () => {
    if (!selectedTenantId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await webhookService.listWebhooks(selectedTenantId);
      setWebhooks(data);
    } catch (err) {
      console.error(err);
      const errorMessage = t('webhooks.fetchError', 'Failed to fetch webhooks');
      setWebhooks([]);
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [selectedTenantId, t]);

  useEffect(() => {
    void fetchWebhooks();
  }, [fetchWebhooks]);

  useEffect(() => {
    setEventTypesError(null);
    void eventService
      .getEventTypes(selectedTenantId ? { tenant_id: selectedTenantId } : undefined)
      .then((types) => {
        setEventTypes(types);
      })
      .catch((err: unknown) => {
        console.error(err);
        setEventTypes([]);
        setEventTypesError(t('webhooks.eventTypesError', 'Failed to load webhook event types'));
      });
  }, [selectedTenantId, t]);

  const handleDelete = async (id: string) => {
    try {
      await webhookService.deleteWebhook(id);
      message.success(t('webhooks.deleteSuccess', 'Webhook deleted'));
      void fetchWebhooks();
    } catch (err) {
      console.error(err);
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
    try {
      const values = await form.validateFields();
      if (editingWebhook) {
        await webhookService.updateWebhook(editingWebhook.id, values);
        message.success(t('webhooks.updateSuccess', 'Webhook updated'));
      } else {
        await webhookService.createWebhook(selectedTenantId, values);
        message.success(t('webhooks.createSuccess', 'Webhook created'));
      }
      setIsModalVisible(false);
      void fetchWebhooks();
    } catch (err) {
      if (isFormValidationError(err)) return;
      console.error(err);
      message.error(
        editingWebhook
          ? t('webhooks.updateError', 'Failed to update webhook')
          : t('webhooks.createError', 'Failed to create webhook')
      );
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
            title={t('webhooks.deleteConfirm', 'Are you sure you want to delete this webhook?')}
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
        <Title level={4}>{t('nav.webhooks')}</Title>
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
        <Alert title={eventTypesError} type="warning" showIcon style={{ marginBottom: 16 }} />
      ) : null}
      {loadError ? (
        <Alert title={loadError} type="error" showIcon style={{ marginBottom: 16 }} />
      ) : null}

      <Table
        rowKey="id"
        columns={columns}
        dataSource={webhooks}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

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
            <Input />
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
          {editingWebhook?.secret && (
            <Form.Item label={t('webhooks.secret', 'Secret')}>
              <Input.Password value={editingWebhook.secret} readOnly />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};
