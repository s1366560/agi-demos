import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, InputNumber, Progress, Select, Tag, message } from 'antd';

import { useThemeColors } from '@/hooks/useThemeColor';

import { useCreateBinding, useBindingSubmitting } from '../../stores/agentBindings';
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

interface FormValues {
  agent_id?: string;
  channel_type?: string;
  channel_id?: string;
  account_id?: string;
  peer_id?: string;
  group_id?: string;
  priority?: number;
}

/**
 * Calculate specificity score client-side based on field presence.
 * Matches backend AgentBinding.specificity_score logic:
 * - peer_id: +8
 * - account_id: +4
 * - channel_id: +2
 * - channel_type: +1
 * - plus priority
 */
function calculateSpecificityScore(values: FormValues): number {
  let score = 0;
  if (values.peer_id) score += 8;
  if (values.account_id) score += 4;
  if (values.channel_id) score += 2;
  if (values.channel_type && values.channel_type !== 'default') score += 1;
  score += values.priority ?? 0;
  return score;
}

function getSpecificityLabel(score: number): { label: string; color: string } {
  if (score >= 10) return { label: 'Very High', color: 'green' };
  if (score >= 6) return { label: 'High', color: 'lime' };
  if (score >= 3) return { label: 'Medium', color: 'gold' };
  if (score >= 1) return { label: 'Low', color: 'orange' };
  return { label: 'Minimal', color: 'default' };
}

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

  const colors = useThemeColors({
    warning: '--color-warning',
    success: '--color-success',
    info: '--color-info',
  });

  // Watch form values for specificity score calculation
  const formValues = Form.useWatch([], form) as FormValues | undefined;
  const specificityScore = useMemo(() => {
    if (!formValues) return 0;
    return calculateSpecificityScore(formValues);
  }, [formValues]);

  const specificityInfo = useMemo(() => getSpecificityLabel(specificityScore), [specificityScore]);

  useEffect(() => {
    if (isOpen && !definitionsLoaded) {
      listDefinitions({ enabled_only: true })
        .then(() => {
          setDefinitionsLoaded(true);
        })
        .catch(() => {
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
        account_id: values.account_id || undefined,
        peer_id: values.peer_id || undefined,
        group_id: values.group_id || undefined,
        priority: values.priority,
      };
      await createBinding(data);
      message.success(t('tenant.agentBindings.messages.createSuccess', 'Binding created'));
      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown[] | undefined };
      if (!err.errorFields) {
        message.error(t('tenant.agentBindings.messages.createError', 'Failed to create binding'));
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
      width={560}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="agent_id"
          label={t('tenant.agentBindings.modal.agent', 'Agent')}
          rules={[
            {
              required: true,
              message: t('tenant.agentBindings.modal.agentRequired', 'Please select an agent'),
            },
          ]}
        >
          <Select
            placeholder={t('tenant.agentBindings.modal.selectAgent', 'Select an agent definition')}
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
          name="account_id"
          label={t('tenant.agentBindings.modal.accountId', 'Account ID')}
          tooltip={t(
            'tenant.agentBindings.modal.accountIdTooltip',
            'Optional: bind to a specific user account'
          )}
        >
          <Input
            placeholder={t(
              'tenant.agentBindings.modal.accountIdPlaceholder',
              'Optional: user account identifier'
            )}
          />
        </Form.Item>

        <Form.Item
          name="peer_id"
          label={t('tenant.agentBindings.modal.peerId', 'Peer ID')}
          tooltip={t(
            'tenant.agentBindings.modal.peerIdTooltip',
            'Optional: bind to a specific peer identity (highest specificity)'
          )}
        >
          <Input
            placeholder={t(
              'tenant.agentBindings.modal.peerIdPlaceholder',
              'Optional: peer identifier'
            )}
          />
        </Form.Item>

        <Form.Item
          name="group_id"
          label={t('tenant.agentBindings.modal.groupId', 'Group ID')}
          tooltip={t(
            'tenant.agentBindings.modal.groupIdTooltip',
            'Optional: group bindings for broadcast routing (all agents in group receive messages)'
          )}
        >
          <Input
            placeholder={t(
              'tenant.agentBindings.modal.groupIdPlaceholder',
              'Optional: broadcast group identifier'
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

        {/* Specificity Score Preview */}
        <div className="mt-4 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {t('tenant.agentBindings.modal.specificityPreview', 'Specificity Preview')}
            </span>
            <Tag color={specificityInfo.color}>{specificityInfo.label}</Tag>
          </div>
          <div className="flex items-center gap-3">
            <Progress
              percent={Math.min(100, (specificityScore / 15) * 100)}
              showInfo={false}
              size="small"
              className="flex-1"
              strokeColor={{
                '0%': colors.warning,
                '50%': colors.success,
                '100%': colors.info,
              }}
            />
            <span className="text-sm font-mono text-slate-600 dark:text-slate-400 w-8 text-right">
              {specificityScore}
            </span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
            {t(
              'tenant.agentBindings.modal.specificityHint',
              'Higher specificity = higher routing priority. Add more specific fields to increase score.'
            )}
          </p>
        </div>
      </Form>
    </Modal>
  );
};

export default AgentBindingModal;
