import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, message } from 'antd';

import { useDefinitions, useListDefinitions } from '@/stores/agentDefinitions';

export interface AddAgentModalProps {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onSubmit: (data: {
    agent_id: string;
    display_name?: string;
    description?: string;
  }) => Promise<void>;
  /** Pre-fill hex coordinates when opened from context menu */
  hexCoords?: { q: number; r: number } | null;
}

interface FormValues {
  agent_id: string;
  display_name: string;
  description: string;
}

export const AddAgentModal: FC<AddAgentModalProps> = ({
  open,
  projectId,
  onClose,
  onSubmit,
  hexCoords,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [definitionsLoaded, setDefinitionsLoaded] = useState(false);

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();
  const availableDefinitions = useMemo(
    () =>
      definitions.filter(
        (definition) => definition.project_id === null || definition.project_id === projectId
      ),
    [definitions, projectId]
  );

  useEffect(() => {
    setDefinitionsLoaded(false);
  }, [projectId]);

  useEffect(() => {
    if (open && !definitionsLoaded) {
      listDefinitions({ enabled_only: true, project_id: projectId })
        .then(() => {
          setDefinitionsLoaded(true);
        })
        .catch(() => {
          // Error handled by store
        });
    }
  }, [open, definitionsLoaded, listDefinitions, projectId]);

  useEffect(() => {
    if (open) {
      form.resetFields();
    }
  }, [open, form]);

  const handleAgentChange = useCallback(
    (agentId: string) => {
      const def = availableDefinitions.find((d) => d.id === agentId);
      if (def) {
        form.setFieldsValue({
          display_name: def.display_name ?? def.name,
        });
      }
    },
    [availableDefinitions, form]
  );

  const handleOk = useCallback(async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload: Parameters<typeof onSubmit>[0] = {
        agent_id: values.agent_id,
      };
      if (values.display_name) payload.display_name = values.display_name;
      if (values.description) payload.description = values.description;
      await onSubmit(payload);
      message.success(t('workspaceDetail.agents.addSuccess', 'Agent added to workspace'));
      onClose();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown[] | undefined };
      if (!err.errorFields) {
        message.error(t('workspaceDetail.agents.addError', 'Failed to add agent'));
      }
    } finally {
      setSubmitting(false);
    }
  }, [form, onSubmit, onClose, t]);

  return (
    <Modal
      title={t('workspaceDetail.agents.addTitle', 'Add Agent to Workspace')}
      open={open}
      onCancel={onClose}
      onOk={() => {
        void handleOk();
      }}
      okText={t('common.add', 'Add')}
      cancelText={t('common.cancel', 'Cancel')}
      confirmLoading={submitting}
      okButtonProps={{ disabled: availableDefinitions.length === 0 }}
      width={480}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="agent_id"
          label={t('workspaceDetail.agents.definitionLabel', 'Agent Definition')}
          rules={[
            {
              required: true,
              message: t('workspaceDetail.agents.definitionRequired', 'Please select an agent'),
            },
          ]}
        >
          <Select
            placeholder={t(
              'workspaceDetail.agents.definitionPlaceholder',
              'Select a tenant or current-project agent definition'
            )}
            notFoundContent={t(
              'workspaceDetail.agents.noAvailableDefinitions',
              'No tenant or current-project agents available'
            )}
            showSearch={{
              filterOption: (input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase()),
            }}
            options={availableDefinitions.map((d) => ({
              label: d.display_name ?? d.name,
              value: d.id,
            }))}
            onChange={handleAgentChange}
          />
        </Form.Item>

        <Form.Item
          name="display_name"
          label={t('workspaceDetail.agents.displayNameLabel', 'Display Name')}
        >
          <Input
            placeholder={t(
              'workspaceDetail.agents.displayNamePlaceholder',
              'Name shown in workspace (optional)'
            )}
          />
        </Form.Item>

        <Form.Item
          name="description"
          label={t('workspaceDetail.agents.descriptionLabel', 'Description')}
        >
          <Input.TextArea
            rows={2}
            placeholder={t(
              'workspaceDetail.agents.descriptionPlaceholder',
              'Brief description (optional)'
            )}
          />
        </Form.Item>

        {hexCoords != null && (
          <div className="text-xs text-slate-400 mt-2">
            {t('workspaceDetail.agents.placementHint', {
              q: hexCoords.q,
              r: hexCoords.r,
              defaultValue: `Will be placed at hex (${hexCoords.q.toString()}, ${hexCoords.r.toString()})`,
            })}
          </div>
        )}
      </Form>
    </Modal>
  );
};
