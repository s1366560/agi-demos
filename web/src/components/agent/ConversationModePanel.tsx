/**
 * ConversationModePanel — mode picker + WorkspaceTask linker (Phase-5 G8).
 *
 * Lets the operator switch a conversation between single / shared /
 * isolated / autonomous modes and, when the mode is ``autonomous``,
 * pick the linked WorkspaceTask whose goal + budget + status drive
 * the 3-gate termination (Phase-5 G3).
 *
 * Agent-First: the task is selected from a bounded workspace roster —
 * no free-form text parsing. Goal & budget live on the WorkspaceTask;
 * this panel does not duplicate goal state on the conversation.
 */

import { memo, useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Segmented, Select, message } from 'antd';

import { restApi } from '@/services/agent/restApi';
import { agentService } from '@/services/agentService';
import { workspaceTaskService } from '@/services/workspaceService';

import { useConversationParticipants } from '@/hooks/useConversationParticipants';

import type { Conversation } from '@/types/agent/core';
import type { WorkspaceTask } from '@/types/workspace';

type Mode = 'single_agent' | 'multi_agent_shared' | 'multi_agent_isolated' | 'autonomous';

export interface ConversationModePanelProps {
  conversationId: string;
  projectId: string;
  className?: string;
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

function resolveParticipantLabel(
  agentId: string | null | undefined,
  participantBindings:
    | Array<{
        agent_id: string;
        display_name: string | null;
        label: string | null;
      }>
    | undefined
): string | null {
  if (!agentId) return null;
  const binding = participantBindings?.find((item) => item.agent_id === agentId);
  return binding?.display_name || binding?.label || agentId;
}

export const ConversationModePanel = memo<ConversationModePanelProps>(
  ({ conversationId, projectId, className }) => {
    const { t } = useTranslation();
    const { roster, refresh } = useConversationParticipants(conversationId);

    const [submitting, setSubmitting] = useState(false);
    const [conversation, setConversation] = useState<Conversation | null>(null);
    const [tasks, setTasks] = useState<WorkspaceTask[]>([]);
    const [taskLoading, setTaskLoading] = useState(false);

    const effectiveMode = (roster?.effective_mode ?? 'single_agent') as Mode;

    const loadConversation = useCallback(async () => {
      try {
        const conv = await restApi.getConversation(conversationId, projectId);
        setConversation(conv);
      } catch (err: unknown) {
        // non-fatal — panel degrades to mode-only UI.
        console.error('[ConversationModePanel] load conversation failed', err);
      }
    }, [conversationId, projectId]);

    useEffect(() => {
      void loadConversation();
    }, [loadConversation]);

    useEffect(() => {
      const ws = conversation?.workspace_id;
      if (!ws) {
        setTasks([]);
        return;
      }
      setTaskLoading(true);
      void workspaceTaskService
        .list(ws)
        .then((items) => {
          setTasks(items);
        })
        .catch((err: unknown) => {
          console.error('[ConversationModePanel] load workspace tasks failed', err);
          setTasks([]);
        })
        .finally(() => {
          setTaskLoading(false);
        });
    }, [conversation?.workspace_id]);

    const handleModeChange = useCallback(
      async (next: Mode) => {
        if (next === effectiveMode) return;
        setSubmitting(true);
        try {
          await agentService.updateConversationMode(conversationId, projectId, {
            conversation_mode: next,
          });
          await refresh();
          await loadConversation();
          message.success(t('agent.workspace.mode.updated', 'Mode updated'));
        } catch (err: unknown) {
          message.error(
            (err as Error).message ||
              t('agent.workspace.mode.updateFailed', 'Failed to update mode')
          );
        } finally {
          setSubmitting(false);
        }
      },
      [conversationId, projectId, effectiveMode, refresh, loadConversation, t]
    );

    const handleTaskChange = useCallback(
      async (nextTaskId: string | null) => {
        if ((conversation?.linked_workspace_task_id ?? null) === nextTaskId) return;
        setSubmitting(true);
        try {
          await agentService.updateConversationMode(conversationId, projectId, {
            linked_workspace_task_id: nextTaskId,
          });
          await loadConversation();
          message.success(t('agent.workspace.task.updated', 'Linked task updated'));
        } catch (err: unknown) {
          message.error(
            (err as Error).message ||
              t('agent.workspace.task.updateFailed', 'Failed to update linked task')
          );
        } finally {
          setSubmitting(false);
        }
      },
      [conversation?.linked_workspace_task_id, conversationId, projectId, loadConversation, t]
    );

    const modeOptions = useMemo(
      () =>
        MODE_OPTIONS.map((opt) => ({
          label: t(opt.labelKey, opt.fallback),
          value: opt.value,
        })),
      [t]
    );

    const taskOptions = useMemo(
      () =>
        tasks.map((task) => ({
          label: `${task.title} · ${task.status}`,
          value: task.id,
        })),
      [tasks]
    );
    const focusedLabel = resolveParticipantLabel(
      roster?.focused_agent_id,
      roster?.participant_bindings
    );
    const coordinatorLabel = resolveParticipantLabel(
      roster?.coordinator_agent_id,
      roster?.participant_bindings
    );
    const linkedTask = tasks.find((task) => task.id === conversation?.linked_workspace_task_id) ?? null;
    const participantCount = roster?.participant_agents.length ?? 0;

    const showTaskPicker =
      effectiveMode === 'autonomous' && !!conversation?.workspace_id;

    return (
      <div
        className={className}
        data-testid="conversation-mode-panel"
        data-runtime-role-contract="derived"
      >
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[#666]">
          {t('agent.workspace.mode.label', 'Mode')}
        </div>
        <Segmented<Mode>
          value={effectiveMode}
          options={modeOptions}
          onChange={(next) => {
            void handleModeChange(next);
          }}
          disabled={submitting}
          block
          data-testid="conversation-mode-toggle"
        />

        <div
          className="mt-3 rounded-md border border-[rgba(0,0,0,0.08)] bg-[#fafafa] px-3 py-2"
          data-testid="conversation-mode-summary"
        >
          <div className="text-[11px] font-medium uppercase tracking-wide text-[#666]">
            {t('agent.workspace.mode.summaryLabel', 'Actor model')}
          </div>
          <div className="mt-2 space-y-1 text-xs text-[#444]">
            <div>{`${t('agent.workspace.mode.participantsLabel', 'Participants')}: ${String(participantCount)}`}</div>
            {coordinatorLabel ? (
              <div>{`${t('agent.workspace.mode.coordinatorLabel', 'Coordinator')}: ${coordinatorLabel}`}</div>
            ) : null}
            {effectiveMode === 'multi_agent_isolated' && focusedLabel ? (
              <div>{`${t('agent.workspace.mode.focusedLabel', 'Focused agent')}: ${focusedLabel}`}</div>
            ) : null}
            <div className="text-[#666]">
              {effectiveMode === 'autonomous'
                ? t(
                    'agent.workspace.mode.derivedRoleAutonomous',
                    'Leader/worker runtime role is derived from attempt context and the linked workspace task.'
                  )
                : effectiveMode === 'multi_agent_isolated'
                  ? t(
                      'agent.workspace.mode.derivedRoleIsolated',
                      'In isolated mode, routing prefers the focused agent before coordinator fallback.'
                    )
                  : t(
                      'agent.workspace.mode.derivedRoleShared',
                      'Conversation roles stay conversation-scoped; runtime authority is still derived at execution time.'
                    )}
            </div>
          </div>
        </div>

        {showTaskPicker ? (
          <div className="mt-4" data-testid="conversation-task-picker">
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[#666]">
              {t('agent.workspace.task.label', 'Linked workspace task')}
            </div>
            <Select<string | null>
              value={conversation.linked_workspace_task_id ?? null}
              onChange={(next) => {
                void handleTaskChange(next ?? null);
              }}
              options={taskOptions}
              loading={taskLoading}
              disabled={submitting}
              allowClear
              placeholder={t('agent.workspace.task.placeholder', 'Pick a workspace task…')}
              className="w-full"
              data-testid="conversation-task-select"
            />
            <div className="mt-1 text-[11px] text-[#999]">
              {t(
                'agent.workspace.task.hint',
                'Goal, budget and termination are driven by the linked task.'
              )}
            </div>
            {linkedTask ? (
              <div className="mt-2 text-[11px] text-[#666]" data-testid="conversation-linked-task-summary">
                {`${t('agent.workspace.task.summaryLabel', 'Linked task')}: ${linkedTask.title} · ${linkedTask.status}`}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }
);

ConversationModePanel.displayName = 'ConversationModePanel';
