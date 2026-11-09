/** In-repo contract. This package is not published to a registry. */

export const CONTRIBUTION_SCHEMA = 'memstack.plugin.contributions/1';
export const SLOT_UI_SCHEMA = 'memstack.slot-ui/1';
export const INVOKE_INPUT_OFFSET = 0;
export const INVOKE_OUTPUT_OFFSET = 65536;
export const MAX_INVOKE_OUTPUT_BYTES = 65536;

export const PERMISSIONS = [
  'tools.execute',
  'skills.register',
  'ui.slot',
  'storage.read',
  'storage.write',
] as const;

export type PluginPermission = (typeof PERMISSIONS)[number];

export interface SlotUiAction {
  readonly id: string;
  readonly label: string;
}

export interface SlotUiDocument {
  readonly schema: typeof SLOT_UI_SCHEMA;
  readonly title: string;
  readonly actions: readonly SlotUiAction[];
}

export interface ScanEvidence {
  readonly status: 'unknown' | 'passed' | 'failed';
  readonly reportDigest: string | null;
}

export function parseSlotUi(payload: unknown): SlotUiDocument {
  if (!payload || typeof payload !== 'object') throw new Error('slot_ui_schema');
  const record = payload as { schema?: unknown; title?: unknown; actions?: unknown };
  if (record.schema !== SLOT_UI_SCHEMA) throw new Error('slot_ui_schema');
  if (typeof record.title !== 'string' || record.title.length < 1 || record.title.length > 120) {
    throw new Error('slot_ui_title');
  }
  if (!Array.isArray(record.actions) || record.actions.length > 16) throw new Error('slot_ui_actions');
  const actions = record.actions.map((item) => {
    if (!item || typeof item !== 'object') throw new Error('slot_ui_action');
    const action = item as { id?: unknown; label?: unknown };
    if (typeof action.id !== 'string' || !/^[a-z0-9-]{1,64}$/.test(action.id)) {
      throw new Error('slot_ui_action');
    }
    if (typeof action.label !== 'string' || action.label.length < 1 || action.label.length > 80) {
      throw new Error('slot_ui_action');
    }
    return { id: action.id, label: action.label };
  });
  return { schema: SLOT_UI_SCHEMA, title: record.title, actions };
}
