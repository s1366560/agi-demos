import type { DesktopRuntimeConfig } from "../types";

export * from "./computerUseContractV2";
import {
  isComputerUseSnapshotForScope,
  type ComputerUseClientV2,
  type ComputerUseSnapshot,
  type ComputerUseOperation,
  type ComputerUseNativeInvoke,
} from "./computerUseContractV2";

export function createComputerUseClientV2(
  config: DesktopRuntimeConfig,
  suppliedInvoke?: ComputerUseNativeInvoke,
): ComputerUseClientV2 {
  const scope = Object.freeze({
    mode: config.mode,
    tenant_id: config.tenantId,
    project_id: config.projectId,
    credential: config.mode === "local" ? config.apiKey : "",
  });
  const invoke: ComputerUseNativeInvoke =
    suppliedInvoke ??
    ((command, args) => {
      const desktop =
        typeof window === "undefined" ? undefined : window.__MEMSTACK_DESKTOP__;
      if (desktop?.runtime !== "electron" || !desktop.core?.invoke)
        return Promise.reject(new Error("cua_native_unavailable"));
      return desktop.core.invoke(command, args);
    });
  const call = async (
    operation: ComputerUseOperation,
    signal?: AbortSignal,
  ) => {
    signal?.throwIfAborted();
    if (!scope.tenant_id || !scope.project_id)
      throw new Error("cua_scope_unavailable");
    const value = await invoke("computer_use_manage_v2", {
      input: { ...scope, operation },
    });
    signal?.throwIfAborted();
    return value;
  };
  const requireSnapshot = (value: unknown): ComputerUseSnapshot => {
    const result = value as ComputerUseSnapshot;
    if (
      !isComputerUseSnapshotForScope(result, {
        tenantId: scope.tenant_id,
        projectId: scope.project_id,
      })
    )
      throw new Error("cua_snapshot_invalid");
    return result;
  };
  return Object.freeze({
    snapshot: async (signal?: AbortSignal) =>
      requireSnapshot(await call({ action: "status" }, signal)),
    manage: async (operation: ComputerUseOperation, signal?: AbortSignal) =>
      requireSnapshot(await call(operation, signal)),
    preview: async (artifactId: string, signal?: AbortSignal) => {
      const value = (await call(
        { action: "artifact_preview", artifact_id: artifactId },
        signal,
      )) as { artifact_id?: string; data_url?: string };
      if (
        value.artifact_id !== artifactId ||
        typeof value.data_url !== "string" ||
        !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/u.test(
          value.data_url,
        )
      )
        throw new Error("cua_preview_invalid");
      return value.data_url;
    },
    audio: async (artifactId: string, signal?: AbortSignal) => {
      const chunks: ArrayBuffer[] = [];
      let offset = 0;
      for (;;) {
        const value = (await call(
          { action: "audio_chunk", artifact_id: artifactId, offset },
          signal,
        )) as {
          artifact_id?: string;
          mime_type?: string;
          offset?: number;
          next_offset?: number;
          eof?: boolean;
          data_base64?: string;
        };
        if (
          value.artifact_id !== artifactId ||
          value.mime_type !== "audio/wav" ||
          value.offset !== offset ||
          typeof value.data_base64 !== "string" ||
          !Number.isSafeInteger(value.next_offset) ||
          (value.next_offset ?? -1) < offset ||
          (value.next_offset ?? Infinity) > 64 * 1024 * 1024 ||
          (value.next_offset === offset && value.eof !== true)
        )
          throw new Error("cua_audio_invalid");
        const raw = atob(value.data_base64);
        if (
          raw.length > 128 * 1024 ||
          raw.length !== value.next_offset! - offset
        )
          throw new Error("cua_audio_invalid");
        const bytes = new Uint8Array(raw.length);
        for (let index = 0; index < raw.length; index++)
          bytes[index] = raw.charCodeAt(index);
        chunks.push(bytes.buffer);
        offset = value.next_offset!;
        if (value.eof === true) return new Blob(chunks, { type: "audio/wav" });
      }
    },
  });
}
