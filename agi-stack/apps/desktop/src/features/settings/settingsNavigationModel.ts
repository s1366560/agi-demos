import type { ProjectSummary } from '../../types';

export type NavigableSettingsSection =
  | 'account'
  | 'workspace'
  | 'general'
  | 'appearance'
  | 'notifications'
  | 'models'
  | 'skills'
  | 'plugins'
  | 'agents'
  | 'subagents';

export type SettingsSection = NavigableSettingsSection | 'connection';

export type SettingsGroupId = 'account_context' | 'preferences' | 'ai_resources';

export type SettingsGroupDefinition = {
  id: SettingsGroupId;
  sections: NavigableSettingsSection[];
};

export const SETTINGS_GROUPS: SettingsGroupDefinition[] = [
  { id: 'account_context', sections: ['account', 'workspace'] },
  { id: 'preferences', sections: ['general', 'appearance', 'notifications'] },
  { id: 'ai_resources', sections: ['models', 'skills', 'plugins', 'agents', 'subagents'] },
];

export type SettingsSearchCopy = Record<NavigableSettingsSection, readonly [string, string]>;

export function filterSettingsSections(
  query: string,
  copy: SettingsSearchCopy,
): NavigableSettingsSection[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return SETTINGS_GROUPS.flatMap((group) => group.sections).filter((section) => {
    if (!normalizedQuery) return true;
    const [label, description] = copy[section];
    return `${label} ${description}`.toLocaleLowerCase().includes(normalizedQuery);
  });
}

export function projectsForTenant(
  projects: readonly ProjectSummary[],
  tenantId: string,
): ProjectSummary[] {
  if (!tenantId) return [];
  return projects.filter((project) => project.tenant_id === tenantId);
}
