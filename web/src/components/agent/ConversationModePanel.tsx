/**
 * ConversationModePanel — Track F (f-mode-toggle + f-goal-editor).
 *
 * Lets the operator switch a conversation between single / shared /
 * isolated / autonomous modes and edit the goal contract that autonomous
 * mode requires. Persists via `PATCH /agent/conversations/{id}/mode` and
 * refreshes the roster so every consumer (MentionPicker, HITL center,
 * chip rendering) picks up the new effective mode.
 */

import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button, Drawer, Form, Input, InputNumber, Segmented, message } from 'antd';

import { useConversationParticipants } from '@/hooks/useConversationParticipants';
import { agentService } from '@/services/agentService';

type Mode = 'single_agent' | 'multi_agent_shared' | 'multi_agent_isolated' | 'autonomous';

export interface ConversationModePanelProps {
  conversationId: string;
  projectId: string;
  className?: string;
}

interface GoalFormValues {
  primary_goal: string;
  operator_guidance?: string;
  blocking_categories?: string;
  max_turns?: number | null;
  max_usd?: number | null;
  max_wall_seconds?: number | null;
  supervisor_tick_seconds?: number;
}

const MODE_OPTIONS: Array<{ value: Mode; labelKey: string; fallback: string }> = [
  { value: 'single_agent', labelKey: 'agent.workspace.mode.single', fallback: 'Single' },
  { value: 'multi_agent_shared', labelKey: 'agent.workspace.mode.shared', fallback: 'Shared' },
  {
    value: 'multi_agent_isolated',
    labelKey: 'agent.workspace.mode.isolated',
    fallback: 'Isolated',
  },
  { value: 'autonomous', labelKey: 'agent.workspace.mode.autonomous', fallback: 'Autonomous' },
];

export const ConversationModePanel = memo<ConversationModePanelProps>(
  ({ conversationId, projectId, className }) => {
    const { t } = useTranslation();
    const { roster, refresh } = useConversationParticipants(conversationId);

    const [goalOpen, setGoalOpen] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [form] = Form.useForm<GoalFormValues>();

    const effectiveMode = (roster?.effective_mode ?? 'single_agent') as Mode;

    const loadGoalFromConversation = useCallback(async () => {
      try {
        // Pull the persisted goal_contract from the conversation record so
        // the drawer opens with existing values rather than blanks.
        const conv = await agentService.getConversation(conversationId, projectId);
        const contract = (
          conv as { goal_contract?: Record<string, unknown> | null | undefined } | null
        )?.goal_contract;
        if (contract) {
          form.setFieldsValue({
            primary_goal: String(contract.primary_goal ?? ''),
            operator_guidance: String(contract.operator_guidance ?? ''),
            blocking_categories: Array.isArray(contract.blocking_categories)
              ? (contract.blocking_categories as string[]).join(', ')
              : '',
            max_turns:
              (contract.budget as { max_turns?: number | null } | undefined)?.max_turns ?? null,
            max_usd: (contract.budget as { max_usd?: number | null } | undefined)?.max_usd ?? null,
            max_wall_seconds:
              (contract.budget as { max_wall_seconds?: number | null } | undefined)
                ?.max_wall_seconds ?? null,
            supervisor_tick_seconds: (contract.supervisor_tick_seconds as number | undefined) ?? 120,
          });
        } else {
          form.resetFields();
          form.setFieldsValue({ supervisor_tick_seconds: 120 });
        }
      } catch {
        form.resetFields();
        form.setFieldsValue({ supervisor_tick_seconds: 120 });
      }
    }, [conversationId, projectId, form]);

    useEffect(() => {
      if (goalOpen) {
        void loadGoalFromConversation();
      }
    }, [goalOpen, loadGoalFromConversation]);

    const handleModeChange = useCallback(
      async (next: Mode) => {
        if (next === effectiveMode) return;
        if (next === 'autonomous') {
          setGoalOpen(true);
          return;
        }
        setSubmitting(true);
        try {
          await agentService.updateConversationMode(conversationId, projectId, {
            conversation_mode: next,
          });
          await refresh();
          message.success(t('agent.workspace.mode.updated', 'Mode updated'));
        } catch (err) {
          message.error(
            (err as Error).message ||
              t('agent.workspace.mode.updateFailed', 'Failed to update mode')
          );
        } finally {
          setSubmitting(false);
        }
      },
      [conversationId, projectId, effectiveMode, refresh, t]
    );

    const handleGoalSubmit = useCallback(async () => {
      try {
        const values = await form.validateFields();
        setSubmitting(true);
        const blockingCategories = (values.blocking_categories ?? '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean);
        await agentService.updateConversationMode(conversationId, projectId, {
          conversation_mode: 'autonomous',
          goal_contract: {
            primary_goal: values.primary_goal.trim(),
            blocking_categories: blockingCategories,
            operator_guidance: (values.operator_guidance ?? '').trim(),
            budget: {
              max_turns: values.max_turns ?? null,
              max_usd: values.max_usd ?? null,
              max_wall_seconds: values.max_wall_seconds ?? null,
            },
            supervisor_tick_seconds: values.supervisor_tick_seconds ?? 120,
          },
        });
        await refresh();
        setGoalOpen(false);
        message.success(t('agent.workspace.goal.saved', 'Goal contract saved'));
      } catch (err) {
        if ((err as { errorFields?: unknown }).errorFields) {
          // antd validation error — already rendered in-form
          return;
        }
        message.error(
          (err as Error).message || t('agent.workspace.goal.saveFailed', 'Failed to save goal')
        );
      } finally {
        setSubmitting(false);
      }
    }, [conversationId, projectId, form, refresh, t]);

    const modeOptions = useMemo(
      () =>
        MODE_OPTIONS.map((opt) => ({
          label: t(opt.labelKey, opt.fallback),
          value: opt.value,
        })),
      [t]
    );

    return (
      <div className={className} data-testid="conversation-mode-panel">
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[#666]">
          {t('agent.workspace.mode.label', 'Mode')}
        </div>
        <Segmented<Mode>
          value={effectiveMode}
          options={modeOptions}
          onChange={(next) => void handleModeChange(next as Mode)}
          disabled={submitting}
          block
          data-testid="conversation-mode-toggle"
        />
        {effectiveMode === 'autonomous' && (
          <Button
            type="link"
            size="small"
            className="mt-2 px-0"
            onClick={() => {
              setGoalOpen(true);
            }}
            data-testid="conversation-mode-edit-goal"
          >
            {t('agent.workspace.goal.edit', 'Edit goal contract')}
          </Button>
        )}

        <Drawer
          title={t('agent.workspace.goal.drawerTitle', 'Goal contract')}
          placement="right"
          width={420}
          open={goalOpen}
          onClose={() => {
            setGoalOpen(false);
          }}
          destroyOnHidden
          data-testid="goal-contract-drawer"
          extra={
            <div className="flex gap-2">
              <Button
                onClick={() => {
                  setGoalOpen(false);
                }}
              >
                {t('common.cancel', 'Cancel')}
              </Button>
              <Button
                type="primary"
                loading={submitting}
                onClick={() => void handleGoalSubmit()}
                data-testid="goal-contract-submit"
              >
                {t('common.save', 'Save')}
              </Button>
            </div>
          }
        >
          <Form
            layout="vertical"
            form={form}
            requiredMark="optional"
            initialValues={{ supervisor_tick_seconds: 120 }}
          >
            <Form.Item
              label={t('agent.workspace.goal.primaryGoal', 'Primary goal')}
              name="primary_goal"
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: t(
                    'agent.workspace.goal.primaryGoalRequired',
                    'Goal cannot be empty'
                  ),
                },
              ]}
            >
              <Input.TextArea
                rows={3}
                maxLength={1000}
                data-testid="goal-contract-primary-goal"
              />
            </Form.Item>
            <Form.Item
              label={t('agent.workspace.goal.operatorGuidance', 'Operator guidance')}
              name="operator_guidance"
              tooltip={t(
                'agent.workspace.goal.operatorGuidanceTooltip',
                'Prose instructions injected into the coordinator prompt (not pattern-matched).'
              )}
            >
              <Input.TextArea rows={3} maxLength={2000} />
            </Form.Item>
            <Form.Item
              label={t('agent.workspace.goal.blockingCategories', 'Blocking categories')}
              name="blocking_categories"
              tooltip={t(
                'agent.workspace.goal.blockingCategoriesTooltip',
                'Comma-separated side-effect categories that require human approval (e.g. payment, delete).'
              )}
            >
              <Input placeholder="payment, delete" />
            </Form.Item>
            <Form.Item
              label={t('agent.workspace.goal.maxTurns', 'Max turns')}
              name="max_turns"
            >
              <InputNumber
                min={1}
                step={1}
                className="w-full"
                data-testid="goal-contract-max-turns"
              />
            </Form.Item>
            <Form.Item label={t('agent.workspace.goal.maxUsd', 'Max USD')} name="max_usd">
              <InputNumber min={0.01} step={0.1} className="w-full" />
            </Form.Item>
            <Form.Item
              label={t('agent.workspace.goal.maxWallSeconds', 'Max wall seconds')}
              name="max_wall_seconds"
            >
              <InputNumber min={1} step={60} className="w-full" />
            </Form.Item>
            <Form.Item
              label={t(
                'agent.workspace.goal.supervisorTickSeconds',
                'Supervisor tick (seconds)'
              )}
              name="supervisor_tick_seconds"
              rules={[{ required: true, type: 'number', min: 1 }]}
            >
              <InputNumber min={1} step={30} className="w-full" />
            </Form.Item>
          </Form>
        </Drawer>
      </div>
    );
  }
);

ConversationModePanel.displayName = 'ConversationModePanel';
