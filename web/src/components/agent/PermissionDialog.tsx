/**
 * PermissionDialog Component
 * 
 * Displays a permission request from the agent when it needs user approval
 * to execute a tool with elevated privileges or sensitive operations.
 */

import React from 'react';

import { SafetyOutlined, WarningOutlined, CodeOutlined } from '@ant-design/icons';

import { Modal, Space, Button, Tag, Typography, Alert, Descriptions } from '@/components/ui/lazyAntd';

import type { PermissionAskedEventData } from '../../types/agent';

const { Text, Paragraph } = Typography;

interface PermissionDialogProps {
  data: PermissionAskedEventData;
  onRespond: (requestId: string, granted: boolean) => void;
  onCancel?: () => void;
}

const riskLevelLabels: Record<string, string> = {
  low: '低风险',
  medium: '中等风险',
  high: '高风险',
};

const riskLevelColors: Record<string, string> = {
  low: 'green',
  medium: 'gold',
  high: 'red',
};

const riskLevelIcons: Record<string, React.ReactNode> = {
  low: <SafetyOutlined style={{ color: '#52c41a' }} />,
  medium: <WarningOutlined style={{ color: '#faad14' }} />,
  high: <WarningOutlined style={{ color: '#f5222d' }} />,
};

export const PermissionDialog: React.FC<PermissionDialogProps> = ({
  data,
  onRespond,
  onCancel,
}) => {
  const riskLevel = data.risk_level || 'medium';

  const handleGrant = () => {
    onRespond(data.request_id, true);
  };

  const handleDeny = () => {
    onRespond(data.request_id, false);
  };

  return (
    <Modal
      open={true}
      title={
        <Space>
          {riskLevelIcons[riskLevel]}
          <span>工具权限请求</span>
          <Tag color={riskLevelColors[riskLevel]}>
            {riskLevelLabels[riskLevel]}
          </Tag>
        </Space>
      }
      onCancel={onCancel}
      footer={[
        <Button key="deny" danger onClick={handleDeny}>
          拒绝
        </Button>,
        <Button
          key="grant"
          type="primary"
          onClick={handleGrant}
          icon={<SafetyOutlined />}
        >
          授权执行
        </Button>,
      ]}
      width={600}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
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
          <Descriptions.Item label={<Space><CodeOutlined /> 工具名称</Space>}>
            <Text code>{data.tool_name}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="权限类型">
            <Tag color={data.permission_type === 'ask' ? 'blue' : data.permission_type === 'allow' ? 'green' : 'red'}>
              {data.permission_type === 'ask' ? '需要确认' : data.permission_type === 'allow' ? '允许' : '禁止'}
            </Tag>
          </Descriptions.Item>
        </Descriptions>

        {/* Request Description */}
        <div>
          <Text strong>请求描述：</Text>
          <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
            {data.description || '代理需要执行此工具来完成当前任务。'}
          </Paragraph>
        </div>

        {/* Context Preview */}
        {data.context && Object.keys(data.context).length > 0 && (
          <div>
            <Text strong>上下文信息：</Text>
            <pre
              style={{
                marginTop: 8,
                padding: 12,
                backgroundColor: '#f5f5f5',
                borderRadius: 4,
                fontSize: 12,
                maxHeight: 200,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(data.context, null, 2)}
            </pre>
          </div>
        )}
      </Space>
    </Modal>
  );
};

export default PermissionDialog;
