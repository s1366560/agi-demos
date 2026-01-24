/**
 * DecisionModal Component
 * 
 * Displays a decision request from the agent with detailed options.
 * Used during execution phase when the agent needs user decision at critical points.
 */

import React, { useState } from 'react';
import { Modal, Radio, Input, Space, Button, Tag, Typography, Alert, Divider } from 'antd';
import {
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DollarOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { DecisionAskedEventData, DecisionOption } from '../../types/agent';

const { Text, Paragraph, Title } = Typography;
const { TextArea } = Input;

interface DecisionModalProps {
  data: DecisionAskedEventData;
  onRespond: (requestId: string, decision: string) => void;
  onCancel?: () => void;
}

const decisionTypeLabels: Record<string, string> = {
  branch: '分支选择',
  method: '方法选择',
  confirmation: '确认操作',
  risk: '风险确认',
  custom: '自定义',
};

const decisionTypeColors: Record<string, string> = {
  branch: 'blue',
  method: 'green',
  confirmation: 'orange',
  risk: 'red',
  custom: 'default',
};

const decisionTypeIcons: Record<string, React.ReactNode> = {
  branch: <ExclamationCircleOutlined />,
  method: <CheckCircleOutlined />,
  confirmation: <WarningOutlined />,
  risk: <WarningOutlined style={{ color: '#ff4d4f' }} />,
  custom: <ExclamationCircleOutlined />,
};

const DecisionOptionCard: React.FC<{
  option: DecisionOption;
  isSelected: boolean;
  onSelect: () => void;
}> = ({ option, isSelected, onSelect }) => {
  const hasRisks = option.risks && option.risks.length > 0;

  return (
    <div
      onClick={onSelect}
      className={`
        p-4 rounded-lg border-2 cursor-pointer transition-all
        ${isSelected 
          ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20' 
          : 'border-slate-200 dark:border-slate-700 hover:border-primary-300'
        }
      `}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1">
          <Radio checked={isSelected} />
          <Text strong className="text-base">{option.label}</Text>
          {option.recommended && (
            <Tag color="green" className="text-xs">
              推荐
            </Tag>
          )}
        </div>
      </div>

      {option.description && (
        <Paragraph className="text-sm text-slate-600 dark:text-slate-400 mb-3 ml-6">
          {option.description}
        </Paragraph>
      )}

      {/* Estimated time and cost */}
      {(option.estimated_time || option.estimated_cost) && (
        <div className="flex gap-4 ml-6 mb-2">
          {option.estimated_time && (
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <ClockCircleOutlined />
              <span>{option.estimated_time}</span>
            </div>
          )}
          {option.estimated_cost && (
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <DollarOutlined />
              <span>{option.estimated_cost}</span>
            </div>
          )}
        </div>
      )}

      {/* Risks */}
      {hasRisks && (
        <Alert
          message="风险提示"
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

export const DecisionModal: React.FC<DecisionModalProps> = ({
  data,
  onRespond,
  onCancel,
}) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data.options.find(opt => opt.recommended)?.id || data.default_option || null
  );
  const [customInput, setCustomInput] = useState('');

  const handleSubmit = () => {
    if (selectedOption === 'custom' && data.allow_custom) {
      if (customInput.trim()) {
        onRespond(data.request_id, customInput.trim());
      }
    } else if (selectedOption) {
      onRespond(data.request_id, selectedOption);
    }
  };

  const isSubmitDisabled = 
    !selectedOption || 
    (selectedOption === 'custom' && !customInput.trim());

  const selectedOptionData = data.options.find(opt => opt.id === selectedOption);
  const hasHighRisk = selectedOptionData?.risks && selectedOptionData.risks.length > 0;

  return (
    <Modal
      open={true}
      title={
        <Space>
          {decisionTypeIcons[data.decision_type]}
          <span>需要决策</span>
          <Tag color={decisionTypeColors[data.decision_type]}>
            {decisionTypeLabels[data.decision_type]}
          </Tag>
        </Space>
      }
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          取消
        </Button>,
        <Button
          key="submit"
          type={hasHighRisk ? 'default' : 'primary'}
          danger={hasHighRisk}
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
        >
          {hasHighRisk ? '确认并承担风险' : '确认决策'}
        </Button>,
      ]}
      width={700}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Question */}
        <div className="mb-4">
          <Title level={5} className="text-slate-800 dark:text-slate-200">
            {data.question}
          </Title>
        </div>

        {/* Context (if provided) */}
        {data.context && Object.keys(data.context).length > 0 && (
          <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800 mb-4">
            <Text className="text-sm text-blue-700 dark:text-blue-300">
              <strong>决策上下文：</strong>
            </Text>
            <div className="mt-2 space-y-1">
              {Object.entries(data.context).map(([key, value]) => (
                <div key={key} className="text-sm">
                  <Text className="text-blue-600 dark:text-blue-400">
                    {key}:
                  </Text>{' '}
                  <Text className="text-blue-800 dark:text-blue-200">
                    {JSON.stringify(value)}
                  </Text>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Default option notice */}
        {data.default_option && (
          <Alert
            message="超时默认选项"
            description={`如果您未在限定时间内做出决策，系统将自动选择：${
              data.options.find(opt => opt.id === data.default_option)?.label
            }`}
            type="info"
            showIcon
            className="mb-4"
          />
        )}

        <Divider />

        {/* Options */}
        <div className="space-y-3">
          {data.options.map((option) => (
            <DecisionOptionCard
              key={option.id}
              option={option}
              isSelected={selectedOption === option.id}
              onSelect={() => setSelectedOption(option.id)}
            />
          ))}

          {/* Custom input option */}
          {data.allow_custom && (
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
      </div>
    </Modal>
  );
};

export default DecisionModal;
