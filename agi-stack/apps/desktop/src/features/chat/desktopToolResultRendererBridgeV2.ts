import type { ToolCallPresentationKind } from './chatTimelineModel';

export type DesktopToolResultRendererStatusV2 = 'complete' | 'failed';

export interface DesktopToolResultRendererPayloadV2 {
  readonly schemaVersion: 1;
  readonly resultId: string;
  readonly toolName: string;
  readonly status: DesktopToolResultRendererStatusV2;
  readonly kind: ToolCallPresentationKind;
  readonly resultLabel: string;
  readonly kindLabel: string;
  readonly statusLabel: string;
}

export interface CreateDesktopToolResultRendererPayloadV2 {
  readonly resultId: string;
  readonly toolName: string;
  readonly status: DesktopToolResultRendererStatusV2;
  readonly kind: ToolCallPresentationKind;
  readonly resultLabel: string;
  readonly kindLabel: string;
  readonly statusLabel: string;
}

type SlotHostMessageV2 =
  | Readonly<{ type: 'slot:init'; slotId: string; payload?: unknown }>
  | Readonly<{
      type: 'slot:event';
      slotId: string;
      name: string;
      data?: unknown;
    }>
  | Readonly<{ type: 'slot:dispose'; slotId: string }>;

type SlotGuestMessageV2 =
  | Readonly<{ type: 'slot:ready'; slotId: string }>
  | Readonly<{ type: 'slot:resize'; slotId: string; height: number }>
  | Readonly<{
      type: 'slot:action';
      slotId: string;
      name: string;
      data?: unknown;
    }>
  | Readonly<{ type: 'slot:error'; slotId: string; message: string }>;

type SlotProtocolMessageV2 = SlotHostMessageV2 | SlotGuestMessageV2;

export interface DesktopToolResultRendererProtocolV2 {
  readonly decode: (value: unknown) => SlotProtocolMessageV2 | null;
  readonly encode: (message: SlotHostMessageV2) => unknown;
  readonly isGuestForSlot: (
    message: SlotProtocolMessageV2,
    slotId: string,
  ) => message is SlotGuestMessageV2;
}

export interface DesktopToolResultRendererFrameWindowV2 {
  postMessage(message: unknown, targetOrigin: string): void;
}

export interface DesktopToolResultRendererMessageEventV2 {
  readonly data: unknown;
  readonly origin: string;
  readonly source: unknown;
}

export interface DesktopToolResultRendererBridgeOptionsV2 {
  readonly frameWindow: DesktopToolResultRendererFrameWindowV2;
  readonly onError: (errorCode: string) => void;
  readonly onResize: (height: number) => void;
  readonly payload: DesktopToolResultRendererPayloadV2;
  readonly protocol: DesktopToolResultRendererProtocolV2;
  readonly slotId: string;
}

const MAX_FRAME_HEIGHT_V2 = 160;
const TOOL_RESULT_KINDS_V2 = new Set<ToolCallPresentationKind>([
  'search',
  'read',
  'command',
  'edit',
  'check',
  'tool',
]);

export function createDesktopToolResultRendererPayloadV2(
  input: CreateDesktopToolResultRendererPayloadV2,
): DesktopToolResultRendererPayloadV2 {
  const resultId = requiredTextV2(input.resultId, 'result_id');
  const resultLabel = requiredTextV2(input.resultLabel, 'result_label');
  const kindLabel = requiredTextV2(input.kindLabel, 'kind_label');
  const statusLabel = requiredTextV2(input.statusLabel, 'status_label');
  if (!TOOL_RESULT_KINDS_V2.has(input.kind)) {
    throw new Error('desktop_tool_result_renderer_kind_invalid');
  }
  if (input.status !== 'complete' && input.status !== 'failed') {
    throw new Error('desktop_tool_result_renderer_status_invalid');
  }
  return Object.freeze({
    schemaVersion: 1,
    resultId,
    toolName: input.toolName.trim(),
    status: input.status,
    kind: input.kind,
    resultLabel,
    kindLabel,
    statusLabel,
  });
}

export class DesktopToolResultRendererBridgeV2 {
  private disposed = false;
  private payload: DesktopToolResultRendererPayloadV2;
  private ready = false;

  constructor(private readonly options: DesktopToolResultRendererBridgeOptionsV2) {
    this.payload = options.payload;
  }

  handleMessage(event: DesktopToolResultRendererMessageEventV2): boolean {
    if (this.disposed || event.source !== this.options.frameWindow || event.origin !== 'null') {
      return false;
    }
    const message = this.options.protocol.decode(event.data);
    if (message === null || !this.options.protocol.isGuestForSlot(message, this.options.slotId)) {
      return false;
    }
    switch (message.type) {
      case 'slot:ready':
        this.activate();
        return true;
      case 'slot:resize':
        if (Number.isFinite(message.height) && message.height > 0) {
          this.options.onResize(Math.min(Math.round(message.height), MAX_FRAME_HEIGHT_V2));
        }
        return true;
      case 'slot:action':
        this.options.onError('desktop_tool_result_renderer_action_rejected');
        return true;
      case 'slot:error':
        this.options.onError('desktop_tool_result_renderer_guest_error');
        return true;
    }
  }

  activate(): void {
    if (this.disposed || this.ready) return;
    this.ready = true;
    this.post({
      type: 'slot:init',
      slotId: this.options.slotId,
      payload: this.payload,
    });
  }

  updatePayload(payload: DesktopToolResultRendererPayloadV2): void {
    if (this.disposed) return;
    this.payload = payload;
    if (!this.ready) return;
    this.post({
      type: 'slot:event',
      slotId: this.options.slotId,
      name: 'tool-result',
      data: payload,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.post({ type: 'slot:dispose', slotId: this.options.slotId });
  }

  private post(message: SlotHostMessageV2): void {
    try {
      this.options.frameWindow.postMessage(this.options.protocol.encode(message), '*');
    } catch {
      this.options.onError('desktop_tool_result_renderer_transport_error');
    }
  }
}

function requiredTextV2(value: string, field: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new Error(`desktop_tool_result_renderer_${field}_required`);
  }
  return normalized;
}
