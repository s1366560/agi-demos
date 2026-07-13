import { useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  CopyIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  EyeOpenIcon,
  GearIcon,
  GlobeIcon,
  InfoCircledIcon,
  LightningBoltIcon,
  Link2Icon,
  LockClosedIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PlusIcon,
  ReloadIcon,
  RocketIcon,
  SewingPinIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';
import { Dialog } from './Dialog';

const providerSeed = [
  {
    id: 'openai',
    name: 'OpenAI',
    type: 'Cloud API',
    status: 'connected',
    statusLabel: 'Connected',
    auth: 'API key',
    credential: 'Workspace secret ·•••• 7K2Q',
    endpoint: 'https://api.openai.com/v1',
    modelCount: 4,
    lastCheck: '2 min ago',
    latency: '1.8s',
    success: '99.2%',
    spend: '$184.20',
    models: [
      { id: 'gpt-5.5', name: 'GPT-5.5', context: '128k', enabled: true, capabilities: ['Reasoning', 'Tools', 'Vision'], role: 'Default' },
      { id: 'gpt-5.5-mini', name: 'GPT-5.5 mini', context: '128k', enabled: true, capabilities: ['Fast', 'Tools'], role: 'Fast tasks' },
      { id: 'gpt-5.5-codex', name: 'GPT-5.5 Codex', context: '192k', enabled: true, capabilities: ['Code', 'Tools'], role: 'Coding' },
      { id: 'text-embedding-3-large', name: 'Embedding 3 large', context: '8k', enabled: false, capabilities: ['Embedding'], role: '' },
    ],
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    type: 'Cloud API',
    status: 'connected',
    statusLabel: 'Connected',
    auth: 'OAuth',
    credential: 'Claude account · Alex Chen',
    endpoint: 'https://api.anthropic.com',
    modelCount: 3,
    lastCheck: '8 min ago',
    latency: '2.1s',
    success: '98.7%',
    spend: '$96.40',
    models: [
      { id: 'claude-sonnet-4-5', name: 'Claude Sonnet 4.5', context: '200k', enabled: true, capabilities: ['Reasoning', 'Code', 'Vision'], role: 'Fallback' },
      { id: 'claude-opus-4-1', name: 'Claude Opus 4.1', context: '200k', enabled: false, capabilities: ['Reasoning', 'Vision'], role: '' },
      { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', context: '200k', enabled: true, capabilities: ['Fast', 'Tools'], role: 'Fast fallback' },
    ],
  },
  {
    id: 'google',
    name: 'Google AI',
    type: 'Cloud API',
    status: 'connected',
    statusLabel: 'Connected',
    auth: 'API key',
    credential: 'Workspace secret ·•••• M91A',
    endpoint: 'https://generativelanguage.googleapis.com',
    modelCount: 5,
    lastCheck: '14 min ago',
    latency: '2.6s',
    success: '97.9%',
    spend: '$142.80',
    models: [
      { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', context: '1m', enabled: true, capabilities: ['Reasoning', 'Vision', 'Long context'], role: 'Long context' },
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', context: '1m', enabled: true, capabilities: ['Fast', 'Vision'], role: 'Vision' },
      { id: 'gemini-embedding-001', name: 'Gemini Embedding', context: '2k', enabled: false, capabilities: ['Embedding'], role: '' },
    ],
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    type: 'Model gateway',
    status: 'attention',
    statusLabel: 'Needs model filter',
    auth: 'API key',
    credential: 'Workspace secret ·•••• R8F4',
    endpoint: 'https://openrouter.ai/api/v1',
    modelCount: 0,
    lastCheck: '1 hour ago',
    latency: '—',
    success: '—',
    spend: '$0.00',
    models: [],
  },
  {
    id: 'ollama',
    name: 'Ollama',
    type: 'Local runtime',
    status: 'offline',
    statusLabel: 'Offline',
    auth: 'No authentication',
    credential: 'Local connection',
    endpoint: 'http://localhost:11434/v1',
    modelCount: 2,
    lastCheck: 'Yesterday',
    latency: 'Unavailable',
    success: '94.5%',
    spend: 'Local compute',
    models: [
      { id: 'qwen3-coder:30b', name: 'Qwen3 Coder 30B', context: '32k', enabled: true, capabilities: ['Code', 'Tools'], role: 'Private coding' },
      { id: 'nomic-embed-text', name: 'Nomic Embed Text', context: '8k', enabled: true, capabilities: ['Embedding'], role: 'Local embedding' },
    ],
  },
];

const setupOptions = [
  { id: 'azure', name: 'Azure OpenAI', type: 'Enterprise cloud', auth: 'API key', endpoint: 'https://{resource}.openai.azure.com', models: ['gpt-5.5-deployment', 'gpt-5.5-mini-deployment'] },
  { id: 'bedrock', name: 'AWS Bedrock', type: 'Enterprise cloud', auth: 'AWS credentials', endpoint: 'us-east-1', models: ['anthropic.claude-sonnet-4-5-v1', 'amazon.nova-pro-v1'] },
  { id: 'xai', name: 'xAI', type: 'Cloud API', auth: 'OAuth or API key', endpoint: 'https://api.x.ai/v1', models: ['grok-4', 'grok-4-fast'] },
  { id: 'lmstudio', name: 'LM Studio', type: 'Local runtime', auth: 'No authentication', endpoint: 'http://localhost:1234/v1', models: ['loaded-model'] },
  { id: 'custom', name: 'OpenAI-compatible', type: 'Custom endpoint', auth: 'API key', endpoint: 'https://api.example.com/v1', models: ['custom-model'] },
];

function ConnectionStatus({ provider }) {
  const { t } = useI18n();
  return (
    <span className={`provider-status ${provider.status}`}>
      <i />
      {t(provider.statusLabel)}
    </span>
  );
}

function ProviderFact({ label, value, accent = false }) {
  return (
    <div className="provider-fact">
      <span>{label}</span>
      <b className={accent ? 'accent' : ''}>{value}</b>
    </div>
  );
}

function ProviderOverview({ provider, onTabChange }) {
  const { t } = useI18n();
  const enabledModels = provider.models.filter((model) => model.enabled);
  return (
    <div className="provider-panel-grid">
      <section className="provider-health-card">
        <header>
          <div><span>{t('CONNECTION')}</span><h3>{t('Provider health')}</h3></div>
          <ConnectionStatus provider={provider} />
        </header>
        <div className="provider-health-row">
          <div className="provider-health-icon"><Link2Icon /></div>
          <div><b>{provider.endpoint}</b><span>{t(provider.auth)} · {t(provider.credential)}</span></div>
          <button type="button" onClick={() => onTabChange('Connection')}>{t('Manage')}</button>
        </div>
        <div className="provider-health-meta">
          <span><CheckCircledIcon /> {t('Last verified')} {t(provider.lastCheck)}</span>
          <span><ReloadIcon /> {provider.modelCount} {t('models discovered')}</span>
        </div>
      </section>

      <section className="provider-model-summary">
        <header>
          <div><span>{t('MODEL CATALOG')}</span><h3>{t('Enabled models')}</h3></div>
          <button type="button" onClick={() => onTabChange('Models')}>{t('Manage models')} <ArrowRightIcon /></button>
        </header>
        {enabledModels.length ? enabledModels.slice(0, 4).map((model) => (
          <article key={model.id}>
            <CubeIcon />
            <div><b>{model.name}</b><span>{model.id} · {model.context} {t('context')}</span></div>
            <em>{t(model.role || 'Enabled')}</em>
          </article>
        )) : (
          <div className="provider-empty-state"><ExclamationTriangleIcon /><b>{t('No models enabled')}</b><span>{t('Add a model ID or refresh discovery before using this provider.')}</span><button type="button" onClick={() => onTabChange('Models')}>{t('Choose models')}</button></div>
        )}
      </section>

      <section className="provider-routing-card">
        <header><div><span>{t('WORKSPACE ROUTING')}</span><h3>{t('Current model roles')}</h3></div><MixerHorizontalIcon /></header>
        <div className="provider-routing-list">
          <div><span>{t('Default')}</span><b>OpenAI / GPT-5.5</b><em>{t('Planning and execution')}</em></div>
          <div><span>{t('Fast tasks')}</span><b>OpenAI / GPT-5.5 mini</b><em>{t('Titles and lightweight transforms')}</em></div>
          <div><span>{t('Fallback')}</span><b>Anthropic / Claude Sonnet 4.5</b><em>{t('Provider errors and rate limits')}</em></div>
        </div>
        <button type="button" onClick={() => onTabChange('Routing')}>{t('Edit routing policy')} <ArrowRightIcon /></button>
      </section>
    </div>
  );
}

function ProviderConnection({ provider, onProviderChange, onToast }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [testState, setTestState] = useState('idle');
  const [form, setForm] = useState({ auth: provider.auth, endpoint: provider.endpoint, credential: '' });

  function testConnection() {
    setTestState('testing');
    window.setTimeout(() => {
      setTestState('success');
      onToast(`${provider.name} ${t('connection verified')}.`);
    }, 650);
  }

  function saveConnection() {
    onProviderChange({ ...provider, auth: form.auth, endpoint: form.endpoint, status: 'connected', statusLabel: 'Connected', lastCheck: 'Just now' });
    setEditing(false);
    setTestState('success');
    onToast(`${provider.name} ${t('connection saved')}.`);
  }

  return (
    <section className="provider-form-card">
      <header>
        <div><span>{t('CONNECTION')}</span><h3>{t('Authentication and endpoint')}</h3><p>{t('Credentials belong to the provider connection, not to individual models.')}</p></div>
        <button type="button" onClick={() => setEditing((value) => !value)}><GearIcon /> {t(editing ? 'Cancel edit' : 'Edit connection')}</button>
      </header>
      <div className="provider-form-section">
        <div className="provider-form-heading"><span>1</span><div><b>{t('Authentication')}</b><small>{t('Choose how this provider authorizes requests.')}</small></div></div>
        <div className="provider-auth-options" role="group" aria-label={t('Authentication method')}>
          {['OAuth', 'API key', 'Environment secret'].map((auth) => (
            <button className={form.auth === auth ? 'selected' : ''} type="button" disabled={!editing} key={auth} onClick={() => setForm((current) => ({ ...current, auth }))}>
              {auth === 'OAuth' ? <GlobeIcon /> : <LockClosedIcon />}
              <span><b>{t(auth)}</b><small>{t(auth === 'OAuth' ? 'Sign in and refresh automatically' : auth === 'API key' ? 'Store an encrypted workspace secret' : 'Reference a secret from the runtime')}</small></span>
            </button>
          ))}
        </div>
        <label className="provider-input-label"><span>{t(form.auth === 'Environment secret' ? 'Secret name' : form.auth === 'OAuth' ? 'Connected account' : 'API key')}</span><div className="provider-secret-input"><input disabled={!editing} type={form.auth === 'API key' ? 'password' : 'text'} value={editing ? form.credential : provider.credential} onChange={(event) => setForm((current) => ({ ...current, credential: event.target.value }))} placeholder={form.auth === 'API key' ? 'sk-…' : form.auth === 'Environment secret' ? 'OPENAI_API_KEY' : 'Alex Chen'} /><EyeOpenIcon /></div><small>{t('Secrets are encrypted and never shown again after saving.')}</small></label>
      </div>

      <div className="provider-form-section">
        <div className="provider-form-heading"><span>2</span><div><b>{t('Endpoint')}</b><small>{t('Use the provider default unless a gateway or local server is required.')}</small></div></div>
        <label className="provider-input-label"><span>{t('Base URL')}</span><input disabled={!editing} value={form.endpoint} onChange={(event) => setForm((current) => ({ ...current, endpoint: event.target.value }))} /></label>
        <button className="provider-advanced-toggle" type="button" onClick={() => setAdvanced((value) => !value)}>{t('Advanced request settings')} <ChevronDownIcon className={advanced ? 'open' : ''} /></button>
        {advanced ? <div className="provider-advanced-grid"><label><span>{t('API mode')}</span><select disabled={!editing} defaultValue="chat-completions"><option value="chat-completions">Chat Completions</option><option value="responses">Responses API</option><option value="anthropic">Anthropic Messages</option></select></label><label><span>{t('Timeout')}</span><input disabled={!editing} defaultValue="120 seconds" /></label><label className="wide"><span>{t('Custom headers')}</span><input disabled={!editing} placeholder="X-Organization: workspace-team" /></label></div> : null}
      </div>

      <div className="provider-test-row">
        <div className={`provider-test-result ${testState}`}>
          {testState === 'success' ? <CheckCircledIcon /> : testState === 'testing' ? <ReloadIcon className="spin" /> : <InfoCircledIcon />}
          <span><b>{t(testState === 'success' ? 'Connection verified' : testState === 'testing' ? 'Testing provider…' : 'Test before saving')}</b><small>{t(testState === 'success' ? 'Authentication works and the provider responded.' : 'Checks authentication, endpoint, and model discovery.')}</small></span>
        </div>
        <button type="button" onClick={testConnection} disabled={testState === 'testing'}>{t('Test connection')}</button>
        {editing ? <button className="primary" type="button" onClick={saveConnection} disabled={testState !== 'success'}>{t('Save connection')}</button> : null}
      </div>
    </section>
  );
}

function ProviderModels({ provider, onProviderChange, onToast }) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [manualModel, setManualModel] = useState('');
  const visibleModels = provider.models.filter((model) => `${model.name} ${model.id}`.toLowerCase().includes(query.toLowerCase()));

  function toggleModel(modelId) {
    onProviderChange({ ...provider, models: provider.models.map((model) => model.id === modelId ? { ...model, enabled: !model.enabled } : model) });
  }

  function syncModels() {
    setSyncing(true);
    window.setTimeout(() => {
      setSyncing(false);
      onToast(`${provider.name}: ${provider.models.length || 0} ${t('models discovered')}.`);
    }, 650);
  }

  function addManualModel() {
    if (!manualModel.trim()) return;
    const id = manualModel.trim();
    onProviderChange({ ...provider, modelCount: provider.models.length + 1, models: [...provider.models, { id, name: id, context: 'Unknown', enabled: true, capabilities: ['Custom'], role: '' }] });
    setManualModel('');
    onToast(`${id} ${t('added to the provider catalog')}.`);
  }

  return (
    <section className="provider-model-catalog">
      <header>
        <div><span>{t('MODEL CATALOG')}</span><h3>{t('Choose models from this provider')}</h3><p>{t('Only enabled models appear in agent and routing selectors.')}</p></div>
        <button type="button" onClick={syncModels} disabled={syncing}><ReloadIcon className={syncing ? 'spin' : ''} /> {t(syncing ? 'Discovering…' : 'Refresh models')}</button>
      </header>
      <div className="provider-model-tools">
        <label><MagnifyingGlassIcon /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('Search model IDs')} /></label>
        <span>{provider.models.filter((model) => model.enabled).length} {t('enabled')} · {provider.models.length} {t('discovered')}</span>
      </div>
      {visibleModels.length ? <div className="provider-model-table">
        <div className="provider-model-table-head"><span>{t('Model')}</span><span>{t('Capabilities')}</span><span>{t('Context')}</span><span>{t('Available')}</span></div>
        {visibleModels.map((model) => <div className="provider-model-row" key={model.id}><div><CubeIcon /><span><b>{model.name}</b><small>{model.id}</small></span></div><div className="provider-capabilities">{model.capabilities.map((capability) => <span key={capability}>{t(capability)}</span>)}</div><span>{model.context}</span><button className={`provider-switch ${model.enabled ? 'on' : ''}`} type="button" role="switch" aria-checked={model.enabled} onClick={() => toggleModel(model.id)}><i /></button></div>)}
      </div> : <div className="provider-empty-state large"><ExclamationTriangleIcon /><b>{t('Automatic discovery returned no models')}</b><span>{t('Some providers do not expose a compatible /models endpoint. Add exact model IDs manually.')}</span></div>}
      <div className="provider-manual-model">
        <div><SewingPinIcon /><span><b>{t('Add model ID manually')}</b><small>{t('Use this when discovery is unavailable or the provider catalog is very large.')}</small></span></div>
        <label><input value={manualModel} onChange={(event) => setManualModel(event.target.value)} placeholder="anthropic/claude-sonnet-4-5" /><button type="button" onClick={addManualModel} disabled={!manualModel.trim()}><PlusIcon /> {t('Add model')}</button></label>
      </div>
    </section>
  );
}

function ProviderRouting({ providers, onToast }) {
  const { t } = useI18n();
  const availableModels = providers.flatMap((provider) => provider.models.filter((model) => model.enabled).map((model) => ({ value: `${provider.name} / ${model.name}`, provider: provider.name, model: model.name })));
  const [roles, setRoles] = useState({ default: 'OpenAI / GPT-5.5', fast: 'OpenAI / GPT-5.5 mini', coding: 'OpenAI / GPT-5.5 Codex', vision: 'Google AI / Gemini 2.5 Flash' });
  const [fallbacks, setFallbacks] = useState(['Anthropic / Claude Sonnet 4.5', 'Google AI / Gemini 2.5 Pro']);

  return (
    <section className="provider-routing-form">
      <header><div><span>{t('WORKSPACE ROUTING')}</span><h3>{t('Assign models by workload')}</h3><p>{t('Routing is separate from provider credentials and can be changed without reconnecting.')}</p></div><button className="primary" type="button" onClick={() => onToast(t('Workspace routing policy saved.'))}><CheckCircledIcon /> {t('Save routing')}</button></header>
      <div className="provider-role-grid">
        {[
          ['default', 'Default model', 'Planning, tool use, and complex execution'],
          ['fast', 'Fast model', 'Titles, summaries, and lightweight transforms'],
          ['coding', 'Coding model', 'Repository work and code review'],
          ['vision', 'Vision model', 'Screenshots, diagrams, and visual QA'],
        ].map(([key, label, description]) => <label key={key}><span><b>{t(label)}</b><small>{t(description)}</small></span><select value={roles[key]} onChange={(event) => setRoles((current) => ({ ...current, [key]: event.target.value }))}>{availableModels.map((model) => <option key={`${key}-${model.value}`} value={model.value}>{model.value}</option>)}</select></label>)}
      </div>
      <section className="provider-fallback-editor">
        <header><div><span>{t('FAILOVER')}</span><h3>{t('Fallback order')}</h3></div><small>{t('Used for authentication errors, rate limits, timeouts, and provider failures.')}</small></header>
        {fallbacks.map((fallback, index) => <div key={`${fallback}-${index}`}><span>{index + 1}</span><select value={fallback} onChange={(event) => setFallbacks((current) => current.map((value, currentIndex) => currentIndex === index ? event.target.value : value))}>{availableModels.map((model) => <option key={`${index}-${model.value}`} value={model.value}>{model.value}</option>)}</select><button type="button" onClick={() => setFallbacks((current) => current.filter((_, currentIndex) => currentIndex !== index))}>{t('Remove')}</button></div>)}
        <button type="button" onClick={() => setFallbacks((current) => [...current, availableModels[0]?.value ?? 'OpenAI / GPT-5.5'])}><PlusIcon /> {t('Add fallback')}</button>
      </section>
    </section>
  );
}

function ProviderUsage({ provider }) {
  const { t } = useI18n();
  return (
    <div className="provider-panel-grid">
      <section className="provider-metric-grid">
        <ProviderFact label={t('Success rate')} value={provider.success} accent />
        <ProviderFact label={t('Median latency')} value={provider.latency} />
        <ProviderFact label={t('Spend this month')} value={provider.spend} />
        <ProviderFact label={t('Enabled models')} value={String(provider.models.filter((model) => model.enabled).length)} />
      </section>
      <section className="provider-activity-card">
        <header><div><span>{t('RECENT SIGNALS')}</span><h3>{t('Connection activity')}</h3></div><ActivityLogIcon /></header>
        {[
          ['Model discovery completed', provider.lastCheck],
          ['Credential health check passed', 'Yesterday'],
          ['Routing policy used fallback', '3 days ago'],
        ].map(([event, time], index) => <div key={event}><span className={index === 2 ? 'warning' : ''}>{index === 2 ? <ExclamationTriangleIcon /> : <CheckCircledIcon />}</span><div><b>{t(event)}</b><small>{t(time)} · Alex Chen</small></div><button type="button"><ArrowRightIcon /></button></div>)}
      </section>
    </div>
  );
}

function AddProviderDialog({ onClose, onAdd }) {
  const { t } = useI18n();
  const [step, setStep] = useState(1);
  const [selectedId, setSelectedId] = useState('azure');
  const [auth, setAuth] = useState('API key');
  const [credential, setCredential] = useState('');
  const [endpoint, setEndpoint] = useState(setupOptions[0].endpoint);
  const [tested, setTested] = useState(false);
  const [selectedModels, setSelectedModels] = useState(() => new Set(setupOptions[0].models));
  const selected = setupOptions.find((option) => option.id === selectedId) ?? setupOptions[0];

  function chooseProvider(option) {
    setSelectedId(option.id);
    setAuth(option.auth.includes('OAuth') ? 'OAuth' : option.auth);
    setEndpoint(option.endpoint);
    setSelectedModels(new Set(option.models));
    setTested(false);
  }

  function complete() {
    onAdd({
      id: selected.id,
      name: selected.name,
      type: selected.type,
      status: 'connected',
      statusLabel: 'Connected',
      auth,
      credential: auth === 'No authentication' ? 'Local connection' : 'Workspace secret ·•••• NEW',
      endpoint,
      modelCount: selectedModels.size,
      lastCheck: 'Just now',
      latency: 'Not measured',
      success: 'Not measured',
      spend: '$0.00',
      models: selected.models.filter((id) => selectedModels.has(id)).map((id) => ({ id, name: id, context: 'Auto', enabled: true, capabilities: ['Tools'], role: '' })),
    });
  }

  return (
    <Dialog title={`${t('Add provider')} · ${t('Step')} ${step}/3`} onClose={onClose}>
      <div className="provider-wizard">
        <div className="provider-wizard-steps">{[1, 2, 3].map((value) => <span className={step >= value ? 'active' : ''} key={value}><i>{step > value ? <CheckCircledIcon /> : value}</i>{t(value === 1 ? 'Provider' : value === 2 ? 'Connect' : 'Models')}</span>)}</div>
        {step === 1 ? <section><header><h3>{t('Choose a provider')}</h3><p>{t('Connect a cloud API, enterprise platform, or local OpenAI-compatible runtime.')}</p></header><div className="provider-option-grid">{setupOptions.map((option) => <button className={selectedId === option.id ? 'selected' : ''} type="button" key={option.id} onClick={() => chooseProvider(option)}><span><CubeIcon /></span><div><b>{option.name}</b><small>{t(option.type)}</small></div>{selectedId === option.id ? <CheckCircledIcon /> : null}</button>)}</div></section> : null}
        {step === 2 ? <section><header><h3>{t('Connect')} {selected.name}</h3><p>{t('Authenticate once at provider level, then verify before selecting models.')}</p></header><div className="provider-wizard-form"><label><span>{t('Authentication method')}</span><select value={auth} onChange={(event) => setAuth(event.target.value)}><option>API key</option><option>OAuth</option><option>Environment secret</option><option>No authentication</option></select></label>{auth !== 'No authentication' ? <label><span>{t(auth === 'Environment secret' ? 'Secret name' : auth === 'OAuth' ? 'Connected account' : 'API key')}</span><input type={auth === 'API key' ? 'password' : 'text'} value={credential} onChange={(event) => setCredential(event.target.value)} placeholder={auth === 'API key' ? 'sk-…' : auth === 'Environment secret' ? 'PROVIDER_API_KEY' : 'Sign in with browser'} /></label> : null}<label><span>{t(selected.type === 'Enterprise cloud' && selected.id === 'bedrock' ? 'Region' : 'Base URL')}</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label><button className={`provider-wizard-test ${tested ? 'success' : ''}`} type="button" onClick={() => setTested(true)}>{tested ? <CheckCircledIcon /> : <LightningBoltIcon />} {t(tested ? 'Connection verified' : 'Test connection')}</button></div></section> : null}
        {step === 3 ? <section><header><h3>{t('Enable discovered models')}</h3><p>{t('Enabled models become available to agents and workspace routing.')}</p></header><div className="provider-wizard-models">{selected.models.map((model) => <label key={model}><input type="checkbox" checked={selectedModels.has(model)} onChange={() => setSelectedModels((current) => { const next = new Set(current); if (next.has(model)) next.delete(model); else next.add(model); return next; })} /><CubeIcon /><span><b>{model}</b><small>{t('Discovered from provider')}</small></span></label>)}</div></section> : null}
        <footer><button type="button" onClick={step === 1 ? onClose : () => setStep((value) => value - 1)}>{t(step === 1 ? 'Cancel' : 'Back')}</button><button className="primary" type="button" disabled={step === 2 && !tested || step === 3 && selectedModels.size === 0} onClick={step === 3 ? complete : () => setStep((value) => value + 1)}>{t(step === 3 ? 'Add provider' : 'Continue')} <ArrowRightIcon /></button></footer>
      </div>
    </Dialog>
  );
}

export function ModelProviderWorkspace({ onToast }) {
  const { t } = useI18n();
  const [providers, setProviders] = useState(providerSeed);
  const [selectedId, setSelectedId] = useState('openai');
  const [tab, setTab] = useState('Overview');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('All');
  const [adding, setAdding] = useState(false);
  const provider = providers.find((item) => item.id === selectedId) ?? providers[0];
  const filteredProviders = useMemo(() => providers.filter((item) => {
    const matchesSearch = `${item.name} ${item.type}`.toLowerCase().includes(query.toLowerCase());
    const matchesFilter = filter === 'All' || (filter === 'Connected' && item.status === 'connected') || (filter === 'Attention' && item.status !== 'connected');
    return matchesSearch && matchesFilter;
  }), [filter, providers, query]);

  function updateProvider(nextProvider) {
    setProviders((current) => current.map((item) => item.id === nextProvider.id ? nextProvider : item));
  }

  function addProvider(nextProvider) {
    setProviders((current) => [...current, nextProvider]);
    setSelectedId(nextProvider.id);
    setTab('Overview');
    setAdding(false);
    onToast(`${nextProvider.name} ${t('connected with')} ${nextProvider.modelCount} ${t('models')}.`);
  }

  return (
    <main className="model-provider-workspace">
      <section className="provider-catalog">
        <header><div><span>{t('INFERENCE')}</span><h2>{t('Providers')}</h2><p>{t('Connect once, then choose models and routing.')}</p></div><button className="icon-button" type="button" onClick={() => setAdding(true)} aria-label={t('Add provider')}><PlusIcon /></button></header>
        <label className="provider-search"><MagnifyingGlassIcon /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('Search providers')} /></label>
        <div className="provider-filters">{['All', 'Connected', 'Attention'].map((value) => <button className={filter === value ? 'active' : ''} type="button" key={value} onClick={() => setFilter(value)}>{t(value)}</button>)}</div>
        <div className="provider-count"><span>{filteredProviders.length} {t('providers')}</span><button type="button" onClick={() => setAdding(true)}><PlusIcon /> {t('Add')}</button></div>
        <div className="provider-list">{filteredProviders.map((item) => <button className={selectedId === item.id ? 'selected' : ''} type="button" key={item.id} onClick={() => { setSelectedId(item.id); setTab('Overview'); }}><span className="provider-list-icon"><CubeIcon /></span><span className="provider-list-copy"><b>{item.name}</b><small>{t(item.type)} · {item.modelCount} {t('models')}</small><ConnectionStatus provider={item} /></span><ArrowRightIcon /></button>)}</div>
      </section>

      <section className="provider-detail">
        <header className="provider-detail-topbar"><div className="breadcrumb"><span>{t('settings.title')}</span><span>/</span><span>{t('Models')}</span><span>/</span><b>{provider.name}</b></div><div><span className="detail-scope"><LockClosedIcon />{t('Workspace')}</span><button className="icon-button" type="button" onClick={() => onToast(`${provider.name} ${t('configuration link copied')}.`)} aria-label={t('Copy link')}><CopyIcon /></button><button className="provider-add-action" type="button" onClick={() => setAdding(true)}><PlusIcon /> {t('Add provider')}</button></div></header>
        <div className="provider-detail-scroll">
          <section className="provider-identity">
            <div className="provider-identity-icon"><CubeIcon /></div>
            <div><span>{t('MODEL PROVIDER')} · {t(provider.type).toUpperCase()}</span><h1>{provider.name}</h1><p>{t('Provider credentials, endpoint health, available models, and workspace routing are managed independently.')}</p><div><ConnectionStatus provider={provider} /><span className="provider-auth-badge"><LockClosedIcon /> {t(provider.auth)}</span></div></div>
            <section><small>{t('ENDPOINT')}</small><b>{provider.endpoint.replace(/^https?:\/\//, '').split('/')[0]}</b><span>{t('Last verified')} {t(provider.lastCheck)}</span></section>
          </section>
          <nav className="provider-tabs" aria-label={`${provider.name} ${t('provider settings')}`}>{['Overview', 'Connection', 'Models', 'Routing', 'Usage'].map((value) => <button className={tab === value ? 'active' : ''} type="button" key={value} onClick={() => setTab(value)}>{t(value)}</button>)}</nav>
          <div className="provider-tab-content">
            {tab === 'Overview' ? <ProviderOverview provider={provider} onTabChange={setTab} /> : null}
            {tab === 'Connection' ? <ProviderConnection key={provider.id} provider={provider} onProviderChange={updateProvider} onToast={onToast} /> : null}
            {tab === 'Models' ? <ProviderModels provider={provider} onProviderChange={updateProvider} onToast={onToast} /> : null}
            {tab === 'Routing' ? <ProviderRouting providers={providers} onToast={onToast} /> : null}
            {tab === 'Usage' ? <ProviderUsage provider={provider} /> : null}
          </div>
        </div>
      </section>
      {adding ? <AddProviderDialog onClose={() => setAdding(false)} onAdd={addProvider} /> : null}
    </main>
  );
}
