import type {
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
  RuntimeMode,
} from '../../types';

export type ResourceSection = 'skills' | 'plugins' | 'agents';
export type ManagedResource = ManagedSkill | ManagedPlugin | ManagedAgentDefinition;
export type ManagedResourceListFilter = 'all' | 'active' | 'attention';
export type ManagedResourceStatus = 'active' | 'disabled' | 'attention';

export type ManagedResourceMeta =
  | { kind: 'text'; value: string }
  | { kind: 'version'; value: string }
  | { kind: 'tool_count'; count: number }
  | { kind: 'skill_count'; count: number };

export type ManagedResourceView = {
  id: string;
  title: string;
  description: string;
  meta: ManagedResourceMeta[];
  status: ManagedResourceStatus;
};

export type ManagedResourceFact = {
  key:
    | 'scope'
    | 'source'
    | 'version'
    | 'updatedAt'
    | 'package'
    | 'kind'
    | 'discovery'
    | 'model'
    | 'project';
  value: string;
};

export type ManagedResourceCapabilityGroup = {
  key: 'tools' | 'providers' | 'skills' | 'channels' | 'mcpServers' | 'fallbackModels';
  values: string[];
};

export type ManagedResourceAction = {
  kind: 'set_skill_status' | 'set_plugin_enabled' | 'set_agent_enabled';
  nextActive: boolean;
};

export function resourceIsActive(section: ResourceSection, item: ManagedResource): boolean {
  return managedResourceStatus(section, item) === 'active';
}

export function managedResourceStatus(
  section: ResourceSection,
  item: ManagedResource,
): ManagedResourceStatus {
  if (section === 'skills') {
    const status = stringValue((item as ManagedSkill).status).toLowerCase();
    if (status === 'active' || status === 'enabled') return 'active';
    if (status === 'disabled' || status === 'inactive') return 'disabled';
    return 'attention';
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    if (!plugin.discovered) return 'attention';
    return plugin.enabled ? 'active' : 'disabled';
  }
  const agent = item as ManagedAgentDefinition;
  if (typeof agent.enabled === 'boolean') return agent.enabled ? 'active' : 'disabled';
  const status = agent.status?.trim().toLowerCase();
  if (status === 'active' || status === 'enabled') return 'active';
  if (status === 'disabled' || status === 'inactive' || status === 'paused') return 'disabled';
  return 'attention';
}

export function filterManagedResources(
  section: ResourceSection,
  items: readonly ManagedResource[],
  query: string,
  filter: ManagedResourceListFilter,
): ManagedResource[] {
  const needle = query.trim().toLowerCase();
  return items.filter((item) => {
    const matchesQuery =
      !needle || managedResourceSearchValues(section, item).some((value) => value.includes(needle));
    const status = managedResourceStatus(section, item);
    const matchesFilter =
      filter === 'all' ||
      (filter === 'active' ? status === 'active' : status !== 'active');
    return matchesQuery && matchesFilter;
  });
}

export function managedResourceView(
  section: ResourceSection,
  item: ManagedResource,
): ManagedResourceView {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    const version = stringValue(skill.version_label) || numericString(skill.current_version);
    return {
      id: skill.id,
      title: skill.name || skill.id,
      description: skill.description || '',
      meta: compactMeta([
        textMeta(skill.scope),
        { kind: 'tool_count', count: cleanStrings(skill.tools).length },
        version ? { kind: 'version', value: version } : null,
      ]),
      status: managedResourceStatus(section, item),
    };
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    const toolCount = toolNames(plugin).length;
    return {
      id: plugin.id,
      title: plugin.name || plugin.id,
      description: plugin.package || plugin.kind || plugin.source || '',
      meta: compactMeta([
        textMeta(plugin.source),
        plugin.version ? { kind: 'version', value: plugin.version } : null,
        toolCount > 0 ? { kind: 'tool_count', count: toolCount } : null,
      ]),
      status: managedResourceStatus(section, item),
    };
  }
  const agent = item as ManagedAgentDefinition;
  const model = agentModel(agent);
  const tools = cleanStrings(agent.allowed_tools);
  const skills = cleanStrings(agent.allowed_skills);
  return {
    id: agent.id,
    title: agent.display_name || agent.name || agent.id,
    description: stringValue(agent.description),
    meta: compactMeta([
      agent.display_name && agent.name !== agent.display_name ? textMeta(agent.name) : null,
      textMeta(model),
      tools.length > 0 ? { kind: 'tool_count', count: tools.length } : null,
      skills.length > 0 ? { kind: 'skill_count', count: skills.length } : null,
    ]),
    status: managedResourceStatus(section, item),
  };
}

export function managedResourceFacts(
  section: ResourceSection,
  item: ManagedResource,
): ManagedResourceFact[] {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return compactFacts([
      fact('scope', skill.scope),
      fact('source', stringValue(skill.source)),
      fact('version', stringValue(skill.version_label) || numericString(skill.current_version)),
      fact('updatedAt', skill.updated_at ?? ''),
    ]);
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return compactFacts([
      fact('source', plugin.source),
      fact('package', plugin.package ?? ''),
      fact('version', plugin.version ?? ''),
      fact('kind', plugin.kind ?? ''),
      fact('discovery', plugin.discovered ? 'discovered' : 'unavailable'),
    ]);
  }
  const agent = item as ManagedAgentDefinition;
  return compactFacts([
    fact('model', agentModel(agent)),
    fact('project', stringValue(agent.project_id)),
    fact('source', stringValue(agent.source)),
    fact('updatedAt', agent.updated_at ?? ''),
  ]);
}

export function managedResourceCapabilityGroups(
  section: ResourceSection,
  item: ManagedResource,
): ManagedResourceCapabilityGroup[] {
  if (section === 'skills') {
    return compactGroups([{ key: 'tools', values: cleanStrings((item as ManagedSkill).tools) }]);
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return compactGroups([
      { key: 'tools', values: toolNames(plugin) },
      { key: 'providers', values: cleanStrings(plugin.providers) },
      { key: 'skills', values: cleanStrings(plugin.skills) },
      { key: 'channels', values: cleanStrings(plugin.channel_types) },
    ]);
  }
  const agent = item as ManagedAgentDefinition;
  return compactGroups([
    { key: 'tools', values: cleanStrings(agent.allowed_tools) },
    { key: 'skills', values: cleanStrings(agent.allowed_skills) },
    { key: 'mcpServers', values: cleanStrings(agent.allowed_mcp_servers) },
    { key: 'fallbackModels', values: cleanStrings(arrayValue(agent.fallback_models)) },
  ]);
}

export function resolveManagedResourceSelection(
  items: readonly ManagedResource[],
  selectedId: string | null,
): ManagedResource | null {
  return items.find((item) => item.id === selectedId) ?? items[0] ?? null;
}

export function managedResourceSnapshotIsCurrent(
  section: ResourceSection,
  contextKey: string,
  loadedSection: ResourceSection | null,
  loadedContextKey: string | null,
): boolean {
  return loadedSection === section && loadedContextKey === contextKey;
}

export function managedResourceAction(
  section: ResourceSection,
  item: ManagedResource,
  canManage: boolean,
  mode: RuntimeMode,
): ManagedResourceAction | null {
  if (!canManage || resourceIsImmutable(section, item, mode)) return null;
  if (section === 'plugins' && !(item as ManagedPlugin).discovered) return null;
  return {
    kind:
      section === 'skills'
        ? 'set_skill_status'
        : section === 'plugins'
          ? 'set_plugin_enabled'
          : 'set_agent_enabled',
    nextActive: !resourceIsActive(section, item),
  };
}

export function managedResourceManagementAllowed(
  mode: RuntimeMode,
  roles: readonly string[],
  section: ResourceSection,
  item: ManagedResource,
): boolean {
  const normalizedRoles = new Set(roles.map((role) => role.trim().toLowerCase()));
  const isAdmin = normalizedRoles.has('admin');
  const isOwner = normalizedRoles.has('owner');
  if (mode === 'local') return isAdmin || isOwner;
  if (section === 'agents') return isAdmin || isOwner;
  if (section === 'plugins') return isAdmin || isOwner;
  const skill = item as ManagedSkill;
  return skill.scope === 'project'
    ? isAdmin || isOwner || normalizedRoles.has('member')
    : isAdmin || isOwner;
}

export function resourceIsImmutable(
  section: ResourceSection,
  item: ManagedResource,
  mode: RuntimeMode,
): boolean {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return skill.is_system_skill === true || skill.scope.trim().toLowerCase() === 'system';
  }
  if (section === 'plugins') {
    return mode === 'local' && (item as ManagedPlugin).source === 'builtin';
  }
  const agent = item as ManagedAgentDefinition;
  return stringValue(agent.source) === 'builtin' || agent.id.startsWith('builtin:');
}

function managedResourceSearchValues(
  section: ResourceSection,
  item: ManagedResource,
): string[] {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return normalizeSearchValues([
      skill.id,
      skill.name,
      skill.description,
      skill.scope,
      stringValue(skill.source),
      ...cleanStrings(skill.tools),
    ]);
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return normalizeSearchValues([
      plugin.id,
      plugin.name,
      plugin.source,
      plugin.package,
      plugin.version,
      plugin.kind,
      ...cleanStrings(plugin.providers),
      ...cleanStrings(plugin.skills),
      ...cleanStrings(plugin.channel_types),
      ...toolNames(plugin),
    ]);
  }
  const agent = item as ManagedAgentDefinition;
  return normalizeSearchValues([
    agent.id,
    agent.name,
    agent.display_name,
    stringValue(agent.description),
    agentModel(agent),
    stringValue(agent.project_id),
    stringValue(agent.source),
    ...cleanStrings(agent.allowed_tools),
    ...cleanStrings(agent.allowed_skills),
    ...cleanStrings(agent.allowed_mcp_servers),
    ...cleanStrings(arrayValue(agent.fallback_models)),
  ]);
}

function agentModel(agent: ManagedAgentDefinition): string {
  return stringValue(agent.model) || agent.model_name || '';
}

function toolNames(plugin: ManagedPlugin): string[] {
  return cleanStrings(
    plugin.tool_definitions?.map((tool) =>
      typeof tool.name === 'string' ? tool.name : '',
    ),
  );
}

function cleanStrings(values: readonly unknown[] | undefined): string[] {
  const seen = new Set<string>();
  return (values ?? [])
    .filter((value): value is string => typeof value === 'string')
    .map((value) => value.trim())
    .filter((value) => Boolean(value) && !seen.has(value) && Boolean(seen.add(value)));
}

function arrayValue(value: unknown): readonly unknown[] {
  return Array.isArray(value) ? value : [];
}

function normalizeSearchValues(values: readonly unknown[]): string[] {
  return values
    .filter((value): value is string => typeof value === 'string')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function numericString(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
}

function textMeta(value: unknown): ManagedResourceMeta | null {
  const text = stringValue(value);
  return text ? { kind: 'text', value: text } : null;
}

function compactMeta(
  values: Array<ManagedResourceMeta | null>,
): ManagedResourceMeta[] {
  return values.filter((value): value is ManagedResourceMeta => value !== null);
}

function fact(key: ManagedResourceFact['key'], value: unknown): ManagedResourceFact | null {
  const text = stringValue(value);
  return text ? { key, value: text } : null;
}

function compactFacts(
  values: Array<ManagedResourceFact | null>,
): ManagedResourceFact[] {
  return values.filter((value): value is ManagedResourceFact => value !== null);
}

function compactGroups(
  groups: ManagedResourceCapabilityGroup[],
): ManagedResourceCapabilityGroup[] {
  return groups.filter((group) => group.values.length > 0);
}
