export type AgentPermissionMode = "ask" | "auto_edit" | "full_access";

export const PERMISSION_MODES: readonly AgentPermissionMode[] = [
  "ask",
  "auto_edit",
  "full_access",
] as const;

export type AgentThinkingLevel = "default" | "low" | "medium" | "high";

export const THINKING_LEVELS: readonly AgentThinkingLevel[] = [
  "default",
  "low",
  "medium",
  "high",
] as const;
