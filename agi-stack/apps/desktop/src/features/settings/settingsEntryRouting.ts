import type { SettingsSection } from './SettingsWindow';

export type SettingsEntry = 'sidebar' | 'workspace_overview' | 'runtime_connection';

const sectionByEntry = {
  sidebar: 'account',
  workspace_overview: 'workspace',
  runtime_connection: 'connection',
} as const satisfies Record<SettingsEntry, SettingsSection>;

export function settingsSectionForEntry(entry: SettingsEntry): SettingsSection {
  return sectionByEntry[entry];
}
