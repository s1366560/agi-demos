export type DesktopConversationRendererActionV2 = 'open-commands';

export type DesktopConversationRendererWorkflowTargetV2 =
  | 'changes'
  | 'pull'
  | 'plan'
  | 'background'
  | 'artifacts';

export interface DesktopConversationRendererPayloadV2 {
  readonly schemaVersion: 1;
  readonly commandsLabel: string;
  readonly conversationId: string;
  readonly disabled: boolean;
  readonly messageCount: number;
  readonly sending: boolean;
  readonly workflowTarget: DesktopConversationRendererWorkflowTargetV2;
}

export interface CreateDesktopConversationRendererPayloadV2 {
  readonly commandsLabel: string;
  readonly conversationId: string | null | undefined;
  readonly disabled: boolean;
  readonly messageCount: number;
  readonly sending: boolean;
  readonly workflowTarget: DesktopConversationRendererWorkflowTargetV2;
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

export interface DesktopConversationRendererProtocolV2 {
  readonly decode: (value: unknown) => SlotProtocolMessageV2 | null;
  readonly encode: (message: SlotHostMessageV2) => unknown;
  readonly isGuestForSlot: (
    message: SlotProtocolMessageV2,
    slotId: string,
  ) => message is SlotGuestMessageV2;
}

export interface DesktopConversationRendererFrameWindowV2 {
  postMessage(message: unknown, targetOrigin: string): void;
}

export interface DesktopConversationRendererMessageEventV2 {
  readonly data: unknown;
  readonly origin: string;
  readonly source: unknown;
}

export interface DesktopConversationRendererBridgeOptionsV2 {
  readonly frameWindow: DesktopConversationRendererFrameWindowV2;
  readonly onAction: (action: DesktopConversationRendererActionV2) => void;
  readonly onError: (errorCode: string) => void;
  readonly onResize: (height: number) => void;
  readonly payload: DesktopConversationRendererPayloadV2;
  readonly protocol: DesktopConversationRendererProtocolV2;
  readonly slotId: string;
}

const MAX_FRAME_HEIGHT_V2 = 320;
const WORKFLOW_TARGETS_V2 =
  new Set<DesktopConversationRendererWorkflowTargetV2>([
    'changes',
    'pull',
    'plan',
    'background',
    'artifacts',
  ]);

export function createDesktopConversationRendererPayloadV2(
  input: CreateDesktopConversationRendererPayloadV2,
): DesktopConversationRendererPayloadV2 {
  const commandsLabel = input.commandsLabel.trim();
  if (commandsLabel.length === 0) {
    throw new Error('desktop_conversation_renderer_commands_label_required');
  }
  if (!Number.isSafeInteger(input.messageCount) || input.messageCount < 0) {
    throw new Error('desktop_conversation_renderer_message_count_invalid');
  }
  if (!WORKFLOW_TARGETS_V2.has(input.workflowTarget)) {
    throw new Error('desktop_conversation_renderer_workflow_target_invalid');
  }
  return Object.freeze({
    schemaVersion: 1,
    commandsLabel,
    conversationId: input.conversationId?.trim() ?? '',
    disabled: input.disabled,
    messageCount: input.messageCount,
    sending: input.sending,
    workflowTarget: input.workflowTarget,
  });
}

export class DesktopConversationRendererBridgeV2 {
  private disposed = false;
  private payload: DesktopConversationRendererPayloadV2;
  private ready = false;

  constructor(
    private readonly options: DesktopConversationRendererBridgeOptionsV2,
  ) {
    this.payload = options.payload;
  }

  handleMessage(event: DesktopConversationRendererMessageEventV2): boolean {
    if (
      this.disposed ||
      event.source !== this.options.frameWindow ||
      event.origin !== 'null'
    ) {
      return false;
    }
    const message = this.options.protocol.decode(event.data);
    if (
      message === null ||
      !this.options.protocol.isGuestForSlot(message, this.options.slotId)
    ) {
      return false;
    }
    switch (message.type) {
      case 'slot:ready':
        this.activate();
        return true;
      case 'slot:resize':
        if (Number.isFinite(message.height) && message.height > 0) {
          this.options.onResize(
            Math.min(Math.round(message.height), MAX_FRAME_HEIGHT_V2),
          );
        }
        return true;
      case 'slot:action':
        if (message.name === 'open-commands') {
          this.options.onAction('open-commands');
        } else {
          this.options.onError('desktop_conversation_renderer_action_rejected');
        }
        return true;
      case 'slot:error':
        this.options.onError('desktop_conversation_renderer_guest_error');
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

  updatePayload(payload: DesktopConversationRendererPayloadV2): void {
    if (this.disposed) return;
    this.payload = payload;
    if (!this.ready) return;
    this.post({
      type: 'slot:event',
      slotId: this.options.slotId,
      name: 'conversation-state',
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
      this.options.frameWindow.postMessage(
        this.options.protocol.encode(message),
        '*',
      );
    } catch {
      this.options.onError('desktop_conversation_renderer_transport_error');
    }
  }
}
