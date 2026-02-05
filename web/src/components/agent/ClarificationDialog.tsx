/**
 * ClarificationDialog Component
 * 
 * Displays a clarification question from the agent with selectable options.
 * Used during planning phase when the agent needs user input to resolve ambiguity.
 */

import React, { useState } from 'react';

import { QuestionCircleOutlined, CheckCircleOutlined } from '@ant-design/icons';

import { Modal, Radio, Input, Space, Button, Tag, Typography } from '@/components/ui/lazyAntd';

import type { ClarificationAskedEventData } from '../../types/agent';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface ClarificationDialogProps {
  data: ClarificationAskedEventData;
  onRespond: (requestId: string, answer: string) => void;
  onCancel?: () => void;
}

const clarificationTypeLabels: Record<string, string> = {
  scope: '范围确认',
  approach: '方案选择',
  prerequisite: '前置条件',
  priority: '优先级',
  custom: '自定义',
};

const clarificationTypeColors: Record<string, string> = {
  scope: 'blue',
  approach: 'green',
  prerequisite: 'orange',
  priority: 'purple',
  custom: 'default',
};

export const ClarificationDialog: React.FC<ClarificationDialogProps> = ({
  data,
  onRespond,
  onCancel,
}) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(
    data.options.find(opt => opt.recommended)?.id || null
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

  return (
    <Modal
      open={true}
      title={
        <Space>
          <QuestionCircleOutlined style={{ color: '#1890ff' }} />
          <span>需要澄清</span>
          <Tag color={clarificationTypeColors[data.clarification_type]}>
            {clarificationTypeLabels[data.clarification_type]}
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
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
        >
          确认
        </Button>,
      ]}
      width={600}
      destroyOnHidden
    >
      <div className="space-y-4">
        {/* Question */}
        <div className="mb-4">
          <Paragraph className="text-base font-medium text-slate-800 dark:text-slate-200">
            {data.question}
          </Paragraph>
        </div>

        {/* Context (if provided) */}
        {data.context && Object.keys(data.context).length > 0 && (
          <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800 mb-4">
            <Text className="text-sm text-blue-700 dark:text-blue-300">
              <strong>上下文：</strong>
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

        {/* Options */}
        <Radio.Group
          value={selectedOption}
          onChange={(e) => setSelectedOption(e.target.value)}
          className="w-full"
        >
          <Space direction="vertical" className="w-full" size="middle">
            {data.options.map((option) => (
              <Radio key={option.id} value={option.id} className="w-full">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2">
                    <Text strong>{option.label}</Text>
                    {option.recommended && (
                      <Tag color="green" className="text-xs">
                        推荐
                      </Tag>
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

            {/* Custom input option */}
            {data.allow_custom && (
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
      </div>
    </Modal>
  );
};

export default ClarificationDialog;
