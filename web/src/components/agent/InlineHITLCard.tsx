/**
 * InlineHITLCard - Human-in-the-Loop inline card component
 *
 * Renders HITL requests directly in the message timeline as interactive cards.
 * Unified styling with MessageBubble components for consistent UX.
 *
 * Supports 4 HITL types:
 * - Clarification: Multiple choice or custom input questions
 * - Decision: Detailed options with risks, time estimates, cost
 * - EnvVar: Environment variable input forms
 * - Permission: Tool permission requests
 */

import React, { memo, useState, useCallback, useEffect } from 'react';

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
  Wrench,
  Bot,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { LazyButton, LazyProgress, LazyTag } from '@/components/ui/lazyAntd';

import { useUnifiedHITLStore } from '../../stores/hitlStore.unified';

import type {
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
} from '../../types/agent';
import type { HITLType, HITLResponseData } from '../../types/hitl.unified';

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

// Get light gradient background for card (matching MessageBubble glass-morphism style)
const getHITLLightGradientClass = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return 'from-blue-50/90 to-sky-50/70 dark:from-blue-900/25 dark:to-sky-900/15';
    case 'decision':
      return 'from-amber-50/90 to-orange-50/70 dark:from-amber-900/25 dark:to-orange-900/15';
    case 'env_var':
      return 'from-violet-50/90 to-purple-50/70 dark:from-violet-900/25 dark:to-purple-900/15';
    case 'permission':
      return 'from-rose-50/90 to-red-50/70 dark:from-rose-900/25 dark:to-red-900/15';
    default:
      return 'from-blue-50/90 to-sky-50/70 dark:from-blue-900/25 dark:to-sky-900/15';
  }
};

// Get border color class
const getHITLBorderClass = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return 'border-blue-200/50 dark:border-blue-800/30';
    case 'decision':
      return 'border-amber-200/50 dark:border-amber-800/30';
    case 'env_var':
      return 'border-violet-200/50 dark:border-violet-800/30';
    case 'permission':
      return 'border-rose-200/50 dark:border-rose-800/30';
    default:
      return 'border-blue-200/50 dark:border-blue-800/30';
  }
};

// Get icon background gradient class
const getHITLIconBgClass = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return 'from-blue-100 to-sky-100 dark:from-blue-900/40 dark:to-sky-900/30';
    case 'decision':
      return 'from-amber-100 to-orange-100 dark:from-amber-900/40 dark:to-orange-900/30';
    case 'env_var':
      return 'from-violet-100 to-purple-100 dark:from-violet-900/40 dark:to-purple-900/30';
    case 'permission':
      return 'from-rose-100 to-red-100 dark:from-rose-900/40 dark:to-red-900/30';
    default:
      return 'from-blue-100 to-sky-100 dark:from-blue-900/40 dark:to-sky-900/30';
  }
};

// Get icon color class
const getHITLIconColorClass = (type: HITLType) => {
  switch (type) {
    case 'clarification':
      return 'text-blue-600 dark:text-blue-400';
    case 'decision':
      return 'text-amber-600 dark:text-amber-400';
    case 'env_var':
      return 'text-violet-600 dark:text-violet-400';
    case 'permission':
      return 'text-rose-600 dark:text-rose-400';
    default:
      return 'text-blue-600 dark:text-blue-400';
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

/** Countdown timer display - Unified with MessageBubble style */
const CountdownTimer: React.FC<{
  expiresAt?: string;
  timeoutSeconds?: number;
  color?: string;
}> = memo(({ expiresAt, timeoutSeconds = 300, color = 'blue' }) => {
  // Calculate initial remaining time
  const calculateRemaining = useCallback((): number | null => {
    if (!expiresAt) return null;
    const now = Date.now();
    const expires = new Date(expiresAt).getTime();
    return Math.max(0, Math.floor((expires - now) / 1000));
  }, [expiresAt]);

  const [remaining, setRemaining] = useState<number | null>(calculateRemaining);

  useEffect(() => {
    if (!expiresAt) {
      setRemaining(null);
      return;
    }

    const interval = setInterval(() => {
      setRemaining(calculateRemaining());
    }, 1000);
    return () => clearInterval(interval);
  }, [expiresAt, calculateRemaining]);

  if (remaining === null) return null;

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const progressPercent = Math.max(0, (remaining / timeoutSeconds) * 100);
  const isUrgent = remaining < 60;

  const strokeColorMap: Record<string, string> = {
    blue: '#3b82f6',
    orange: '#f59e0b',
    purple: '#8b5cf6',
    red: '#ef4444',
  };

  return (
    <div className="flex items-center gap-2">
      <Clock className={`w-3.5 h-3.5 ${isUrgent ? 'text-rose-500' : 'text-slate-400'}`} />
      <span
        className={`text-xs font-mono ${isUrgent ? 'text-rose-500 font-medium' : 'text-slate-500'}`}
      >
        {minutes}:{seconds.toString().padStart(2, '0')}
      </span>
      <LazyProgress
        percent={progressPercent}
        size="small"
        showInfo={false}
        strokeColor={isUrgent ? '#ef4444' : strokeColorMap[color] || '#3b82f6'}
        className="w-14"
      />
    </div>
  );
});
CountdownTimer.displayName = 'CountdownTimer';

/** Clarification card content - Unified styling */
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
    <div className="space-y-4">
      <p className="text-[15px] leading-7 text-slate-700 dark:text-slate-300">{data.question}</p>

      <Radio.Group
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        className="flex flex-col gap-3 w-full"
      >
        {data.options.map((option) => (
          <div
            key={option.id}
            className={`p-3 rounded-xl border-2 cursor-pointer transition-all ${
              selected === option.id
                ? 'border-blue-400 bg-blue-50/50 dark:bg-blue-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-700'
            }`}
            onClick={() => setSelected(option.id)}
          >
            <Radio value={option.id} className="w-full">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm text-slate-800 dark:text-slate-200">
                  {option.label}
                </span>
                {option.recommended && (
                  <LazyTag color="green" className="text-xs">
                    推荐
                  </LazyTag>
                )}
              </div>
              {option.description && (
                <p className="text-xs text-slate-500 dark:text-slate-400 ml-6 mt-1 leading-relaxed">
                  {option.description}
                </p>
              )}
            </Radio>
          </div>
        ))}
        {data.allow_custom && (
          <div
            className={`p-3 rounded-xl border-2 cursor-pointer transition-all ${
              selected === '__custom__'
                ? 'border-blue-400 bg-blue-50/50 dark:bg-blue-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-700'
            }`}
            onClick={() => setSelected('__custom__')}
          >
            <Radio value="__custom__" className="w-full">
              <span className="font-medium text-sm text-slate-800 dark:text-slate-200">
                自定义回答
              </span>
            </Radio>
          </div>
        )}
      </Radio.Group>

      {selected === '__custom__' && data.allow_custom && (
        <Input.TextArea
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          placeholder="请输入您的回答..."
          rows={3}
          className="mt-2 rounded-xl"
        />
      )}

      <div className="flex justify-end pt-2">
        <LazyButton
          type="primary"
          onClick={handleSubmit}
          disabled={isDisabled}
          loading={isSubmitting}
          size="middle"
          className="rounded-lg"
        >
          确认
        </LazyButton>
      </div>
    </div>
  );
});
ClarificationContent.displayName = 'ClarificationContent';

/** Decision card content - Unified styling */
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
    <div className="space-y-4">
      <p className="text-[15px] leading-7 text-slate-700 dark:text-slate-300">{data.question}</p>

      <div className="space-y-3">
        {data.options.map((option) => {
          const isSelected = selected === option.id;
          const isExpanded = expanded === option.id;
          const hasDetails = option.estimated_time || option.estimated_cost || option.risks?.length;

          return (
            <div
              key={option.id}
              className={`
                rounded-xl p-4 cursor-pointer transition-all border-2
                ${
                  isSelected
                    ? 'border-amber-400 bg-amber-50/50 dark:bg-amber-900/20 shadow-sm'
                    : 'border-slate-200 dark:border-slate-700 hover:border-amber-300 dark:hover:border-amber-700'
                }
              `}
              onClick={() => setSelected(option.id)}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`
                  w-5 h-5 rounded-full border-2 mt-0.5 flex-shrink-0 flex items-center justify-center
                  ${isSelected ? 'border-amber-500 bg-amber-500' : 'border-slate-300 dark:border-slate-600'}
                `}
                >
                  {isSelected && <div className="w-2 h-2 rounded-full bg-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm text-slate-800 dark:text-slate-200">
                      {option.label}
                    </span>
                    {option.recommended && (
                      <LazyTag color="green" className="text-xs">
                        推荐
                      </LazyTag>
                    )}
                    {option.risks && option.risks.length > 0 && (
                      <LazyTag color="orange" className="text-xs">
                        <AlertTriangle className="w-3 h-3 mr-1" />
                        有风险
                      </LazyTag>
                    )}
                  </div>
                  {option.description && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
                      {option.description}
                    </p>
                  )}

                  {/* Metadata row */}
                  {(option.estimated_time || option.estimated_cost) && (
                    <div className="flex items-center gap-4 mt-3 text-xs text-slate-500 dark:text-slate-400">
                      {option.estimated_time && (
                        <span className="flex items-center gap-1.5 px-2 py-1 bg-slate-100 dark:bg-slate-800 rounded-md">
                          <Clock className="w-3 h-3" />
                          {option.estimated_time}
                        </span>
                      )}
                      {option.estimated_cost && (
                        <span className="px-2 py-1 bg-slate-100 dark:bg-slate-800 rounded-md">
                          💰 {option.estimated_cost}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Expandable risks */}
                  {hasDetails && (
                    <button
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 mt-3 transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpanded(isExpanded ? null : option.id);
                      }}
                    >
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5" />
                      )}
                      {isExpanded ? '收起详情' : '查看详情'}
                    </button>
                  )}

                  {isExpanded && option.risks && option.risks.length > 0 && (
                    <div className="mt-3 p-3 bg-amber-50 dark:bg-amber-900/30 rounded-lg border border-amber-200 dark:border-amber-800/50">
                      <p className="font-medium text-amber-700 dark:text-amber-400 mb-2 text-xs flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        风险提示
                      </p>
                      <ul className="list-disc list-inside text-amber-600 dark:text-amber-300 space-y-1 text-xs">
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
          size="middle"
          className="rounded-lg"
        >
          确认选择
        </LazyButton>
      </div>
    </div>
  );
});
DecisionContent.displayName = 'DecisionContent';

/** EnvVar card content - Unified styling */
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
    <div className="space-y-4">
      {data.message && (
        <p className="text-[15px] leading-7 text-slate-700 dark:text-slate-300">{data.message}</p>
      )}

      <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-2 px-3 py-2 bg-slate-100 dark:bg-slate-800 rounded-lg">
        <Wrench className="w-3.5 h-3.5" />
        <span>工具: {data.tool_name}</span>
      </div>

      <Form form={form} layout="vertical" size="middle">
        {data.fields && data.fields.length > 0 ? (
          data.fields.map((field) => (
            <Form.Item
              key={field.name}
              name={field.name}
              label={
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {field.label}
                  {field.required && <span className="text-rose-500 ml-1">*</span>}
                </span>
              }
              rules={field.required ? [{ required: true, message: `请输入 ${field.label}` }] : []}
              tooltip={field.description}
              initialValue={field.default_value}
            >
              {field.input_type === 'password' ? (
                <Input.Password
                  placeholder={field.placeholder || `请输入 ${field.label}`}
                  className="rounded-lg"
                />
              ) : field.input_type === 'textarea' ? (
                <Input.TextArea
                  placeholder={field.placeholder || `请输入 ${field.label}`}
                  rows={3}
                  className="rounded-lg"
                />
              ) : (
                <Input
                  placeholder={field.placeholder || `请输入 ${field.label}`}
                  className="rounded-lg"
                />
              )}
            </Form.Item>
          ))
        ) : (
          <div className="text-sm text-slate-500 dark:text-slate-400 py-4 text-center">
            暂无需配置的环境变量
          </div>
        )}
      </Form>

      <div className="flex items-center justify-between pt-2">
        <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400 cursor-pointer hover:text-slate-700 dark:hover:text-slate-200 transition-colors">
          <input
            type="checkbox"
            checked={saveForLater}
            onChange={(e) => setSaveForLater(e.target.checked)}
            className="rounded w-4 h-4 accent-violet-500"
          />
          <span>保存配置以便下次使用</span>
        </label>
        <LazyButton
          type="primary"
          onClick={handleSubmit}
          loading={isSubmitting}
          size="middle"
          className="rounded-lg"
        >
          提交
        </LazyButton>
      </div>
    </div>
  );
});
EnvVarContent.displayName = 'EnvVarContent';

/** Permission card content - Unified styling */
const PermissionContent: React.FC<{
  data: PermissionAskedEventData;
  onSubmit: (response: HITLResponseData) => void;
  isSubmitting: boolean;
}> = memo(({ data, onSubmit, isSubmitting }) => {
  const [remember, setRemember] = useState(false);

  const riskConfig = {
    low: { color: 'green', bgClass: 'bg-emerald-50 dark:bg-emerald-900/20', borderClass: 'border-emerald-200 dark:border-emerald-800/50', textClass: 'text-emerald-700 dark:text-emerald-400' },
    medium: { color: 'orange', bgClass: 'bg-amber-50 dark:bg-amber-900/20', borderClass: 'border-amber-200 dark:border-amber-800/50', textClass: 'text-amber-700 dark:text-amber-400' },
    high: { color: 'red', bgClass: 'bg-rose-50 dark:bg-rose-900/20', borderClass: 'border-rose-200 dark:border-rose-800/50', textClass: 'text-rose-700 dark:text-rose-400' },
  } as const;

  const risk = data.risk_level ? riskConfig[data.risk_level] : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-100 to-red-100 dark:from-rose-900/40 dark:to-red-900/30 flex items-center justify-center">
          <Shield className="w-4 h-4 text-rose-600 dark:text-rose-400" />
        </div>
        <div className="flex-1">
          <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
            {data.tool_name}
          </span>
        </div>
        {data.risk_level && (
          <LazyTag color={risk?.color} className="text-xs">
            风险: {data.risk_level === 'low' ? '低' : data.risk_level === 'medium' ? '中' : '高'}
          </LazyTag>
        )}
      </div>

      {risk && (
        <div className={`p-3 rounded-lg border ${risk.bgClass} ${risk.borderClass}`}>
          <p className={`text-sm ${risk.textClass} flex items-center gap-2`}>
            <AlertTriangle className="w-4 h-4" />
            <span className="font-medium">
              {data.risk_level === 'high'
                ? '高风险操作'
                : data.risk_level === 'medium'
                  ? '中等风险操作'
                  : '低风险操作'}
            </span>
          </p>
        </div>
      )}

      <p className="text-[15px] leading-7 text-slate-700 dark:text-slate-300">{data.description}</p>

      <div className="flex items-center justify-between pt-2">
        <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400 cursor-pointer hover:text-slate-700 dark:hover:text-slate-200 transition-colors">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="rounded w-4 h-4 accent-rose-500"
          />
          <span>记住此选择</span>
        </label>
        <div className="flex gap-2">
          <LazyButton
            danger
            onClick={() => onSubmit({ action: 'deny', remember })}
            loading={isSubmitting}
            size="middle"
            className="rounded-lg"
          >
            拒绝
          </LazyButton>
          <LazyButton
            type="primary"
            onClick={() => onSubmit({ action: 'allow', remember })}
            loading={isSubmitting}
            size="middle"
            className="rounded-lg"
          >
            允许
          </LazyButton>
        </div>
      </div>
    </div>
  );
});
PermissionContent.displayName = 'PermissionContent';

/** Answered state display - Unified with MessageBubble style */
const AnsweredState: React.FC<{
  hitlType: HITLType;
  answeredValue?: string;
  createdAt?: string;
}> = memo(({ hitlType, answeredValue, createdAt }) => {
  const iconBgClass = getHITLIconBgClass(hitlType);
  const iconColorClass = getHITLIconColorClass(hitlType);
  const lightGradientClass = getHITLLightGradientClass(hitlType);
  const borderClass = getHITLBorderClass(hitlType);

  const title =
    hitlType === 'clarification'
      ? '已回答'
      : hitlType === 'decision'
        ? '已确认'
        : hitlType === 'env_var'
          ? '已配置'
          : '已授权';

  return (
    <div className="flex items-start gap-3 animate-fade-in-up">
      <div
        className={`w-8 h-8 rounded-xl bg-gradient-to-br ${iconBgClass} flex items-center justify-center flex-shrink-0`}
      >
        <CheckCircle2 className={`w-4 h-4 ${iconColorClass}`} />
      </div>
      <div className="flex-1 max-w-[85%] md:max-w-[75%]">
        <div
          className={`bg-gradient-to-r ${lightGradientClass} rounded-xl p-4 border ${borderClass} shadow-sm`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-800 dark:text-slate-200 flex items-center gap-2">
              <CheckCircle2 className={`w-4 h-4 ${iconColorClass}`} />
              {title}
            </span>
            {createdAt && (
              <span className="text-xs text-slate-400">{formatTimeAgo(createdAt)}</span>
            )}
          </div>
          {answeredValue && (
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-2 pl-6">
              选择: <span className="font-medium text-slate-800 dark:text-slate-200">{answeredValue}</span>
            </p>
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

export const InlineHITLCard: React.FC<InlineHITLCardProps> = memo(
  ({
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
    const { submitResponse, isSubmitting, submittingRequestId, requestStatuses } =
      useUnifiedHITLStore(
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

    const handleSubmit = useCallback(
      async (responseData: HITLResponseData) => {
        try {
          await submitResponse(requestId, hitlType, responseData);
        } catch (error) {
          console.error('Failed to submit HITL response:', error);
        }
      },
      [requestId, hitlType, submitResponse]
    );

    // Show answered state
    if (isAnswered) {
      return (
        <AnsweredState hitlType={hitlType} answeredValue={answeredValue} createdAt={createdAt} />
      );
    }

    const icon = getHITLIcon(hitlType);
    const title = getHITLTitle(hitlType);
    const color = getHITLColor(hitlType);
    const iconBgClass = getHITLIconBgClass(hitlType);
    const iconColorClass = getHITLIconColorClass(hitlType);
    const lightGradientClass = getHITLLightGradientClass(hitlType);
    const borderClass = getHITLBorderClass(hitlType);

    return (
      <div className="flex items-start gap-3 animate-fade-in-up">
        {/* Avatar - Unified with MessageBubble style */}
        <div
          className={`w-8 h-8 rounded-xl bg-gradient-to-br ${iconBgClass} flex items-center justify-center flex-shrink-0 shadow-sm`}
        >
          <span className={iconColorClass}>{icon}</span>
        </div>

        {/* Card - Modern glass-morphism style unified with MessageBubble */}
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div
            className={`bg-gradient-to-r ${lightGradientClass} rounded-2xl rounded-tl-sm border ${borderClass} shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden`}
          >
            {/* Header - Modern style */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-inherit border-opacity-50">
              <div className="flex items-center gap-2">
                <Bot className={`w-4 h-4 ${iconColorClass}`} />
                <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {title}
                </span>
                <LazyTag color={color} className="text-xs rounded-full">
                  {hitlType}
                </LazyTag>
              </div>
              <CountdownTimer expiresAt={expiresAt} timeoutSeconds={timeoutSeconds} color={color} />
            </div>

            {/* Content */}
            <div className="p-4 bg-white/60 dark:bg-slate-900/40">
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
  }
);
InlineHITLCard.displayName = 'InlineHITLCard';

export default InlineHITLCard;
