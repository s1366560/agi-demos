import type {
  CloudProductEndpoint,
  CloudProductRequestMethod,
} from "./cloudProductEndpointPolicy";

type Request = Readonly<{
  method?: CloudProductRequestMethod;
  body?: Readonly<Record<string, unknown>>;
  mutation?: unknown;
}>;

const PROVIDER_FIELDS = new Set([
  "name",
  "provider_type",
  "base_url",
  "is_active",
  "auth_method",
  "llm_model",
  "allowed_models",
  "embedding_model",
  "api_key",
  "environment_variable",
]);
const MCP_FIELDS = new Set([
  "name",
  "description",
  "server_type",
  "transport_config",
  "enabled",
  "project_id",
  "idempotency_key",
]);

/** Only the existing desktop settings HTTP projection's requests are admitted here. */
export function authorizeCloudSettingsResourceEndpoint(
  request: Request,
  target: URL,
): CloudProductEndpoint | null {
  const segments = target.pathname.split("/");
  if (segments[3] === "llm-providers")
    return providerEndpoint(request, target, segments);
  if (segments[3] === "mcp") return mcpEndpoint(request, target, segments);
  return null;
}

function providerEndpoint(
  request: Request,
  target: URL,
  segments: string[],
): CloudProductEndpoint | null {
  if (request.mutation !== undefined) {
    const mutation = request.mutation as Record<string, unknown>;
    if (
      !mutation ||
      typeof mutation !== "object" ||
      mutation.kind !== "idempotency-only" ||
      Object.keys(mutation).length !== 2 ||
      !identifier(mutation.idempotency_key) ||
      !(
        (request.method === "POST" &&
          target.pathname === "/api/v1/llm-providers/") ||
        (request.method === "DELETE" &&
          segments.length === 5 &&
          request.body?.idempotency_key === mutation.idempotency_key)
      )
    )
      return null;
  }
  const read =
    request.method === "GET" &&
    request.body === undefined &&
    request.mutation === undefined;
  const noQuery = [...target.searchParams].length === 0;
  const resource = segments[4];
  if (segments.length === 5 && resource === "") {
    if (
      read &&
      [...target.searchParams].length === 1 &&
      target.searchParams.get("include_inactive") === "true"
    )
      return endpoint();
    if (
      request.method === "POST" &&
      noQuery &&
      fields(request.body, PROVIDER_FIELDS)
    )
      return endpoint();
    return null;
  }
  if (segments.length === 5 && resource === "types")
    return read && noQuery ? endpoint() : null;
  if (segments.length === 6 && resource === "models" && identifier(segments[5]))
    return read && noQuery ? endpoint() : null;
  if (segments.length === 5 && resource === "routing-policy") {
    if (
      read &&
      [...target.searchParams].length === 2 &&
      identifier(target.searchParams.get("project_id")) &&
      identifier(target.searchParams.get("workspace_id"))
    )
      return endpoint(
        target.searchParams.get("project_id"),
        target.searchParams.get("workspace_id"),
      );
    if (
      request.method === "PUT" &&
      noQuery &&
      fields(
        request.body,
        new Set([
          "project_id",
          "workspace_id",
          "roles",
          "fallbacks",
          "expected_revision",
        ]),
      ) &&
      identifier(request.body?.project_id) &&
      identifier(request.body?.workspace_id)
    )
      return endpoint(request.body.project_id, request.body.workspace_id);
    return null;
  }
  if (segments.length === 5 && resource === "test-connection")
    return request.method === "POST" &&
      noQuery &&
      fields(request.body, PROVIDER_FIELDS)
      ? endpoint()
      : null;
  if (!identifier(resource) || !noQuery) return null;
  if (segments.length === 6 && segments[5] === "usage")
    return read ? endpoint() : null;
  if (segments.length === 6 && segments[5] === "health-check")
    return request.method === "POST" &&
      request.body !== undefined &&
      Object.keys(request.body).length === 0
      ? endpoint()
      : null;
  if (
    segments.length === 5 &&
    request.method === "PUT" &&
    fields(request.body, new Set([...PROVIDER_FIELDS, "expected_revision"])) &&
    revision(request.body?.expected_revision)
  )
    return endpoint();
  if (
    segments.length === 5 &&
    request.method === "DELETE" &&
    fields(request.body, new Set(["expected_revision", "idempotency_key"])) &&
    revision(request.body?.expected_revision) &&
    identifier(request.body?.idempotency_key)
  )
    return endpoint();
  return null;
}

function mcpEndpoint(
  request: Request,
  target: URL,
  segments: string[],
): CloudProductEndpoint | null {
  if (request.mutation !== undefined) return null;
  const read =
    request.method === "GET" &&
    request.body === undefined &&
    request.mutation === undefined;
  const noQuery = [...target.searchParams].length === 0;
  if (segments.length === 4) {
    if (
      read &&
      [...target.searchParams].length === 1 &&
      identifier(target.searchParams.get("project_id"))
    )
      return endpoint(target.searchParams.get("project_id"));
    if (
      request.method === "POST" &&
      noQuery &&
      fields(request.body, MCP_FIELDS) &&
      identifier(request.body?.project_id)
    )
      return endpoint(request.body.project_id);
    return null;
  }
  if (
    !identifier(segments[4]) ||
    !noQuery ||
    ["apps", "tools", "credentials"].includes(segments[4]!)
  )
    return null;
  const scoped = (projectId: string | null = null): CloudProductEndpoint =>
    Object.freeze({
      ...endpoint(projectId),
      mcpServerId: decodeURIComponent(segments[4]!),
    });
  if (segments.length === 5 && read) return scoped();
  if (
    segments.length === 6 &&
    segments[5] === "test" &&
    request.method === "POST" &&
    request.body === undefined
  )
    return scoped();
  if (
    segments.length === 5 &&
    request.method === "PUT" &&
    fields(request.body, MCP_FIELDS) &&
    identifier(request.body?.project_id)
  )
    return scoped(request.body.project_id);
  if (
    segments.length === 5 &&
    request.method === "DELETE" &&
    fields(request.body, new Set(["project_id", "idempotency_key"])) &&
    identifier(request.body?.project_id)
  )
    return scoped(request.body.project_id);
  return null;
}

function fields(body: Request["body"], allowed: ReadonlySet<string>): boolean {
  return (
    body !== undefined &&
    Object.keys(body).length > 0 &&
    Object.keys(body).every((key) => allowed.has(key))
  );
}
function identifier(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 256 &&
    value === value.trim() &&
    !/[\u0000-\u001f\u007f]/u.test(value)
  );
}
function revision(value: unknown): boolean {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
function endpoint(
  projectId: string | null = null,
  workspaceId: string | null = null,
): CloudProductEndpoint {
  return Object.freeze({
    kind: projectId === null ? "tenant-admin" : "project",
    tenantId: null,
    projectId,
    workspaceId,
  });
}
