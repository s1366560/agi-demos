import {
  loadReplMediaV2,
  type ToolResultMediaV2,
  type ToolResultPresentationV2,
} from "@agistack/plugin-slots";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
} from "@agistack/plugin-slots";

import { useI18n } from "../../i18n";
import { useOptionalDesktopRendererGenerationV2 } from "../../plugins/desktopRendererGenerationContextV2";
import type { DesktopToolResultRendererModuleV2 } from "../../plugins/desktopToolResultRendererModuleV2";
import type { AuthorizedUiSlotDefinitionV2 } from "../../plugins/uiSlotRegistry";
import { usePlatformPluginUiSlots } from "../settings/usePlatformPluginUiSlots";
import { useComputerUseDevice } from "../settings/ComputerUseDeviceProvider";
import { useTimelineInspection } from "../session/TimelineInspectionContext";
import { projectToolResultPresentationV2 } from "./toolResultPresentationV2";
import { computerUsePreviewBlobV2 } from "./computerUseResultPresentationV2";
import type { ToolCallPresentationKind } from "./chatTimelineModel";
import {
  createDesktopToolResultRendererPayloadV2,
  DesktopToolResultRendererBridgeV2,
  type DesktopToolResultRendererPayloadV2,
  type DesktopToolResultRendererProtocolV2,
  type DesktopToolResultRendererStatusV2,
} from "./desktopToolResultRendererBridgeV2";

const TOOL_RESULT_RENDERER_PROTOCOL_V2: DesktopToolResultRendererProtocolV2 =
  Object.freeze({
    decode: decodeSlotMessage,
    encode: encodeSlotMessage,
    isGuestForSlot: isGuestMessageForSlot,
  });

export interface PlatformPluginToolResultSlotsProps {
  readonly resultId: string;
  readonly presentation?: ToolResultPresentationV2;
  readonly toolName: string;
  readonly status: DesktopToolResultRendererStatusV2;
  readonly kind: ToolCallPresentationKind;
}

export function PlatformPluginToolResultSlots({
  resultId,
  presentation,
  toolName,
  status,
  kind,
}: PlatformPluginToolResultSlotsProps) {
  const { t } = useI18n();
  const generation = useOptionalDesktopRendererGenerationV2();
  const { sessionKey } = useTimelineInspection();
  const { slots, error, loading } = usePlatformPluginUiSlots({ active: true });
  const [hostError, setHostError] = useState<string | null>(null);
  // Stable declared content prevents unrelated timeline rerenders from restarting playback.
  const presentationKey = JSON.stringify(
    presentation ? projectToolResultPresentationV2(presentation, "") : null,
  );
  const stablePresentation = useMemo(() => {
    const value = JSON.parse(presentationKey);
    return value ? projectToolResultPresentationV2(value, "") : undefined;
  }, [presentationKey]);
  const payload = useMemo(
    () =>
      createDesktopToolResultRendererPayloadV2({
        resultId,
        presentation: stablePresentation,
        toolName,
        status,
        kind,
        resultLabel: t("chat.toolResult"),
        kindLabel:
          kind === "tool" || kind === "repl_output"
            ? t("chat.toolResult")
            : t(`session.toolKind.${kind}`),
        statusLabel: t(`session.toolStatus.${status}`),
      }),
    [kind, resultId, stablePresentation, status, t, toolName],
  );
  const visible = slots.filter((slot) => slot.slot === "tool_result_renderer");
  if (generation === null || visible.length === 0) return null;

  return (
    <section
      className="platform-plugin-tool-result-slots"
      aria-live="polite"
      data-loading={loading || undefined}
      data-error={hostError ?? error ?? undefined}
    >
      {visible.map((slot) => {
        const module =
          generation.composition.resolveToolResultRendererModule(slot);
        if (module === null) return null;
        return (
          <DesktopToolResultRendererFrameV2
            key={`${sessionKey}:${generation.meta.digest}:${slot.sourceEntryId}:${slot.pluginId}:${slot.id}:${resultId}`}
            ownerKey={sessionKey}
            module={module}
            onError={setHostError}
            payload={payload}
            slot={slot}
          />
        );
      })}
    </section>
  );
}

function DesktopToolResultRendererFrameV2({
  ownerKey,
  module,
  onError,
  payload,
  slot,
}: Readonly<{
  ownerKey: string | null;
  module: DesktopToolResultRendererModuleV2;
  onError: (errorCode: string) => void;
  payload: DesktopToolResultRendererPayloadV2;
  slot: AuthorizedUiSlotDefinitionV2;
}>) {
  const { t } = useI18n();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<DesktopToolResultRendererBridgeV2 | null>(null);
  const frameLoadedRef = useRef(false);
  const payloadRef = useRef(payload);
  const [height, setHeight] = useState(40);
  const { client } = useComputerUseDevice();
  const [replMedia, setReplMedia] = useState<Readonly<{
    owner: typeof client;
    presentation: ToolResultPresentationV2;
    ownerKey: string;
    values: readonly ToolResultMediaV2[];
  }> | null>(null);
  const replPresentation =
    payload.presentation?.kind === "repl_output" ? payload.presentation : null;
  useEffect(() => {
    setReplMedia(null);
    if (!client || !replPresentation || !ownerKey) return;
    const controller = new AbortController();
    void loadReplMediaV2(
      replPresentation,
      async (reference, signal) => {
        if (reference.store === "conversation_tool_media") {
          if (!client.conversationMedia)
            throw new Error("tool_media_store_unavailable");
          return client.conversationMedia(ownerKey, reference, signal);
        }
        return reference.kind === "image"
          ? computerUsePreviewBlobV2(
              await client.preview(reference.artifactId, signal),
            )
          : client.audio(reference.artifactId, signal);
      },
      controller.signal,
    )
      .then((values) => {
        if (!controller.signal.aborted)
          setReplMedia({
            owner: client,
            ownerKey,
            presentation: replPresentation,
            values,
          });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [client, ownerKey, replPresentation]);
  const [preview, setPreview] = useState<Readonly<{
    owner: typeof client;
    artifactId: string;
    mimeType: string;
    bytes: Uint8Array;
  }> | null>(null);
  const artifactId =
    payload.presentation?.kind === "computer_use"
      ? payload.presentation.screenshotArtifactId
      : undefined;
  const iconId =
    payload.presentation?.kind === "computer_use"
      ? payload.presentation.appIconArtifactId
      : undefined;
  const [icon, setIcon] = useState<
    | Readonly<{
        owner: typeof client;
        value: DesktopToolResultRendererPayloadV2["computerUseAppIcon"];
      }>
    | undefined
  >();
  const resolvedPayload = useMemo(
    () => ({
      ...payload,
      mediaLoadingLabel: t("cua.loading"),
      mediaUnavailableLabel: t("cua.unavailable"),
      ...(replMedia &&
      replMedia.owner === client &&
      replMedia.ownerKey === ownerKey &&
      replMedia.presentation === replPresentation
        ? { media: replMedia.values }
        : {}),
      ...(preview &&
      preview.owner === client &&
      preview.artifactId === artifactId
        ? {
            computerUsePreview: {
              artifactId: preview.artifactId,
              mimeType: preview.mimeType,
              bytes: preview.bytes,
            },
          }
        : {}),
      ...(icon && icon.owner === client && icon.value?.artifactId === iconId
        ? { computerUseAppIcon: icon.value }
        : {}),
    }),
    [
      payload,
      preview,
      artifactId,
      icon,
      iconId,
      client,
      ownerKey,
      replMedia,
      replPresentation,
      t,
    ],
  );
  payloadRef.current = resolvedPayload;
  useEffect(() => {
    setPreview(null);
    if (!artifactId || !client) return;
    const controller = new AbortController();
    void client
      .preview(artifactId, controller.signal)
      .then(async (data) => {
        const blob = computerUsePreviewBlobV2(data);
        const bytes = new Uint8Array(await blob.arrayBuffer());
        if (controller.signal.aborted) return;
        // The opaque guest cannot read a parent-origin blob URL. Its own
        // renderer creates the preview from structured-cloned authorized bytes.
        setPreview({ owner: client, artifactId, mimeType: blob.type, bytes });
      })
      .catch(() => undefined);
    return () => {
      controller.abort();
    };
  }, [artifactId, client]);
  useEffect(() => {
    setIcon(undefined);
    if (!iconId || !client) return;
    const controller = new AbortController();
    void client
      .preview(iconId, controller.signal)
      .then(async (data) => {
        const blob = computerUsePreviewBlobV2(data);
        const bytes = new Uint8Array(await blob.arrayBuffer());
        if (!controller.signal.aborted)
          setIcon({
            owner: client,
            value: { artifactId: iconId, mimeType: blob.type, bytes },
          });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [iconId, client]);

  const handleFrameLoad = useCallback(() => {
    frameLoadedRef.current = true;
    bridgeRef.current?.activate();
  }, []);

  useEffect(() => {
    const frameWindow = iframeRef.current?.contentWindow;
    if (frameWindow === null || frameWindow === undefined) return;
    const bridge = new DesktopToolResultRendererBridgeV2({
      frameWindow,
      onError,
      onResize: setHeight,
      payload: payloadRef.current,
      protocol: TOOL_RESULT_RENDERER_PROTOCOL_V2,
      slotId: slot.id,
    });
    bridgeRef.current = bridge;
    if (frameLoadedRef.current) bridge.activate();
    const listener = (event: MessageEvent) => {
      bridge.handleMessage(event);
    };
    window.addEventListener("message", listener);
    return () => {
      window.removeEventListener("message", listener);
      bridge.dispose();
      if (bridgeRef.current === bridge) bridgeRef.current = null;
    };
  }, [module, onError, slot.id]);

  useEffect(() => {
    bridgeRef.current?.updatePayload(resolvedPayload);
  }, [resolvedPayload]);

  return (
    <iframe
      ref={iframeRef}
      className="platform-plugin-tool-result-frame"
      data-contract={slot.contract}
      data-module-ref={module.moduleRef}
      data-plugin-id={slot.pluginId}
      height={height}
      onLoad={handleFrameLoad}
      sandbox="allow-scripts"
      srcDoc={module.srcDoc}
      title={payload.resultLabel}
    />
  );
}

export default PlatformPluginToolResultSlots;
