import type { CloudSocketScope } from "./cloudSocketPolicy";

type Send = (value: Record<string, unknown>) => Promise<void>;
type NativeInvoke = (
  command: string,
  args: Record<string, unknown>,
) => Promise<unknown>;
export interface ComputerUseCloudDeviceHooks {
  opened(
    connectionId: string,
    scope: CloudSocketScope,
    send: Send,
  ): Promise<void>;
  receive(
    connectionId: string,
    scope: CloudSocketScope,
    text: string,
    send: Send,
  ): boolean;
  closed(connectionId: string, scope: CloudSocketScope): void;
}
type Connection = {
  scope: CloudSocketScope;
  send: Send;
  deviceId: string;
  descriptor: string;
  timer?: ReturnType<typeof setTimeout>;
  controlTimer?: ReturnType<typeof setTimeout>;
  pendingControls: Map<string, string>;
  closed: boolean;
};
type NativeResult = {
  request_id: string;
  output_json: string;
  is_error: boolean;
  media: { artifact_id: string; mime_type: string; size_bytes: number }[];
  control_outcome?: "user_paused" | "user_stopped";
  control_generation?: string;
  permission_required?: unknown;
  authorization_revision?: unknown;
};
const MEDIA_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "audio/wav",
]);
const REQUEST_ID = /^[A-Za-z0-9_-]{1,128}$/u;

function validatePermissionResult(result: NativeResult): void {
  const permission = result.permission_required;
  if (permission === undefined || permission === null) return;
  const object = (value: unknown): value is Record<string, unknown> =>
    value !== null && typeof value === "object" && !Array.isArray(value);
  const keys = (value: Record<string, unknown>, expected: string[]) =>
    Object.keys(value).length === expected.length &&
    expected.every((key) => Object.hasOwn(value, key));
  const identity = (value: unknown): value is string =>
    typeof value === "string" && value.length > 0 && value.length <= 256;
  const invalid = () => { throw new Error("cua_cloud_permission_result_invalid"); };
  if (
    result.is_error || result.control_outcome !== undefined ||
    result.control_generation !== undefined ||
    !Number.isSafeInteger(result.authorization_revision) ||
    (result.authorization_revision as number) < 1 ||
    !object(permission) || !keys(permission, ["kind", "binding", "demand"])
  ) return invalid();
  const { kind, binding, demand } = permission;
  if (
    !["native_consent", "cloud_execution_step"].includes(kind as string) ||
    !object(binding) ||
    !keys(binding, ["tool_name", "input_digest", "engine_session_id", "cell_id", "step_id"]) ||
    !identity(binding.tool_name) || !identity(binding.engine_session_id) ||
    typeof binding.input_digest !== "string" || !/^[0-9a-f]{64}$/u.test(binding.input_digest) ||
    (binding.cell_id === null) !== (binding.step_id === null) ||
    (binding.cell_id !== null && (!identity(binding.cell_id) || !identity(binding.step_id))) ||
    !object(demand) || demand.error !== "cua_permission_required" ||
    !object(demand.request)
  ) return invalid();
  const request = demand.request;
  if (
    request.engine_session_id !== binding.engine_session_id ||
    request.tool_name !== binding.tool_name ||
    !["request_id", "session_id", "app", "identity_digest", "capability", "tool_name", "input_digest"]
      .every((key) => typeof request[key] === "string" && request[key].length > 0) ||
    !Array.isArray(demand.scopes) || demand.scopes.length === 0 ||
    !demand.scopes.every((scope) => ["once", "session", "always"].includes(scope))
  ) return invalid();
  if (
    (kind === "native_consent" && ["execution_step", "mcp_tool"].includes(request.capability as string)) ||
    (kind === "cloud_execution_step" && (binding.cell_id === null ||
      request.capability !== "execution_step" ||
      demand.scopes.length !== 1 || demand.scopes[0] !== "once"))
  ) invalid();
}

/** Only authenticated server frames reach this main-process bridge. */
export function createComputerUseCloudDeviceBridge(
  invoke: NativeInvoke,
): ComputerUseCloudDeviceHooks {
  const connections = new Map<string, Connection>();
  const active = new Map<string, Set<string>>();
  const native = (
    connectionId: string,
    scope: CloudSocketScope,
    action: string,
    fields: Record<string, unknown> = {},
    requestDeadlineMs?: number,
  ) =>
    invoke("computer_use_cloud_v2", {
      input: { action, connection_id: connectionId, scope, ...fields },
      ...(requestDeadlineMs === undefined ? {} : { request_deadline_ms: requestDeadlineMs }),
    });
  const announce = async (id: string, connection: Connection) => {
    const result = (await native(id, connection.scope, "describe")) as {
      device_id?: string;
      tool_definitions?: unknown[];
      scope?: unknown;
      revision?: number;
    };
    if (connection.closed) return;
    if (
      typeof result.device_id !== "string" ||
      !Array.isArray(result.tool_definitions)
    )
      throw new Error("cua_cloud_descriptor_invalid");
    const descriptor = JSON.stringify({
      device_id: result.device_id,
      tool_definitions: result.tool_definitions,
      revision: result.revision,
    });
    connection.deviceId = result.device_id;
    if (connection.descriptor !== descriptor) {
      await connection.send({
        type: "computer_use_device",
        device_id: result.device_id,
        tool_definitions: result.tool_definitions,
        scope: result.scope,
      });
      connection.descriptor = descriptor;
    }
  };
  const refresh = (id: string, connection: Connection) => {
    connection.timer = setTimeout(() => {
      void announce(id, connection)
        .catch(() => undefined)
        .finally(() => {
          if (!connection.closed) refresh(id, connection);
        });
    }, 15000);
    connection.timer.unref?.();
  };
  const pollControls = (id: string, connection: Connection) => {
    if (
      connection.closed ||
      connection.controlTimer ||
      !connection.pendingControls.size
    )
      return;
    connection.controlTimer = setTimeout(() => {
      const poll = async () => {
        const result = (await native(
          id,
          connection.scope,
          "control_events",
        )) as { events?: unknown };
        if (connection.closed) return;
        if (!Array.isArray(result.events) || result.events.length > 256)
          throw new Error("cua_cloud_control_events_invalid");
        for (const event of result.events) {
          if (!event || typeof event !== "object" || Array.isArray(event))
            throw new Error("cua_cloud_control_events_invalid");
          const value = event as Record<string, unknown>;
          if (
            typeof value.request_id !== "string" ||
            !REQUEST_ID.test(value.request_id) ||
            typeof value.session_id !== "string" ||
            !REQUEST_ID.test(value.session_id) ||
            typeof value.control_generation !== "string" ||
            !REQUEST_ID.test(value.control_generation) ||
            (value.state !== "resumed" && value.state !== "stopped")
          )
            throw new Error("cua_cloud_control_events_invalid");
          if (
            connection.pendingControls.get(value.request_id) !==
            value.control_generation
          )
            continue;
          await connection.send({
            type: "computer_use_control_state",
            request_id: value.request_id,
            session_id: value.session_id,
            control_generation: value.control_generation,
            state: value.state,
          });
          connection.pendingControls.delete(value.request_id);
          if (connection.closed) return;
        }
      };
      void poll()
        .catch(() => undefined)
        .finally(() => {
          connection.controlTimer = undefined;
          pollControls(id, connection);
        });
    }, 1000);
    connection.controlTimer.unref?.();
  };
  const execute = async (
    id: string,
    connection: Connection,
    requestId: string,
    expiresAt?: number,
  ) => {
    const requests = active.get(id) ?? new Set<string>();
    active.set(id, requests);
    if (requests.has(requestId)) return;
    requests.add(requestId);
    try {
      const result = (await native(id, connection.scope, "call", {
        request_id: requestId,
      }, expiresAt === undefined ? undefined : expiresAt * 1000)) as NativeResult;
      if (connection.closed) return;
      if (
        result.request_id !== requestId ||
        typeof result.output_json !== "string" ||
        typeof result.is_error !== "boolean" ||
        !Array.isArray(result.media)
      )
        throw new Error("cua_cloud_result_invalid");
      // Only the private host record carries provenance. The server separately
      // binds it to the current owner, claim revision and persisted inner step.
      validatePermissionResult(result);
      if (result.control_outcome !== undefined) {
        const output: unknown = JSON.parse(result.output_json);
        if (
          !["user_paused", "user_stopped"].includes(result.control_outcome) ||
          result.is_error ||
          result.media.length !== 0 ||
          (result.control_outcome === "user_paused" &&
            (typeof result.control_generation !== "string" ||
              !REQUEST_ID.test(result.control_generation))) ||
          (result.control_outcome !== "user_paused" &&
            result.control_generation !== undefined) ||
          !output ||
          typeof output !== "object" ||
          Array.isArray(output) ||
          Object.keys(output).length !== 3 ||
          !("type" in output) ||
          output.type !== "computer_use_control" ||
          !("status" in output) ||
          output.status !== result.control_outcome ||
          !("retry_allowed" in output) ||
          output.retry_allowed !== false
        )
          throw new Error("cua_cloud_control_outcome_invalid");
      }
      if (
        result.control_outcome === undefined &&
        result.control_generation !== undefined
      )
        throw new Error("cua_cloud_control_outcome_invalid");
      if (
        result.media.filter((media) => media.mime_type !== "audio/wav").length >
          20 ||
        result.media.reduce((total, media) => total + media.size_bytes, 0) >
          64 * 1024 * 1024 ||
        new Set(result.media.map((media) => media.artifact_id)).size !==
          result.media.length
      )
        throw new Error("cua_cloud_media_invalid");
      for (const media of result.media)
        if (
          !REQUEST_ID.test(media.artifact_id) ||
          !MEDIA_MIMES.has(media.mime_type) ||
          !Number.isSafeInteger(media.size_bytes) ||
          media.size_bytes < 0 ||
          media.size_bytes >
            (media.mime_type === "audio/wav" ? 64 : 8) * 1024 * 1024
        )
          throw new Error("cua_cloud_media_invalid");
      await connection.send({
        type: "computer_use_result",
        request_id: requestId,
        output_json: result.output_json,
        is_error: result.is_error === true,
        media: result.media,
        ...(result.permission_required === undefined || result.permission_required === null
          ? {}
          : {
              permission_required: result.permission_required,
              authorization_revision: result.authorization_revision,
            }),
        ...(result.control_outcome === undefined
          ? {}
          : { control_outcome: result.control_outcome }),
        ...(result.control_generation === undefined
          ? {}
          : { control_generation: result.control_generation }),
      });
      if (
        result.control_outcome === "user_paused" &&
        result.control_generation
      ) {
        connection.pendingControls.set(requestId, result.control_generation);
        pollControls(id, connection);
      }
      for (const media of result.media) {
        let offset = 0;
        while (!connection.closed) {
          const chunk = (await native(id, connection.scope, "media", {
            request_id: requestId,
            artifact_id: media.artifact_id,
            offset,
          })) as {
            artifact_id?: string;
            mime_type?: string;
            offset?: number;
            next_offset?: number;
            data_base64?: string;
            eof?: boolean;
          };
          if (
            chunk.artifact_id !== media.artifact_id ||
            chunk.mime_type !== media.mime_type ||
            chunk.offset !== offset ||
            typeof chunk.data_base64 !== "string" ||
            !Number.isSafeInteger(chunk.next_offset) ||
            chunk.next_offset! < offset ||
            chunk.next_offset! > media.size_bytes ||
            Buffer.from(chunk.data_base64, "base64").byteLength !==
              chunk.next_offset! - offset ||
            (chunk.next_offset === offset && !chunk.eof)
          )
            throw new Error("cua_cloud_media_invalid");
          await connection.send({
            type: "computer_use_media",
            request_id: requestId,
            artifact_id: media.artifact_id,
            mime_type: media.mime_type,
            offset,
            data_base64: chunk.data_base64,
            eof: chunk.eof === true,
          });
          offset = chunk.next_offset!;
          if (chunk.eof === true) {
            if (offset !== media.size_bytes)
              throw new Error("cua_cloud_media_incomplete");
            break;
          }
        }
      }
    } catch (error) {
      if (!connection.closed)
        await connection.send({
          type: "computer_use_result",
          request_id: requestId,
          output_json: JSON.stringify({
            error:
              error instanceof Error
                ? error.message
                : "cua_cloud_execution_failed",
          }),
          is_error: true,
          media: [],
        });
    } finally {
      requests.delete(requestId);
    }
  };
  return {
    async opened(id, scope, send) {
      const connection = {
        scope,
        send,
        deviceId: "",
        descriptor: "",
        closed: false,
        pendingControls: new Map<string, string>(),
      };
      connections.set(id, connection);
      try {
        await announce(id, connection);
      } finally {
        if (!connection.closed) refresh(id, connection);
      }
    },
    receive(id, scope, text, send) {
      let message: Record<string, unknown>;
      try {
        message = JSON.parse(text);
      } catch {
        return false;
      }
      if (!message || typeof message !== "object") return false;
      if (
        ![
          "computer_use_request",
          "computer_use_cancel",
          "computer_use_device_ready",
        ].includes(message.type as string)
      )
        return false;
      const connection = connections.get(id);
      if (!connection || connection.closed) return true;
      if (message.type === "computer_use_device_ready") {
        if (message.device_id !== connection.deviceId)
          throw new Error("cua_cloud_device_mismatch");
        if (message.ready !== false)
          void native(id, scope, "ready").catch(() => undefined);
        return true;
      }
      if (
        typeof message.request_id !== "string" ||
        !REQUEST_ID.test(message.request_id)
      )
        throw new Error("cua_cloud_request_invalid");
      if (message.type === "computer_use_cancel") {
        void native(id, scope, "cancel", {
          request_id: message.request_id,
        }).catch(() => undefined);
        return true;
      }
      if (message.expires_at !== undefined && (!Number.isSafeInteger(message.expires_at) || (message.expires_at as number) <= 0)) {
        throw new Error("cua_cloud_request_deadline_invalid");
      }
      void execute(id, connection, message.request_id, message.expires_at as number | undefined).catch(() => undefined);
      return true;
    },
    closed(id, scope) {
      const connection = connections.get(id);
      if (connection) {
        connection.closed = true;
        if (connection.timer) clearTimeout(connection.timer);
        if (connection.controlTimer) clearTimeout(connection.controlTimer);
        connection.pendingControls.clear();
        connections.delete(id);
      }
      active.delete(id);
      void native(id, scope, "close").catch(() => undefined);
    },
  };
}
