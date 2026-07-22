import type { AgentWsEvent } from '../../types';

const AGENT_DEFINITION_EVENT_TYPES = new Set([
  'agent_definition_created',
  'agent_definition_updated',
  'agent_definition_deleted',
]);

export function latestAgentDefinitionEvent(
  events: readonly AgentWsEvent[],
): AgentWsEvent | null {
  return (
    events.find((event) => {
      const type = event.type ?? event.event_type;
      return typeof type === 'string' && AGENT_DEFINITION_EVENT_TYPES.has(type);
    }) ?? null
  );
}
