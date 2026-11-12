export interface SignedSlotActionV2 {
  readonly id: string;
  readonly label: string;
}

export interface SignedSlotUiV2 {
  readonly schema: 'memstack.slot-ui/1';
  readonly title: string;
  readonly actions: readonly SignedSlotActionV2[];
}

export function parseSlotUi(payload: unknown): SignedSlotUiV2 {
  if (!payload || typeof payload !== 'object') throw new Error('slot_ui_schema');
  const record = payload as { schema?: unknown; title?: unknown; actions?: unknown };
  if (record.schema !== 'memstack.slot-ui/1') throw new Error('slot_ui_schema');
  if (typeof record.title !== 'string' || record.title.length < 1 || record.title.length > 120) {
    throw new Error('slot_ui_title');
  }
  if (!Array.isArray(record.actions) || record.actions.length > 16) throw new Error('slot_ui_actions');
  return {
    schema: 'memstack.slot-ui/1',
    title: record.title,
    actions: record.actions.map((item) => {
      if (!item || typeof item !== 'object') throw new Error('slot_ui_action');
      const action = item as { id?: unknown; label?: unknown };
      if (typeof action.id !== 'string' || !/^[a-z0-9-]{1,64}$/.test(action.id)) {
        throw new Error('slot_ui_action');
      }
      if (typeof action.label !== 'string' || action.label.length < 1 || action.label.length > 80) {
        throw new Error('slot_ui_action');
      }
      return { id: action.id, label: action.label };
    }),
  };
}
