import type { UiSlotKind } from './types';

/** Only a host-selected presentation crosses into an isolated result renderer. */
export type ToolResultPresentationV2 =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'summary'; readonly summary: string }
  | {
      readonly kind: 'computer_use';
      readonly app: string;
      readonly text: string;
      readonly summary: string;
      readonly screenshotArtifactId?: string;
      readonly appIconArtifactId?: string;
      readonly windowId?: string;
      readonly windowTitle?: string;
      readonly observedAt?: string;
    }
  | {
      readonly kind: 'table';
      readonly columns: readonly string[];
      readonly rows: readonly (readonly string[])[];
    }
  | {
      readonly kind: 'diff';
      readonly before: string;
      readonly after: string;
      readonly language?: string;
    };

export interface SlotOwnerIdentityV2 {
  readonly tenantId?: string;
  readonly projectId?: string;
  readonly conversationId?: string | null;
}

export interface SlotDestinationV2 {
  readonly id: string;
  readonly label: string;
}

export interface SlotContextMapV2 {
  readonly nav_item: SlotOwnerIdentityV2 & {
    readonly kind: 'navigation';
    readonly destinations: readonly SlotDestinationV2[];
  };
  readonly settings_page: SlotOwnerIdentityV2 & {
    readonly kind: 'settings';
    readonly sections: readonly SlotDestinationV2[];
  };
  readonly conversation_renderer: SlotOwnerIdentityV2 & {
    readonly kind: 'conversation';
    readonly messageCount: number;
    readonly streaming: boolean;
    readonly commandsLabel: string;
  };
  readonly composer_action: SlotOwnerIdentityV2 & {
    readonly kind: 'composer';
    readonly draftRevision: string;
    readonly locked: boolean;
    readonly templatesLabel: string;
  };
  readonly mcp_canvas: SlotOwnerIdentityV2 & {
    readonly kind: 'canvas';
    readonly activeTabId: string | null;
    readonly tabs: readonly SlotDestinationV2[];
  };
  readonly tool_result_renderer: SlotOwnerIdentityV2 & {
    readonly kind: 'tool-result';
    readonly toolName: string;
    readonly status: 'complete' | 'failed';
    readonly presentation: ToolResultPresentationV2;
  };
}

export type SlotContextV2<K extends UiSlotKind = UiSlotKind> =
  K extends keyof SlotContextMapV2 ? SlotContextMapV2[K] : SlotOwnerIdentityV2;

export type SlotActionV2 =
  | { readonly type: 'navigate'; readonly destinationId: string }
  | { readonly type: 'settings.open'; readonly sectionId: string }
  | { readonly type: 'conversation.open-commands' }
  | { readonly type: 'composer.open-templates' }
  | {
      readonly type: 'composer.insert-text';
      readonly text: string;
      readonly draftRevision: string;
    }
  | { readonly type: 'canvas.select-tab'; readonly tabId: string };

export function decodeSlotActionV2(value: unknown): SlotActionV2 | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    return null;
  const action = value as Record<string, unknown>;
  switch (action.type) {
    case 'navigate':
      return typeof action.destinationId === 'string'
        ? { type: action.type, destinationId: action.destinationId }
        : null;
    case 'settings.open':
      return typeof action.sectionId === 'string'
        ? { type: action.type, sectionId: action.sectionId }
        : null;
    case 'conversation.open-commands':
    case 'composer.open-templates':
      return { type: action.type };
    case 'composer.insert-text':
      return typeof action.text === 'string' &&
        typeof action.draftRevision === 'string'
        ? {
            type: action.type,
            text: action.text,
            draftRevision: action.draftRevision,
          }
        : null;
    case 'canvas.select-tab':
      return typeof action.tabId === 'string'
        ? { type: action.type, tabId: action.tabId }
        : null;
    default:
      return null;
  }
}
