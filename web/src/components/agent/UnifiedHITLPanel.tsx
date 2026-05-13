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
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Code,
  FileText,
  HelpCircle,
  Key,
  Lock,
  ShieldCheck,
  XCircle,
} from 'lucide-react';

import { useTranslation } from 'react-i18next';

import { useThemeColors } from '@/hooks/useThemeColor';

import {
  decodeEnvVarContext,
  decodeHtmlEntities,
  decodeUnifiedEnvVarRequestData,
} from '@/utils/hitlEnvVarDisplay';
import {
  getOptionDescriptionText,
  getOptionLabelText,
  getOptionRiskList,
} from '@/utils/hitlOptionDisplay';

import {
  Modal,
  Form,
  Input,
  Radio,
  Checkbox,
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

interface TypeConfigEntry {
  icon: React.ReactNode;
  title: string;
  color: string;
  submitText: string;
}

const TYPE_CONFIG: Record<HITLType, TypeConfigEntry> = {
  clarification: {
    icon: <HelpCircle style={{ color: 'var(--color-info)' }} size={16} />,
    title: 'hitl.types.clarification.title',
    color: 'blue',
    submitText: 'hitl.types.clarification.submitText',
  },
  decision: {
    icon: <AlertCircle style={{ color: 'var(--color-warning)' }} size={16} />,
    title: 'hitl.types.decision.title',
    color: 'gold',
    submitText: 'hitl.types.decision.submitText',
  },
  env_var: {
    icon: <Key style={{ color: 'var(--color-success)' }} size={16} />,
    title: 'hitl.types.envVar.title',
    color: 'green',
    submitText: 'hitl.types.envVar.submitText',
  },
  permission: {
    icon: <ShieldCheck style={{ color: 'var(--color-tile-purple)' }} size={16} />,
    title: 'hitl.types.permission.title',
    color: 'purple',
    submitText: 'hitl.types.permission.submitText',
  },
};

const CLARIFICATION_TYPE_LABELS: Record<string, string> = {
  scope: 'hitl.clarificationType.scope',
  approach: 'hitl.clarificationType.approach',
  prerequisite: 'hitl.clarificationType.prerequisite',
  priority: 'hitl.clarificationType.priority',
  custom: 'hitl.clarificationType.custom',
};

const DECISION_TYPE_LABELS: Record<string, string> = {
  branch: 'hitl.decisionType.branch',
  method: 'hitl.decisionType.method',
  confirmation: 'hitl.decisionType.confirmation',
  risk: 'hitl.decisionType.risk',
  custom: 'hitl.decisionType.custom',
};

const RISK_LEVEL_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  low: {
    label: 'hitl.risk.low',
    color: 'green',
    icon: <ShieldCheck style={{ color: 'var(--color-success)' }} size={16} />,
  },
  medium: {
    label: 'hitl.risk.medium',
    color: 'gold',
    icon: <AlertTriangle style={{ color: 'var(--color-warning)' }} size={16} />,
  },
  high: {
    label: 'hitl.risk.high',
    color: 'red',
    icon: <AlertTriangle style={{ color: 'var(--color-error)' }} size={16} />,
  },
};

// =============================================================================
// Main Component
// =============================================================================

interface UnifiedHITLPanelProps {
  request: UnifiedHITLRequest;
  onClose?: (() => void) | undefined;
}

export const UnifiedHITLPanel: React.FC<UnifiedHITLPanelProps> = ({ request, onClose }) => {
  const { t } = useTranslation();
  const submitResponse = useUnifiedHITLStore((state) => state.submitResponse);
  const cancelRequest = useUnifiedHITLStore((state) => state.cancelRequest);
  const isSubmitting = useIsSubmitting(request.requestId);
  const tc = useThemeColors({ error: '--color-error', success: '--color-success' });

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

    return () => {
      clearInterval(timer);
    };
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

  const handleSubmit = useCallback(
    async (responseData: HITLResponseData) => {
      try {
        await submitResponse(request.requestId, request.hitlType, responseData);
        onClose?.();
      } catch (error) {
        console.error('Failed to submit HITL response:', error);
      }
    },
    [submitResponse, request, onClose]
  );

  // Calculate progress percentage
  const progressPercent = useMemo(() => {
    if (remainingTime === null || !request.timeoutSeconds) return 100;
    return Math.max(0, (remainingTime / request.timeoutSeconds) * 100);
  }, [remainingTime, request.timeoutSeconds]);

  const progressStatus =
    progressPercent <= 20 ? 'exception' : progressPercent <= 50 ? 'normal' : 'success';

  return (
    <Modal
      open={true}
      title={
        <div className="flex items-center justify-between">
          <Space>
            {config.icon}
            <span>{t(config.title)}</span>
            <SubtypeTag request={request} />
          </Space>
          {remainingTime !== null && (
            <Tooltip title={t('hitl.remainingTime')}>
              <Badge
                count={`${Math.floor(remainingTime)}s`}
                style={{
                  backgroundColor: progressPercent <= 20 ? tc.error : tc.success,
                  marginRight: 8,
                }}
              >
                <Clock style={{ marginRight: 4 }} size={16} />
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
          submitText={t(config.submitText)}
        />
      </div>
    </Modal>
  );
};

// =============================================================================
// Sub-components
// =============================================================================

const SubtypeTag: React.FC<{ request: UnifiedHITLRequest }> = ({ request }) => {
  const { t } = useTranslation();
  let label: string | undefined;
  let color = 'default';

  switch (request.hitlType) {
    case 'clarification':
      if (request.clarificationData?.clarificationType) {
        const key = CLARIFICATION_TYPE_LABELS[request.clarificationData.clarificationType];
        label = key ? t(key) : undefined;
        color = 'blue';
      }
      break;
    case 'decision':
      if (request.decisionData?.decisionType) {
        const key = DECISION_TYPE_LABELS[request.decisionData.decisionType];
        label = key ? t(key) : undefined;
        color = request.decisionData.decisionType === 'risk' ? 'red' : 'orange';
      }
      break;
    case 'env_var':
      if (request.envVarData?.toolName) {
        label = decodeHtmlEntities(request.envVarData.toolName) ?? request.envVarData.toolName;
        color = 'green';
      }
      break;
    case 'permission':
      if (request.permissionData?.riskLevel) {
        const risk = RISK_LEVEL_CONFIG[request.permissionData.riskLevel];
        label = risk?.label ? t(risk.label) : undefined;
        color = risk?.color || 'purple';
      }
      break;
  }

  return label ? <Tag color={color}>{label}</Tag> : null;
};

const ContextAlert: React.FC<{ request: UnifiedHITLRequest }> = ({ request }) => {
  const { t } = useTranslation();
  const context =
    request.hitlType === 'env_var'
      ? decodeEnvVarContext(request.envVarData?.context)
      : request.clarificationData?.context ||
        request.decisionData?.context ||
        request.permissionData?.context;

  if (!context || Object.keys(context).length === 0) return null;

  return (
    <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
      <Text className="text-sm text-blue-700 dark:text-blue-300 font-semibold">{t('hitl.contextHeading')}</Text>
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
  const { t } = useTranslation();
  const data = request.clarificationData;
  const hasOptions = data?.options && data.options.length > 0;
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data?.options.find((opt) => opt.recommended)?.id || null
  );
  const [customInput, setCustomInput] = useState('');

  const handleSubmit = () => {
    if (!hasOptions && customInput.trim()) {
      onSubmit({ answer: customInput.trim() });
      return;
    }
    if (selectedOption === 'custom' && data?.allowCustom) {
      if (customInput.trim()) {
        onSubmit({ answer: customInput.trim() });
      }
    } else if (selectedOption) {
      onSubmit({ answer: selectedOption });
    }
  };

  const isSubmitDisabled = (() => {
    if (!hasOptions) return !customInput.trim();
    if (selectedOption === 'custom') return !customInput.trim();
    return !selectedOption;
  })();

  return (
    <div className="space-y-4">
      {/* Question */}
      <Paragraph className="text-base font-medium text-slate-800 dark:text-slate-200">
        {request.question || data?.question}
      </Paragraph>

      {/* Options or empty-options fallback */}
      {hasOptions ? (
        <Radio.Group
          value={selectedOption}
          onChange={(e) => {
            setSelectedOption(e.target.value);
          }}
          className="w-full"
        >
          <Space direction="vertical" className="w-full" size="middle">
            {data?.options.map((option, idx) => {
              const optionLabel = getOptionLabelText(option.label) ?? option.id;
              const optionDescription = getOptionDescriptionText(option.description);

              return (
                <Radio key={option.id || `option-${idx}`} value={option.id} className="w-full">
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <Text strong>{optionLabel}</Text>
                      {option.recommended && (
                        <Tag color="green" className="text-xs">
                          {t('hitl.recommended')}
                        </Tag>
                      )}
                    </div>
                    {optionDescription ? (
                      <Text type="secondary" className="text-sm mt-1">
                        {optionDescription}
                      </Text>
                    ) : null}
                  </div>
                </Radio>
              );
            })}

            {data?.allowCustom && (
              <Radio value="custom" className="w-full">
                <div className="flex flex-col w-full">
                  <Text strong>{t('hitl.customAnswer')}</Text>
                  {selectedOption === 'custom' && (
                    <TextArea
                      value={customInput}
                      onChange={(e) => {
                        setCustomInput(e.target.value);
                      }}
                      placeholder={t('hitl.answerPlaceholder')}
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
      ) : data?.allowCustom ? (
        <div className="space-y-2">
          <Text type="secondary">{t('hitl.noPresetOptions')}</Text>
          <TextArea
            value={customInput}
            onChange={(e) => {
              setCustomInput(e.target.value);
            }}
            placeholder={t('hitl.answerPlaceholder')}
            rows={3}
            autoFocus
          />
        </div>
      ) : (
        <Alert message={t('hitl.emptyOptionsMessage')} description={t('hitl.emptyOptionsDescription')} type="info" showIcon />
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{t('hitl.cancel')}</Button>
        <Button
          type="primary"
          icon={<CheckCircle2 size={16} />}
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
  const { t } = useTranslation();
  const data = request.decisionData;
  const hasOptions = data?.options && data.options.length > 0;
  const isMultiSelect = data?.selectionMode === 'multiple';
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data?.options.find((opt) => opt.recommended)?.id || data?.defaultOption || null
  );
  const [selectedMultiple, setSelectedMultiple] = useState<string[]>([]);
  const [customInput, setCustomInput] = useState('');

  const toggleMultiSelect = useCallback((id: string) => {
    setSelectedMultiple((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }, []);

  const handleSubmit = () => {
    if (!hasOptions && customInput.trim()) {
      onSubmit({ decision: customInput.trim() });
      return;
    }
    if (selectedOption === 'custom' && data?.allowCustom) {
      if (customInput.trim()) {
        onSubmit({ decision: customInput.trim() });
      }
    } else if (isMultiSelect) {
      if (selectedMultiple.length > 0) {
        onSubmit({ decision: selectedMultiple });
      }
    } else if (selectedOption) {
      onSubmit({ decision: selectedOption });
    }
  };

  const isSubmitDisabled = (() => {
    if (!hasOptions) return !customInput.trim();
    if (isMultiSelect) return selectedMultiple.length === 0;
    if (selectedOption === 'custom') return !customInput.trim();
    return !selectedOption;
  })();

  const selectedOptionData = data?.options.find((opt) => opt.id === selectedOption);
  const hasHighRisk = getOptionRiskList(selectedOptionData?.risks).length > 0;
  const defaultOptionLabel =
    getOptionLabelText(data?.options.find((opt) => opt.id === data.defaultOption)?.label) ??
    data?.defaultOption;

  return (
    <div className="space-y-4">
      {/* Question */}
      <Title level={5} className="text-slate-800 dark:text-slate-200">
        {request.question || data?.question}
      </Title>

      {/* Default option warning */}
      {data?.defaultOption && (
        <Alert
          message={t('hitl.timeoutDefaultMessage')}
          description={t('hitl.timeoutDefaultDescription', { label: defaultOptionLabel ?? '' })}
          type="info"
          showIcon
        />
      )}

      <Divider />

      {/* Options */}
      {hasOptions ? (
        <div className="space-y-3">
          {data?.options.map((option, idx) => (
            <DecisionOptionCard
              key={option.id || `option-${idx}`}
              option={option}
              selected={
                isMultiSelect ? selectedMultiple.includes(option.id) : selectedOption === option.id
              }
              isMultiSelect={isMultiSelect}
              onSelect={() => {
                if (isMultiSelect) {
                  toggleMultiSelect(option.id);
                } else {
                  setSelectedOption(option.id);
                }
              }}
            />
          ))}

          {data?.allowCustom && !isMultiSelect && (
            <div
              onClick={() => {
                setSelectedOption('custom');
              }}
              className={`
                p-4 rounded-lg border-2 cursor-pointer transition-[color,background-color,border-color,box-shadow,opacity,transform]
                ${
                  selectedOption === 'custom'
                    ? 'border-primary-500 bg-primary-50' + ' dark:bg-primary-900/20'
                    : 'border-slate-200 dark:border-slate-700' + ' hover:border-primary-300'
                }
              `}
            >
              <div className="flex items-center gap-2 mb-2">
                <Radio checked={selectedOption === 'custom'} />
                <Text strong>{t('hitl.customDecision')}</Text>
              </div>
              {selectedOption === 'custom' && (
                <TextArea
                  value={customInput}
                  onChange={(e) => {
                    setCustomInput(e.target.value);
                  }}
                  placeholder={t('hitl.decisionPlaceholder')}
                  rows={3}
                  className="ml-6"
                  autoFocus
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                />
              )}
            </div>
          )}
        </div>
      ) : data?.allowCustom ? (
        <div className="space-y-2">
          <Text type="secondary">{t('hitl.noPresetOptions')}</Text>
          <TextArea
            value={customInput}
            onChange={(e) => {
              setCustomInput(e.target.value);
            }}
            placeholder={t('hitl.decisionPlaceholder')}
            rows={3}
            autoFocus
          />
        </div>
      ) : (
        <Alert
          message={t('hitl.emptyOptionsMessage')}
          description={t('hitl.emptyDecisionDescription')}
          type="info"
          showIcon
        />
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{t('hitl.cancel')}</Button>
        <Button
          type={hasHighRisk ? 'default' : 'primary'}
          danger={hasHighRisk ?? false}
          icon={<CheckCircle2 size={16} />}
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
          loading={isSubmitting}
        >
          {hasHighRisk ? t('hitl.confirmAndAcceptRisk') : submitText}
        </Button>
      </div>
    </div>
  );
};

const DecisionOptionCard: React.FC<{
  option: DecisionOption;
  selected: boolean;
  isMultiSelect?: boolean;
  onSelect: () => void;
}> = ({ option, selected, isMultiSelect = false, onSelect }) => {
  const { t } = useTranslation();
  const optionLabel = getOptionLabelText(option.label) ?? option.id;
  const optionRisks = getOptionRiskList(option.risks);
  const hasRisks = optionRisks.length > 0;
  const optionDescription = getOptionDescriptionText(option.description);

  return (
    <div
      onClick={onSelect}
      className={`
        p-4 rounded-lg border-2 cursor-pointer transition-[color,background-color,border-color,box-shadow,opacity,transform]
        ${
          selected
            ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
            : 'border-slate-200 dark:border-slate-700' + ' hover:border-primary-300'
        }
      `}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1">
          {isMultiSelect ? <Checkbox checked={selected} /> : <Radio checked={selected} />}
          <Text strong className="text-base">
            {optionLabel}
          </Text>
          {option.recommended && (
            <Tag color="green" className="text-xs">
              {t('hitl.recommended')}
            </Tag>
          )}
        </div>
      </div>

      {optionDescription ? (
        <Paragraph className={'text-sm text-slate-600 dark:text-slate-400 mb-3 ml-6'}>
          {optionDescription}
        </Paragraph>
      ) : null}

      {(option.estimatedTime || option.estimatedCost) && (
        <div className="flex gap-4 ml-6 mb-2">
          {option.estimatedTime && (
            <div className={'flex items-center gap-1 text-xs text-slate-500'}>
              <Clock size={16} />
              <span>{option.estimatedTime}</span>
            </div>
          )}
          {option.estimatedCost && (
            <div className={'flex items-center gap-1 text-xs text-slate-500'}>
              <span>$</span>
              <span>{option.estimatedCost}</span>
            </div>
          )}
        </div>
      )}

      {hasRisks && (
        <Alert
          title={t('hitl.riskAlertTitle')}
          description={
            <ul className="list-disc list-inside space-y-1 text-sm">
              {optionRisks.map((risk, idx) => (
                <li key={idx}>{risk}</li>
              ))}
            </ul>
          }
          type="warning"
          showIcon
          icon={<AlertTriangle size={16} />}
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
  const { t } = useTranslation();
  const data = useMemo(
    () => decodeUnifiedEnvVarRequestData(request.envVarData),
    [request.envVarData]
  );
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
      placeholder: field.placeholder || t('hitl.envInputPlaceholder', { label: field.label }),
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
    text: <FileText size={16} />,
    password: <Lock size={16} />,
    textarea: <FileText size={16} />,
  };

  return (
    <div className="space-y-4">
      {/* Message */}
      {data?.message && <Alert title={data.message} type="info" showIcon />}

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
                  <Tag color="red" className="text-xs">
                    {t('hitl.envRequiredTag')}
                  </Tag>
                )}
              </Space>
            }
            rules={[
              {
                required: field.required,
                message: t('hitl.envValidationMessage', { label: field.label }),
              },
            ]}
            extra={
              field.description && (
                <Paragraph type="secondary" className="text-xs mt-1 mb-0">
                  {field.description}
                </Paragraph>
              )
            }
          >
            {renderInput(field)}
          </Form.Item>
        ))}
      </Form>

      {/* Security Notice */}
      {data?.fields.some((f) => f.inputType === 'password') && (
        <Alert
          message={t('hitl.envSecurityTitle')}
          description={t('hitl.envSecurityDescription')}
          type="warning"
          showIcon
        />
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{t('hitl.cancel')}</Button>
        <Button
          type="primary"
          icon={<CheckCircle2 size={16} />}
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
  const { t } = useTranslation();
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
          message={t('hitl.highRiskTitle')}
          description={t('hitl.highRiskDescription')}
          showIcon
        />
      )}

      {/* Tool Information */}
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item
          label={
            <Space>
              <Code size={16} /> {t('hitl.toolName')}
            </Space>
          }
        >
          <Text code>{data?.toolName}</Text>
        </Descriptions.Item>
        <Descriptions.Item label={t('hitl.requestedAction')}>
          <Text>{data?.action}</Text>
        </Descriptions.Item>
        <Descriptions.Item label={t('hitl.riskLevel')}>
          <Tag
            {...(riskConfig?.color != null ? { color: riskConfig.color } : {})}
            icon={riskConfig?.icon}
          >
            {riskConfig?.label ? t(riskConfig.label) : null}
          </Tag>
        </Descriptions.Item>
      </Descriptions>

      {/* Request Description */}
      {data?.description && (
        <div>
          <Text strong>{t('hitl.requestDescription')}</Text>
          <Paragraph className="mt-2">{data.description}</Paragraph>
        </div>
      )}

      {/* Details */}
      {data?.details && Object.keys(data.details).length > 0 && (
        <div>
          <Text strong>{t('hitl.detailsHeading')}</Text>
          <pre className="mt-2 p-3 bg-slate-100 dark:bg-slate-800 rounded text-xs overflow-auto max-h-48">
            {JSON.stringify(data.details, null, 2)}
          </pre>
        </div>
      )}

      <Divider />

      {/* Actions */}
      <div className="flex justify-between">
        <Button danger icon={<XCircle size={16} />} onClick={handleDeny} loading={isSubmitting}>
          {t('hitl.deny')}
        </Button>
        <Space>
          {data?.allowRemember && (
            <Button onClick={handleGrantAlways} loading={isSubmitting}>
              {t('hitl.allowAlways')}
            </Button>
          )}
          <Button
            type="primary"
            icon={<ShieldCheck size={16} />}
            onClick={handleGrant}
            loading={isSubmitting}
          >
            {t('hitl.authorize')}
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
