export type ShortcutPlatform = 'mac' | 'other';

export type ShortcutGroup = 'navigation' | 'composer' | 'general';

export type ShortcutDefinition = {
  id: string;
  labelKey: string;
  chords: { mac: string; other: string };
  group: ShortcutGroup;
};

export type ShortcutGroupSection = {
  group: ShortcutGroup;
  shortcuts: readonly ShortcutDefinition[];
};

export const SHORTCUT_GROUPS: readonly ShortcutGroup[] = [
  'navigation',
  'composer',
  'general',
];

// Every entry mirrors a shortcut that is implemented in the shell today:
// - App.tsx global keydown: Cmd/Ctrl+K and `/` open the command palette,
//   Escape closes open overlays.
// - CommandPalette list: ArrowUp/ArrowDown move, Home/End jump, Enter runs.
// - ChatPanel composer: Enter sends (Shift+Enter inserts a newline),
//   Cmd/Ctrl+Enter sends even while run-input delivery options are present,
//   Cmd/Ctrl+F toggles conversation search.
// - NewThreadComposer: Cmd/Ctrl+Enter sends the new thread.
export const KEYBOARD_SHORTCUTS: readonly ShortcutDefinition[] = [
  {
    id: 'command-palette',
    labelKey: 'shortcuts.action.commandPalette',
    chords: { mac: '⌘ K', other: 'Ctrl K' },
    group: 'navigation',
  },
  {
    id: 'quick-open-palette',
    labelKey: 'shortcuts.action.quickOpenPalette',
    chords: { mac: '/', other: '/' },
    group: 'navigation',
  },
  {
    id: 'palette-move',
    labelKey: 'shortcuts.action.paletteMove',
    chords: { mac: '↑ ↓', other: '↑ ↓' },
    group: 'navigation',
  },
  {
    id: 'palette-jump',
    labelKey: 'shortcuts.action.paletteJump',
    chords: { mac: 'Home End', other: 'Home End' },
    group: 'navigation',
  },
  {
    id: 'palette-run',
    labelKey: 'shortcuts.action.paletteRun',
    chords: { mac: 'Enter', other: 'Enter' },
    group: 'navigation',
  },
  {
    id: 'conversation-search',
    labelKey: 'shortcuts.action.conversationSearch',
    chords: { mac: '⌘ F', other: 'Ctrl F' },
    group: 'navigation',
  },
  {
    id: 'composer-send',
    labelKey: 'shortcuts.action.composerSend',
    chords: { mac: 'Enter', other: 'Enter' },
    group: 'composer',
  },
  {
    id: 'composer-modifier-send',
    labelKey: 'shortcuts.action.composerModifierSend',
    chords: { mac: '⌘ Enter', other: 'Ctrl Enter' },
    group: 'composer',
  },
  {
    id: 'composer-newline',
    labelKey: 'shortcuts.action.composerNewline',
    chords: { mac: '⇧ Enter', other: 'Shift Enter' },
    group: 'composer',
  },
  {
    id: 'show-shortcuts',
    labelKey: 'shortcuts.action.showShortcuts',
    chords: { mac: '⌘ /', other: 'Ctrl /' },
    group: 'general',
  },
  {
    id: 'close-overlay',
    labelKey: 'shortcuts.action.closeOverlay',
    chords: { mac: 'Esc', other: 'Esc' },
    group: 'general',
  },
];

export function detectShortcutPlatform(userAgent?: string, platform?: string): ShortcutPlatform {
  const haystack = `${platform ?? ''} ${userAgent ?? ''}`.toLowerCase();
  return haystack.includes('mac') ? 'mac' : 'other';
}

export function shortcutById(id: string): ShortcutDefinition | undefined {
  return KEYBOARD_SHORTCUTS.find((definition) => definition.id === id);
}

export function shortcutChordFor(
  definition: ShortcutDefinition,
  platform: ShortcutPlatform,
): string {
  return definition.chords[platform];
}

export function shortcutChordSegments(chord: string): readonly string[] {
  return chord.split(/\s+/).filter((segment) => segment.length > 0);
}

export function shortcutGroups(): readonly ShortcutGroupSection[] {
  return SHORTCUT_GROUPS.map((group) => ({
    group,
    shortcuts: KEYBOARD_SHORTCUTS.filter((definition) => definition.group === group),
  }));
}
