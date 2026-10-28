import type {
  CloudProductEndpoint,
  CloudProductRequestMethod,
} from "./cloudProductEndpointPolicy";

export function authorizeCloudToolMediaEndpoint(
  request: Readonly<{
    method?: CloudProductRequestMethod;
    body?: unknown;
    form?: unknown;
    mutation?: unknown;
    response?: Readonly<{ kind: string; max_bytes: number }>;
  }>,
  target: URL,
): CloudProductEndpoint | null {
  const parts = target.pathname.split("/");
  if (
    request.method !== "GET" ||
    request.body !== undefined ||
    request.form !== undefined ||
    request.mutation !== undefined ||
    request.response?.kind !== "binary" ||
    !Number.isSafeInteger(request.response.max_bytes) ||
    request.response.max_bytes < 1 ||
    request.response.max_bytes > 10 * 1024 * 1024 ||
    parts.length !== 8 ||
    parts.slice(0, 5).join("/") !== "/api/v1/agent/conversations" ||
    parts[6] !== "tool-media"
  )
    return null;
  const query = [...target.searchParams.keys()];
  if (
    query.length !== 2 ||
    new Set(query).size !== 2 ||
    !query.every((key) => key === "tenant_id" || key === "project_id")
  )
    return null;
  try {
    const values = [
      parts[5],
      parts[7],
      target.searchParams.get("tenant_id"),
      target.searchParams.get("project_id"),
    ].map((value) => decodeURIComponent(value ?? ""));
    if (
      values.some(
        (value) =>
          !value ||
          value.length > 256 ||
          value !== value.trim() ||
          /[\u0000-\u0020\u007f/\\?#]/u.test(value) ||
          value === "." ||
          value === "..",
      )
    )
      return null;
    return {
      kind: "project",
      tenantId: values[2],
      projectId: values[3],
      workspaceId: null,
      conversationId: values[0],
    };
  } catch {
    return null;
  }
}
