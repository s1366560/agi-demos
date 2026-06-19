const AGENT_TOOL_NAMES = new Set([
  'agent_spawn',
  'agent_stop',
  'agent_send',
  'agent_list',
  'agent_sessions',
  'agent_history',
]);

export function isAgentTool(toolName: string): boolean {
  return AGENT_TOOL_NAMES.has(toolName);
}
