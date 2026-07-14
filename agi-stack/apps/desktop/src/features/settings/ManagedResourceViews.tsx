import { Badge, Button, Text } from '@radix-ui/themes';
import {
  ComponentInstanceIcon,
  MagicWandIcon,
  PersonIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
} from '../../types';

export type ResourceSection = 'skills' | 'plugins' | 'agents';
export type ManagedResource = ManagedSkill | ManagedPlugin | ManagedAgentDefinition;

export function resourceIsActive(
  section: ResourceSection,
  item: ManagedResource,
): boolean {
  if (section === 'skills') return (item as ManagedSkill).status === 'active';
  if (section === 'plugins') return (item as ManagedPlugin).enabled;
  return (item as ManagedAgentDefinition).enabled !== false;
}

const resourceLabelKey: Record<ResourceSection, string> = {
  skills: 'settings.skills',
  plugins: 'settings.plugins',
  agents: 'settings.agents',
};

export function ResourceRow({
  section,
  item,
  selected,
  busy,
  onSelect,
  onAction,
}: {
  section: ResourceSection;
  item: ManagedResource;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onAction: () => void;
}) {
  const { t } = useI18n();
  const view = resourceView(section, item, t);
  return (
    <article className={`settings-resource-row ${selected ? 'selected' : ''}`}>
      <button type="button" className="settings-resource-main" onClick={onSelect}>
        <span className="settings-resource-icon">
          <view.Icon />
        </span>
        <div>
          <strong>{view.name}</strong>
          <p>{view.description}</p>
          <div className="settings-resource-meta">
            {view.meta.map((value) => (
              <span key={value}>{value}</span>
            ))}
          </div>
        </div>
      </button>
      <aside>
        <Badge color={view.active ? 'green' : 'gray'} variant="soft">
          {view.status}
        </Badge>
        <Button size="1" variant="soft" loading={busy} onClick={onAction}>
          {view.active ? t('settings.disable') : t('settings.enable')}
        </Button>
      </aside>
    </article>
  );
}

export function ResourceDetail({
  section,
  item,
}: {
  section: ResourceSection;
  item: ManagedResource;
}) {
  const { t } = useI18n();
  const view = resourceView(section, item, t);
  const facts = resourceFacts(section, item, t);
  const capabilities = resourceCapabilities(section, item);
  return (
    <aside className="settings-resource-detail">
      <header>
        <span className="settings-resource-icon">
          <view.Icon />
        </span>
        <div>
          <Text size="1" color="gray">
            {t(resourceLabelKey[section]).toUpperCase()}
          </Text>
          <h2>{view.name}</h2>
          <p>{view.description}</p>
        </div>
        <Badge color={view.active ? 'green' : 'gray'} variant="soft">
          {view.status}
        </Badge>
      </header>
      <dl>
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <section>
        <Text size="1" color="gray">
          {t('settings.capabilitiesRelationships').toUpperCase()}
        </Text>
        {capabilities.length > 0 ? (
          <div className="settings-detail-chips">
            {capabilities.map((capability, index) => (
              <span key={`${capability}-${index}`}>{capability}</span>
            ))}
          </div>
        ) : (
          <p className="settings-detail-empty">{t('settings.noCapabilities')}</p>
        )}
      </section>
    </aside>
  );
}

export function SettingsState({
  text,
  detail,
  error = false,
}: {
  text: string;
  detail?: string;
  error?: boolean;
}) {
  return (
    <div className={`settings-resource-state ${error ? 'error' : ''}`}>
      <strong>{text}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function resourceFacts(
  section: ResourceSection,
  item: ManagedResource,
  t: (key: string) => string,
): Array<[string, string]> {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return [
      [t('settings.scope'), skill.scope],
      [t('settings.version'), `v${skill.current_version ?? 0}`],
      [t('settings.status'), skill.status],
      [t('settings.source'), skill.is_system_skill ? t('settings.system') : t('settings.managed')],
    ];
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return [
      [t('settings.source'), plugin.source],
      [t('settings.package'), plugin.package || t('settings.builtIn')],
      [t('settings.version'), plugin.version || t('settings.unversioned')],
      [
        t('settings.discovery'),
        plugin.discovered ? t('settings.discovered') : t('settings.unavailable'),
      ],
    ];
  }
  const agent = item as ManagedAgentDefinition;
  return [
    [t('settings.model'), agent.model_name || t('settings.tenantDefault')],
    [
      t('settings.status'),
      agent.enabled === false ? t('settings.disabled') : agent.status || t('settings.active'),
    ],
    [t('settings.tools'), String(agent.allowed_tools?.length ?? 0)],
    [t('settings.skills'), String(agent.allowed_skills?.length ?? 0)],
  ];
}

function resourceCapabilities(section: ResourceSection, item: ManagedResource): string[] {
  if (section === 'skills') return (item as ManagedSkill).tools.slice(0, 20);
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return [
      ...(plugin.providers ?? []),
      ...(plugin.skills ?? []),
      ...(plugin.channel_types ?? []),
      ...(plugin.tool_definitions ?? []).map((tool) => String(tool.name ?? 'tool')),
    ].slice(0, 20);
  }
  const agent = item as ManagedAgentDefinition;
  return [
    ...(agent.allowed_tools ?? []),
    ...(agent.allowed_skills ?? []),
    ...(agent.allowed_mcp_servers ?? []),
  ].slice(0, 20);
}

function resourceView(
  section: ResourceSection,
  item: ManagedResource,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (section === 'skills') {
    const skill = item as ManagedSkill;
    return {
      name: skill.name,
      description: skill.description,
      status: skill.status,
      active: skill.status === 'active',
      meta: [
        skill.scope,
        t('settings.toolCount', { count: skill.tools.length }),
        `v${skill.current_version ?? 0}`,
      ],
      Icon: MagicWandIcon,
    };
  }
  if (section === 'plugins') {
    const plugin = item as ManagedPlugin;
    return {
      name: plugin.name,
      description: plugin.package || plugin.kind || plugin.source,
      status: plugin.enabled ? t('settings.active') : t('settings.disabled'),
      active: plugin.enabled,
      meta: [
        plugin.source,
        plugin.version,
        t('settings.toolCount', { count: plugin.tool_definitions?.length ?? 0 }),
      ].filter(Boolean) as string[],
      Icon: ComponentInstanceIcon,
    };
  }
  const agent = item as ManagedAgentDefinition;
  return {
    name: agent.name,
    description: agent.display_name || agent.system_prompt || agent.model_name || agent.id,
    status:
      agent.enabled === false
        ? t('settings.disabled')
        : agent.status || t('settings.active'),
    active: agent.enabled !== false,
    meta: [
      agent.model_name,
      t('settings.toolCount', { count: agent.allowed_tools?.length ?? 0 }),
      t('settings.skillCount', { count: agent.allowed_skills?.length ?? 0 }),
    ].filter(Boolean) as string[],
    Icon: PersonIcon,
  };
}
