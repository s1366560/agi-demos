import {
  Cross2Icon,
  ExclamationTriangleIcon,
  MixerHorizontalIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button, Select, Switch, TextArea, TextField } from '@radix-ui/themes';
import { useMemo, useState } from 'react';

import { useI18n } from '../../i18n';
import type {
  TenantAgentDashboardController,
  TenantAgentDashboardViewModel,
} from './tenantAgentDashboardController';
import type {
  TenantAgentConfig,
  TenantAgentEditableConfig,
  TenantAgentRun,
} from './tenantAgentDashboardClient';
import { TenantAgentDashboardHookEditor } from './TenantAgentDashboardHookEditor';
import { TenantAgentDashboardTraceView } from './TenantAgentDashboardTraceView';
import './TenantAgentDashboardPage.css';

export function TenantAgentDashboardPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantAgentDashboardViewModel;
  controller: TenantAgentDashboardController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  if (model.state === 'loading' || model.state === 'forbidden' || model.state === 'unavailable') {
    return <DashboardState model={model} onRetry={onRetry} />;
  }
  return (
    <section className="tenant-agent-dashboard" data-state={model.state}>
      <header className="tenant-agent-dashboard-header">
        <div>
          <span>{t('tenantAgentDashboard.eyebrow')}</span>
          <h1>{t('tenantAgentDashboard.title')}</h1>
          <p>{t('tenantAgentDashboard.subtitle')}</p>
        </div>
        <div className="tenant-agent-dashboard-actions">
          <span>
            {t('tenantAgentDashboard.activeRuns', {
              count: model.activeRunCount,
            })}
          </span>
          <Button
            color="gray"
            variant="soft"
            disabled={model.busyAction !== null}
            onClick={onRetry}
          >
            <ReloadIcon />
            {t('common.refresh')}
          </Button>
        </div>
      </header>
      {model.state === 'stale' || model.state === 'conflict' ? (
        <div className="tenant-agent-dashboard-notice" role="status">
          <ExclamationTriangleIcon />
          <span>
            {t(
              model.state === 'conflict'
                ? 'tenantAgentDashboard.state.conflict'
                : 'tenantAgentDashboard.state.stale',
            )}
          </span>
          <code>{model.reasonCode}</code>
          {model.configConflict ? (
            <span>
              {t('tenantAgentDashboard.state.conflictRevisions', {
                expected: model.configConflict.expectedRevision,
                authority: model.configConflict.authorityRevision,
              })}
            </span>
          ) : null}
          <Button color="gray" variant="ghost" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        </div>
      ) : null}
      <div className="tenant-agent-dashboard-grid">
        <ConfigPanel model={model} onEdit={() => setEditing(true)} />
        <HookCatalog model={model} />
      </div>
      <RunSection model={model} controller={controller} />
      {model.selectedTrace ? (
        <TenantAgentDashboardTraceView model={model} controller={controller} />
      ) : null}
      {editing && model.config && controller ? (
        <ConfigEditor
          config={model.config}
          hookCatalog={model.hookCatalog}
          busy={model.busyAction === 'update'}
          onClose={() => setEditing(false)}
          onSave={async (input) => {
            await controller.updateConfig(input);
            setEditing(false);
          }}
        />
      ) : null}
    </section>
  );
}

function ConfigPanel({
  model,
  onEdit,
}: Readonly<{
  model: TenantAgentDashboardViewModel;
  onEdit: () => void;
}>) {
  const { t } = useI18n();
  const config = model.config;
  if (!config) return null;
  return (
    <article className="tenant-agent-dashboard-card">
      <header>
        <div>
          <span>{t('tenantAgentDashboard.config.eyebrow')}</span>
          <h2>{t('tenantAgentDashboard.config.title')}</h2>
        </div>
        {model.allowedActions.includes('update-config') ? (
          <Button color="gray" onClick={onEdit}>
            <MixerHorizontalIcon />
            {t('tenantAgentDashboard.config.edit')}
          </Button>
        ) : null}
      </header>
      <dl>
        <ConfigValue label={t('tenantAgentDashboard.config.model')} value={config.llmModel} />
        <ConfigValue
          label={t('tenantAgentDashboard.config.temperature')}
          value={String(config.llmTemperature)}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.planSteps')}
          value={String(config.maxWorkPlanSteps)}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.timeout')}
          value={`${config.toolTimeoutSeconds}s`}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.multiAgent')}
          value={t(config.multiAgentEnabled ? 'common.enabled' : 'common.disabled')}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.revision')}
          value={String(config.authorityRevision)}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.agentRuntime')}
          value={model.runtimeInfo?.agentRuntimeMode ?? '—'}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.memoryRuntime')}
          value={model.runtimeInfo?.memoryRuntimeMode ?? '—'}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.toolProvider')}
          value={model.runtimeInfo?.toolProviderMode ?? '—'}
        />
        <ConfigValue
          label={t('tenantAgentDashboard.config.failurePersistence')}
          value={
            model.runtimeInfo
              ? t(
                  model.runtimeInfo.failurePersistenceEnabled
                    ? 'common.enabled'
                    : 'common.disabled',
                )
              : '—'
          }
        />
      </dl>
      <div className="tenant-agent-dashboard-tool-policy">
        <ToolList
          title={t('tenantAgentDashboard.config.enabledTools')}
          tools={config.enabledTools}
        />
        <ToolList
          title={t('tenantAgentDashboard.config.disabledTools')}
          tools={config.disabledTools}
        />
      </div>
    </article>
  );
}

function HookCatalog({ model }: Readonly<{ model: TenantAgentDashboardViewModel }>) {
  const { t } = useI18n();
  return (
    <article className="tenant-agent-dashboard-card">
      <header>
        <div>
          <span>{t('tenantAgentDashboard.hooks.eyebrow')}</span>
          <h2>{t('tenantAgentDashboard.hooks.title')}</h2>
        </div>
        <strong>{model.hookCatalog.length}</strong>
      </header>
      {model.hookCatalog.length === 0 ? (
        <p className="tenant-agent-dashboard-empty-copy">{t('tenantAgentDashboard.hooks.empty')}</p>
      ) : (
        <ul className="tenant-agent-dashboard-hook-list">
          {model.hookCatalog.map((hook) => (
            <li key={hook.key}>
              <div>
                <strong>{hook.displayName}</strong>
                <code>{hook.key}</code>
              </div>
              <p>{hook.description}</p>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function RunSection({
  model,
  controller,
}: Readonly<{
  model: TenantAgentDashboardViewModel;
  controller: TenantAgentDashboardController | null;
}>) {
  const { t } = useI18n();
  const statuses = useMemo(
    () => [...new Set(model.runs.map((run) => run.status))].sort(),
    [model.runs],
  );
  return (
    <section className="tenant-agent-dashboard-runs">
      <header>
        <div>
          <span>{t('tenantAgentDashboard.runs.eyebrow')}</span>
          <h2>{t('tenantAgentDashboard.runs.title')}</h2>
        </div>
        <div className="tenant-agent-dashboard-filters">
          <TextField.Root
            value={model.filters.search}
            placeholder={t('tenantAgentDashboard.runs.search')}
            onChange={(event) =>
              controller?.setFilters({
                ...model.filters,
                search: event.target.value,
              })
            }
          />
          <Select.Root
            value={model.filters.status ?? 'all'}
            onValueChange={(status) =>
              controller?.setFilters({
                ...model.filters,
                status: status === 'all' ? null : status,
              })
            }
          >
            <Select.Trigger aria-label={t('tenantAgentDashboard.runs.status')} />
            <Select.Content>
              <Select.Item value="all">{t('common.all')}</Select.Item>
              {statuses.map((status) => (
                <Select.Item key={status} value={status}>
                  {status}
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
        </div>
      </header>
      {model.visibleRuns.length === 0 ? (
        <div className="tenant-agent-dashboard-run-empty">
          <h3>{t('tenantAgentDashboard.runs.emptyTitle')}</h3>
          <p>{t('tenantAgentDashboard.runs.emptyDescription')}</p>
        </div>
      ) : (
        <div className="tenant-agent-dashboard-run-list">
          {model.visibleRuns.map((run) => (
            <RunCard
              key={run.runId}
              run={run}
              selected={model.selectedRunId === run.runId}
              onSelect={() => {
                void controller?.inspectRun(run.runId).catch(() => undefined);
              }}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RunCard({
  run,
  selected,
  onSelect,
}: Readonly<{ run: TenantAgentRun; selected: boolean; onSelect: () => void }>) {
  return (
    <button
      type="button"
      className="tenant-agent-dashboard-run"
      data-selected={selected}
      onClick={onSelect}
    >
      <div>
        <strong>{run.subagentName}</strong>
        <span data-status={run.status}>{run.status}</span>
      </div>
      <p>{run.task}</p>
      <footer>
        <code>{run.runId}</code>
        <time>{run.createdAt}</time>
      </footer>
    </button>
  );
}

function ConfigEditor({
  config,
  hookCatalog,
  busy,
  onClose,
  onSave,
}: Readonly<{
  config: TenantAgentConfig;
  hookCatalog: TenantAgentDashboardViewModel['hookCatalog'];
  busy: boolean;
  onClose: () => void;
  onSave: (input: TenantAgentEditableConfig) => Promise<void>;
}>) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(() => ({
    ...config,
    enabledToolsText: config.enabledTools.join(', '),
    disabledToolsText: config.disabledTools.join(', '),
  }));
  const [hooksValid, setHooksValid] = useState(true);
  const input: TenantAgentEditableConfig = {
    llmModel: draft.llmModel.trim(),
    llmTemperature: draft.llmTemperature,
    patternLearningEnabled: draft.patternLearningEnabled,
    multiLevelThinkingEnabled: draft.multiLevelThinkingEnabled,
    maxWorkPlanSteps: draft.maxWorkPlanSteps,
    toolTimeoutSeconds: draft.toolTimeoutSeconds,
    enabledTools: splitTools(draft.enabledToolsText),
    disabledTools: splitTools(draft.disabledToolsText),
    runtimeHooks: draft.runtimeHooks,
  };
  return (
    <div className="tenant-agent-dashboard-editor-backdrop">
      <form
        className="tenant-agent-dashboard-editor"
        onSubmit={(event) => {
          event.preventDefault();
          void onSave(input).catch(() => undefined);
        }}
      >
        <header>
          <div>
            <span>{t('tenantAgentDashboard.config.editorEyebrow')}</span>
            <h2>{t('tenantAgentDashboard.config.editorTitle')}</h2>
          </div>
          <Button type="button" color="gray" variant="ghost" onClick={onClose}>
            <Cross2Icon />
          </Button>
        </header>
        <label>
          <span>{t('tenantAgentDashboard.config.model')}</span>
          <TextField.Root
            required
            value={draft.llmModel}
            onChange={(event) => setDraft({ ...draft, llmModel: event.target.value })}
          />
        </label>
        <div className="tenant-agent-dashboard-editor-row">
          <NumericField
            label={t('tenantAgentDashboard.config.temperature')}
            value={draft.llmTemperature}
            step="0.1"
            onChange={(llmTemperature) => setDraft({ ...draft, llmTemperature })}
          />
          <NumericField
            label={t('tenantAgentDashboard.config.planSteps')}
            value={draft.maxWorkPlanSteps}
            step="1"
            onChange={(maxWorkPlanSteps) => setDraft({ ...draft, maxWorkPlanSteps })}
          />
          <NumericField
            label={t('tenantAgentDashboard.config.timeout')}
            value={draft.toolTimeoutSeconds}
            step="1"
            onChange={(toolTimeoutSeconds) => setDraft({ ...draft, toolTimeoutSeconds })}
          />
        </div>
        <label>
          <span>{t('tenantAgentDashboard.config.enabledTools')}</span>
          <TextArea
            value={draft.enabledToolsText}
            onChange={(event) => setDraft({ ...draft, enabledToolsText: event.target.value })}
          />
        </label>
        <label>
          <span>{t('tenantAgentDashboard.config.disabledTools')}</span>
          <TextArea
            value={draft.disabledToolsText}
            onChange={(event) => setDraft({ ...draft, disabledToolsText: event.target.value })}
          />
        </label>
        <div className="tenant-agent-dashboard-editor-switches">
          <SwitchField
            label={t('tenantAgentDashboard.config.patternLearning')}
            checked={draft.patternLearningEnabled}
            onChange={(patternLearningEnabled) => setDraft({ ...draft, patternLearningEnabled })}
          />
          <SwitchField
            label={t('tenantAgentDashboard.config.multiLevelThinking')}
            checked={draft.multiLevelThinkingEnabled}
            onChange={(multiLevelThinkingEnabled) =>
              setDraft({ ...draft, multiLevelThinkingEnabled })
            }
          />
        </div>
        <TenantAgentDashboardHookEditor
          configuredHooks={config.runtimeHooks}
          catalog={hookCatalog}
          onValidityChange={setHooksValid}
          onChange={(runtimeHooks) => setDraft((current) => ({ ...current, runtimeHooks }))}
        />
        <footer>
          <Button type="button" color="gray" variant="soft" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" color="gray" disabled={busy || !input.llmModel || !hooksValid}>
            {t('common.save')}
          </Button>
        </footer>
      </form>
    </div>
  );
}

function DashboardState({
  model,
  onRetry,
}: Readonly<{ model: TenantAgentDashboardViewModel; onRetry: () => void }>) {
  const { t } = useI18n();
  return (
    <section className="tenant-agent-dashboard-state" data-state={model.state}>
      <span>{t('tenantAgentDashboard.eyebrow')}</span>
      <h1>{t(`tenantAgentDashboard.state.${model.state}.title`)}</h1>
      <p>{t(`tenantAgentDashboard.state.${model.state}.description`)}</p>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.retryVisible ? (
        <Button color="gray" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}

function ConfigValue({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ToolList({ title, tools }: Readonly<{ title: string; tools: readonly string[] }>) {
  return (
    <div>
      <strong>{title}</strong>
      <div>
        {tools.length ? tools.map((tool) => <code key={tool}>{tool}</code>) : <span>—</span>}
      </div>
    </div>
  );
}

function NumericField({
  label,
  value,
  step,
  onChange,
}: Readonly<{
  label: string;
  value: number;
  step: string;
  onChange: (value: number) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <TextField.Root
        type="number"
        required
        step={step}
        value={String(value)}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function SwitchField({
  label,
  checked,
  onChange,
}: Readonly<{
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}

function splitTools(value: string): readonly string[] {
  return [
    ...new Set(
      value
        .split(/[\n,]/u)
        .map((tool) => tool.trim())
        .filter(Boolean),
    ),
  ];
}
