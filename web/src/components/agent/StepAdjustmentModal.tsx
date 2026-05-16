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

import { useTranslation } from 'react-i18next';

import { Modal, Tag, Button, Space, Typography, Empty, Alert } from 'antd';
import { Check, CheckCircle2, X, XCircle } from 'lucide-react';

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
  className?: string | undefined;
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
  const { t } = useTranslation();
  const hasNewInput =
    adjustment.new_tool_input && Object.keys(adjustment.new_tool_input).length > 0;

  return (
    <li className="flex flex-col gap-3 border-b border-slate-100 py-4 last:border-0 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Tag color={getAdjustmentTypeColor(adjustment.adjustment_type)}>
            {adjustment.adjustment_type}
          </Tag>
          <Text strong className="break-all">
            {adjustment.step_id}
          </Text>
        </div>
        <div className="mt-2">
          <Paragraph className="mb-1 text-sm">{adjustment.reason}</Paragraph>
          {hasNewInput && (
            <Alert
              type="info"
              title={t('agent.stepAdjustment.newToolInput', {
                defaultValue: 'New Tool Input',
              })}
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
      </div>
      <Space className="shrink-0 self-start">
        <Button
          type="text"
          icon={<Check size={16} />}
          onClick={() => {
            onApprove(adjustment.step_id);
          }}
          className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
          title={t('agent.stepAdjustment.approveTitle', { defaultValue: 'Approve adjustment' })}
        >
          {t('agent.stepAdjustment.approve', { defaultValue: 'Approve' })}
        </Button>
        <Button
          type="text"
          icon={<X size={16} />}
          onClick={() => {
            onReject(adjustment.step_id);
          }}
          className="text-red-500 hover:text-red-600 hover:bg-red-50"
          title={t('agent.stepAdjustment.rejectTitle', { defaultValue: 'Reject adjustment' })}
        >
          {t('agent.stepAdjustment.reject', { defaultValue: 'Reject' })}
        </Button>
      </Space>
    </li>
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
  const { t } = useTranslation();

  const { hasAdjustments, adjustmentCount, footer } = useMemo(() => {
    const count = adjustments?.length ?? 0;
    const has = count > 0;

    const modalFooter = has ? (
      <div className="flex justify-between">
        <Space>
          <Button icon={<XCircle size={16} />} onClick={onRejectAll} className="text-red-500">
            {t('agent.stepAdjustment.rejectAll', { defaultValue: 'Reject All' })}
          </Button>
          <Button icon={<CheckCircle2 size={16} />} onClick={onApproveAll} type="primary">
            {t('agent.stepAdjustment.approveAll', { defaultValue: 'Approve All' })}
          </Button>
        </Space>
        <Button onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
        <Button
          type="primary"
          onClick={() => {
            onApproveAll();
            onClose();
          }}
        >
          {t('common.confirm', { defaultValue: 'Confirm' })}
        </Button>
      </div>
    ) : (
      <Button onClick={onClose}>{t('common.close', { defaultValue: 'Close' })}</Button>
    );

    return { hasAdjustments: has, adjustmentCount: count, footer: modalFooter };
  }, [adjustments, onApproveAll, onRejectAll, onClose, t]);

  return (
    <Modal
      title={
        <Space>
          <CheckCircle2 className="text-blue-500" size={16} />
          <span>
            {t('agent.stepAdjustment.title', { defaultValue: 'Step Adjustments Review' })}
          </span>
          {hasAdjustments && (
            <Tag color="blue">
              {t('agent.stepAdjustment.pendingCount', {
                count: adjustmentCount,
                defaultValue: '{{count}} pending',
              })}
            </Tag>
          )}
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
        <Empty
          description={t('agent.stepAdjustment.empty', {
            defaultValue: 'No adjustments to review',
          })}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <ul
          aria-label={t('agent.stepAdjustment.listLabel', {
            defaultValue: 'Step adjustments',
          })}
          className="m-0 max-h-96 list-none overflow-y-auto p-0"
        >
          {(adjustments ?? []).map((adjustment) => (
            <AdjustmentItem
              key={adjustment.step_id}
              adjustment={adjustment}
              onApprove={onApprove}
              onReject={onReject}
            />
          ))}
        </ul>
      )}
    </Modal>
  );
};

export default StepAdjustmentModal;
