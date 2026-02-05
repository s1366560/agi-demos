/**
 * UnifiedHITLPanel Component
 * 
 * A unified Human-in-the-Loop panel that handles all HITL request types:
 * - Clarification: Questions requiring user input
 * - Decision: Choices with detailed options
 * - EnvVar: Environment variable configuration
 * - Permission: Tool authorization requests
 * 
 * Features:
 * - Progress countdown timer for timeouts
 * - Unified styling with type-specific content
 * - Keyboard shortcuts for quick responses
 * - Responsive design for mobile/desktop
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';

import {
  QuestionCircleOutlined,
  ExclamationCircleOutlined,
  KeyOutlined,
  SafetyOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  WarningOutlined,
  LockOutlined,
  FileTextOutlined,
  CodeOutlined,
} from '@ant-design/icons';

import { 
  Modal, 
  Form, 
  Input, 
  Radio, 
  Button, 
  Tag, 
  Typography, 
  Alert, 
  Space, 
  Divider,
  Progress,
  Tooltip,
  Badge,
  Descriptions,
} from '@/components/ui/lazyAntd';

import { useUnifiedHITLStore, useIsSubmitting } from '../../stores/hitlStore.unified';
import { getRemainingTimeSeconds } from '../../types/hitl.unified';

import type { 
  UnifiedHITLRequest, 
  HITLType,
  HITLResponseData,
  DecisionOption,
  EnvVarField,
} from '../../types/hitl.unified';


const { Text, Paragraph, Title } = Typography;
const { TextArea } = Input;

// =============================================================================
// Type-specific configurations
// =============================================================================

const TYPE_CONFIG: Record<HITLType, {
  icon: React.ReactNode;
  title: string;
  color: string;
  submitText: string;
}> = {
  clarification: {
    icon: <QuestionCircleOutlined style={{ color: '#1890ff' }} />,
    title: '需要澄清',
    color: 'blue',
    submitText: '确认回答',
  },
  decision: {
    icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
    title: '需要决策',
    color: 'gold',
    submitText: '确认决策',
  },
  env_var: {
    icon: <KeyOutlined style={{ color: '#52c41a' }} />,
    title: '配置环境变量',
    color: 'green',
    submitText: '保存配置',
  },
  permission: {
    icon: <SafetyOutlined style={{ color: '#722ed1' }} />,
    title: '权限请求',
    color: 'purple',
    submitText: '授权执行',
  },
};

const CLARIFICATION_TYPE_LABELS: Record<string, string> = {
  scope: '范围确认',
  approach: '方案选择',
  prerequisite: '前置条件',
  priority: '优先级',
  custom: '自定义',
};

const DECISION_TYPE_LABELS: Record<string, string> = {
  branch: '分支选择',
  method: '方法选择',
  confirmation: '确认操作',
  risk: '风险确认',
  custom: '自定义',
};

const RISK_LEVEL_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  low: { label: '低风险', color: 'green', icon: <SafetyOutlined style={{ color: '#52c41a' }} /> },
  medium: { label: '中等风险', color: 'gold', icon: <WarningOutlined style={{ color: '#faad14' }} /> },
  high: { label: '高风险', color: 'red', icon: <WarningOutlined style={{ color: '#f5222d' }} /> },
};

// =============================================================================
// Main Component
// =============================================================================

interface UnifiedHITLPanelProps {
  request: UnifiedHITLRequest;
  onClose?: () => void;
}

export const UnifiedHITLPanel: React.FC<UnifiedHITLPanelProps> = ({
  request,
  onClose,
}) => {
  const submitResponse = useUnifiedHITLStore((state) => state.submitResponse);
  const cancelRequest = useUnifiedHITLStore((state) => state.cancelRequest);
  const isSubmitting = useIsSubmitting(request.requestId);
  
  const [remainingTime, setRemainingTime] = useState<number | null>(
    getRemainingTimeSeconds(request)
  );

  // Update remaining time every second
  useEffect(() => {
    const timer = setInterval(() => {
      const remaining = getRemainingTimeSeconds(request);
      setRemainingTime(remaining);
      if (remaining !== null && remaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [request]);

  const config = TYPE_CONFIG[request.hitlType];
  
  const handleCancel = useCallback(async () => {
    try {
      await cancelRequest(request.requestId, 'User cancelled');
      onClose?.();
    } catch (error) {
      console.error('Failed to cancel HITL request:', error);
    }
  }, [cancelRequest, request.requestId, onClose]);

  const handleSubmit = useCallback(async (responseData: HITLResponseData) => {
    try {
      await submitResponse(request.requestId, request.hitlType, responseData);
      onClose?.();
    } catch (error) {
      console.error('Failed to submit HITL response:', error);
    }
  }, [submitResponse, request, onClose]);

  // Calculate progress percentage
  const progressPercent = useMemo(() => {
    if (remainingTime === null || !request.timeoutSeconds) return 100;
    return Math.max(0, (remainingTime / request.timeoutSeconds) * 100);
  }, [remainingTime, request.timeoutSeconds]);

  const progressStatus = progressPercent <= 20 ? 'exception' : progressPercent <= 50 ? 'normal' : 'success';

  return (
    <Modal
      open={true}
      title={
        <div className="flex items-center justify-between">
          <Space>
            {config.icon}
            <span>{config.title}</span>
            <SubtypeTag request={request} />
          </Space>
          {remainingTime !== null && (
            <Tooltip title="剩余时间">
              <Badge 
                count={`${Math.floor(remainingTime)}s`}
                style={{ 
                  backgroundColor: progressPercent <= 20 ? '#f5222d' : '#52c41a',
                  marginRight: 8
                }}
              >
                <ClockCircleOutlined style={{ fontSize: 16, marginRight: 4 }} />
              </Badge>
            </Tooltip>
          )}
        </div>
      }
      onCancel={handleCancel}
      footer={null}
      width={700}
      destroyOnHidden
      className="hitl-panel-modal"
    >
      <div className="space-y-4">
        {/* Timeout Progress */}
        {remainingTime !== null && (
          <Progress 
            percent={progressPercent} 
            status={progressStatus}
            showInfo={false}
            size="small"
          />
        )}

        {/* Context Alert */}
        <ContextAlert request={request} />

        {/* Type-specific Content */}
        <HITLContent 
          request={request}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
          isSubmitting={isSubmitting}
          submitText={config.submitText}
        />
      </div>
    </Modal>
  );
};

// =============================================================================
// Sub-components
// =============================================================================

const SubtypeTag: React.FC<{ request: UnifiedHITLRequest }> = ({ request }) => {
  let label: string | undefined;
  let color = 'default';

  switch (request.hitlType) {
    case 'clarification':
      if (request.clarificationData?.clarificationType) {
        label = CLARIFICATION_TYPE_LABELS[request.clarificationData.clarificationType];
        color = 'blue';
      }
      break;
    case 'decision':
      if (request.decisionData?.decisionType) {
        label = DECISION_TYPE_LABELS[request.decisionData.decisionType];
        color = request.decisionData.decisionType === 'risk' ? 'red' : 'orange';
      }
      break;
    case 'env_var':
      if (request.envVarData?.toolName) {
        label = request.envVarData.toolName;
        color = 'green';
      }
      break;
    case 'permission':
      if (request.permissionData?.riskLevel) {
        const risk = RISK_LEVEL_CONFIG[request.permissionData.riskLevel];
        label = risk?.label;
        color = risk?.color || 'purple';
      }
      break;
  }

  return label ? <Tag color={color}>{label}</Tag> : null;
};

const ContextAlert: React.FC<{ request: UnifiedHITLRequest }> = ({ request }) => {
  const context = 
    request.clarificationData?.context ||
    request.decisionData?.context ||
    request.envVarData?.context ||
    request.permissionData?.context;

  if (!context || Object.keys(context).length === 0) return null;

  return (
    <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
      <Text className="text-sm text-blue-700 dark:text-blue-300 font-semibold">
        上下文信息：
      </Text>
      <div className="mt-2 space-y-1">
        {Object.entries(context).map(([key, value]) => (
          <div key={key} className="text-sm">
            <Text className="text-blue-600 dark:text-blue-400">{key}:</Text>{' '}
            <Text className="text-blue-800 dark:text-blue-200">
              {typeof value === 'object' ? JSON.stringify(value) : String(value)}
            </Text>
          </div>
        ))}
      </div>
    </div>
  );
};

// =============================================================================
// Content Components (type-specific)
// =============================================================================

interface HITLContentProps {
  request: UnifiedHITLRequest;
  onSubmit: (response: HITLResponseData) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  submitText: string;
}

const HITLContent: React.FC<HITLContentProps> = (props) => {
  switch (props.request.hitlType) {
    case 'clarification':
      return <ClarificationContent {...props} />;
    case 'decision':
      return <DecisionContent {...props} />;
    case 'env_var':
      return <EnvVarContent {...props} />;
    case 'permission':
      return <PermissionContent {...props} />;
    default:
      return <div>Unknown HITL type</div>;
  }
};

// =============================================================================
// Clarification Content
// =============================================================================

const ClarificationContent: React.FC<HITLContentProps> = ({
  request,
  onSubmit,
  onCancel,
  isSubmitting,
  submitText,
}) => {
  const data = request.clarificationData;
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data?.options.find(opt => opt.recommended)?.id || null
  );
  const [customInput, setCustomInput] = useState('');

  const handleSubmit = () => {
    if (selectedOption === 'custom' && data?.allowCustom) {
      if (customInput.trim()) {
        onSubmit({ answer: customInput.trim() });
      }
    } else if (selectedOption) {
      onSubmit({ answer: selectedOption });
    }
  };

  const isSubmitDisabled = 
    !selectedOption || 
    (selectedOption === 'custom' && !customInput.trim());

  return (
    <div className="space-y-4">
      {/* Question */}
      <Paragraph className="text-base font-medium text-slate-800 dark:text-slate-200">
        {request.question || data?.question}
      </Paragraph>

      {/* Options */}
      <Radio.Group
        value={selectedOption}
        onChange={(e) => setSelectedOption(e.target.value)}
        className="w-full"
      >
        <Space direction="vertical" className="w-full" size="middle">
          {data?.options.map((option) => (
            <Radio key={option.id} value={option.id} className="w-full">
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <Text strong>{option.label}</Text>
                  {option.recommended && (
                    <Tag color="green" className="text-xs">推荐</Tag>
                  )}
                </div>
                {option.description && (
                  <Text type="secondary" className="text-sm mt-1">
                    {option.description}
                  </Text>
                )}
              </div>
            </Radio>
          ))}

          {data?.allowCustom && (
            <Radio value="custom" className="w-full">
              <div className="flex flex-col w-full">
                <Text strong>自定义输入</Text>
                {selectedOption === 'custom' && (
                  <TextArea
                    value={customInput}
                    onChange={(e) => setCustomInput(e.target.value)}
                    placeholder="输入您的答案..."
                    rows={3}
                    className="mt-2"
                    autoFocus
                  />
                )}
              </div>
            </Radio>
          )}
        </Space>
      </Radio.Group>

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>取消</Button>
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
          loading={isSubmitting}
        >
          {submitText}
        </Button>
      </div>
    </div>
  );
};

// =============================================================================
// Decision Content
// =============================================================================

const DecisionContent: React.FC<HITLContentProps> = ({
  request,
  onSubmit,
  onCancel,
  isSubmitting,
  submitText,
}) => {
  const data = request.decisionData;
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data?.options.find(opt => opt.recommended)?.id || data?.defaultOption || null
  );
  const [customInput, setCustomInput] = useState('');

  const handleSubmit = () => {
    if (selectedOption === 'custom' && data?.allowCustom) {
      if (customInput.trim()) {
        onSubmit({ decision: customInput.trim() });
      }
    } else if (selectedOption) {
      onSubmit({ decision: selectedOption });
    }
  };

  const isSubmitDisabled =
    !selectedOption ||
    (selectedOption === 'custom' && !customInput.trim());

  const selectedOptionData = data?.options.find(opt => opt.id === selectedOption);
  const hasHighRisk = selectedOptionData?.risks && selectedOptionData.risks.length > 0;

  return (
    <div className="space-y-4">
      {/* Question */}
      <Title level={5} className="text-slate-800 dark:text-slate-200">
        {request.question || data?.question}
      </Title>

      {/* Default option warning */}
      {data?.defaultOption && (
        <Alert
          message="超时默认选项"
          description={`如果您未在限定时间内做出决策，系统将自动选择：${
            data.options.find(opt => opt.id === data.defaultOption)?.label
          }`}
          type="info"
          showIcon
        />
      )}

      <Divider />

      {/* Options */}
      <div className="space-y-3">
        {data?.options.map((option) => (
          <DecisionOptionCard
            key={option.id}
            option={option}
            selected={selectedOption === option.id}
            onSelect={() => setSelectedOption(option.id)}
          />
        ))}

        {data?.allowCustom && (
          <div
            onClick={() => setSelectedOption('custom')}
            className={`
              p-4 rounded-lg border-2 cursor-pointer transition-all
              ${selectedOption === 'custom'
                ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-primary-300'
              }
            `}
          >
            <div className="flex items-center gap-2 mb-2">
              <Radio checked={selectedOption === 'custom'} />
              <Text strong>自定义决策</Text>
            </div>
            {selectedOption === 'custom' && (
              <TextArea
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                placeholder="输入您的决策..."
                rows={3}
                className="ml-6"
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            )}
          </div>
        )}
      </div>

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>取消</Button>
        <Button
          type={hasHighRisk ? 'default' : 'primary'}
          danger={hasHighRisk}
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
          loading={isSubmitting}
        >
          {hasHighRisk ? '确认并承担风险' : submitText}
        </Button>
      </div>
    </div>
  );
};

const DecisionOptionCard: React.FC<{
  option: DecisionOption;
  selected: boolean;
  onSelect: () => void;
}> = ({ option, selected, onSelect }) => {
  const hasRisks = option.risks && option.risks.length > 0;

  return (
    <div
      onClick={onSelect}
      className={`
        p-4 rounded-lg border-2 cursor-pointer transition-all
        ${selected
          ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
          : 'border-slate-200 dark:border-slate-700 hover:border-primary-300'
        }
      `}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1">
          <Radio checked={selected} />
          <Text strong className="text-base">{option.label}</Text>
          {option.recommended && (
            <Tag color="green" className="text-xs">推荐</Tag>
          )}
        </div>
      </div>

      {option.description && (
        <Paragraph className="text-sm text-slate-600 dark:text-slate-400 mb-3 ml-6">
          {option.description}
        </Paragraph>
      )}

      {(option.estimatedTime || option.estimatedCost) && (
        <div className="flex gap-4 ml-6 mb-2">
          {option.estimatedTime && (
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <ClockCircleOutlined />
              <span>{option.estimatedTime}</span>
            </div>
          )}
          {option.estimatedCost && (
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <span>$</span>
              <span>{option.estimatedCost}</span>
            </div>
          )}
        </div>
      )}

      {hasRisks && (
        <Alert
          title="风险提示"
          description={
            <ul className="list-disc list-inside space-y-1 text-sm">
              {option.risks!.map((risk, idx) => (
                <li key={idx}>{risk}</li>
              ))}
            </ul>
          }
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          className="ml-6 mt-2"
        />
      )}
    </div>
  );
};

// =============================================================================
// EnvVar Content
// =============================================================================

const EnvVarContent: React.FC<HITLContentProps> = ({
  request,
  onSubmit,
  onCancel,
  isSubmitting,
  submitText,
}) => {
  const data = request.envVarData;
  const [form] = Form.useForm();

  useEffect(() => {
    const initialValues: Record<string, string> = {};
    data?.fields.forEach((field) => {
      if (field.defaultValue) {
        initialValues[field.name] = field.defaultValue;
      }
    });
    form.setFieldsValue(initialValues);
  }, [data?.fields, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      
      // Filter out empty optional fields
      const filteredValues: Record<string, string> = {};
      Object.entries(values).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          filteredValues[key] = String(value);
        }
      });
      
      onSubmit({ values: filteredValues, save: false });
    } catch (error) {
      console.error('Form validation failed:', error);
    }
  };

  const renderInput = (field: EnvVarField) => {
    const commonProps = {
      placeholder: field.placeholder || `请输入${field.label}`,
    };

    switch (field.inputType) {
      case 'password':
        return <Input.Password {...commonProps} />;
      case 'textarea':
        return <TextArea {...commonProps} rows={4} />;
      case 'text':
      default:
        return <Input {...commonProps} />;
    }
  };

  const inputTypeIcons: Record<string, React.ReactNode> = {
    text: <FileTextOutlined />,
    password: <LockOutlined />,
    textarea: <FileTextOutlined />,
  };

  return (
    <div className="space-y-4">
      {/* Message */}
      {data?.message && (
        <Alert title={data.message} type="info" showIcon />
      )}

      {/* Form Fields */}
      <Form form={form} layout="vertical">
        {data?.fields.map((field) => (
          <Form.Item
            key={field.name}
            name={field.name}
            label={
              <Space>
                {inputTypeIcons[field.inputType]}
                <span>{field.label}</span>
                {field.required && (
                  <Tag color="red" className="text-xs">必填</Tag>
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

      {/* Security Notice */}
      {data?.fields.some(f => f.inputType === 'password') && (
        <Alert
          message="安全提示"
          description="密码类型的环境变量将被加密存储，保护您的敏感信息。"
          type="warning"
          showIcon
        />
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>取消</Button>
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          loading={isSubmitting}
        >
          {submitText}
        </Button>
      </div>
    </div>
  );
};

// =============================================================================
// Permission Content
// =============================================================================

const PermissionContent: React.FC<HITLContentProps> = ({
  request,
  onSubmit,
  onCancel: _onCancel,
  isSubmitting,
}) => {
  const data = request.permissionData;
  const riskLevel = data?.riskLevel || 'medium';
  const riskConfig = RISK_LEVEL_CONFIG[riskLevel];

  const handleGrant = () => {
    onSubmit({ action: 'allow', remember: false });
  };

  const handleGrantAlways = () => {
    onSubmit({ action: 'allow_always', remember: true });
  };

  const handleDeny = () => {
    onSubmit({ action: 'deny', remember: false });
  };

  return (
    <div className="space-y-4">
      {/* Risk Warning */}
      {riskLevel === 'high' && (
        <Alert
          type="warning"
          message="高风险操作警告"
          description="此操作可能对系统造成重大影响，请仔细审查后再决定。"
          showIcon
        />
      )}

      {/* Tool Information */}
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item 
          label={<Space><CodeOutlined /> 工具名称</Space>}
        >
          <Text code>{data?.toolName}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="请求操作">
          <Text>{data?.action}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="风险等级">
          <Tag 
            color={riskConfig.color}
            icon={riskConfig.icon}
          >
            {riskConfig.label}
          </Tag>
        </Descriptions.Item>
      </Descriptions>

      {/* Request Description */}
      {data?.description && (
        <div>
          <Text strong>请求描述：</Text>
          <Paragraph className="mt-2">
            {data.description}
          </Paragraph>
        </div>
      )}

      {/* Details */}
      {data?.details && Object.keys(data.details).length > 0 && (
        <div>
          <Text strong>详细信息：</Text>
          <pre className="mt-2 p-3 bg-slate-100 dark:bg-slate-800 rounded text-xs overflow-auto max-h-48">
            {JSON.stringify(data.details, null, 2)}
          </pre>
        </div>
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-between">
        <Button 
          danger 
          icon={<CloseCircleOutlined />}
          onClick={handleDeny}
          loading={isSubmitting}
        >
          拒绝
        </Button>
        <Space>
          {data?.allowRemember && (
            <Button
              onClick={handleGrantAlways}
              loading={isSubmitting}
            >
              总是允许
            </Button>
          )}
          <Button
            type="primary"
            icon={<SafetyOutlined />}
            onClick={handleGrant}
            loading={isSubmitting}
          >
            授权执行
          </Button>
        </Space>
      </div>
    </div>
  );
};

// =============================================================================
// Exports
// =============================================================================

export default UnifiedHITLPanel;
