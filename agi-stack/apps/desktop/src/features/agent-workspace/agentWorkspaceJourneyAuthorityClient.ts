import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from "../../api/client";
import type { DesktopRuntimeConfig } from "../../types";

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

export const AGENT_WORKSPACE_JOURNEY_IDS = Object.freeze([
  "bootstrap-and-scope",
  "conversation-lifecycle",
  "stream-and-run-control",
  "hitl-and-a2ui",
  "roster-and-subagents",
  "work-review",
  "content-and-export",
  "local-runtime",
] as const);

export type AgentWorkspaceJourneyId =
  (typeof AGENT_WORKSPACE_JOURNEY_IDS)[number];

export type AgentWorkspaceJourneyObservation = Readonly<{
  availability: "degraded" | "unavailable";
  reasonCode: string;
  observedActions: readonly string[];
}>;

export type AgentWorkspaceJourneySnapshot = Readonly<{
  authority: "cloud" | "local";
  authoritySource: "cloud_service" | "sidecar";
  provenance: "observed";
  authorityRevision: number | null;
  scope: Readonly<{
    tenantId: string;
    projectId: string;
    workspaceId: string | null;
  }>;
  journeys: Readonly<
    Record<AgentWorkspaceJourneyId, AgentWorkspaceJourneyObservation>
  >;
}>;

export type AgentWorkspaceJourneyAuthorityClientOptions = Readonly<{
  fetchImpl?: typeof fetch;
}>;

export interface AgentWorkspaceJourneyAuthorityClient {
  probe(signal?: AbortSignal): Promise<AgentWorkspaceJourneySnapshot>;
}

export function createAgentWorkspaceJourneyAuthorityClient(
  config: DesktopRuntimeConfig,
  options: AgentWorkspaceJourneyAuthorityClientOptions = {},
): AgentWorkspaceJourneyAuthorityClient {
  const runtimeConfig = Object.freeze({ ...config });
  const credential = desktopApiCredential(runtimeConfig);
  const launchCapability = desktopLaunchCapability(runtimeConfig);
  const tenantId = identifier(runtimeConfig.tenantId);
  const projectId = identifier(runtimeConfig.projectId);
  const workspaceId = identifier(runtimeConfig.workspaceId);
  if (!credential)
    throw contractError("agent_workspace_journey_trusted_session_required");
  if (!tenantId || !projectId) {
    throw contractError("agent_workspace_journey_scope_unavailable");
  }
  if (runtimeConfig.mode === "local" && !launchCapability) {
    throw contractError("agent_workspace_journey_launch_capability_required");
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  const scope = Object.freeze({ tenantId, projectId, workspaceId });
  const request = createJsonRequester(
    runtimeConfig,
    credential,
    launchCapability,
    fetchImpl,
  );

  return Object.freeze({
    async probe(signal?: AbortSignal) {
      const actions = emptyActions();
      try {
        const user = await request("/api/v1/auth/me", signal);
        const userId = activeUserId(user);
        if (!userId)
          throw contractError("agent_workspace_journey_session_invalid");
        actions["bootstrap-and-scope"].push("restore-session");

        const workspaceContext = await request(
          "/api/v1/workspace-context",
          signal,
        );
        if (!validWorkspaceContext(workspaceContext, scope)) {
          throw contractError("agent_workspace_journey_scope_conflict");
        }
        const authorityRevision = workspaceContextRevision(workspaceContext);
        if (authorityRevision === null) {
          throw contractError(
            "agent_workspace_journey_authority_revision_invalid",
          );
        }

        if (runtimeConfig.mode === "cloud") {
          const features = await optionalRequest(
            request,
            "/api/v1/system/features",
            signal,
          );
          if (Array.isArray(features)) {
            actions["bootstrap-and-scope"].push("load-system-features");
          }
        }
        const tenants = await optionalRequest(
          request,
          runtimeConfig.mode === "local" ? "/api/v1/tenants" : "/api/v1/tenants/",
          signal,
        );
        if (hasScopedItem(tenants, "tenants", tenantId)) {
          actions["bootstrap-and-scope"].push("load-tenants");
        }
        const projects = await optionalRequest(
          request,
          runtimeConfig.mode === "local" ? "/api/v1/projects" : "/api/v1/projects/",
          signal,
        );
        if (hasScopedProject(projects, tenantId, projectId)) {
          actions["bootstrap-and-scope"].push("resolve-conversation");
        }

        const conversationParameters = new URLSearchParams({
          project_id: projectId,
          status: "active",
          limit: "1",
          offset: "0",
        });
        if (workspaceId) conversationParameters.set("workspace_id", workspaceId);
        const conversationPage = await optionalRequest(
          request,
          `/api/v1/agent/conversations?${conversationParameters.toString()}`,
          signal,
        );
        if (
          conversationPage !== null &&
          !validConversationPage(conversationPage, scope, userId)
        ) {
          throw contractError("agent_workspace_journey_scope_conflict");
        }
        const conversation = firstConversation(conversationPage, scope, userId);
        if (conversationPage !== null) {
          actions["conversation-lifecycle"].push("list-conversations");
        }
        if (conversation) {
          await probeConversationJourneys(
            request,
            runtimeConfig.mode,
            scope,
            conversation,
            actions,
            signal,
          );
        }

        await probeProjectJourneys(
          request,
          runtimeConfig.mode,
          projectId,
          actions,
          signal,
        );
        await probeContentJourneys(
          request,
          runtimeConfig.mode,
          projectId,
          conversation,
          actions,
          signal,
        );
        await probeRuntimeJourney(
          request,
          runtimeConfig.mode,
          projectId,
          actions,
          signal,
        );
        const finalWorkspaceContext = await request(
          "/api/v1/workspace-context",
          signal,
        );
        if (!validWorkspaceContext(finalWorkspaceContext, scope)) {
          throw contractError("agent_workspace_journey_scope_conflict");
        }
        const finalAuthorityRevision = workspaceContextRevision(
          finalWorkspaceContext,
        );
        if (finalAuthorityRevision === null) {
          throw contractError(
            "agent_workspace_journey_authority_revision_invalid",
          );
        }
        if (finalAuthorityRevision !== authorityRevision) {
          throw contractError("agent_workspace_journey_authority_stale");
        }
        return snapshot(runtimeConfig.mode, scope, authorityRevision, actions);
      } catch (error) {
        if (signal?.aborted) throw error;
        const reasonCode =
          error instanceof DesktopApiError
            ? error.message
            : "agent_workspace_journey_unavailable";
        return unavailableSnapshot(runtimeConfig.mode, scope, reasonCode);
      }
    },
  });
}

type JourneyActions = Record<AgentWorkspaceJourneyId, string[]>;
type JsonRequester = (path: string, signal?: AbortSignal) => Promise<unknown>;
type Scope = Readonly<{
  tenantId: string;
  projectId: string;
  workspaceId: string | null;
}>;
type Conversation = Readonly<{
  id: string;
  userId: string;
  workspaceId: string | null;
}>;
type RunReference = Readonly<{ id: string; revision: number }>;

function createJsonRequester(
  config: DesktopRuntimeConfig,
  credential: string,
  launchCapability: string | null,
  fetchImpl: typeof fetch,
): JsonRequester {
  return async (path, signal) => {
    const headers = new Headers({
      Accept: "application/json",
      Authorization: `Bearer ${credential}`,
    });
    if (config.mode === "local" && launchCapability) {
      headers.set("X-Agistack-Launch", launchCapability);
    }
    const response = await fetchImpl(absoluteUrl(config.apiBaseUrl, path), {
      method: "GET",
      headers,
      credentials: "omit",
      signal,
    });
    const payload = await responsePayload(response);
    if (!response.ok) {
      throw new DesktopApiError(
        `agent_workspace_journey_http_${response.status}`,
        response.status,
        payload,
      );
    }
    return payload;
  };
}

async function optionalRequest(
  request: JsonRequester,
  path: string,
  signal?: AbortSignal,
): Promise<unknown | null> {
  try {
    return await request(path, signal);
  } catch (error) {
    if (signal?.aborted) throw error;
    return null;
  }
}

async function probeConversationJourneys(
  request: JsonRequester,
  mode: "cloud" | "local",
  scope: Scope,
  conversation: Conversation,
  actions: JourneyActions,
  signal?: AbortSignal,
): Promise<void> {
  const conversationPath = `/api/v1/agent/conversations/${encodeURIComponent(conversation.id)}`;
  let localSession: unknown = null;
  let activeRun: RunReference | null = null;
  let latestRun: RunReference | null = null;
  if (mode === "cloud") {
    const detail = await optionalRequest(
      request,
      `${conversationPath}?project_id=${encodeURIComponent(scope.projectId)}`,
      signal,
    );
    if (validConversation(detail, scope, conversation)) {
      actions["conversation-lifecycle"].push("get-conversation");
    }
  } else {
    const sessionParameters = new URLSearchParams({
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
    });
    if (conversation.workspaceId) {
      sessionParameters.set("workspace_id", conversation.workspaceId);
    }
    localSession = await optionalRequest(
      request,
      `${conversationPath}/session?${sessionParameters.toString()}`,
      signal,
    );
    if (validSessionProjection(localSession, scope, conversation)) {
      actions["conversation-lifecycle"].push("get-conversation");
      activeRun = sessionRunReference(
        localSession,
        "current_run",
        mode,
        scope,
        conversation.id,
      );
      latestRun = firstSessionRunReference(
        localSession,
        mode,
        scope,
        conversation.id,
      );
      if (activeRun) {
        actions["stream-and-run-control"].push("get-active-run");
      }
      if (latestRun) {
        actions["stream-and-run-control"].push("get-latest-run");
      }
      if (hasSessionPendingSurface(localSession, conversation.id)) {
        actions["hitl-and-a2ui"].push("render-surface");
      }
      if (hasArrayField(localSession, "artifact_versions")) {
        actions["content-and-export"].push("list-artifacts");
      }
    }
  }
  const historyPath = `${conversationPath}/messages?project_id=${encodeURIComponent(scope.projectId)}`;
  const history = await optionalRequest(request, historyPath, signal);
  if (validHistory(history, conversation.id)) {
    actions["conversation-lifecycle"].push("load-history");
  }
  if (mode === "cloud") {
    const active = await optionalRequest(
      request,
      `${conversationPath}/active-run`,
      signal,
    );
    activeRun = runReferenceFromEnvelope(
      active,
      "active_run",
      mode,
      scope,
      conversation.id,
    );
    if (activeRun) {
      actions["stream-and-run-control"].push("get-active-run");
    }
    const latest = await optionalRequest(
      request,
      `${conversationPath}/latest-run`,
      signal,
    );
    latestRun = runReferenceFromEnvelope(
      latest,
      "latest_run",
      mode,
      scope,
      conversation.id,
    );
    if (latestRun) {
      actions["stream-and-run-control"].push("get-latest-run");
    }
  }
  const runs =
    mode === "local"
      ? await optionalRequest(request, `${conversationPath}/runs`, signal)
      : null;
  const run =
    firstRun(runs, mode, scope, conversation.id) ?? latestRun ?? activeRun;
  if (run) {
    const inputs = await optionalRequest(
      request,
      `/api/v1/agent/runs/${encodeURIComponent(run.id)}/inputs`,
      signal,
    );
    if (validRunInputs(inputs, run)) {
      actions["stream-and-run-control"].push("list-run-inputs");
    }
  }
  if (mode === "cloud") {
    const pending = await optionalRequest(
      request,
      `/api/v1/agent/hitl/conversations/${encodeURIComponent(conversation.id)}/pending`,
      signal,
    );
    if (hasPendingSurface(pending, conversation.id)) {
      actions["hitl-and-a2ui"].push("render-surface");
    }
    const participants = await optionalRequest(
      request,
      `${conversationPath}/participants`,
      signal,
    );
    if (validRoster(participants, conversation.id)) {
      actions["roster-and-subagents"].push("list-participants");
    }
  } else if (
    hasHistorySurface(history, conversation.id) &&
    !actions["hitl-and-a2ui"].includes("render-surface")
  ) {
    actions["hitl-and-a2ui"].push("render-surface");
  }
  const subagents = await optionalRequest(
    request,
    `/api/v1/subagents/?tenant_id=${encodeURIComponent(scope.tenantId)}`,
    signal,
  );
  if (hasArrayField(subagents, mode === "local" ? "items" : "subagents")) {
    actions["roster-and-subagents"].push("list-subagents");
  }
  if (run) {
    if (mode === "cloud") {
      const summary = await optionalRequest(
        request,
        `/api/v1/agent/runs/${encodeURIComponent(run.id)}/summary`,
        signal,
      );
      if (validSummary(summary, run.id, scope, conversation.id)) {
        actions["work-review"].push(
          "view-run-summary",
          "view-usage",
          "view-cost",
        );
      }
    }
    if (mode === "local" || run.revision > 0) {
      const changeParameters = new URLSearchParams({
        expected_revision: String(run.revision),
      });
      if (mode === "cloud") changeParameters.set("scope", "run");
      const changes = await optionalRequest(
        request,
        `/api/v1/agent/runs/${encodeURIComponent(run.id)}/changes?${changeParameters.toString()}`,
        signal,
      );
      if (validChanges(changes, run.id, conversation.id)) {
        actions["work-review"].push("view-run-changes");
      }
    }
  }
}

async function probeProjectJourneys(
  request: JsonRequester,
  mode: "cloud" | "local",
  projectId: string,
  actions: JourneyActions,
  signal?: AbortSignal,
): Promise<void> {
  const encodedProject = encodeURIComponent(projectId);
  const myWork = await optionalRequest(
    request,
    `/api/v1/projects/${encodedProject}/my-work`,
    signal,
  );
  if (
    recordField(myWork, "project_id") === projectId &&
    hasArrayField(myWork, "items")
  ) {
    actions["work-review"].push("list-my-work");
  }
  const readState = await optionalRequest(
    request,
    `/api/v1/projects/${encodedProject}/activity/read-state`,
    signal,
  );
  if (
    recordField(readState, "project_id") === projectId &&
    hasArrayField(readState, "entries")
  ) {
    actions["work-review"].push("read-activity");
  }
  void mode;
}

async function probeContentJourneys(
  request: JsonRequester,
  mode: "cloud" | "local",
  projectId: string,
  conversation: Conversation | null,
  actions: JourneyActions,
  signal?: AbortSignal,
): Promise<void> {
  if (mode !== "cloud") return;
  if (conversation) {
    const attachments = await optionalRequest(
      request,
      `/api/v1/attachments?conversation_id=${encodeURIComponent(conversation.id)}`,
      signal,
    );
    if (hasArrayField(attachments, "attachments")) {
      actions["content-and-export"].push("list-attachments");
    }
  }
  const artifacts = await optionalRequest(
    request,
    `/api/v1/artifacts?project_id=${encodeURIComponent(projectId)}&limit=100`,
    signal,
  );
  if (hasArrayField(artifacts, "artifacts")) {
    actions["content-and-export"].push("list-artifacts");
  }
}

async function probeRuntimeJourney(
  request: JsonRequester,
  mode: "cloud" | "local",
  projectId: string,
  actions: JourneyActions,
  signal?: AbortSignal,
): Promise<void> {
  const encodedProject = encodeURIComponent(projectId);
  const capabilities = await optionalRequest(
    request,
    `/api/v1/projects/${encodedProject}/sandbox/capabilities`,
    signal,
  );
  const sandbox = await optionalRequest(
    request,
    `/api/v1/projects/${encodedProject}/sandbox`,
    signal,
  );
  if (
    !isRecord(sandbox) ||
    sandbox.status !== "running" ||
    sandbox.is_healthy !== true
  )
    return;
  const terminalAvailable =
    nestedField(capabilities, "terminal_interactive", "availability") ===
    "available";
  if (
    terminalAvailable &&
    typeof sandbox.terminal_url === "string" &&
    sandbox.terminal_url
  ) {
    actions["local-runtime"].push("open-terminal", "connect-terminal");
  }
  const desktopAvailable =
    nestedField(capabilities, "kasm_vnc", "availability") === "available";
  if (
    typeof sandbox.desktop_url === "string" &&
    sandbox.desktop_url &&
    (mode === "cloud" || desktopAvailable)
  ) {
    actions["local-runtime"].push("open-remote-desktop");
  }
}

function snapshot(
  mode: "cloud" | "local",
  scope: Scope,
  authorityRevision: number,
  actions: JourneyActions,
): AgentWorkspaceJourneySnapshot {
  const journeys = Object.fromEntries(
    AGENT_WORKSPACE_JOURNEY_IDS.map((journeyId) => {
      const observedActions = Object.freeze(
        orderActions(journeyId, actions[journeyId]),
      );
      const suffix = observedActions.length > 0 ? "partial" : "empty";
      const availability =
        observedActions.length > 0 ? "degraded" : "unavailable";
      return [
        journeyId,
        Object.freeze({
          availability,
          reasonCode: `agent_workspace_journey_${journeyId.replaceAll("-", "_")}_${suffix}`,
          observedActions,
        }),
      ];
    }),
  ) as Record<AgentWorkspaceJourneyId, AgentWorkspaceJourneyObservation>;
  return Object.freeze({
    authority: mode,
    authoritySource: mode === "local" ? "sidecar" : "cloud_service",
    provenance: "observed",
    authorityRevision,
    scope,
    journeys: Object.freeze(journeys),
  });
}

function orderActions(
  journeyId: AgentWorkspaceJourneyId,
  actions: readonly string[],
): string[] {
  const unique = [...new Set(actions)];
  if (journeyId !== "work-review") return unique;
  const order = [
    "list-my-work",
    "read-activity",
    "view-run-summary",
    "view-run-changes",
    "view-usage",
    "view-cost",
  ];
  return unique.sort(
    (left, right) => order.indexOf(left) - order.indexOf(right),
  );
}

function unavailableSnapshot(
  mode: "cloud" | "local",
  scope: Scope,
  reasonCode: string,
): AgentWorkspaceJourneySnapshot {
  const unavailable = (): AgentWorkspaceJourneyObservation =>
    Object.freeze({
      availability: "unavailable",
      reasonCode,
      observedActions: Object.freeze([]),
    });
  const journeys: Record<
    AgentWorkspaceJourneyId,
    AgentWorkspaceJourneyObservation
  > = {
    "bootstrap-and-scope": unavailable(),
    "conversation-lifecycle": unavailable(),
    "stream-and-run-control": unavailable(),
    "hitl-and-a2ui": unavailable(),
    "roster-and-subagents": unavailable(),
    "work-review": unavailable(),
    "content-and-export": unavailable(),
    "local-runtime": unavailable(),
  };
  return Object.freeze({
    authority: mode,
    authoritySource: mode === "local" ? "sidecar" : "cloud_service",
    provenance: "observed",
    authorityRevision: null,
    scope,
    journeys: Object.freeze(journeys),
  });
}

function emptyActions(): JourneyActions {
  return {
    "bootstrap-and-scope": [],
    "conversation-lifecycle": [],
    "stream-and-run-control": [],
    "hitl-and-a2ui": [],
    "roster-and-subagents": [],
    "work-review": [],
    "content-and-export": [],
    "local-runtime": [],
  };
}

async function responsePayload(response: Response): Promise<unknown> {
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength >= MAX_RESPONSE_BYTES) {
    throw contractError("agent_workspace_journey_response_too_large");
  }
  if (
    !(response.headers.get("content-type") ?? "")
      .toLowerCase()
      .includes("application/json")
  ) {
    throw contractError("agent_workspace_journey_response_not_json");
  }
  const text = response.body
    ? await readBoundedResponseText(response.body)
    : "";
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    throw contractError("agent_workspace_journey_response_invalid_json");
  }
}

async function readBoundedResponseText(
  body: ReadableStream<Uint8Array>,
): Promise<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let byteLength = 0;
  let text = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      byteLength += chunk.value.byteLength;
      if (byteLength >= MAX_RESPONSE_BYTES) {
        try {
          await reader.cancel();
        } catch {
          // Preserve the stable size reason even when transport cancellation fails.
        }
        throw contractError("agent_workspace_journey_response_too_large");
      }
      text += decoder.decode(chunk.value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

function activeUserId(value: unknown): string | null {
  if (!isRecord(value) || value.is_active !== true) return null;
  return identifier(value.user_id);
}

function validWorkspaceContext(value: unknown, scope: Scope): boolean {
  if (!isRecord(value) || !isRecord(value.context)) return false;
  return (
    value.context.tenant_id === scope.tenantId &&
    value.context.project_id === scope.projectId
  );
}

function workspaceContextRevision(value: unknown): number | null {
  if (!isRecord(value) || !isRecord(value.context)) return null;
  return nonNegativeInteger(value.context.revision)
    ? value.context.revision
    : null;
}

function validConversationPage(
  value: unknown,
  scope: Scope,
  userId: string,
): boolean {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    value.items.length > 1 ||
    !nonNegativeInteger(value.total) ||
    value.total < value.items.length ||
    value.offset !== 0 ||
    value.limit !== 1 ||
    typeof value.has_more !== "boolean"
  ) {
    return false;
  }
  return value.items.every(
    (item) =>
      isRecord(item) &&
      identifier(item.id) !== null &&
      item.user_id === userId &&
      item.tenant_id === scope.tenantId &&
      item.project_id === scope.projectId &&
      matchesWorkspaceScope(item.workspace_id, scope.workspaceId),
  );
}

function firstConversation(
  value: unknown,
  scope: Scope,
  userId: string,
): Conversation | null {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    !isRecord(value.items[0])
  )
    return null;
  const item = value.items[0];
  const id = identifier(item.id);
  const workspaceId = optionalIdentifier(item.workspace_id);
  return id &&
    workspaceId !== undefined &&
    item.user_id === userId &&
    item.tenant_id === scope.tenantId &&
    item.project_id === scope.projectId &&
    matchesWorkspaceScope(workspaceId, scope.workspaceId)
    ? Object.freeze({ id, userId, workspaceId })
    : null;
}

function validConversation(
  value: unknown,
  scope: Scope,
  conversation: Conversation,
): boolean {
  return (
    isRecord(value) &&
    value.id === conversation.id &&
    value.user_id === conversation.userId &&
    value.tenant_id === scope.tenantId &&
    value.project_id === scope.projectId &&
    value.workspace_id === conversation.workspaceId
  );
}

function validHistory(value: unknown, conversationId: string): boolean {
  return (
    isRecord(value) &&
    (value.conversationId === conversationId ||
      value.conversation_id === conversationId) &&
    Array.isArray(value.timeline)
  );
}

function hasHistorySurface(value: unknown, conversationId: string): boolean {
  return (
    isRecord(value) &&
    validHistory(value, conversationId) &&
    Array.isArray(value.approval_requests) &&
    value.approval_requests.length > 0
  );
}

function runReferenceFromEnvelope(
  value: unknown,
  key: string,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): RunReference | null {
  return isRecord(value)
    ? runReference(value[key], mode, scope, conversationId)
    : null;
}

function validRun(
  value: unknown,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): boolean {
  return (
    isRecord(value) &&
    identifier(value.id) !== null &&
    nonNegativeInteger(value.revision) &&
    (mode === "local" || value.tenant_id === scope.tenantId) &&
    value.project_id === scope.projectId &&
    value.conversation_id === conversationId
  );
}

function runReference(
  value: unknown,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): RunReference | null {
  if (!validRun(value, mode, scope, conversationId) || !isRecord(value)) {
    return null;
  }
  const id = identifier(value.id);
  return id && nonNegativeInteger(value.revision)
    ? Object.freeze({ id, revision: value.revision })
    : null;
}

function firstRun(
  value: unknown,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): RunReference | null {
  if (!isRecord(value) || !Array.isArray(value.runs)) return null;
  return runReference(value.runs[0], mode, scope, conversationId);
}

function validRunInputs(value: unknown, run: RunReference): boolean {
  return (
    isRecord(value) &&
    value.run_id === run.id &&
    value.run_revision === run.revision &&
    Array.isArray(value.inputs)
  );
}

function validSessionProjection(
  value: unknown,
  scope: Scope,
  conversation: Conversation,
): boolean {
  return (
    isRecord(value) &&
    value.schema_version === 1 &&
    validConversation(value.conversation, scope, conversation) &&
    identifier(value.snapshot_revision) !== null &&
    Array.isArray(value.run_history) &&
    Array.isArray(value.pending_hitl) &&
    Array.isArray(value.artifact_versions)
  );
}

function sessionRunReference(
  value: unknown,
  key: string,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): RunReference | null {
  return isRecord(value)
    ? runReference(value[key], mode, scope, conversationId)
    : null;
}

function firstSessionRunReference(
  value: unknown,
  mode: "cloud" | "local",
  scope: Scope,
  conversationId: string,
): RunReference | null {
  if (!isRecord(value) || !Array.isArray(value.run_history)) return null;
  return runReference(value.run_history[0], mode, scope, conversationId);
}

function hasSessionPendingSurface(
  value: unknown,
  conversationId: string,
): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value.pending_hitl) &&
    value.pending_hitl.some(
      (item) =>
        isRecord(item) &&
        item.conversation_id === conversationId &&
        item.status === "pending",
    )
  );
}

function hasPendingSurface(value: unknown, conversationId: string): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value.requests) &&
    value.requests.some(
      (item) =>
        isRecord(item) &&
        item.conversation_id === conversationId &&
        item.status === "pending",
    )
  );
}

function validRoster(value: unknown, conversationId: string): boolean {
  return (
    isRecord(value) &&
    value.conversation_id === conversationId &&
    Array.isArray(value.participant_agents) &&
    Array.isArray(value.participant_bindings)
  );
}

function validSummary(
  value: unknown,
  runId: string,
  scope: Scope,
  conversationId: string,
): boolean {
  return (
    isRecord(value) &&
    value.run_id === runId &&
    value.tenant_id === scope.tenantId &&
    value.project_id === scope.projectId &&
    value.conversation_id === conversationId &&
    value.summary_state === "recorded"
  );
}

function validChanges(
  value: unknown,
  runId: string,
  conversationId: string,
): boolean {
  return (
    isRecord(value) &&
    value.run_id === runId &&
    value.conversation_id === conversationId &&
    value.status === "ready" &&
    Array.isArray(value.files)
  );
}

function hasScopedItem(value: unknown, key: string, id: string): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value[key]) &&
    value[key].some((item) => isRecord(item) && item.id === id)
  );
}

function hasScopedProject(
  value: unknown,
  tenantId: string,
  projectId: string,
): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value.projects) &&
    value.projects.some(
      (item) =>
        isRecord(item) &&
        item.id === projectId &&
        item.tenant_id === tenantId,
    )
  );
}

function hasArrayField(value: unknown, key: string): boolean {
  return isRecord(value) && Array.isArray(value[key]);
}

function recordField(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined;
}

function nestedField(value: unknown, key: string, nestedKey: string): unknown {
  return isRecord(value) && isRecord(value[key])
    ? value[key][nestedKey]
    : undefined;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}

function identifier(value: unknown): string | null {
  return typeof value === "string" && value.trim() === value && value.length > 0
    ? value
    : null;
}

function optionalIdentifier(value: unknown): string | null | undefined {
  if (value === null) return null;
  return identifier(value) ?? undefined;
}

function matchesWorkspaceScope(
  value: unknown,
  expectedWorkspaceId: string | null,
): boolean {
  const workspaceId = optionalIdentifier(value);
  return (
    workspaceId !== undefined &&
    (expectedWorkspaceId === null || workspaceId === expectedWorkspaceId)
  );
}

function nonNegativeInteger(value: unknown): value is number {
  return (
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
