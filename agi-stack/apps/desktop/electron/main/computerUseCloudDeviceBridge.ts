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
};
const MEDIA_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "audio/wav",
]);
const REQUEST_ID = /^[A-Za-z0-9_-]{1,128}$/u;

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
  ) =>
    invoke("computer_use_cloud_v2", {
      input: { action, connection_id: connectionId, scope, ...fields },
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
  ) => {
    const requests = active.get(id) ?? new Set<string>();
    active.set(id, requests);
    if (requests.has(requestId)) return;
    requests.add(requestId);
    try {
      const result = (await native(id, connection.scope, "call", {
        request_id: requestId,
      })) as NativeResult;
      if (connection.closed) return;
      if (
        result.request_id !== requestId ||
        typeof result.output_json !== "string" ||
        typeof result.is_error !== "boolean" ||
        !Array.isArray(result.media)
      )
        throw new Error("cua_cloud_result_invalid");
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
      void execute(id, connection, message.request_id).catch(() => undefined);
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
