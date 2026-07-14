import { useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  BarChartIcon,
  CheckCircledIcon,
  CodeIcon,
  ComponentInstanceIcon,
  CopyIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  ExternalLinkIcon,
  FileTextIcon,
  GearIcon,
  IdCardIcon,
  InfoCircledIcon,
  LightningBoltIcon,
  Link2Icon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  MagicWandIcon,
  MixerHorizontalIcon,
  Pencil1Icon,
  PersonIcon,
  PlayIcon,
  PlusIcon,
  ReloadIcon,
  RocketIcon,
  StackIcon,
  TargetIcon,
} from '@radix-ui/react-icons';

import { Dialog } from './Dialog';
import { ModelProviderWorkspace } from './ModelProviderWorkspace';
import { useI18n } from '../i18n';
import { managementCatalog } from '../managementData';

const categoryMeta = {
  models: {
    label: 'Models',
    singular: 'model',
    eyebrow: 'Inference',
    description: 'Providers, routing, budgets, and runtime health',
    Icon: CubeIcon,
    tabs: ['Overview', 'Configuration', 'Usage', 'Audit'],
  },
  skills: {
    label: 'Skills',
    singular: 'skill',
    eyebrow: 'Capabilities',
    description: 'Reusable instructions, tools, and validation',
    Icon: MagicWandIcon,
    tabs: ['Overview', 'Instructions', 'Validation', 'Versions'],
  },
  plugins: {
    label: 'Plugins',
    singular: 'plugin',
    eyebrow: 'Connections',
    description: 'External systems, permissions, and tools',
    Icon: ComponentInstanceIcon,
    tabs: ['Overview', 'Permissions', 'Tools', 'Activity'],
  },
  agents: {
    label: 'Agents',
    singular: 'agent',
    eyebrow: 'Workforce',
    description: 'Roles, models, capabilities, and autonomy',
    Icon: PersonIcon,
    tabs: ['Overview', 'Behavior', 'Capabilities', 'Evaluations'],
  },
};

const statusKind = {
  healthy: 'positive',
  active: 'positive',
  connected: 'positive',
  attention: 'warning',
  update: 'warning',
  draft: 'neutral',
  paused: 'neutral',
  available: 'neutral',
  offline: 'negative',
};

function StatusPill({ item }) {
  const { t } = useI18n();
  return <span className={`management-status ${statusKind[item.status] ?? 'neutral'}`}><i />{t(item.statusLabel)}</span>;
}

function Fact({ label, value, accent = false }) {
  return <div className="management-fact"><span>{label}</span><b className={accent ? 'accent' : ''}>{value}</b></div>;
}

function ChipList({ items = [] }) {
  const { t } = useI18n();
  return <div className="management-chips">{items.map((item) => <span key={item}>{t(item)}</span>)}</div>;
}

function OverviewPanel({ category, item }) {
  const { t } = useI18n();
  if (category === 'models') {
    return (
      <>
        <section className="management-metric-grid">
          <Fact label={t('Success rate')} value={item.success} accent />
          <Fact label={t('Latency')} value={item.latency} />
          <Fact label={t('Spend')} value={item.spend} />
          <Fact label={t('Used by')} value={`${item.usedBy} ${t('agents')}`} />
        </section>
        <section className="management-card routing-map">
          <header><div><span>{t('ROUTING')}</span><h3>{t('Runtime chain')}</h3></div><MixerHorizontalIcon /></header>
          <div className="routing-node primary-node"><CubeIcon /><span><b>{item.name}</b><small>{t('Primary model')}</small></span></div>
          <ArrowRightIcon className="routing-arrow" />
          <div className="routing-node"><ReloadIcon /><span><b>{item.fallback}</b><small>{t('Automatic fallback')}</small></span></div>
          <p>{t('Fallback activates on provider errors, timeout, or budget policy. Agent-level overrides stay visible in the audit log.')}</p>
        </section>
        <section className="management-card relation-card"><header><div><span>{t('RELATIONSHIPS')}</span><h3>{t('Agents using this model')}</h3></div><Link2Icon /></header><RelationRows rows={[`Atlas · ${t('Primary')}`, `Dev · ${t('Primary')}`, `Review guardian · ${t('Fallback')}`]} /></section>
      </>
    );
  }

  if (category === 'skills') {
    return (
      <>
        <section className="management-metric-grid three">
          <Fact label={t('Validation')} value={item.success} accent />
          <Fact label={t('Current version')} value={item.version} />
          <Fact label={t('Used by')} value={`${item.usedBy} ${t('agents')}`} />
        </section>
        <section className="management-card instruction-preview"><header><div><span>{t('SKILL CONTRACT')}</span><h3>{t('What this skill does')}</h3></div><FileTextIcon /></header><p>{t(item.instructions)}</p><div className="contract-grid"><Fact label={t('Default model')} value={item.model} /><Fact label={t('Owner')} value={item.owner} /></div></section>
        <section className="management-card"><header><div><span>{t('TOOL BOUNDARY')}</span><h3>{t('Allowed tools')}</h3></div><LockClosedIcon /></header><ChipList items={item.tools} /></section>
      </>
    );
  }

  if (category === 'plugins') {
    return (
      <>
        <section className="management-metric-grid three">
          <Fact label={t('Agents')} value={item.usedBy ? `${item.usedBy} using` : 'Not in use'} />
          <Fact label={t('Activity')} value={item.events} accent={item.usedBy > 0} />
          <Fact label={t('Updates')} value={item.updated} />
        </section>
        <section className="management-card permission-summary"><header><div><span>{t('DATA ACCESS')}</span><h3>{t('Granted permissions')}</h3></div><LockClosedIcon /></header><CheckRows rows={item.permissions} /></section>
        <section className="management-card"><header><div><span>{t('CAPABILITIES')}</span><h3>{t('Tools exposed to agents')}</h3></div><StackIcon /></header><ChipList items={item.tools} /></section>
      </>
    );
  }

  return (
    <>
      <section className="management-metric-grid three">
        <Fact label={t('Outcome quality')} value={item.success} accent />
        <Fact label={t('Runs this month')} value={String(item.usedBy)} />
        <Fact label={t('Autonomy')} value={item.autonomy} />
      </section>
      <section className="agent-assembly">
        <article className="management-card"><header><div><span>{t('REASONING')}</span><h3>{t('Model routing')}</h3></div><CubeIcon /></header><RelationRows rows={[`${item.model} · ${t('Primary')}`, `${item.fallback} · ${t('Fallback')}`]} /></article>
        <article className="management-card"><header><div><span>{t('CONTEXT')}</span><h3>{t('Memory boundary')}</h3></div><IdCardIcon /></header><p>{item.memory}. Context is isolated by scope and recorded on each run.</p></article>
      </section>
      <section className="management-card"><header><div><span>{t('CAPABILITY GRAPH')}</span><h3>{t('Skills and plugin dependencies')}</h3></div><Link2Icon /></header><div className="capability-groups"><div><small>{t('SKILLS')}</small><ChipList items={item.skills} /></div><div><small>{t('PLUGINS')}</small><ChipList items={item.plugins} /></div></div></section>
    </>
  );
}

function RelationRows({ rows }) {
  return <div className="management-relation-rows">{rows.map((row) => <button type="button" key={row}><PersonIcon /><span>{row}</span><ArrowRightIcon /></button>)}</div>;
}

function CheckRows({ rows }) {
  return <div className="management-check-rows">{rows.map((row) => <div key={row}><CheckCircledIcon /><span>{row}</span></div>)}</div>;
}

function GenericTabPanel({ category, tab, item, editing, onEditingChange, onToast }) {
  const { t } = useI18n();
  if (tab === 'Configuration' || tab === 'Behavior' || tab === 'Instructions') {
    const isModel = category === 'models';
    const isAgent = category === 'agents';
    return (
      <section className="management-form-card">
        <header><div><span>{t(tab).toUpperCase()}</span><h3>{t(isModel ? 'Runtime configuration' : isAgent ? 'Agent operating contract' : 'Skill instructions')}</h3></div><button type="button" onClick={() => onEditingChange(!editing)}><Pencil1Icon />{t(editing ? 'Cancel edit' : 'Edit')}</button></header>
        <div className="management-form-grid">
          <label><span>{t(isModel ? 'Provider model ID' : isAgent ? 'Role' : 'Skill name')}</span><input disabled={!editing} defaultValue={isModel ? item.modelId : isAgent ? item.role : item.name} /></label>
          <label><span>{t(isModel ? 'Fallback model' : isAgent ? 'Primary model' : 'Default model')}</span><input disabled={!editing} defaultValue={isModel ? item.fallback : isAgent ? item.model : item.model} /></label>
          <label className="wide"><span>{t(isModel ? 'Runtime policy' : isAgent ? 'Operating instructions' : 'Instructions')}</span><textarea disabled={!editing} defaultValue={isModel ? `Temperature ${item.temperature}. Timeout ${item.timeout}. Route failures to ${item.fallback}.` : isAgent ? `Act as ${item.role}. ${item.autonomy}. Keep context inside ${item.memory.toLowerCase()}.` : item.instructions} /></label>
          <label><span>{t(isModel ? 'Monthly budget' : isAgent ? 'Memory' : 'Scope')}</span><input disabled={!editing} defaultValue={isModel ? item.budget : isAgent ? item.memory : item.scope} /></label>
          <label><span>{t(isModel ? 'Visibility' : isAgent ? 'Approval policy' : 'Published version')}</span><input disabled={!editing} defaultValue={isModel ? item.scope : isAgent ? item.autonomy : item.version} /></label>
        </div>
        {editing ? <footer><span><InfoCircledIcon /> Changes create a new audited configuration version.</span><button className="primary" type="button" onClick={() => { onEditingChange(false); onToast(`${item.name} configuration saved.`); }}><CheckCircledIcon /> {t('Save changes')}</button></footer> : null}
      </section>
    );
  }

  if (['Usage', 'Activity', 'Evaluations', 'Validation'].includes(tab)) {
    return (
      <>
        <section className="management-metric-grid three">
          <Fact label={t('30-day activity')} value={category === 'plugins' ? item.events : `${Math.max(item.usedBy * 4, 12)} runs`} accent />
          <Fact label={t('Success')} value={item.success ?? '99.1%'} />
          <Fact label={t('Last event')} value="18 minutes ago" />
        </section>
        <section className="management-card activity-card"><header><div><span>{t('RECENT SIGNALS')}</span><h3>{t(tab)} timeline</h3></div><ActivityLogIcon /></header>{['Configuration verified', 'Completed an approved task', 'Policy and permission check passed'].map((event, index) => <div className="activity-row" key={event}><span className={index === 2 ? 'warning' : ''}><CheckCircledIcon /></span><div><b>{t(event)}</b><small>{index + 1} hour{index ? 's' : ''} ago · Alex Chen</small></div><button type="button"><ExternalLinkIcon /></button></div>)}</section>
      </>
    );
  }

  if (tab === 'Permissions') {
    return <section className="management-card permission-detail"><header><div><span>{t('PERMISSION SET')}</span><h3>{t('Least-privilege access')}</h3></div><LockClosedIcon /></header><CheckRows rows={item.permissions} /><div className="permission-note"><ExclamationTriangleIcon /><p>Write actions always require the agent's run policy and human approval boundary. Plugin installation never expands an agent's permissions automatically.</p></div></section>;
  }

  if (tab === 'Capabilities' || tab === 'Tools') {
    const primary = category === 'agents' ? item.skills : item.tools;
    const secondary = category === 'agents' ? item.plugins : item.permissions;
    return <section className="management-card capability-detail"><header><div><span>{t('DEPENDENCY GRAPH')}</span><h3>{t('Available capabilities')}</h3></div><StackIcon /></header><div className="capability-groups"><div><small>{t(category === 'agents' ? 'SKILLS' : 'TOOLS')}</small><ChipList items={primary} /></div><div><small>{t(category === 'agents' ? 'PLUGIN DEPENDENCIES' : 'GUARDRAILS')}</small><ChipList items={secondary} /></div></div></section>;
  }

  if (tab === 'Audit' || tab === 'Versions') {
    return <section className="management-card version-list"><header><div><span>{t('CHANGE HISTORY')}</span><h3>{t('Audited versions')}</h3></div><ActivityLogIcon /></header>{['Current configuration', 'Policy update', 'Initial workspace release'].map((name, index) => <div key={name}><span>{index === 0 ? item.version ?? 'v4.8.1' : `v${Math.max(1, 3 - index)}.${index}.0`}</span><section><b>{t(name)}</b><small>{index === 0 ? t('Today') : `${index * 6} days ago`} · Alex Chen</small></section><button type="button">{t('View diff')}</button></div>)}</section>;
  }

  return <OverviewPanel category={category} item={item} />;
}

function CreateResourceDialog({ category, onClose, onCreate }) {
  const { t } = useI18n();
  const meta = categoryMeta[category];
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  return (
    <Dialog title={`${t('Create draft')} · ${t(meta.singular)}`} onClose={onClose}>
      <form className="management-create-form" onSubmit={(event) => { event.preventDefault(); onCreate({ name, description }); }}>
        <div className="creation-callout"><meta.Icon /><span><b>{t('Start with a governed draft')}</b><small>Configure scope and dependencies before publishing to the workspace.</small></span></div>
        <label><span>{t('Name')}</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder={`New ${meta.singular} name`} /></label>
        <label><span>{t('Description')}</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What should teammates and agents know about it?" /></label>
        <div className="creation-grid"><label><span>{t('Scope')}</span><button type="button" className="select-field">{t('Workspace')} <span>⌄</span></button></label><label><span>{t('Initial state')}</span><button type="button" className="select-field">{t('Draft')} <span>⌄</span></button></label></div>
        <div className="dialog-actions"><button type="button" onClick={onClose}>{t('Cancel')}</button><button className="primary" type="submit" disabled={!name.trim()}><PlusIcon /> {t('Create draft')}</button></div>
      </form>
    </Dialog>
  );
}

export function ManagementWorkspace({ onToast, embedded = false, category: controlledCategory }) {
  const { t } = useI18n();
  const [internalCategory, setInternalCategory] = useState('models');
  const category = controlledCategory ?? internalCategory;
  const [catalog, setCatalog] = useState(() => managementCatalog);
  const [selectedIds, setSelectedIds] = useState({ models: 'gpt-55', skills: 'competitive-research', plugins: 'github', agents: 'atlas' });
  const [tab, setTab] = useState('Overview');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('All');
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const meta = categoryMeta[category];
  const items = catalog[category];
  const filteredItems = useMemo(() => items.filter((item) => {
    const matchesSearch = `${item.name} ${item.description} ${item.meta}`.toLowerCase().includes(query.toLowerCase());
    const matchesFilter = filter === 'All' || (filter === 'Active' && ['healthy', 'active', 'connected'].includes(item.status)) || (filter === 'Attention' && ['attention', 'update', 'offline'].includes(item.status));
    return matchesSearch && matchesFilter;
  }), [filter, items, query]);
  const selected = items.find((item) => item.id === selectedIds[category]) ?? filteredItems[0] ?? items[0];
  const SelectedIcon = meta.Icon;

  if (category === 'models') {
    return <ModelProviderWorkspace onToast={onToast} />;
  }

  function changeCategory(nextCategory) {
    setInternalCategory(nextCategory);
    setTab('Overview');
    setQuery('');
    setFilter('All');
    setEditing(false);
  }

  function updateStatus(nextStatus, nextLabel, message) {
    setCatalog((current) => ({ ...current, [category]: current[category].map((item) => item.id === selected.id ? { ...item, status: nextStatus, statusLabel: nextLabel } : item) }));
    onToast(message);
  }

  function primaryAction() {
    if (category === 'plugins') {
      if (selected.status === 'available') updateStatus('connected', 'Connected', `${selected.name} installed and connected.`);
      else if (selected.status === 'update') updateStatus('connected', 'Connected', `${selected.name} updated to the latest version.`);
      else updateStatus('available', 'Disabled', `${selected.name} disabled for new agent runs.`);
      return;
    }
    if (category === 'agents') {
      const enabling = selected.status !== 'active';
      updateStatus(enabling ? 'active' : 'paused', enabling ? 'Active' : 'Paused', `${selected.name} ${enabling ? 'enabled' : 'paused'}.`);
      return;
    }
    if (category === 'skills') {
      onToast(`${selected.name} validation passed in 2.4 seconds.`);
      return;
    }
    setTab('Configuration');
    setEditing(true);
  }

  const actionLabel = t(category === 'plugins' ? selected.status === 'available' ? 'Install plugin' : selected.status === 'update' ? 'Update plugin' : 'Disable plugin' : category === 'agents' ? selected.status === 'active' ? 'Pause agent' : 'Enable agent' : category === 'skills' ? 'Run validation' : 'Edit config');

  function createResource(draft) {
    const id = `created-${category}-${Date.now()}`;
    const base = {
      id,
      name: draft.name,
      description: draft.description || `New ${meta.singular} draft ready for configuration.`,
      status: 'draft',
      statusLabel: 'Draft',
      meta: 'Draft · not published',
      scope: 'Workspace',
      usedBy: 0,
      tags: ['Draft'],
      provider: 'Not configured', modelId: 'Not configured', latency: 'No runs', spend: '$0.00', success: 'Not evaluated', fallback: 'Not configured', temperature: '0.2', timeout: '120 seconds', budget: 'Not set',
      owner: 'Alex Chen', updated: 'Just now', version: '0.1.0', model: 'GPT-5.5', tools: ['No tools selected'], instructions: 'Add instructions before publishing this draft.',
      publisher: 'Workspace draft', permissions: ['No permissions granted'], events: 'No activity',
      role: 'New agent role', autonomy: 'Plan approval required', memory: 'Task-only memory', skills: ['No skills selected'], plugins: ['No plugins selected'],
    };
    setCatalog((current) => ({ ...current, [category]: [base, ...current[category]] }));
    setSelectedIds((current) => ({ ...current, [category]: id }));
    setCreating(false);
    setTab('Overview');
    onToast(`${draft.name} draft created.`);
  }

  return (
    <main className={`management-workspace ${embedded ? 'embedded' : ''}`}>
      {!embedded ? (
        <aside className="management-categories">
          <header><span>MANAGE</span><h1>{t('Workspace')}</h1><p>Govern the building blocks every agent can use.</p></header>
          <nav aria-label="Management categories">
            {Object.entries(categoryMeta).map(([key, value]) => <button className={category === key ? 'active' : ''} type="button" key={key} onClick={() => changeCategory(key)}><value.Icon /><span><b>{t(value.label)}</b><small>{value.description}</small></span><em>{catalog[key].length}</em></button>)}
          </nav>
          <section className="governance-note"><LockClosedIcon /><span><b>Workspace governed</b><small>All changes are versioned and auditable.</small></span></section>
        </aside>
      ) : null}

      <section className="management-catalog">
        <header><div><span>{t(meta.eyebrow)}</span><h2>{t(meta.label)}</h2></div><button className="icon-button management-add" type="button" onClick={() => setCreating(true)} aria-label={`${t('Create draft')} ${t(meta.singular)}`}><PlusIcon /></button></header>
        <label className="management-search"><MagnifyingGlassIcon /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`${t('nav.search')} ${t(meta.label)}`} /></label>
        <div className="management-filters">{['All', 'Active', 'Attention'].map((value) => <button className={filter === value ? 'active' : ''} type="button" key={value} onClick={() => setFilter(value)}>{t(value)}</button>)}</div>
        <div className="catalog-count"><span>{filteredItems.length} {t(meta.label)}</span><button type="button">{t('Recently updated')}</button></div>
        <div className="management-item-list">
          {filteredItems.map((item) => <button className={`management-item ${selected.id === item.id ? 'selected' : ''}`} type="button" key={item.id} onClick={() => { setSelectedIds((current) => ({ ...current, [category]: item.id })); setTab('Overview'); setEditing(false); }}><span className="management-item-icon"><SelectedIcon /></span><span className="management-item-copy"><b>{item.name}</b><small>{t(item.description)}</small><em>{t(item.meta)}</em></span><StatusPill item={item} /></button>)}
          {!filteredItems.length ? <div className="empty-catalog"><MagnifyingGlassIcon /><b>{t('No matches')}</b><span>{t('Try another name or clear the status filter.')}</span></div> : null}
        </div>
      </section>

      <section className="management-detail">
        <header className="management-detail-topbar"><div className="breadcrumb"><span>{t('settings.title')}</span><span>/</span><span>{t(meta.label)}</span><span>/</span><b>{selected.name}</b></div><div><span className="detail-scope"><LockClosedIcon />{t(selected.scope)}</span><button className="icon-button" type="button" onClick={() => onToast(`${selected.name} link copied.`)} aria-label={t('Copy link')}><CopyIcon /></button><button className="management-primary-action" type="button" onClick={primaryAction}>{category === 'skills' ? <PlayIcon /> : category === 'agents' ? <RocketIcon /> : category === 'plugins' ? <LightningBoltIcon /> : <Pencil1Icon />}{actionLabel}</button></div></header>
        <div className="management-detail-scroll">
          <section className="management-identity">
            <div className={`management-identity-icon ${category}`}><SelectedIcon /></div>
            <div><span>{t(meta.singular).toUpperCase()} · {t(selected.scope).toUpperCase()}</span><h1>{selected.name}</h1><p>{t(selected.description)}</p><div><StatusPill item={selected} /><ChipList items={selected.tags} /></div></div>
            <section><small>{t(category === 'models' ? 'PROVIDER' : category === 'plugins' ? 'PUBLISHER' : 'OWNER')}</small><b>{selected.provider ?? selected.publisher ?? selected.owner}</b><small>{category === 'models' ? selected.modelId : category === 'agents' ? selected.role : selected.updated}</small></section>
          </section>
          <nav className="management-tabs" aria-label={`${selected.name} detail sections`}>{meta.tabs.map((value) => <button className={tab === value ? 'active' : ''} type="button" key={value} onClick={() => { setTab(value); setEditing(false); }}>{t(value)}</button>)}</nav>
          <div className="management-tab-content">
            {tab === 'Overview' ? <OverviewPanel category={category} item={selected} /> : <GenericTabPanel category={category} tab={tab} item={selected} editing={editing} onEditingChange={setEditing} onToast={onToast} />}
          </div>
        </div>
      </section>
      {creating ? <CreateResourceDialog category={category} onClose={() => setCreating(false)} onCreate={createResource} /> : null}
    </main>
  );
}
