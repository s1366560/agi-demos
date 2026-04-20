/**
 * Persistent badge in the chat header that identifies the agent definition
 * owning the current conversation. Distinct from the transient
 * `activeAgentNode` strip (which appears only while an agent is actively
 * running): this badge stays visible whenever the conversation has an
 * `agent_config.selected_agent_id` (or `metadata.agent_id`), so users always
 * know which agent definition is in charge of a given workspace task /
 * worker session — including when the actor is idle waiting for input.
 */

import { useEffect, useMemo } from 'react';

import { Bot } from 'lucide-react';

import { useAgentDefinitionStore } from '../../stores/agentDefinitions';

import type { Conversation } from '../../types/agent';

interface ConversationAgentBadgeProps {
  conversation: Conversation | null | undefined;
}

function readAgentId(conv: Conversation | null | undefined): string | null {
  if (!conv) return null;
  const fromConfig = conv.agent_config?.['selected_agent_id'];
  if (typeof fromConfig === 'string' && fromConfig.length > 0) {
    return fromConfig;
  }
  const fromMetadata = conv.metadata?.['agent_id'];
  if (typeof fromMetadata === 'string' && fromMetadata.length > 0) {
    return fromMetadata;
  }
  return null;
}

export function ConversationAgentBadge({
  conversation,
}: ConversationAgentBadgeProps) {
  const agentId = readAgentId(conversation);

  const definitions = useAgentDefinitionStore((state) => state.definitions);
  const listDefinitions = useAgentDefinitionStore(
    (state) => state.listDefinitions
  );

  // Lazy-load the definitions list so the badge can resolve a display
  // name even if the user navigated directly to the conversation deep
  // link without first visiting the definitions page.
  useEffect(() => {
    if (agentId && definitions.length === 0) {
      void listDefinitions().catch(() => {
        // Silent — we'll fall back to showing the id below.
      });
    }
  }, [agentId, definitions.length, listDefinitions]);

  const definition = useMemo(() => {
    if (!agentId) return null;
    return definitions.find((d) => d.id === agentId) ?? null;
  }, [agentId, definitions]);

  if (!agentId) return null;

  const label =
    definition?.display_name ||
    definition?.name ||
    `Agent ${agentId.slice(0, 8)}`;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 text-xs font-medium px-2 py-0.5"
      title={`Conversation owner: ${definition?.name ?? agentId}`}
      data-testid="conversation-agent-badge"
    >
      <Bot size={12} />
      <span className="max-w-[12rem] truncate">{label}</span>
    </span>
  );
}
