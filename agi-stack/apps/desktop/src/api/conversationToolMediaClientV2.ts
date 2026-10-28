import {
  readToolResultMediaResponseV2,
  type ReplMediaReferenceV2,
} from "@agistack/plugin-slots";
import type { DesktopRuntimeConfig } from "../types";
import { desktopApiCredential, desktopLaunchCapability } from "./client";
import { desktopApiFetch } from "./cloudRequestBroker";

export function createConversationToolMediaReaderV2(
  config: DesktopRuntimeConfig,
) {
  const owner = Object.freeze({ ...config });
  return async (
    conversationId: string,
    reference: ReplMediaReferenceV2,
    signal: AbortSignal,
  ): Promise<Blob> => {
    signal.throwIfAborted();
    if (
      reference.store !== "conversation_tool_media" ||
      !conversationId ||
      !owner.tenantId ||
      !owner.projectId ||
      reference.sizeBytes > 10 * 1024 * 1024
    )
      throw new Error("tool_media_owner_unavailable");
    const query = new URLSearchParams({
      tenant_id: owner.tenantId,
      project_id: owner.projectId,
    });
    const path = `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/tool-media/${encodeURIComponent(reference.artifactId)}?${query}`;
    const headers = new Headers({ Accept: reference.mimeType });
    const credential = desktopApiCredential(owner);
    if (credential) headers.set("Authorization", `Bearer ${credential}`);
    const launch = desktopLaunchCapability(owner);
    if (launch) headers.set("X-Agistack-Launch", launch);
    const response = await desktopApiFetch(
      owner,
      path,
      { method: "GET", headers, signal },
      { responseType: "binary", maxBytes: reference.sizeBytes },
    );
    return readToolResultMediaResponseV2(response, reference, signal);
  };
}
