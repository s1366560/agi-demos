/**
 * EnvVarInputModal Component
 *
 * Displays a form for users to input environment variables requested by an agent tool.
 * Supports multiple field types (text, password, textarea) and handles batch submissions.
 */

import { useState, useEffect, useCallback } from 'react';
import type { FC, ReactNode } from 'react';

import { KeyOutlined, CheckCircleOutlined, LockOutlined, FileTextOutlined } from '@ant-design/icons';

import { Modal, Form, Input, Space, Button, Tag, Typography, Alert } from '@/components/ui/lazyAntd';

import type { EnvVarRequestedEventData, EnvVarField, EnvVarInputType } from '../../types/agent';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface EnvVarInputModalProps {
  data: EnvVarRequestedEventData;
  onSubmit: (requestId: string, values: Record<string, string>) => void;
  onCancel?: () => void;
}

const inputTypeIcons: Record<EnvVarInputType, ReactNode> = {
  text: <FileTextOutlined />,
  password: <LockOutlined />,
  textarea: <FileTextOutlined />,
};

const inputTypeLabels: Record<EnvVarInputType, string> = {
  text: '文本',
  password: '密码',
  textarea: '多行文本',
};

export const EnvVarInputModal: FC<EnvVarInputModalProps> = ({
  data,
  onSubmit,
  onCancel,
}) => {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  // Safely get fields array with fallback
  const fields = data.fields || [];

  // Initialize form with default values
  useEffect(() => {
    const initialValues: Record<string, string> = {};
    fields.forEach((field) => {
      if (field.default_value) {
        initialValues[field.name] = field.default_value;
      }
    });
    form.setFieldsValue(initialValues);
  }, [fields, form]);

  const handleSubmit = useCallback(async () => {
    try {
      setSubmitting(true);
      const values = await form.validateFields();
      
      // Filter out empty optional fields
      const filteredValues: Record<string, string> = {};
      Object.entries(values).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          filteredValues[key] = String(value);
        }
      });
      
      onSubmit(data.request_id, filteredValues);
    } catch (error) {
      console.error('Form validation failed:', error);
    } finally {
      setSubmitting(false);
    }
  }, [form, data.request_id, onSubmit]);

  const renderInput = (field: EnvVarField) => {
    const commonProps = {
      placeholder: field.placeholder || `请输入${field.label}`,
    };

    switch (field.input_type) {
      case 'password':
        return <Input.Password {...commonProps} />;
      case 'textarea':
        return <TextArea {...commonProps} rows={4} />;
      case 'text':
      default:
        return <Input {...commonProps} />;
    }
  };

  return (
    <Modal
      open={true}
      title={
        <Space>
          <KeyOutlined style={{ color: '#1890ff' }} />
          <span>配置环境变量</span>
          <Tag color="blue">{data.tool_name}</Tag>
        </Space>
      }
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          取消
        </Button>,
        <Button
          key="submit"
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          loading={submitting}
        >
          保存并继续
        </Button>,
      ]}
      width={600}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Message */}
        {data.message && (
          <Alert
            message={data.message}
            type="info"
            showIcon
            className="mb-4"
          />
        )}

        {/* Context (if provided) */}
        {data.context && Object.keys(data.context).length > 0 && (
          <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800 mb-4">
            <Text className="text-sm text-blue-700 dark:text-blue-300">
              <strong>上下文信息：</strong>
            </Text>
            <div className="mt-2 space-y-1">
              {Object.entries(data.context).map(([key, value]) => (
                <div key={key} className="text-sm">
                  <Text className="text-blue-600 dark:text-blue-400">{key}:</Text>{' '}
                  <Text className="text-blue-800 dark:text-blue-200">
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </Text>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Form Fields */}
        <Form
          form={form}
          layout="vertical"
          className="mt-4"
        >
          {fields.map((field) => (
            <Form.Item
              key={field.name}
              name={field.name}
              label={
                <Space>
                  {inputTypeIcons[field.input_type]}
                  <span>{field.label}</span>
                  <Tag color="default" className="text-xs">
                    {inputTypeLabels[field.input_type]}
                  </Tag>
                  {field.required && (
                    <Tag color="red" className="text-xs">
                      必填
                    </Tag>
                  )}
                </Space>
              }
              rules={[
                {
                  required: field.required,
                  message: `请输入${field.label}`,
                },
              ]}
              extra={field.description && (
                <Paragraph type="secondary" className="text-xs mt-1 mb-0">
                  {field.description}
                </Paragraph>
              )}
            >
              {renderInput(field)}
            </Form.Item>
          ))}
        </Form>

        {/* Security Notice for passwords */}
        {data.fields.some(f => f.input_type === 'password') && (
          <Alert
            message="安全提示"
            description="密码类型的环境变量将被加密存储，保护您的敏感信息。"
            type="warning"
            showIcon
            className="mt-4"
          />
        )}
      </div>
    </Modal>
  );
};
