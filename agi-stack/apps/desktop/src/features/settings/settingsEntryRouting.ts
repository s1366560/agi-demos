import type { SettingsSection } from './settingsNavigationModel';

export type SettingsEntry =
  | 'sidebar'
  | 'sidebar_notifications'
  | 'workspace_overview'
  | 'profile_workspace_switch'
  | 'browser_integration'
  | 'runtime_connection';

const sectionByEntry = {
  sidebar: 'account',
  sidebar_notifications: 'notifications',
  workspace_overview: 'workspace',
  profile_workspace_switch: 'workspace',
  browser_integration: 'browser',
  runtime_connection: 'connection',
} as const satisfies Record<SettingsEntry, SettingsSection>;

export function settingsSectionForEntry(entry: SettingsEntry): SettingsSection {
  return sectionByEntry[entry];
}
