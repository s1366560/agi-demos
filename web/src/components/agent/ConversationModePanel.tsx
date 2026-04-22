/**
 * ConversationModePanel — mode-picker (G1: GoalContract removed).
 *
 * Lets the operator switch a conversation between single / shared /
 * isolated / autonomous modes. Persists via
 * `PATCH /agent/conversations/{id}/mode` and refreshes the roster.
 *
 * Autonomous mode's goal/budget now lives on the linked WorkspaceTask
 * (G8 will add the WorkspaceTask picker here).
 */

import { memo, useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Segmented, message } from 'antd';

import { useConversationParticipants } from '@/hooks/useConversationParticipants';
import { agentService } from '@/services/agentService';

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

export const ConversationModePanel = memo<ConversationModePanelProps>(
  ({ conversationId, projectId, className }) => {
    const { t } = useTranslation();
    const { roster, refresh } = useConversationParticipants(conversationId);

    const [submitting, setSubmitting] = useState(false);

    const effectiveMode = (roster?.effective_mode ?? 'single_agent') as Mode;

    const handleModeChange = useCallback(
      async (next: Mode) => {
        if (next === effectiveMode) return;
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
      </div>
    );
  }
);

ConversationModePanel.displayName = 'ConversationModePanel';
