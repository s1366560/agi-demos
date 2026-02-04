/**
 * InlineHITLCard - Human-in-the-Loop inline card component
 *
 * Renders HITL requests directly in the message timeline as interactive cards.
 * Replaces the modal-based approach for a more natural conversation flow.
 *
 * Supports 4 HITL types:
 * - Clarification: Multiple choice or custom input questions
 * - Decision: Detailed options with risks, time estimates, cost
 * - EnvVar: Environment variable input forms
 * - Permission: Tool permission requests
 */

import React, { memo, useState, useCallback, useEffect } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { LazyButton, LazyProgress, LazyTag } from '@/components/ui/lazyAntd';
import { Radio, Input, Form } from 'antd';
import {
  HelpCircle,
  GitBranch,
  Key,
  Shield,
  Clock,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import type {
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
} from '../../types/agent';
import type { HITLType, HITLResponseData } from '../../types/hitl.unified';
import { useUnifiedHITLStore } from '../../stores/hitlStore.unified';

// =============================================================================
// Types
// =============================================================================

export interface InlineHITLCardProps {
  /** HITL type */
  hitlType: HITLType;
  /** Request ID for submission */
  requestId: string;
  /** Clarification data (if type is clarification) */
  clarificationData?: ClarificationAskedEventData;
  /** Decision data (if type is decision) */
  decisionData?: DecisionAskedEventData;
  /** EnvVar data (if type is env_var) */
  envVarData?: EnvVarRequestedEventData;
  /** Permission data (if type is permission) */
  permissionData?: PermissionAskedEventData;
  /** Whether already answered */
  isAnswered?: boolean;
  /** The answer that was provided (for answered state) */
  answeredValue?: string;
  /** Created timestamp */
  createdAt?: string;
  /** Expires timestamp */
  expiresAt?: string;
  /** Timeout in seconds */
  timeoutSeconds?: number;
}

// =============================================================================
// Utilities
// =============================================================================

const getHITLIcon = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return <HelpCircle className="w-5 h-5" />;
    case 'decision':
      return <GitBranch className="w-5 h-5" />;
    case 'env_var':
      return <Key className="w-5 h-5" />;
    case 'permission':
      return <Shield className="w-5 h-5" />;
    default:
      return <HelpCircle className="w-5 h-5" />;
  }
};

const getHITLTitle = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return '需要澄清';
    case 'decision':
      return '需要决策';
    case 'env_var':
      return '需要配置';
    case 'permission':
      return '需要授权';
    default:
      return '需要输入';
  }
};

const getHITLColor = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return 'blue';
    case 'decision':
      return 'orange';
    case 'env_var':
      return 'purple';
    case 'permission':
      return 'red';
    default:
      return 'blue';
  }
};

const formatTimeAgo = (timestamp: string) => {
  const now = Date.now();
  const time = new Date(timestamp).getTime();
  const diff = Math.floor((now - time) / 1000);

  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
};

// =============================================================================
// Sub-Components
// =============================================================================

/** Countdown timer display */
const CountdownTimer: React.FC<{
  expiresAt?: string;
  timeoutSeconds?: number;
}> = memo(({ expiresAt, timeoutSeconds = 300 }) => {
  const [remaining, setRemaining] = useState<number | null>(null);

  useEffect(() => {
    if (!expiresAt) {
      setRemaining(null);
      return;
    }

    const updateRemaining = () => {
      const now = Date.now();
      const expires = new Date(expiresAt).getTime();
      const diff = Math.max(0, Math.floor((expires - now) / 1000));
      setRemaining(diff);
    };

    updateRemaining();
    const interval = setInterval(updateRemaining, 1000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  if (remaining === null) return null;

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const progressPercent = Math.max(0, (remaining / timeoutSeconds) * 100);
  const isUrgent = remaining < 60;

  return (
    <div className="flex items-center gap-2">
      <Clock className={`w-4 h-4 ${isUrgent ? 'text-red-500' : 'text-slate-400'}`} />
      <span className={`text-sm font-mono ${isUrgent ? 'text-red-500 font-medium' : 'text-slate-500'}`}>
        {minutes}:{seconds.toString().padStart(2, '0')}
      </span>
      <LazyProgress
        percent={progressPercent}
        size="small"
        showInfo={false}
        strokeColor={isUrgent ? '#ef4444' : '#3b82f6'}
        className="w-16"
      />
    </div>
  );
});
CountdownTimer.displayName = 'CountdownTimer';

/** Clarification card content */
const ClarificationContent: React.FC<{
  data: ClarificationAskedEventData;
  onSubmit: (response: HITLResponseData) => void;
  isSubmitting: boolean;
}> = memo(({ data, onSubmit, isSubmitting }) => {
  const [selected, setSelected] = useState<string | null>(null);
  const [customInput, setCustomInput] = useState('');

  const handleSubmit = useCallback(() => {
    if (selected === '__custom__' && data.allow_custom) {
      if (customInput.trim()) {
        onSubmit({ answer: customInput.trim() });
      }
    } else if (selected) {
      onSubmit({ answer: selected });
    }
  }, [selected, customInput, data.allow_custom, onSubmit]);

  const isDisabled = !selected || (selected === '__custom__' && !customInput.trim());

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-700 dark:text-slate-300">{data.question}</p>

      <Radio.Group
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        className="flex flex-col gap-2"
      >
        {data.options.map((option) => (
          <Radio key={option.id} value={option.id} className="w-full">
            <div className="flex items-center gap-2">
              <span>{option.label}</span>
              {option.recommended && (
                <LazyTag color="green" className="text-xs">推荐</LazyTag>
              )}
            </div>
            {option.description && (
              <p className="text-xs text-slate-500 ml-6 mt-0.5">{option.description}</p>
            )}
          </Radio>
        ))}
        {data.allow_custom && (
          <Radio value="__custom__">自定义回答</Radio>
        )}
      </Radio.Group>

      {selected === '__custom__' && data.allow_custom && (
        <Input.TextArea
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          placeholder="请输入您的回答..."
          rows={2}
          className="mt-2"
        />
      )}

      <div className="flex justify-end pt-2">
        <LazyButton
          type="primary"
          onClick={handleSubmit}
          disabled={isDisabled}
          loading={isSubmitting}
          size="small"
        >
          确认
        </LazyButton>
      </div>
    </div>
  );
});
ClarificationContent.displayName = 'ClarificationContent';

/** Decision card content */
const DecisionContent: React.FC<{
  data: DecisionAskedEventData;
  onSubmit: (response: HITLResponseData) => void;
  isSubmitting: boolean;
}> = memo(({ data, onSubmit, isSubmitting }) => {
  const [selected, setSelected] = useState<string | null>(data.default_option || null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const handleSubmit = useCallback(() => {
    if (selected) {
      onSubmit({ decision: selected });
    }
  }, [selected, onSubmit]);

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-700 dark:text-slate-300">{data.question}</p>

      <div className="space-y-2">
        {data.options.map((option) => {
          const isSelected = selected === option.id;
          const isExpanded = expanded === option.id;
          const hasDetails = option.estimated_time || option.estimated_cost || option.risks?.length;

          return (
            <div
              key={option.id}
              className={`
                border rounded-lg p-3 cursor-pointer transition-all
                ${isSelected
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                }
              `}
              onClick={() => setSelected(option.id)}
            >
              <div className="flex items-start gap-3">
                <div className={`
                  w-4 h-4 rounded-full border-2 mt-0.5 flex-shrink-0
                  ${isSelected ? 'border-primary bg-primary' : 'border-slate-300'}
                `}>
                  {isSelected && (
                    <CheckCircle2 className="w-full h-full text-white" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{option.label}</span>
                    {option.recommended && (
                      <LazyTag color="green" className="text-xs">推荐</LazyTag>
                    )}
                    {option.risks?.length && (
                      <LazyTag color="orange" className="text-xs">
                        <AlertTriangle className="w-3 h-3 mr-1" />
                        有风险
                      </LazyTag>
                    )}
                  </div>
                  {option.description && (
                    <p className="text-xs text-slate-500 mt-1">{option.description}</p>
                  )}

                  {/* Metadata row */}
                  {(option.estimated_time || option.estimated_cost) && (
                    <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                      {option.estimated_time && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {option.estimated_time}
                        </span>
                      )}
                      {option.estimated_cost && (
                        <span>💰 {option.estimated_cost}</span>
                      )}
                    </div>
                  )}

                  {/* Expandable risks */}
                  {hasDetails && (
                    <button
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 mt-2"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpanded(isExpanded ? null : option.id);
                      }}
                    >
                      {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      {isExpanded ? '收起详情' : '查看详情'}
                    </button>
                  )}

                  {isExpanded && option.risks?.length && (
                    <div className="mt-2 p-2 bg-orange-50 dark:bg-orange-900/20 rounded text-xs">
                      <p className="font-medium text-orange-700 dark:text-orange-400 mb-1">
                        ⚠️ 风险提示
                      </p>
                      <ul className="list-disc list-inside text-orange-600 dark:text-orange-300 space-y-0.5">
                        {option.risks.map((risk, idx) => (
                          <li key={idx}>{risk}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex justify-end pt-2">
        <LazyButton
          type="primary"
          onClick={handleSubmit}
          disabled={!selected}
          loading={isSubmitting}
          size="small"
        >
          确认选择
        </LazyButton>
      </div>
    </div>
  );
});
DecisionContent.displayName = 'DecisionContent';

/** EnvVar card content */
const EnvVarContent: React.FC<{
  data: EnvVarRequestedEventData;
  onSubmit: (response: HITLResponseData) => void;
  isSubmitting: boolean;
}> = memo(({ data, onSubmit, isSubmitting }) => {
  const [form] = Form.useForm();
  const [saveForLater, setSaveForLater] = useState(true);

  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      onSubmit({ values, save: saveForLater });
    } catch {
      // Validation failed
    }
  }, [form, saveForLater, onSubmit]);

  return (
    <div className="space-y-3">
      {data.message && (
        <p className="text-sm text-slate-700 dark:text-slate-300">{data.message}</p>
      )}

      <div className="text-xs text-slate-500 flex items-center gap-1">
        <Wrench className="w-3 h-3" />
        工具: {data.tool_name}
      </div>

      <Form form={form} layout="vertical" size="small">
        {data.fields.map((field) => (
          <Form.Item
            key={field.name}
            name={field.name}
            label={field.label}
            rules={field.required ? [{ required: true, message: `请输入 ${field.label}` }] : []}
            tooltip={field.description}
            initialValue={field.default_value}
          >
            {field.input_type === 'password' ? (
              <Input.Password placeholder={field.placeholder || `请输入 ${field.label}`} />
            ) : field.input_type === 'textarea' ? (
              <Input.TextArea placeholder={field.placeholder || `请输入 ${field.label}`} rows={3} />
            ) : (
              <Input placeholder={field.placeholder || `请输入 ${field.label}`} />
            )}
          </Form.Item>
        ))}
      </Form>

      <div className="flex items-center justify-between pt-2">
        <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
          <input
            type="checkbox"
            checked={saveForLater}
            onChange={(e) => setSaveForLater(e.target.checked)}
            className="rounded"
          />
          保存配置以便下次使用
        </label>
        <LazyButton
          type="primary"
          onClick={handleSubmit}
          loading={isSubmitting}
          size="small"
        >
          提交
        </LazyButton>
      </div>
    </div>
  );
});
EnvVarContent.displayName = 'EnvVarContent';

/** Permission card content */
const PermissionContent: React.FC<{
  data: PermissionAskedEventData;
  onSubmit: (response: HITLResponseData) => void;
  isSubmitting: boolean;
}> = memo(({ data, onSubmit, isSubmitting }) => {
  const [remember, setRemember] = useState(false);

  const riskColorMap = {
    low: 'green',
    medium: 'orange',
    high: 'red',
  } as const;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-slate-500" />
        <span className="text-sm font-medium">{data.tool_name}</span>
        {data.risk_level && (
          <LazyTag color={riskColorMap[data.risk_level]}>
            风险: {data.risk_level === 'low' ? '低' : data.risk_level === 'medium' ? '中' : '高'}
          </LazyTag>
        )}
      </div>

      <p className="text-sm text-slate-700 dark:text-slate-300">{data.description}</p>

      <div className="flex items-center justify-between pt-2">
        <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="rounded"
          />
          记住此选择
        </label>
        <div className="flex gap-2">
          <LazyButton
            danger
            onClick={() => onSubmit({ action: 'deny', remember })}
            loading={isSubmitting}
            size="small"
          >
            拒绝
          </LazyButton>
          <LazyButton
            type="primary"
            onClick={() => onSubmit({ action: 'allow', remember })}
            loading={isSubmitting}
            size="small"
          >
            允许
          </LazyButton>
        </div>
      </div>
    </div>
  );
});
PermissionContent.displayName = 'PermissionContent';

/** Answered state display */
const AnsweredState: React.FC<{
  hitlType: HITLType;
  answeredValue?: string;
  createdAt?: string;
}> = memo(({ hitlType, answeredValue, createdAt }) => {
  const color = getHITLColor(hitlType);
  const title = hitlType === 'clarification' ? '已回答'
    : hitlType === 'decision' ? '已确认'
    : hitlType === 'env_var' ? '已配置'
    : '已授权';

  return (
    <div className="flex items-start gap-3 animate-slide-up">
      <div className={`w-8 h-8 rounded-full bg-${color}-100 dark:bg-${color}-900/50 flex items-center justify-center flex-shrink-0`}>
        <CheckCircle2 className={`w-4 h-4 text-${color}-600 dark:text-${color}-400`} />
      </div>
      <div className="flex-1">
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              ✅ {title}
            </span>
            {createdAt && (
              <span className="text-xs text-slate-400">{formatTimeAgo(createdAt)}</span>
            )}
          </div>
          {answeredValue && (
            <p className="text-xs text-slate-500 mt-1">选择: {answeredValue}</p>
          )}
        </div>
      </div>
    </div>
  );
});
AnsweredState.displayName = 'AnsweredState';

// =============================================================================
// Main Component
// =============================================================================

const Wrench = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
  </svg>
);

export const InlineHITLCard: React.FC<InlineHITLCardProps> = memo(({
  hitlType,
  requestId,
  clarificationData,
  decisionData,
  envVarData,
  permissionData,
  isAnswered: isAnsweredProp = false,
  answeredValue: answeredValueProp,
  createdAt,
  expiresAt,
  timeoutSeconds = 300,
}) => {
  // Use useShallow to avoid infinite re-renders from object selector
  const { submitResponse, isSubmitting, submittingRequestId, requestStatuses } = useUnifiedHITLStore(
    useShallow((state) => ({
      submitResponse: state.submitResponse,
      isSubmitting: state.isSubmitting,
      submittingRequestId: state.submittingRequestId,
      requestStatuses: state.requestStatuses,
    }))
  );

  // Check if answered from either props (history) or store (real-time)
  const storeStatus = requestId ? requestStatuses.get(requestId) : undefined;
  const isAnsweredFromStore = storeStatus === 'answered' || storeStatus === 'completed';
  const isAnswered = isAnsweredProp || isAnsweredFromStore;

  // For real-time answered, we don't have the value yet, use prop or placeholder
  const answeredValue = answeredValueProp || (isAnsweredFromStore ? '已提交' : undefined);

  const isCurrentlySubmitting = isSubmitting && submittingRequestId === requestId;

  const handleSubmit = useCallback(async (responseData: HITLResponseData) => {
    try {
      await submitResponse(requestId, hitlType, responseData);
    } catch (error) {
      console.error('Failed to submit HITL response:', error);
    }
  }, [requestId, hitlType, submitResponse]);

  // Show answered state
  if (isAnswered) {
    return (
      <AnsweredState
        hitlType={hitlType}
        answeredValue={answeredValue}
        createdAt={createdAt}
      />
    );
  }

  const icon = getHITLIcon(hitlType);
  const title = getHITLTitle(hitlType);
  const color = getHITLColor(hitlType);

  return (
    <div className="flex items-start gap-3 animate-slide-up">
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full bg-${color}-100 dark:bg-${color}-900/50 flex items-center justify-center flex-shrink-0 text-${color}-600 dark:text-${color}-400`}>
        {icon}
      </div>

      {/* Card */}
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div className={`bg-white dark:bg-slate-800 border-l-4 border-${color}-500 rounded-lg shadow-sm overflow-hidden`}>
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-2 bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-600">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                🤖 {title}
              </span>
              <LazyTag color={color} className="text-xs">{hitlType}</LazyTag>
            </div>
            <CountdownTimer expiresAt={expiresAt} timeoutSeconds={timeoutSeconds} />
          </div>

          {/* Content */}
          <div className="p-4">
            {hitlType === 'clarification' && clarificationData && (
              <ClarificationContent
                data={clarificationData}
                onSubmit={handleSubmit}
                isSubmitting={isCurrentlySubmitting}
              />
            )}
            {hitlType === 'decision' && decisionData && (
              <DecisionContent
                data={decisionData}
                onSubmit={handleSubmit}
                isSubmitting={isCurrentlySubmitting}
              />
            )}
            {hitlType === 'env_var' && envVarData && (
              <EnvVarContent
                data={envVarData}
                onSubmit={handleSubmit}
                isSubmitting={isCurrentlySubmitting}
              />
            )}
            {hitlType === 'permission' && permissionData && (
              <PermissionContent
                data={permissionData}
                onSubmit={handleSubmit}
                isSubmitting={isCurrentlySubmitting}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
});
InlineHITLCard.displayName = 'InlineHITLCard';

export default InlineHITLCard;
