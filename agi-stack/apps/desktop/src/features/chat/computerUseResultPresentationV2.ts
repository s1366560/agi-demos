import type { ToolResultPresentationV2 } from "@agistack/plugin-slots";
import { computerUseTimestamp } from '../../api/computerUseTime';

export function computerUseResultPresentationV2(
  output: unknown,
  summary: string = "",
): ToolResultPresentationV2 {
  let value: unknown = output;
  if (typeof output === "string") {
    try {
      value = JSON.parse(output);
    } catch {
      value = null;
    }
  }
  const record =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const screenshot =
    record.screenshot && typeof record.screenshot === "object"
      ? (record.screenshot as Record<string, unknown>)
      : null;
  const artifactId = screenshot?.artifact_id;
  const icon =
    record.app_icon && typeof record.app_icon === "object"
      ? (record.app_icon as Record<string, unknown>)
      : null;
  const target =
    record.target && typeof record.target === "object"
      ? (record.target as Record<string, unknown>)
      : null;
  const windowId = record.window_id ?? target?.window_id;
  const windowTitle = target?.window_title;
  const observedAt = computerUseTimestamp(record.observed_at ?? screenshot?.observed_at);
  // The host forwards observation text and an owned artifact identity, never the raw media envelope.
  return Object.freeze({
    kind: "computer_use",
    app: typeof record.app === "string" ? record.app.slice(0, 256) : "",
    text: typeof record.text === "string" ? record.text.slice(0, 32768) : "",
    summary: summary.slice(0, 32768),
    ...(typeof artifactId === "string" &&
    /^cua-image-[0-9a-f-]+$/u.test(artifactId)
      ? { screenshotArtifactId: artifactId }
      : {}),
    ...(typeof icon?.artifact_id === "string" &&
    /^cua-image-[0-9a-f-]+$/u.test(icon.artifact_id)
      ? { appIconArtifactId: icon.artifact_id }
      : {}),
    ...(typeof windowId === "string"
      ? { windowId: windowId.slice(0, 256) }
      : {}),
    ...(typeof windowTitle === "string"
      ? { windowTitle: windowTitle.slice(0, 256) }
      : {}),
    ...(typeof observedAt === "string"
      ? { observedAt: observedAt.slice(0, 64) }
      : {}),
  });
}

export function computerUsePreviewBlobV2(dataUrl: string): Blob {
  const match =
    /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/u.exec(dataUrl);
  if (!match || match[2].length > 12 * 1024 * 1024)
    throw new Error("cua_preview_invalid");
  const decoded = atob(match[2]);
  const bytes = Uint8Array.from(decoded, (character) =>
    character.charCodeAt(0),
  );
  return new Blob([bytes], { type: match[1] });
}
