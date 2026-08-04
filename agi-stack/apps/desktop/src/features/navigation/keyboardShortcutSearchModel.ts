import {
  KEYBOARD_SHORTCUTS,
  SHORTCUT_GROUPS,
  shortcutChordFor,
  type ShortcutDefinition,
  type ShortcutGroupSection,
  type ShortcutPlatform,
} from './keyboardShortcutModel';

// Canonical modifier tokens in a fixed order so combos from catalog chords and
// live keypresses compare as plain strings (e.g. 'meta+alt+u').
const MODIFIER_ORDER = ['meta', 'ctrl', 'alt', 'shift'] as const;
type CanonicalModifier = (typeof MODIFIER_ORDER)[number];

const MODIFIER_ALIASES: Record<string, CanonicalModifier> = {
  '⌘': 'meta',
  cmd: 'meta',
  command: 'meta',
  meta: 'meta',
  '⌃': 'ctrl',
  ctrl: 'ctrl',
  control: 'ctrl',
  '⌥': 'alt',
  alt: 'alt',
  option: 'alt',
  '⇧': 'shift',
  shift: 'shift',
};

const KEY_ALIASES: Record<string, string> = {
  '↵': 'enter',
  return: 'enter',
  esc: 'escape',
  '↑': 'arrowup',
  '↓': 'arrowdown',
  '←': 'arrowleft',
  '→': 'arrowright',
  spacebar: 'space',
};

export type ShortcutKeypress = Pick<
  KeyboardEvent,
  'key' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey'
>;

export type ShortcutSearchLabelResolver = (definition: ShortcutDefinition) => string;

function normalizeKeyToken(token: string): string {
  const lowered = token.toLowerCase();
  return KEY_ALIASES[lowered] ?? lowered;
}

function comboString(modifiers: readonly CanonicalModifier[], key: string): string {
  const ordered = MODIFIER_ORDER.filter((modifier) => modifiers.includes(modifier));
  return [...ordered, key].join('+');
}

// Parse a display chord ('⌘ ⌥ U', 'Ctrl Alt U', '↑ ↓', 'Home End') into the
// list of canonical combos it represents. Modifier tokens bind to the next
// key token; consecutive key tokens are alternatives for the same action.
export function shortcutChordCombos(chord: string): readonly string[] {
  const combos: string[] = [];
  let pendingModifiers: CanonicalModifier[] = [];
  for (const segment of chord.split(/\s+/).filter((part) => part.length > 0)) {
    const modifier = MODIFIER_ALIASES[segment.toLowerCase()];
    if (modifier) {
      pendingModifiers = [...pendingModifiers, modifier];
      continue;
    }
    combos.push(comboString(pendingModifiers, normalizeKeyToken(segment)));
    pendingModifiers = [];
  }
  return combos;
}

// Normalize a live keypress into a canonical combo. Pure modifier presses
// return null so the search box can ignore them while the combo is being
// composed.
export function keypressCombo(event: ShortcutKeypress): string | null {
  if (MODIFIER_ALIASES[event.key.toLowerCase()]) return null;
  const modifiers: CanonicalModifier[] = [];
  if (event.metaKey) modifiers.push('meta');
  if (event.ctrlKey) modifiers.push('ctrl');
  if (event.altKey) modifiers.push('alt');
  if (event.shiftKey) modifiers.push('shift');
  const key = normalizeKeyToken(event.key === ' ' ? 'space' : event.key);
  return comboString(modifiers, key);
}

// Filter the shortcut catalog by a free-text query (matches the localized
// label, the label key, and the chord text on either platform) and/or a
// captured keypress combo (matches the platform-resolved binding). Groups
// left empty by the filter are omitted.
export function filterShortcutGroups(options: {
  query: string;
  combo: string | null;
  platform: ShortcutPlatform;
  resolveLabel: ShortcutSearchLabelResolver;
}): ShortcutGroupSection[] {
  const normalizedQuery = options.query.trim().toLowerCase();
  const matches = (definition: ShortcutDefinition): boolean => {
    if (options.combo) {
      const combos = shortcutChordCombos(shortcutChordFor(definition, options.platform));
      if (!combos.includes(options.combo)) return false;
    }
    if (normalizedQuery) {
      const haystack =
        `${options.resolveLabel(definition)} ${definition.labelKey} ` +
        `${definition.chords.mac} ${definition.chords.other}`;
      if (!haystack.toLowerCase().includes(normalizedQuery)) return false;
    }
    return true;
  };
  return SHORTCUT_GROUPS.map((group) => ({
    group,
    shortcuts: KEYBOARD_SHORTCUTS.filter(
      (definition) => definition.group === group && matches(definition),
    ),
  })).filter((section) => section.shortcuts.length > 0);
}
