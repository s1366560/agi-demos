export const SLOT_UI_SCHEMA = 'memstack.slot-ui/1';

export interface SlotUiAction {
  readonly id: string;
  readonly label: string;
  readonly input?: {
    readonly label: string;
    readonly initial: Record<string, unknown>;
  };
}

export interface SlotUiDocument {
  readonly schema: typeof SLOT_UI_SCHEMA;
  readonly title: string;
  readonly actions: readonly SlotUiAction[];
}

export function parseSlotUi(payload: unknown): SlotUiDocument {
  if (!payload || typeof payload !== 'object') throw new Error('slot_ui_schema');
  const record = payload as {
    schema?: unknown;
    title?: unknown;
    actions?: unknown;
  };
  if (record.schema !== SLOT_UI_SCHEMA) throw new Error('slot_ui_schema');
  if (typeof record.title !== 'string' || record.title.length < 1 || record.title.length > 120) {
    throw new Error('slot_ui_title');
  }
  const items = record.actions === undefined ? [] : record.actions;
  if (!Array.isArray(items) || items.length > 16) throw new Error('slot_ui_actions');
  return {
    schema: SLOT_UI_SCHEMA,
    title: record.title,
    actions: items.map((item) => {
      if (!item || typeof item !== 'object') throw new Error('slot_ui_action');
      const action = item as { id?: unknown; label?: unknown; input?: unknown };
      if (typeof action.id !== 'string' || !/^[a-z0-9-]{1,64}$/.test(action.id)) {
        throw new Error('slot_ui_action');
      }
      if (typeof action.label !== 'string' || action.label.length < 1 || action.label.length > 80) {
        throw new Error('slot_ui_action');
      }
      if (action.input === undefined) return { id: action.id, label: action.label };
      if (!action.input || typeof action.input !== 'object') throw new Error('slot_ui_input');
      const form = action.input as { label?: unknown; initial?: unknown };
      if (
        typeof form.label !== 'string' ||
        !form.label.length ||
        form.label.length > 80 ||
        !form.initial ||
        typeof form.initial !== 'object' ||
        Array.isArray(form.initial) ||
        new TextEncoder().encode(JSON.stringify(form.initial)).length > 32768
      )
        throw new Error('slot_ui_input');
      return {
        id: action.id,
        label: action.label,
        input: {
          label: form.label,
          initial: form.initial as Record<string, unknown>,
        },
      };
    }),
  };
}
