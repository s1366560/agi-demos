/**
 * PlanEditor component for editing plan documents in Plan Mode.
 *
 * This component provides a Markdown editor for viewing and editing
 * plan documents during the planning phase.
 */

import { useState, useCallback, useEffect, memo } from 'react';

import {
  EditOutlined,
  CheckOutlined,
  CloseOutlined,
  SaveOutlined,
  FileTextOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import {
  Card,
  Button,
  Typography,
  Space,
  Tag,
  Tooltip,
  Modal,
  Input,
  message,
  Spin,
  Divider,
} from 'antd';

import type { PlanDocument, PlanDocumentStatus } from '../../types/agent';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface PlanEditorProps {
  plan: PlanDocument | null;
  isLoading?: boolean;
  onUpdate?: (content: string) => Promise<void>;
  onApprove?: () => Promise<void>;
  /** Submit plan for review (draft → reviewing) */
  onSubmitForReview?: () => Promise<void>;
  /** Exit plan mode with optional approval and summary */
  onExit?: (approve: boolean, summary?: string) => Promise<void>;
  readOnly?: boolean;
}

const statusColors: Record<PlanDocumentStatus, string> = {
  draft: 'blue',
  reviewing: 'orange',
  approved: 'green',
  archived: 'default',
};

const statusLabels: Record<PlanDocumentStatus, string> = {
  draft: 'Draft',
  reviewing: 'Reviewing',
  approved: 'Approved',
  archived: 'Archived',
};

// Memoized PlanEditor to prevent unnecessary re-renders (rerender-memo)
export const PlanEditor = memo<PlanEditorProps>(
  ({
    plan,
    isLoading = false,
    onUpdate,
    onApprove: _onApprove,
    onSubmitForReview,
    onExit,
    readOnly = false,
  }) => {
    const [isEditing, setIsEditing] = useState(false);
    const [editContent, setEditContent] = useState('');
    const [isSaving, setIsSaving] = useState(false);

    // Reset edit content when plan changes
    useEffect(() => {
      if (plan) {
        setEditContent(plan.content);
      }
    }, [plan?.id, plan?.version]);

    const handleStartEdit = useCallback(() => {
      if (plan) {
        setEditContent(plan.content);
        setIsEditing(true);
      }
    }, [plan]);

    const handleCancelEdit = useCallback(() => {
      setIsEditing(false);
      if (plan) {
        setEditContent(plan.content);
      }
    }, [plan]);

    const handleSave = useCallback(async () => {
      if (!onUpdate || !editContent) return;

      setIsSaving(true);
      try {
        await onUpdate(editContent);
        setIsEditing(false);
        message.success('Plan saved successfully');
      } catch {
        message.error('Failed to save plan');
      } finally {
        setIsSaving(false);
      }
    }, [onUpdate, editContent]);

    const handleApproveAndExit = useCallback(() => {
      Modal.confirm({
        title: 'Approve Plan',
        icon: <ExclamationCircleOutlined />,
        content:
          'Are you sure you want to approve this plan and exit Plan Mode? This will switch back to Build Mode for implementation.',
        okText: 'Approve & Exit',
        cancelText: 'Cancel',
        onOk: async () => {
          if (onExit) {
            try {
              await onExit(true);
              message.success('Plan approved. Switched to Build Mode.');
            } catch {
              message.error('Failed to approve plan');
            }
          }
        },
      });
    }, [onExit]);

    const handleExitWithoutApproval = useCallback(() => {
      Modal.confirm({
        title: 'Exit Plan Mode',
        icon: <ExclamationCircleOutlined />,
        content:
          "Are you sure you want to exit Plan Mode without approving the plan? The plan will be saved as 'Reviewing'.",
        okText: 'Exit',
        cancelText: 'Cancel',
        onOk: async () => {
          if (onExit) {
            try {
              await onExit(false);
              message.info('Exited Plan Mode. Plan saved as Reviewing.');
            } catch {
              message.error('Failed to exit Plan Mode');
            }
          }
        },
      });
    }, [onExit]);

    if (isLoading) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <Spin size="large" />
            <Paragraph style={{ marginTop: 16 }}>Loading plan...</Paragraph>
          </div>
        </Card>
      );
    }

    if (!plan) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px' }}>
            <FileTextOutlined style={{ fontSize: 48, color: '#999' }} />
            <Paragraph style={{ marginTop: 16 }}>
              No plan document loaded. Enter Plan Mode to create a new plan.
            </Paragraph>
          </div>
        </Card>
      );
    }

    const isEditable = plan.status === 'draft' || plan.status === 'reviewing';

    return (
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>{plan.title}</span>
            <Tag color={statusColors[plan.status]}>{statusLabels[plan.status]}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              v{plan.version}
            </Text>
          </Space>
        }
        extra={
          <Space>
            {isEditing ? (
              <>
                <Button icon={<CloseOutlined />} onClick={handleCancelEdit} disabled={isSaving}>
                  Cancel
                </Button>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={handleSave}
                  loading={isSaving}
                >
                  Save
                </Button>
              </>
            ) : (
              <>
                {!readOnly && isEditable && (
                  <Tooltip title="Edit plan content">
                    <Button icon={<EditOutlined />} onClick={handleStartEdit}>
                      Edit
                    </Button>
                  </Tooltip>
                )}
                {onExit && isEditable && (
                  <>
                    {plan.status === 'draft' && onSubmitForReview && (
                      <Button
                        onClick={async () => {
                          try {
                            await onSubmitForReview();
                            message.success('Plan submitted for review');
                          } catch {
                            message.error('Failed to submit plan for review');
                          }
                        }}
                      >
                        Submit for Review
                      </Button>
                    )}
                    <Button onClick={handleExitWithoutApproval}>Exit without Approval</Button>
                    <Button type="primary" icon={<CheckOutlined />} onClick={handleApproveAndExit}>
                      Approve & Exit
                    </Button>
                  </>
                )}
              </>
            )}
          </Space>
        }
      >
        {isEditing ? (
          <TextArea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            autoSize={{ minRows: 20, maxRows: 40 }}
            style={{ fontFamily: 'monospace' }}
            placeholder="Enter plan content in Markdown format..."
          />
        ) : (
          <div
            style={{
              whiteSpace: 'pre-wrap',
              fontFamily: 'monospace',
              lineHeight: 1.6,
              padding: '8px 0',
            }}
          >
            {plan.content}
          </div>
        )}

        <Divider />

        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Created: {new Date(plan.created_at).toLocaleString()}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Updated: {new Date(plan.updated_at).toLocaleString()}
          </Text>
          {Array.isArray(plan.metadata?.explored_files) && (
            <div>
              <Text strong style={{ fontSize: 12 }}>
                Explored Files ({(plan.metadata.explored_files as string[]).length}):
              </Text>
              <div style={{ marginTop: 4 }}>
                {(plan.metadata.explored_files as string[]).slice(0, 5).map((file, i) => (
                  <Tag key={i} style={{ marginBottom: 4 }}>
                    {file}
                  </Tag>
                ))}
                {(plan.metadata.explored_files as string[]).length > 5 && (
                  <Tag>+{(plan.metadata.explored_files as string[]).length - 5} more</Tag>
                )}
              </div>
            </div>
          )}
          {Array.isArray(plan.metadata?.critical_files) && (
            <div>
              <Text strong style={{ fontSize: 12 }}>
                Critical Files (
                {
                  (
                    plan.metadata.critical_files as Array<{
                      path: string;
                      type: string;
                    }>
                  ).length
                }
                ):
              </Text>
              <div style={{ marginTop: 4 }}>
                {(
                  plan.metadata.critical_files as Array<{
                    path: string;
                    type: string;
                  }>
                )
                  .slice(0, 5)
                  .map((file, i) => (
                    <Tag
                      key={i}
                      color={
                        file.type === 'create' ? 'green' : file.type === 'delete' ? 'red' : 'blue'
                      }
                      style={{ marginBottom: 4 }}
                    >
                      [{file.type}] {file.path}
                    </Tag>
                  ))}
              </div>
            </div>
          )}
        </Space>
      </Card>
    );
  }
);

PlanEditor.displayName = 'PlanEditor';

export default PlanEditor;
