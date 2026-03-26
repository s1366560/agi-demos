import React, { useEffect } from 'react';

import { Form, Input, Modal, Select, Slider } from 'antd';

import type { CyberObjective } from '@/types/workspace';

export interface ObjectiveFormValues {
  title: string;
  description?: string | undefined;
  obj_type: 'objective' | 'key_result';
  parent_id?: string | undefined;
  progress?: number | undefined;
}

export interface ObjectiveCreateModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: ObjectiveFormValues) => void;
  initialValues?: Partial<ObjectiveFormValues> | undefined;
  parentObjectives?: CyberObjective[] | undefined;
  loading?: boolean | undefined;
}

export const ObjectiveCreateModal: React.FC<ObjectiveCreateModalProps> = ({
  open,
  onClose,
  onSubmit,
  initialValues,
  parentObjectives = [],
  loading = false,
}) => {
  const [form] = Form.useForm<ObjectiveFormValues>();
  const isEditing = !!initialValues?.title;
  const objType = Form.useWatch('obj_type', form);

  useEffect(() => {
    if (open) {
      if (initialValues) {
        form.setFieldsValue({
          ...initialValues,
          progress: initialValues.progress ?? 0,
        });
      } else {
        form.resetFields();
        form.setFieldsValue({ obj_type: 'objective', progress: 0 });
      }
    }
  }, [open, initialValues, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      onSubmit(values);
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <Modal
      title={isEditing ? 'Edit Objective/Key Result' : 'Create Objective/Key Result'}
      open={open}
      onCancel={onClose}
      onOk={() => {
        void handleOk();
      }}
      confirmLoading={loading}
      destroyOnClose
      width={600}
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="title"
          label="Title"
          rules={[{ required: true, message: 'Please enter a title' }]}
        >
          <Input placeholder="E.g., Increase Q3 Revenue" />
        </Form.Item>

        <Form.Item name="description" label="Description">
          <Input.TextArea placeholder="Add some details about this objective..." rows={3} />
        </Form.Item>

        <div className="grid grid-cols-2 gap-4">
          <Form.Item
            name="obj_type"
            label="Type"
            rules={[{ required: true, message: 'Please select a type' }]}
          >
            <Select>
              <Select.Option value="objective">Objective</Select.Option>
              <Select.Option value="key_result">Key Result</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item name="progress" label="Progress (%)">
            <Slider min={0} max={100} />
          </Form.Item>
        </div>

        {objType === 'key_result' && (
          <Form.Item
            name="parent_id"
            label="Parent Objective"
            rules={[{ required: true, message: 'Please select a parent objective' }]}
          >
            <Select
              placeholder="Select parent objective"
              options={parentObjectives.map((obj) => ({
                label: obj.title,
                value: obj.id,
              }))}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
};
