import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
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
    } catch {
      // Validation failures are expected — antd Form shows inline errors.
    }
  };

  return (
    <Modal
      title={
        isEditing
          ? t('workspaceDetail.objectives.editModalTitle', 'Edit Objective/Key Result')
          : t('workspaceDetail.objectives.createModalTitle', 'Create Objective/Key Result')
      }
      open={open}
      onCancel={onClose}
      onOk={() => {
        void handleOk();
      }}
      confirmLoading={loading}
      destroyOnHidden
      width={600}
      okText={isEditing ? t('common.save', 'Save') : t('common.create', 'Create')}
      cancelText={t('common.cancel', 'Cancel')}
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="title"
          label={t('workspaceDetail.objectives.titleLabel', 'Title')}
          rules={[
            {
              required: true,
              message: t('workspaceDetail.objectives.titleRequired', 'Please enter a title'),
            },
          ]}
        >
          <Input
            placeholder={t(
              'workspaceDetail.objectives.titlePlaceholder',
              'E.g., Increase Q3 Revenue'
            )}
          />
        </Form.Item>

        <Form.Item
          name="description"
          label={t('workspaceDetail.objectives.descriptionLabel', 'Description')}
        >
          <Input.TextArea
            placeholder={t(
              'workspaceDetail.objectives.descriptionPlaceholder',
              'Add some details about this objective…'
            )}
            rows={3}
          />
        </Form.Item>

        <div className="grid grid-cols-2 gap-4">
          <Form.Item
            name="obj_type"
            label={t('workspaceDetail.objectives.typeLabel', 'Type')}
            rules={[
              {
                required: true,
                message: t('workspaceDetail.objectives.typeRequired', 'Please select a type'),
              },
            ]}
          >
            <Select>
              <Select.Option value="objective">
                {t('workspaceDetail.objectives.typeObjective', 'Objective')}
              </Select.Option>
              <Select.Option value="key_result">
                {t('workspaceDetail.objectives.typeKeyResult', 'Key Result')}
              </Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="progress"
            label={t('workspaceDetail.objectives.progressLabel', 'Progress (%)')}
          >
            <Slider min={0} max={100} />
          </Form.Item>
        </div>

        {objType === 'key_result' && (
          <Form.Item
            name="parent_id"
            label={t('workspaceDetail.objectives.parentObjectiveLabel', 'Parent Objective')}
            rules={[
              {
                required: true,
                message: t(
                  'workspaceDetail.objectives.parentObjectiveRequired',
                  'Please select a parent objective'
                ),
              },
            ]}
          >
            <Select
              placeholder={t(
                'workspaceDetail.objectives.parentObjectivePlaceholder',
                'Select parent objective'
              )}
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
