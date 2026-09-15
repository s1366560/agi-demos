import type { AgentConversation } from "../types";

export type ConversationExecutionSelection = NonNullable<
  AgentConversation["execution_selection"]
>;
export type ConversationExecutionSelectionPatch =
  Partial<ConversationExecutionSelection>;
const fields = ["agent_id", "forced_skill_id", "subagent_id"] as const;

export function cloneExecutionSelectionPatch(
  value: unknown,
): ConversationExecutionSelectionPatch {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid execution selection patch");
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).some((key) => !fields.some((field) => field === key))
  ) {
    throw new Error("Invalid execution selection field");
  }
  const result: ConversationExecutionSelectionPatch = {};
  for (const field of fields) {
    if (!Object.hasOwn(record, field)) continue;
    const id = record[field];
    if (
      id !== null &&
      (typeof id !== "string" ||
        !id.length ||
        id !== id.trim() ||
        id.length > 200)
    ) {
      throw new Error("Invalid execution selection identifier");
    }
    result[field] = id as string | null;
  }
  return Object.freeze(result);
}

export function requireExecutionSelection(
  conversation: AgentConversation,
): ConversationExecutionSelection {
  const value = cloneExecutionSelectionPatch(conversation.execution_selection);
  if (!fields.every((field) => Object.hasOwn(value, field))) {
    throw new Error("Missing authoritative execution selection");
  }
  return value as ConversationExecutionSelection;
}
