/**
 * StepAdjustmentModal Component
 *
 * Modal for reviewing and approving/rejecting step adjustments
 * suggested by the reflection process during plan execution.
 *
 * Displays a list of adjustments with approve/reject actions
 * and bulk approve all/reject all functionality.
 *
 * @module components/agent/StepAdjustmentModal
 */

import React, { useMemo } from 'react';

import {
  CheckOutlined,
  CloseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { Modal, List, Tag, Button, Space, Typography, Empty, Alert } from 'antd';

import type { StepAdjustment, AdjustmentType } from '../../types/agent';

const { Text, Paragraph } = Typography;

/**
 * Props for StepAdjustmentModal
 */
export interface StepAdjustmentModalProps {
  /** Whether modal is visible */
  visible: boolean;
  /** Array of step adjustments to review */
  adjustments: StepAdjustment[] | null;
  /** Callback when single adjustment is approved */
  onApprove: (stepId: string) => void;
  /** Callback when single adjustment is rejected */
  onReject: (stepId: string) => void;
  /** Callback when all adjustments are approved */
  onApproveAll: () => void;
  /** Callback when all adjustments are rejected */
  onRejectAll: () => void;
  /** Callback when modal is closed */
  onClose: () => void;
  /** Optional CSS class name */
  className?: string;
}

/**
 * Get color for adjustment type badge
 */
const getAdjustmentTypeColor = (type: AdjustmentType): string => {
  switch (type) {
    case 'modify':
      return 'blue';
    case 'retry':
      return 'orange';
    case 'skip':
      return 'default';
    case 'add_before':
    case 'add_after':
      return 'green';
    case 'replace':
      return 'purple';
    default:
      return 'default';
  }
};

/**
 * Single adjustment item component
 */
interface AdjustmentItemProps {
  adjustment: StepAdjustment;
  onApprove: (stepId: string) => void;
  onReject: (stepId: string) => void;
}

const AdjustmentItem: React.FC<AdjustmentItemProps> = ({ adjustment, onApprove, onReject }) => {
  const hasNewInput =
    adjustment.new_tool_input && Object.keys(adjustment.new_tool_input).length > 0;

  return (
    <List.Item
      className="border-b border-slate-100 last:border-0"
      actions={[
        <Button
          key="approve"
          type="text"
          icon={<CheckOutlined />}
          onClick={() => { onApprove(adjustment.step_id); }}
          className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
          title="Approve adjustment"
        >
          Approve
        </Button>,
        <Button
          key="reject"
          type="text"
          icon={<CloseOutlined />}
          onClick={() => { onReject(adjustment.step_id); }}
          className="text-red-500 hover:text-red-600 hover:bg-red-50"
          title="Reject adjustment"
        >
          Reject
        </Button>,
      ]}
    >
      <List.Item.Meta
        avatar={
          <Tag color={getAdjustmentTypeColor(adjustment.adjustment_type) as any}>
            {adjustment.adjustment_type}
          </Tag>
        }
        title={
          <Space>
            <Text strong>{adjustment.step_id}</Text>
          </Space>
        }
        description={
          <div className="mt-1">
            <Paragraph className="mb-1 text-sm">{adjustment.reason}</Paragraph>
            {hasNewInput && (
              <Alert
                type="info"
                title="New Tool Input"
                description={
                  <pre className="text-xs bg-slate-50 p-2 rounded mt-1 overflow-x-auto">
                    {JSON.stringify(adjustment.new_tool_input, null, 2)}
                  </pre>
                }
                className="mt-2"
                banner
              />
            )}
          </div>
        }
      />
    </List.Item>
  );
};

/**
 * StepAdjustmentModal Component
 *
 * Displays a modal with step adjustments from the reflection process.
 * Users can approve or reject individual adjustments or use bulk actions.
 */
export const StepAdjustmentModal: React.FC<StepAdjustmentModalProps> = ({
  visible,
  adjustments,
  onApprove,
  onReject,
  onApproveAll,
  onRejectAll,
  onClose,
  className = '',
}) => {
  const { hasAdjustments, adjustmentCount, footer } = useMemo(() => {
    const count = adjustments?.length ?? 0;
    const has = count > 0;

    const modalFooter = has ? (
      <div className="flex justify-between">
        <Space>
          <Button icon={<CloseCircleOutlined />} onClick={onRejectAll} className="text-red-500">
            Reject All
          </Button>
          <Button icon={<CheckCircleOutlined />} onClick={onApproveAll} type="primary">
            Approve All
          </Button>
        </Space>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          type="primary"
          onClick={() => {
            onApproveAll();
            onClose();
          }}
        >
          Confirm
        </Button>
      </div>
    ) : (
      <Button onClick={onClose}>Close</Button>
    );

    return { hasAdjustments: has, adjustmentCount: count, footer: modalFooter };
  }, [adjustments, onApproveAll, onRejectAll, onClose]);

  return (
    <Modal
      title={
        <Space>
          <CheckCircleOutlined className="text-blue-500" />
          <span>Step Adjustments Review</span>
          {hasAdjustments && <Tag color="blue">{adjustmentCount} pending</Tag>}
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={footer}
      width={700}
      destroyOnHidden
      className={className}
    >
      {!hasAdjustments ? (
        <Empty description="No adjustments to review" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          dataSource={adjustments!}
          renderItem={(adjustment) => (
            <AdjustmentItem
              key={adjustment.step_id}
              adjustment={adjustment}
              onApprove={onApprove}
              onReject={onReject}
            />
          )}
          className="max-h-96 overflow-y-auto"
        />
      )}
    </Modal>
  );
};

export default StepAdjustmentModal;
