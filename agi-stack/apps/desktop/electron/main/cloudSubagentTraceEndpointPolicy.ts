import type {
  CloudProductEndpoint,
  CloudProductRequestMethod,
} from "./cloudProductEndpointPolicy";

export function authorizeCloudSubagentTraceEndpoint(
  request: Readonly<{
    method?: CloudProductRequestMethod;
    body?: unknown;
    mutation?: unknown;
  }>,
  target: URL,
): CloudProductEndpoint | null {
  if (
    request.method !== "GET" ||
    request.body !== undefined ||
    request.mutation !== undefined ||
    target.search
  )
    return null;
  const parts = target.pathname.split("/");
  if (
    parts.length !== 7 ||
    parts.slice(0, 6).join("/") !== "/api/v1/agent/trace/runs"
  )
    return null;
  try {
    const id = decodeURIComponent(parts[6]);
    if (
      !id ||
      id !== id.trim() ||
      /[\u0000-\u0020\u007f/\\?#]/u.test(id) ||
      [".", ".."].includes(id)
    )
      return null;
    return {
      kind: "project",
      tenantId: null,
      projectId: null,
      workspaceId: null,
      conversationId: id,
    };
  } catch {
    return null;
  }
}
