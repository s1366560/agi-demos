/**
 * MentionPopover - Autocomplete dropdown for @-mentions
 *
 * Appears when the user types "@" in the chat input. Searches entities
 * and memories in the current project and lets the user pick one to
 * insert as a mention reference.
 */

import { memo, useState, useEffect, useRef, forwardRef, useImperativeHandle } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { Hash, FileText, Loader2, Workflow, Users } from 'lucide-react';

import { useSubAgentStore } from '@/stores/subagent';

import { mentionService, type MentionItem } from '@/services/mentionService';

import { useConversationParticipants } from '@/hooks/useConversationParticipants';

export interface MentionPopoverHandle {
  getSelectedItem: () => MentionItem | null;
}

interface MentionPopoverProps {
  query: string;
  projectId: string;
  visible: boolean;
  onSelect: (item: MentionItem) => void;
  onClose: () => void;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
  conversationId?: string | null;
}

export const MentionPopover = memo(
  forwardRef<MentionPopoverHandle, MentionPopoverProps>(
    (
      {
        query,
        projectId,
        visible,
        onSelect,
        selectedIndex,
        onSelectedIndexChange,
        conversationId,
      },
      ref
    ) => {
      const { t } = useTranslation();
      const [items, setItems] = useState<MentionItem[]>([]);
      const [loading, setLoading] = useState(false);
      const listRef = useRef<HTMLDivElement>(null);
      const { subagents, listSubAgents } = useSubAgentStore();
      const { roster } = useConversationParticipants(conversationId ?? null);

      // Ensure subagents are loaded
      useEffect(() => {
        if (subagents.length === 0) {
          listSubAgents({ enabled_only: true }).catch((err: unknown) => {
            void message.error(
              err instanceof Error ? err.message : 'Failed to load sub-agents'
            );
            console.error('MentionPopover: listSubAgents failed', err);
          });
        }
      }, [subagents.length, listSubAgents]);

      useImperativeHandle(ref, () => ({
        getSelectedItem: () => items[selectedIndex] ?? null,
      }));

      // Search on query change (debounced)
      useEffect(() => {
        if (!visible || !query || !projectId) {
          setItems([]);
          onSelectedIndexChange(0);
          return;
        }

        const timer = setTimeout(async () => {
          setLoading(true);
          try {
            // Parallel fetch: mention search + subagent filtering
            const [mentionResults, _] = await Promise.all([
              mentionService.search(query, projectId).catch((err: unknown) => {
                console.error('MentionPopover: search failed', err);
                return [];
              }),
              Promise.resolve(), // Subagents are already in store
            ]);

            // Filter subagents locally
            const subagentResults: MentionItem[] = subagents
              .filter(
                (sa) =>
                  sa.name.toLowerCase().includes(query.toLowerCase()) ||
                  sa.display_name.toLowerCase().includes(query.toLowerCase())
              )
              .map((sa) => ({
                id: sa.id,
                name: sa.name, // Use system name for mention ID
                type: 'subagent',
                summary: sa.trigger.description,
                entityType: 'SubAgent',
              }));

            // Filter conversation participants locally (Track B)
            const participantResults: MentionItem[] = (roster?.participant_agents ?? [])
              .filter((agentId) => agentId.toLowerCase().includes(query.toLowerCase()))
              .map((agentId) => ({
                id: agentId,
                name: agentId,
                type: 'participant',
                entityType: 'Participant',
                ...(agentId === roster?.coordinator_agent_id
                  ? { summary: t('agent.mentions.coordinator', 'Coordinator') }
                  : {}),
              }));

            // Combine results: participants > SubAgents > entities/memories.
            setItems([...participantResults, ...subagentResults, ...mentionResults]);
            onSelectedIndexChange(0);
          } catch (err: unknown) {
            void message.error(
              err instanceof Error ? err.message : 'Failed to search mentions'
            );
            console.error('MentionPopover: search failed', err);
            setItems([]);
            onSelectedIndexChange(0);
          } finally {
            setLoading(false);
          }
        }, 200);

        return () => {
          clearTimeout(timer);
        };
      }, [query, projectId, visible, onSelectedIndexChange, subagents, roster, t]);

      // Scroll selected item into view
      useEffect(() => {
        if (!listRef.current) return;
        const el = listRef.current.children[selectedIndex] as HTMLElement | undefined;
        el?.scrollIntoView({ block: 'nearest' });
      }, [selectedIndex]);

      if (!visible) return null;

      const typeIcon = (item: MentionItem) => {
        if (item.type === 'participant') return <Users size={14} className="text-emerald-500" />;
        if (item.type === 'subagent') return <Workflow size={14} className="text-purple-500" />;
        if (item.type === 'entity') return <Hash size={14} className="text-primary" />;
        return <FileText size={14} className="text-slate-500" />;
      };

      return (
        <div className="absolute bottom-full left-0 mb-2 z-50 bg-white dark:bg-slate-800 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-700 w-72 max-h-64 overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-700">
            <span className="text-xs text-slate-400">
              {t('agent.mentions.title', 'Mention entities or memories')}
            </span>
          </div>
          <div ref={listRef} className="overflow-y-auto max-h-48">
            {loading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2
                  size={16}
                  className="animate-spin motion-reduce:animate-none text-slate-400"
                />
              </div>
            ) : items.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-slate-400">
                {query
                  ? t('agent.mentions.noResults', 'No results found')
                  : t('agent.mentions.typeToSearch', 'Type to search...')}
              </div>
            ) : (
              items.map((item, idx) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    onSelect(item);
                  }}
                  className={`w-full text-left px-3 py-2 flex items-start gap-2 transition-colors ${
                    idx === selectedIndex
                      ? 'bg-primary/10 text-primary'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                  }`}
                >
                  <div className="mt-0.5 flex-shrink-0">{typeIcon(item)}</div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                      {item.name}
                    </div>
                    {item.summary && (
                      <div className="text-xs text-slate-400 truncate mt-0.5">{item.summary}</div>
                    )}
                     {item.entityType && (
                       <span className="text-2xs bg-slate-100 dark:bg-slate-600 text-slate-500 dark:text-slate-300 px-1.5 rounded-full mt-0.5 inline-block">
                         {item.entityType}
                       </span>
                     )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      );
    }
  )
);
MentionPopover.displayName = 'MentionPopover';
