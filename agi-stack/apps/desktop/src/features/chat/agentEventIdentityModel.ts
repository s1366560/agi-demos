function objectField(
  payload: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = payload[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nestedIdentifier(
  payload: Record<string, unknown>,
  keys: readonly string[],
): string | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  for (const key of ['message', 'payload', 'data']) {
    const nested = objectField(payload, key);
    const identifier = nested ? nestedIdentifier(nested, keys) : undefined;
    if (identifier) return identifier;
  }
  return undefined;
}

/**
 * Read the client/protocol message identity without accepting an execution ID.
 * ACK handling uses this so an execution ID can never replace the optimistic
 * client message that the acknowledgement is intended to bind.
 */
export function protocolClientMessageId(
  payload: Record<string, unknown>,
): string | undefined {
  return nestedIdentifier(payload, ['message_id', 'messageId']);
}

/**
 * Read the response identity carried by streaming and terminal Agent events.
 * A response UUID remains authoritative when both identities are present;
 * replay-only events fall back to the ORM execution message identity.
 */
export function protocolStreamMessageId(
  payload: Record<string, unknown>,
): string | undefined {
  return (
    protocolClientMessageId(payload) ??
    nestedIdentifier(payload, ['execution_message_id', 'executionMessageId'])
  );
}
