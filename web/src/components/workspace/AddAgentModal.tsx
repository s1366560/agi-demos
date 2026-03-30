import { useCallback, useEffect, useState } from 'react';
import type { FC } from 'react';

import { Modal, Form, Input, Select, message } from 'antd';

import { useDefinitions, useListDefinitions } from '@/stores/agentDefinitions';


export interface AddAgentModalProps {
  open: boolean;
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
  onClose,
  onSubmit,
  hexCoords,
}) => {
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [definitionsLoaded, setDefinitionsLoaded] = useState(false);

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  useEffect(() => {
    if (open && !definitionsLoaded) {
      listDefinitions({ enabled_only: true })
        .then(() => {
          setDefinitionsLoaded(true);
        })
        .catch(() => {
          // Error handled by store
        });
    }
  }, [open, definitionsLoaded, listDefinitions]);

  useEffect(() => {
    if (open) {
      form.resetFields();
    }
  }, [open, form]);

  const handleAgentChange = useCallback(
    (agentId: string) => {
      const def = definitions.find((d) => d.id === agentId);
      if (def) {
        form.setFieldsValue({
          display_name: def.display_name ?? def.name,
        });
      }
    },
    [definitions, form]
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
      message.success('Agent added to workspace');
      onClose();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown[] | undefined };
      if (!err.errorFields) {
        message.error('Failed to add agent');
      }
    } finally {
      setSubmitting(false);
    }
  }, [form, onSubmit, onClose]);

  return (
    <Modal
      title="Add Agent to Workspace"
      open={open}
      onCancel={onClose}
      onOk={() => { void handleOk(); }}
      okText="Add"
      cancelText="Cancel"
      confirmLoading={submitting}
      width={480}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="agent_id"
          label="Agent Definition"
          rules={[{ required: true, message: 'Please select an agent' }]}
        >
          <Select
            placeholder="Select an agent definition"
            showSearch={{
              filterOption: (input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase()),
            }}
            options={definitions.map((d) => ({
              label: d.display_name ?? d.name,
              value: d.id,
            }))}
            onChange={handleAgentChange}
          />
        </Form.Item>

        <Form.Item name="display_name" label="Display Name">
          <Input placeholder="Name shown in workspace (optional)" />
        </Form.Item>

        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} placeholder="Brief description (optional)" />
        </Form.Item>

        {hexCoords != null && (
          <div className="text-xs text-slate-400 mt-2">
            Will be placed at hex ({hexCoords.q}, {hexCoords.r})
          </div>
        )}
      </Form>
    </Modal>
  );
};
