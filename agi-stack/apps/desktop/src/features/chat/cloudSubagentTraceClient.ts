import { DesktopApiError } from "../../api/client";
import { desktopApiFetch } from "../../api/cloudRequestBroker";
import type {
  AgentConversation,
  AgentTimelineItem,
  DesktopRuntimeConfig,
} from "../../types";
import { projectCloudSubagentTrace } from "./cloudSubagentTraceModel";

export async function loadCloudSubagentTrace(
  config: DesktopRuntimeConfig,
  conversation: Pick<
    AgentConversation,
    "id" | "tenant_id" | "project_id" | "workspace_id"
  >,
  signal?: AbortSignal,
): Promise<AgentTimelineItem[]> {
  if (
    config.mode !== "cloud" ||
    [conversation.id, conversation.tenant_id, conversation.project_id].some(
      (value) => typeof value !== 'string' || !value || value !== value.trim(),
    ) ||
    conversation.tenant_id !== config.tenantId ||
    conversation.project_id !== config.projectId ||
    (conversation.workspace_id ?? null) !== (config.workspaceId || null)
  ) {
    throw new Error("cloud_subagent_trace_scope_invalid");
  }
  const observedAt = Date.now();
  const response = await desktopApiFetch(
    config,
    `/api/v1/agent/trace/runs/${encodeURIComponent(conversation.id)}`,
    { signal },
  );
  const body: unknown = await response.json();
  if (!response.ok)
    throw new DesktopApiError(
      "cloud_subagent_trace_request_failed",
      response.status,
      body,
    );
  return projectCloudSubagentTrace(body, conversation.id, observedAt);
}
