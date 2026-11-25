// Matches the prefix injected by handleSend for forced SubAgent delegation;
// stripped back out when a user message is edited or retried.
const SUBAGENT_DELEGATION_PREFIX_RE =
  /^\[System Instruction: Delegate this task strictly to SubAgent "[^"]+"\]\n/;

export function stripSubAgentDelegationPrefix(content: string): string {
  const match = content.match(SUBAGENT_DELEGATION_PREFIX_RE);
  return match ? content.slice(match[0].length) : content;
}

export function quoteMessage(raw: string): string {
      const trimmed = raw.trim();
      if (!trimmed) return '';
      const excerpt = trimmed.length > 500 ? `${trimmed.slice(0, 500)}…` : trimmed;
      const quoted = excerpt
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n');
      return `${quoted}\n\n`;
}
