/**
 * DoomLoopInterventionModal Component
 *
 * Displays when the agent is detected to be stuck in a doom loop
 * (repeating the same tool calls without progress).
 * Allows user to intervene with various options.
 */

import React, { useState } from 'react';

import {
  WarningOutlined,
  StopOutlined,
  ReloadOutlined,
  EditOutlined,
  BulbOutlined,
} from '@ant-design/icons';

import { formatTimeOnly } from '@/utils/date';

import {
  Modal,
  Radio,
  Space,
  Button,
  Alert,
  Divider,
  List,
  Typography,
} from '@/components/ui/lazyAntd';


const { Text, Title } = Typography;

export interface DoomLoopDetectedEventData {
  request_id: string;
  tool_name: string;
  call_count: number;
  last_calls: Array<{
    tool: string;
    input: Record<string, unknown>;
    timestamp: string;
  }>;
  context?: Record<string, unknown>;
}

interface DoomLoopInterventionModalProps {
  data: DoomLoopDetectedEventData;
  onRespond: (requestId: string, action: string) => void;
  onCancel?: () => void;
}

type InterventionAction =
  | 'stop' // Stop execution
  | 'retry_modified' // Retry with modified approach
  | 'skip_step' // Skip current step
  | 'provide_hint' // Provide hint to agent
  | 'continue'; // Continue anyway (ignore warning)

const interventionOptions = [
  {
    id: 'stop' as InterventionAction,
    label: '停止执行',
    description: '立即停止智能体执行，防止继续浪费资源',
    icon: <StopOutlined style={{ color: '#ff4d4f' }} />,
    recommended: true,
  },
  {
    id: 'retry_modified' as InterventionAction,
    label: '修改后重试',
    description: '引导智能体尝试不同的方法或工具',
    icon: <ReloadOutlined style={{ color: '#1890ff' }} />,
    recommended: false,
  },
  {
    id: 'skip_step' as InterventionAction,
    label: '跳过当前步骤',
    description: '跳过导致死循环的步骤，继续执行后续任务',
    icon: <EditOutlined style={{ color: '#faad14' }} />,
    recommended: false,
  },
  {
    id: 'provide_hint' as InterventionAction,
    label: '提供提示',
    description: '给智能体提供额外信息或方向指引',
    icon: <BulbOutlined style={{ color: '#52c41a' }} />,
    recommended: false,
  },
  {
    id: 'continue' as InterventionAction,
    label: '继续执行',
    description: '忽略警告，继续当前执行（不推荐）',
    icon: <WarningOutlined style={{ color: '#8c8c8c' }} />,
    recommended: false,
  },
];

export const DoomLoopInterventionModal: React.FC<DoomLoopInterventionModalProps> = ({
  data,
  onRespond,
  onCancel,
}) => {
  const [selectedAction, setSelectedAction] = useState<InterventionAction>('stop');

  const handleSubmit = () => {
    onRespond(data.request_id, selectedAction);
  };

  return (
    <Modal
      open={true}
      title={
        <Space>
          <WarningOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
          <span>检测到死循环</span>
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
          danger={selectedAction === 'stop'}
          onClick={handleSubmit}
        >
          {selectedAction === 'stop' ? '停止执行' : '确认干预'}
        </Button>,
      ]}
      width={700}
      closable={false}
      maskClosable={false}
    >
      <div className="space-y-4">
        {/* Warning Alert */}
        <Alert
          message="智能体陷入死循环"
          description={
            <div>
              <Text>
                检测到工具 <Text code>{data.tool_name}</Text> 被重复调用{' '}
                <Text strong style={{ color: '#ff4d4f' }}>
                  {data.call_count}
                </Text>{' '}
                次， 可能陷入无限循环。需要您的干预来解决此问题。
              </Text>
            </div>
          }
          type="error"
          showIcon
          icon={<WarningOutlined />}
        />

        {/* Recent Calls */}
        <div className="mt-4">
          <Title level={5} className="text-slate-700 dark:text-slate-300">
            最近的重复调用：
          </Title>
          <div className="max-h-48 overflow-y-auto bg-slate-50 dark:bg-slate-800 rounded-lg p-3 border border-slate-200 dark:border-slate-700">
            <List
              size="small"
              dataSource={data.last_calls.slice(0, 5)}
              renderItem={(call, idx) => (
                <List.Item
                  key={idx}
                  className="border-b border-slate-200 dark:border-slate-700 last:border-b-0"
                >
                  <div className="w-full">
                    <div className="flex items-center gap-2 mb-1">
                      <Text type="secondary" className="text-xs">
                        #{idx + 1}
                      </Text>
                      <Text code className="text-sm">
                        {call.tool}
                      </Text>
                      <Text type="secondary" className="text-xs">
                        {formatTimeOnly(call.timestamp)}
                      </Text>
                    </div>
                    <pre className="text-xs text-slate-600 dark:text-slate-400 bg-white dark:bg-slate-900 p-2 rounded overflow-x-auto">
                      {JSON.stringify(call.input, null, 2)}
                    </pre>
                  </div>
                </List.Item>
              )}
            />
          </div>
        </div>

        <Divider />

        {/* Intervention Options */}
        <div>
          <Title level={5} className="text-slate-700 dark:text-slate-300 mb-3">
            选择干预方式：
          </Title>
          <Radio.Group
            value={selectedAction}
            onChange={(e) => setSelectedAction(e.target.value)}
            className="w-full"
          >
            <Space direction="vertical" className="w-full" size="middle">
              {interventionOptions.map((option) => (
                <div
                  key={option.id}
                  onClick={() => setSelectedAction(option.id)}
                  className={`
                    p-4 rounded-lg border-2 cursor-pointer transition-all
                    ${
                      selectedAction === option.id
                        ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                        : 'border-slate-200 dark:border-slate-700 hover:border-primary-300'
                    }
                  `}
                >
                  <Radio value={option.id} className="w-full">
                    <div className="flex items-start gap-3">
                      <div className="mt-1">{option.icon}</div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <Text strong className="text-base">
                            {option.label}
                          </Text>
                          {option.recommended && (
                            <span className="px-2 py-0.5 text-xs font-medium text-green-700 bg-green-100 dark:bg-green-900/30 dark:text-green-400 rounded">
                              推荐
                            </span>
                          )}
                        </div>
                        <Text type="secondary" className="text-sm">
                          {option.description}
                        </Text>
                      </div>
                    </div>
                  </Radio>
                </div>
              ))}
            </Space>
          </Radio.Group>
        </div>

        {/* Additional Context */}
        {data.context && Object.keys(data.context).length > 0 && (
          <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <Text className="text-sm text-blue-700 dark:text-blue-300">
              <strong>执行上下文：</strong>
            </Text>
            <div className="mt-2 space-y-1">
              {Object.entries(data.context).map(([key, value]) => (
                <div key={key} className="text-sm">
                  <Text className="text-blue-600 dark:text-blue-400">{key}:</Text>{' '}
                  <Text className="text-blue-800 dark:text-blue-200">{JSON.stringify(value)}</Text>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};

export default DoomLoopInterventionModal;
