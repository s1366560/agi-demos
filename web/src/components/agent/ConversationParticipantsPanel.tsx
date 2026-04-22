/**
 * ConversationParticipantsPanel — Track B P2-3 phase-2 (b-fe-roster).
 *
 * Displays the current roster for a multi-agent conversation with
 * coordinator / focused badges. Delete action removes a participant.
 *
 * Design: compact sidebar panel (monochrome, 1px borders), matching the
 * Vercel-inspired design tokens in .impeccable.md.
 */

import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useConversationParticipants } from '../../hooks/useConversationParticipants';
import { useMentionCandidates } from '../../hooks/useMentionCandidates';

export interface ConversationParticipantsPanelProps {
  conversationId: string | null;
  onSelectAgent?: (agentId: string) => void;
  onRemoveAgent?: (agentId: string) => void;
  className?: string;
}

const badgeBase =
  'inline-flex h-[18px] items-center rounded-full border border-[rgba(0,0,0,0.08)] bg-[#ebebeb] px-2 text-[11px] font-medium text-[#171717]';

const modeLabel = (mode: string) => mode.replace(/_/g, ' ');

export const ConversationParticipantsPanel = memo<ConversationParticipantsPanelProps>(
  ({ conversationId, onSelectAgent, onRemoveAgent, className }) => {
    const { t } = useTranslation();
    const { roster, loading, error, removeParticipant, setCoordinator, addParticipant } =
      useConversationParticipants(conversationId);
    const { candidates } = useMentionCandidates(conversationId, { enabled: !!conversationId });
    const [adding, setAdding] = useState(false);
    const [addError, setAddError] = useState<string | null>(null);

    const availableToAdd = useMemo(() => {
      const rostered = new Set(roster?.participant_agents ?? []);
      return candidates.filter((c) => !rostered.has(c.agent_id));
    }, [candidates, roster?.participant_agents]);

    if (!conversationId) {
      return null;
    }

    if (loading && !roster) {
      return (
        <aside className={className} aria-busy="true">
          <p className="text-sm text-[#666]">
            {t('agent.participants.loading', { defaultValue: 'Loading roster...' })}
          </p>
        </aside>
      );
    }

    if (error) {
      return (
        <aside className={className}>
          <p className="text-sm text-[#ee0000]">
            {t('agent.participants.error', { defaultValue: 'Failed to load roster' })}
          </p>
        </aside>
      );
    }

    if (!roster) {
      return null;
    }

    const { participant_agents, coordinator_agent_id, focused_agent_id, effective_mode } = roster;

    return (
      <aside
        className={className}
        data-testid="conversation-participants-panel"
        aria-label="conversation participants"
      >
        <header className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-medium uppercase tracking-wide text-[#666]">
            {t('agent.participants.title', { defaultValue: 'Participants' })}
          </h3>
          <span className={badgeBase} title={effective_mode}>
            {modeLabel(effective_mode)}
          </span>
        </header>

        {participant_agents.length === 0 ? (
          <p className="text-sm text-[#999]">
            {t('agent.participants.empty', { defaultValue: 'No agents in this conversation.' })}
          </p>
        ) : (
          <ul className="space-y-2">
            {participant_agents.map((agentId) => {
              const isCoordinator = agentId === coordinator_agent_id;
              const isFocused = agentId === focused_agent_id;
              return (
                <li
                  key={agentId}
                  className="flex items-center justify-between gap-2 rounded-md border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2"
                >
                  <button
                    type="button"
                    onClick={() => onSelectAgent?.(agentId)}
                    className="flex-1 text-left text-sm font-medium text-[#171717] hover:text-[#0070f3]"
                  >
                    {agentId}
                  </button>
                  <div className="flex items-center gap-1">
                    {isCoordinator && (
                      <span className={badgeBase}>
                        {t('agent.participants.coordinator', {
                          defaultValue: 'coordinator',
                        })}
                      </span>
                    )}
                    {isFocused && (
                      <span className={badgeBase}>
                        {t('agent.participants.focused', { defaultValue: 'focused' })}
                      </span>
                    )}
                    {!isCoordinator && (
                      <button
                        type="button"
                        onClick={() => void setCoordinator(agentId)}
                        className="rounded px-2 py-0.5 text-xs text-[#666] hover:bg-[#fafafa] hover:text-[#0070f3]"
                        title={t('agent.participants.setCoordinator', {
                          defaultValue: 'Set as coordinator',
                        })}
                        aria-label={t('agent.participants.setCoordinatorFor', {
                          defaultValue: `Set ${agentId} as coordinator`,
                        })}
                      >
                        ★
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={async () => {
                        await removeParticipant(agentId);
                        onRemoveAgent?.(agentId);
                      }}
                      className="rounded px-2 py-0.5 text-xs text-[#999] hover:bg-[#fafafa] hover:text-[#ee0000]"
                      aria-label={t('agent.participants.remove', {
                        defaultValue: `Remove ${agentId}`,
                      })}
                    >
                      ×
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {effective_mode === 'autonomous' && !coordinator_agent_id && participant_agents.length > 0 && (
          <p className="mt-3 text-xs text-[#ee0000]">
            {t('agent.participants.autonomousRequiresCoordinator', {
              defaultValue:
                'Autonomous mode requires a coordinator. Click ★ on a participant to assign.',
            })}
          </p>
        )}
        <div className="mt-3 border-t border-[rgba(0,0,0,0.08)] pt-3">
          {availableToAdd.length === 0 ? (
            <p className="text-xs text-[#999]">
              {t('agent.participants.noneAvailable', {
                defaultValue:
                  'No more agents available. Add agents to the linked workspace to see them here.',
              })}
            </p>
          ) : (
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-[#666]" htmlFor="add-participant-select">
                {t('agent.participants.addLabel', { defaultValue: 'Add agent' })}
              </label>
              <select
                id="add-participant-select"
                data-testid="add-participant-select"
                disabled={adding}
                defaultValue=""
                onChange={async (e) => {
                  const agentId = e.target.value;
                  e.target.value = '';
                  if (!agentId) return;
                  setAdding(true);
                  setAddError(null);
                  try {
                    await addParticipant({ agent_id: agentId });
                  } catch (err) {
                    setAddError(err instanceof Error ? err.message : String(err));
                  } finally {
                    setAdding(false);
                  }
                }}
                className="flex-1 rounded border border-[rgba(0,0,0,0.08)] bg-white px-2 py-1 text-xs text-[#171717] focus:outline-none focus:ring-1 focus:ring-[#0070f3]"
              >
                <option value="">
                  {t('agent.participants.addPlaceholder', { defaultValue: 'Select an agent…' })}
                </option>
                {availableToAdd.map((c) => (
                  <option key={c.agent_id} value={c.agent_id}>
                    {c.display_name ? `${c.display_name} (${c.agent_id})` : c.agent_id}
                  </option>
                ))}
              </select>
            </div>
          )}
          {addError && <p className="mt-2 text-xs text-[#ee0000]">{addError}</p>}
        </div>
      </aside>
    );
  }
);

ConversationParticipantsPanel.displayName = 'ConversationParticipantsPanel';
