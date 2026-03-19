import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, InputNumber, Select, message } from 'antd';

import {
  useCreateBinding,
  useBindingSubmitting,
} from '../../stores/agentBindings';
import { useDefinitions, useListDefinitions } from '../../stores/agentDefinitions';

import type { CreateBindingRequest } from '../../types/multiAgent';

const { Option } = Select;

export interface AgentBindingModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const CHANNEL_TYPES = [
  { value: 'default', label: 'Default (All Channels)' },
  { value: 'web', label: 'Web Chat' },
  { value: 'feishu', label: 'Feishu' },
  { value: 'dingtalk', label: 'DingTalk' },
  { value: 'wechat', label: 'WeChat' },
  { value: 'slack', label: 'Slack' },
  { value: 'api', label: 'API' },
];

export const AgentBindingModal: React.FC<AgentBindingModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [definitionsLoaded, setDefinitionsLoaded] = useState(false);

  const isSubmitting = useBindingSubmitting();
  const createBinding = useCreateBinding();
  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  useEffect(() => {
    if (isOpen && !definitionsLoaded) {
      listDefinitions({ enabled_only: true }).then(() => {
        setDefinitionsLoaded(true);
      }).catch(() => {
        // Error handled by store
      });
    }
  }, [isOpen, definitionsLoaded, listDefinitions]);

  useEffect(() => {
    if (isOpen) {
      form.resetFields();
    }
  }, [isOpen, form]);

  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const data: CreateBindingRequest = {
        agent_id: values.agent_id,
        channel_type: values.channel_type === 'default' ? undefined : values.channel_type,
        channel_id: values.channel_id || undefined,
        priority: values.priority,
      };
      await createBinding(data);
      message.success(
        t('tenant.agentBindings.messages.createSuccess', 'Binding created')
      );
      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown[] | undefined };
      if (!err.errorFields) {
        message.error(
          t('tenant.agentBindings.messages.createError', 'Failed to create binding')
        );
      }
    }
  }, [form, createBinding, onSuccess, t]);

  return (
    <Modal
      title={t('tenant.agentBindings.modal.createTitle', 'Create Agent Binding')}
      open={isOpen}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={t('common.create', 'Create')}
      cancelText={t('common.cancel', 'Cancel')}
      confirmLoading={isSubmitting}
      width={520}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="agent_id"
          label={t('tenant.agentBindings.modal.agent', 'Agent')}
          rules={[
            {
              required: true,
              message: t(
                'tenant.agentBindings.modal.agentRequired',
                'Please select an agent'
              ),
            },
          ]}
        >
          <Select
            placeholder={t(
              'tenant.agentBindings.modal.selectAgent',
              'Select an agent definition'
            )}
            showSearch
            filterOption={(input, option) =>
              (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
            }
            options={definitions.map((d) => ({
              label: d.display_name ?? d.name,
              value: d.id,
            }))}
          />
        </Form.Item>

        <Form.Item
          name="channel_type"
          label={t('tenant.agentBindings.modal.channelType', 'Channel Type')}
          initialValue="default"
        >
          <Select>
            {CHANNEL_TYPES.map((ct) => (
              <Option key={ct.value} value={ct.value}>
                {ct.label}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="channel_id"
          label={t('tenant.agentBindings.modal.channelId', 'Channel ID')}
          tooltip={t(
            'tenant.agentBindings.modal.channelIdTooltip',
            'Leave empty to match all channels of the selected type'
          )}
        >
          <Input
            placeholder={t(
              'tenant.agentBindings.modal.channelIdPlaceholder',
              'Optional: specific channel identifier'
            )}
          />
        </Form.Item>

        <Form.Item
          name="priority"
          label={t('tenant.agentBindings.modal.priority', 'Priority')}
          tooltip={t(
            'tenant.agentBindings.modal.priorityTooltip',
            'Higher priority bindings are matched first. Default is 0.'
          )}
          initialValue={0}
        >
          <InputNumber min={-100} max={100} className="w-full" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default AgentBindingModal;
