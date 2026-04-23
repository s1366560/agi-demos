/**
 * ConversationRosterSection — blackboard Members-tab sub-section.
 *
 * Lists all conversations in the current workspace and embeds
 * ``ConversationParticipantsPanel`` for each expanded conversation,
 * so operators can manage roster + coordinator + focused fields from
 * the blackboard itself — without needing to bounce to the AgentWorkspace
 * right-rail drawer.
 *
 * Deep-link support: ``?conversationId=<id>`` opens that conversation
 * expanded on mount.
 */

import { memo, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { ConversationModePanel } from '@/components/agent/ConversationModePanel';
import { ConversationParticipantsPanel } from '@/components/agent/ConversationParticipantsPanel';
import { HITLCenterPanel } from '@/components/agent/HITLCenterPanel';
import { useWorkspaceConversations } from '@/hooks/useWorkspaceConversations';

export interface ConversationRosterSectionProps {
  projectId: string;
  workspaceId: string;
  className?: string;
}

const modeBadge =
  'inline-flex h-[18px] items-center rounded-full border border-[rgba(0,0,0,0.08)] bg-[#ebebeb] px-2 text-[11px] font-medium text-[#171717]';

export const ConversationRosterSection = memo<ConversationRosterSectionProps>(
  ({ projectId, workspaceId, className }) => {
    const { t } = useTranslation();
    const { conversations, loading, error, refresh } = useWorkspaceConversations(
      projectId,
      workspaceId
    );
    const [searchParams] = useSearchParams();
    const deepLinkConversationId = searchParams.get('conversationId');
    const [expanded, setExpanded] = useState<Set<string>>(() =>
      deepLinkConversationId ? new Set([deepLinkConversationId]) : new Set()
    );

    const sorted = useMemo(
      () =>
        [...conversations].sort((a, b) => {
          const ua = a.updated_at ?? a.created_at ?? '';
          const ub = b.updated_at ?? b.created_at ?? '';
          return ub.localeCompare(ua);
        }),
      [conversations]
    );

    const toggle = (id: string) =>
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });

    return (
      <section
        data-testid="conversation-roster-section"
        aria-label="conversation rosters"
        className={className ?? 'mt-6'}
      >
        <header className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.rosters.title', { defaultValue: 'Conversation Rosters' })}
          </h3>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded px-2 py-0.5 text-xs text-[#666] hover:bg-[#fafafa] hover:text-[#0070f3]"
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </button>
        </header>

        {loading && (
          <p className="text-xs text-[#999]">
            {t('blackboard.rosters.loading', { defaultValue: 'Loading conversations…' })}
          </p>
        )}
        {error && (
          <p className="text-xs text-[#ee0000]">
            {t('blackboard.rosters.error', { defaultValue: 'Failed to load conversations.' })}
          </p>
        )}
        {!loading && !error && sorted.length === 0 && (
          <p className="text-xs text-[#999]">
            {t('blackboard.rosters.empty', {
              defaultValue:
                'No conversations linked to this workspace yet. Start a chat from Agent Workspace with this workspace attached.',
            })}
          </p>
        )}

        <ul className="space-y-2">
          {sorted.map((c) => {
            const isOpen = expanded.has(c.id);
            return (
              <li
                key={c.id}
                className="rounded-md border border-[rgba(0,0,0,0.08)] bg-white"
                data-testid={`conversation-roster-item-${c.id}`}
              >
                <button
                  type="button"
                  onClick={() => toggle(c.id)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="text-xs text-[#999]"
                    >
                      {isOpen ? '▾' : '▸'}
                    </span>
                    <span className="truncate text-sm font-medium text-[#171717]">
                      {c.title || c.id}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {c.conversation_mode && (
                      <span className={modeBadge}>
                        {c.conversation_mode.replace(/_/g, ' ')}
                      </span>
                    )}
                  </span>
                </button>
                {isOpen && (
                  <div className="space-y-4 border-t border-[rgba(0,0,0,0.08)] px-3 py-3">
                    <section data-testid={`roster-mode-${c.id}`}>
                      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#666]">
                        {t('blackboard.rosters.section.mode', { defaultValue: 'Mode' })}
                      </div>
                      <ConversationModePanel conversationId={c.id} projectId={projectId} />
                    </section>
                    <section data-testid={`roster-participants-${c.id}`}>
                      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#666]">
                        {t('blackboard.rosters.section.participants', {
                          defaultValue: 'Participants',
                        })}
                      </div>
                      <ConversationParticipantsPanel conversationId={c.id} />
                    </section>
                    <section data-testid={`roster-hitl-${c.id}`}>
                      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#666]">
                        {t('blackboard.rosters.section.hitl', { defaultValue: 'HITL Center' })}
                      </div>
                      <HITLCenterPanel conversationId={c.id} />
                    </section>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    );
  }
);

ConversationRosterSection.displayName = 'ConversationRosterSection';
