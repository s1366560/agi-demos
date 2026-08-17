export type UiSlotKind =
  | 'nav_item'
  | 'settings_page'
  | 'conversation_renderer'
  | 'tool_result_renderer'
  | 'composer_action'
  | 'mcp_canvas';

export type PluginTrust = 'builtin' | 'signed' | 'tenant-approved' | 'untrusted';

export type PluginRuntime = 'python-trusted' | 'wasm' | 'mcp' | 'subprocess' | 'frontend';

export interface UiSlotDefinition {
  readonly pluginId: string;
  readonly slot: UiSlotKind;
  readonly id: string;
  readonly moduleRef: string;
  readonly permission: string;
  readonly sandbox: boolean;
}

export interface RegisteredUiSlot extends UiSlotDefinition {
  readonly trust: PluginTrust;
  readonly runtime: PluginRuntime;
}

export class UiSlotRegistrationError extends Error {}

type SlotKey = `${UiSlotKind}:${string}`;

function slotKey(definition: UiSlotDefinition): SlotKey {
  return `${definition.slot}:${definition.id}`;
}

export class UiSlotRegistry {
  private readonly slots = new Map<SlotKey, RegisteredUiSlot>();
  private readonly pluginSlots = new Map<string, Set<SlotKey>>();

  register(
    definition: UiSlotDefinition,
    context: { trust: PluginTrust; runtime: PluginRuntime },
  ): () => void {
    if (context.trust !== 'builtin' && context.trust !== 'signed') {
      throw new UiSlotRegistrationError('External frontend modules are not enabled');
    }
    if (context.runtime !== 'frontend') {
      throw new UiSlotRegistrationError('UI slots require the frontend runtime');
    }
    if (!definition.sandbox) {
      throw new UiSlotRegistrationError('UI renderers must run in a sandbox');
    }
    if (!definition.permission.startsWith('ui.')) {
      throw new UiSlotRegistrationError('UI slot permissions must start with ui.');
    }
    const builtinModule = definition.moduleRef.startsWith('builtin:');
    const signedModule = definition.moduleRef.startsWith('signed:');
    if (!builtinModule && !(signedModule && context.trust === 'signed')) {
      throw new UiSlotRegistrationError(
        'Only builtin or signed frontend modules are allowed',
      );
    }

    const key = slotKey(definition);
    if (this.slots.has(key)) {
      throw new UiSlotRegistrationError(`UI slot already registered: ${definition.id}`);
    }
    const registered: RegisteredUiSlot = { ...definition, ...context };
    this.slots.set(key, registered);
    const owned = this.pluginSlots.get(definition.pluginId) ?? new Set<SlotKey>();
    owned.add(key);
    this.pluginSlots.set(definition.pluginId, owned);

    return () => {
      if (this.slots.get(key) !== registered) return;
      this.slots.delete(key);
      this.pluginSlots.get(definition.pluginId)?.delete(key);
    };
  }

  list(slot?: UiSlotKind): RegisteredUiSlot[] {
    return [...this.slots.values()]
      .filter((definition) => !slot || definition.slot === slot)
      .sort((left, right) =>
        `${left.slot}:${left.id}`.localeCompare(`${right.slot}:${right.id}`),
      );
  }

  listByPlugin(pluginId: string): RegisteredUiSlot[] {
    const keys = this.pluginSlots.get(pluginId);
    if (!keys) return [];
    return [...keys]
      .map((key) => this.slots.get(key))
      .filter((definition): definition is RegisteredUiSlot => Boolean(definition))
      .sort((left, right) => left.id.localeCompare(right.id));
  }
}
