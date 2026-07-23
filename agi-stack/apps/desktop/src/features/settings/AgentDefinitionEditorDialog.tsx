import { useRef, useState } from 'react';
import {
  Cross2Icon,
  ExclamationTriangleIcon,
  PersonIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
  ProjectSummary,
} from '../../types';
import {
  agentDefinitionDraftFrom,
  agentDefinitionMutationFromDraft,
  validateAgentDefinitionDraft,
  type AgentDefinitionDraftErrors,
  type AgentDefinitionEditorDraft,
} from './agentDefinitionFormModel';
import { useModalDialog } from './useModalDialog';

import './AgentDefinitionEditorDialog.css';

type EditorTab = 'identity' | 'runtime' | 'capabilities' | 'coordination';

export function AgentDefinitionEditorDialog({
  definition,
  projects,
  initialProjectId,
  externalAcpAgents,
  externalAcpAgentsLoading,
  externalAcpAgentsError,
  busy,
  error,
  onClose,
  onSave,
  onDelete,
}: {
  definition: ManagedAgentDefinition | null;
  projects: ProjectSummary[];
  initialProjectId: string | null;
  externalAcpAgents: ManagedExternalAcpAgent[];
  externalAcpAgentsLoading: boolean;
  externalAcpAgentsError: string | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (input: ManagedAgentDefinitionMutation) => void;
  onDelete: (() => void) | null;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<AgentDefinitionEditorDraft>(() =>
    agentDefinitionDraftFrom(definition, initialProjectId),
  );
  const [errors, setErrors] = useState<AgentDefinitionDraftErrors>({});
  const [activeTab, setActiveTab] = useState<EditorTab>('identity');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: firstInputRef,
    nested: true,
    onClose,
  });

  const update = <K extends keyof AgentDefinitionEditorDraft>(
    key: K,
    value: AgentDefinitionEditorDraft[K],
  ) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const submit = () => {
    const nextErrors = validateAgentDefinitionDraft(draft);
    setErrors(nextErrors);
    const firstError = Object.keys(nextErrors)[0] as keyof AgentDefinitionEditorDraft | undefined;
    if (firstError) {
      setActiveTab(tabForField(firstError));
      return;
    }
    onSave(agentDefinitionMutationFromDraft(draft));
  };

  const tabs: Array<{ id: EditorTab; label: string }> = [
    { id: 'identity', label: t('settings.agentEditor.identity') },
    { id: 'runtime', label: t('settings.agentEditor.runtime') },
    { id: 'capabilities', label: t('settings.agentEditor.capabilities') },
    { id: 'coordination', label: t('settings.agentEditor.coordination') },
  ];

  return (
    <div
      className="agent-definition-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busy) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="agent-definition-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t(
          definition ? 'settings.agentEditor.editTitle' : 'settings.agentEditor.createTitle',
        )}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-definition-dialog-heading">
          <div className="agent-definition-dialog-icon">
            <PersonIcon />
          </div>
          <div>
            <span>{t('settings.agentsEyebrow')}</span>
            <h2>
              {t(
                definition
                  ? 'settings.agentEditor.editTitle'
                  : 'settings.agentEditor.createTitle',
              )}
            </h2>
            <p>{t('settings.agentEditor.description')}</p>
          </div>
          <button
            type="button"
            className="agent-definition-dialog-close"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={onClose}
          >
            <Cross2Icon />
          </button>
        </header>

        <nav className="agent-definition-dialog-tabs" aria-label={t('settings.agentEditor.tabs')}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? 'active' : ''}
              aria-pressed={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="agent-definition-dialog-body">
          {activeTab === 'identity' ? (
            <div className="agent-definition-form-grid">
              <EditorField
                label={t('settings.agentEditor.name')}
                error={fieldError(errors, 'name', t)}
              >
                <input
                  ref={firstInputRef}
                  value={draft.name}
                  disabled={busy || definition?.source === 'builtin'}
                  placeholder="release_reviewer"
                  onChange={(event) => update('name', event.target.value)}
                />
              </EditorField>
              <EditorField
                label={t('settings.agentEditor.displayName')}
                error={fieldError(errors, 'displayName', t)}
              >
                <input
                  value={draft.displayName}
                  disabled={busy}
                  onChange={(event) => update('displayName', event.target.value)}
                />
              </EditorField>
              <EditorField label={t('settings.agentEditor.scope')}>
                <select
                  value={draft.scopeId}
                  disabled={busy}
                  onChange={(event) => update('scopeId', event.target.value)}
                >
                  <option value="">{t('settings.agentEditor.tenantScope')}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.agentEditor.systemPrompt')}
                error={fieldError(errors, 'systemPrompt', t)}
              >
                <textarea
                  rows={6}
                  value={draft.systemPrompt}
                  disabled={busy}
                  onChange={(event) => update('systemPrompt', event.target.value)}
                />
              </EditorField>
              <EditorField
                className="wide"
                label={t('settings.agentEditor.triggerDescription')}
                error={fieldError(errors, 'triggerDescription', t)}
              >
                <input
                  value={draft.triggerDescription}
                  disabled={busy}
                  onChange={(event) => update('triggerDescription', event.target.value)}
                />
              </EditorField>
              <ListField
                label={t('settings.agentEditor.triggerKeywords')}
                value={draft.triggerKeywords}
                disabled={busy}
                onChange={(value) => update('triggerKeywords', value)}
              />
              <ListField
                label={t('settings.agentEditor.triggerExamples')}
                value={draft.triggerExamples}
                disabled={busy}
                onChange={(value) => update('triggerExamples', value)}
              />
            </div>
          ) : null}

          {activeTab === 'runtime' ? (
            <div className="agent-definition-form-grid">
              <h3 className="agent-definition-form-section">
                {t('settings.agentEditor.execution')}
              </h3>
              <EditorField label={t('settings.agentEditor.executionBackend')}>
                <select
                  value={draft.executionBackendType}
                  disabled={busy}
                  onChange={(event) =>
                    update(
                      'executionBackendType',
                      event.target.value === 'acp_external' ? 'acp_external' : 'memstack',
                    )
                  }
                >
                  <option value="memstack">
                    {t('settings.agentEditor.executionBackendMemstack')}
                  </option>
                  <option value="acp_external">
                    {t('settings.agentEditor.executionBackendAcp')}
                  </option>
                </select>
              </EditorField>
              {draft.executionBackendType === 'acp_external' ? (
                <EditorField
                  label={t('settings.agentEditor.externalAcpAgent')}
                  error={
                    fieldError(errors, 'executionBackendAcpAgentKey', t) ??
                    externalAcpAgentsError ??
                    undefined
                  }
                >
                  <select
                    value={draft.executionBackendAcpAgentKey}
                    disabled={busy || externalAcpAgentsLoading}
                    onChange={(event) =>
                      update('executionBackendAcpAgentKey', event.target.value)
                    }
                  >
                    <option value="">
                      {t(
                        externalAcpAgentsLoading
                          ? 'settings.agentEditor.loadingExternalAcpAgents'
                          : 'settings.agentEditor.selectExternalAcpAgent',
                      )}
                    </option>
                    {draft.executionBackendAcpAgentKey &&
                    !externalAcpAgents.some(
                      (agent) => agent.agentKey === draft.executionBackendAcpAgentKey,
                    ) ? (
                      <option value={draft.executionBackendAcpAgentKey}>
                        {draft.executionBackendAcpAgentKey}
                      </option>
                    ) : null}
                    {externalAcpAgents
                      .filter(
                        (agent) =>
                          agent.enabled ||
                          agent.agentKey === draft.executionBackendAcpAgentKey,
                      )
                      .map((agent) => (
                        <option
                          key={agent.id}
                          value={agent.agentKey}
                          disabled={!agent.enabled || !agent.available}
                        >
                          {agent.name} ({agent.agentKey})
                        </option>
                      ))}
                  </select>
                </EditorField>
              ) : null}
              <EditorField label={t('settings.agentEditor.model')}>
                <input
                  value={draft.model}
                  disabled={busy || draft.executionBackendType === 'acp_external'}
                  placeholder="inherit"
                  onChange={(event) => update('model', event.target.value)}
                />
              </EditorField>
              <NumberField
                label={t('settings.agentEditor.temperature')}
                value={draft.temperature}
                min={0}
                max={2}
                step={0.1}
                disabled={busy}
                error={fieldError(errors, 'temperature', t)}
                onChange={(value) => update('temperature', value)}
              />
              <NumberField
                label={t('settings.agentEditor.maxTokens')}
                value={draft.maxTokens}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'maxTokens', t)}
                onChange={(value) => update('maxTokens', value)}
              />
              <NumberField
                label={t('settings.agentEditor.maxIterations')}
                value={draft.maxIterations}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'maxIterations', t)}
                onChange={(value) => update('maxIterations', value)}
              />
              <ListField
                className="wide"
                label={t('settings.agentEditor.fallbackModels')}
                value={draft.fallbackModels}
                disabled={busy}
                onChange={(value) => update('fallbackModels', value)}
              />
              <h3 className="agent-definition-form-section">
                {t('settings.agentEditor.workspaceConfig')}
              </h3>
              <EditorField label={t('settings.agentEditor.workspaceType')}>
                <select
                  value={draft.workspaceType}
                  disabled={busy}
                  onChange={(event) => {
                    const value = event.target.value;
                    update(
                      'workspaceType',
                      value === 'isolated' || value === 'inherited' ? value : 'shared',
                    );
                  }}
                >
                  <option value="shared">{t('settings.agentEditor.workspaceShared')}</option>
                  <option value="isolated">{t('settings.agentEditor.workspaceIsolated')}</option>
                  <option value="inherited">
                    {t('settings.agentEditor.workspaceInherited')}
                  </option>
                </select>
              </EditorField>
              <EditorField label={t('settings.agentEditor.workspaceBaseDir')}>
                <input
                  value={draft.workspaceBaseDir}
                  disabled={busy}
                  onChange={(event) => update('workspaceBaseDir', event.target.value)}
                />
              </EditorField>
            </div>
          ) : null}

          {activeTab === 'capabilities' ? (
            <div className="agent-definition-form-grid">
              <ListField
                className="wide"
                label={t('settings.agentEditor.allowedTools')}
                value={draft.allowedTools}
                disabled={busy}
                onChange={(value) => update('allowedTools', value)}
              />
              <ListField
                label={t('settings.agentEditor.allowedSkills')}
                value={draft.allowedSkills}
                disabled={busy}
                onChange={(value) => update('allowedSkills', value)}
              />
              <ListField
                label={t('settings.agentEditor.allowedMcpServers')}
                value={draft.allowedMcpServers}
                disabled={busy}
                onChange={(value) => update('allowedMcpServers', value)}
              />
              <EditorField label={t('settings.agentEditor.toolPolicyPrecedence')}>
                <select
                  value={draft.toolPolicyPrecedence}
                  disabled={busy}
                  onChange={(event) =>
                    update(
                      'toolPolicyPrecedence',
                      event.target.value === 'allow_first' ? 'allow_first' : 'deny_first',
                    )
                  }
                >
                  <option value="deny_first">{t('settings.agentEditor.denyFirst')}</option>
                  <option value="allow_first">{t('settings.agentEditor.allowFirst')}</option>
                </select>
              </EditorField>
              <ListField
                label={t('settings.agentEditor.toolPolicyAllow')}
                value={draft.toolPolicyAllow}
                disabled={busy}
                onChange={(value) => update('toolPolicyAllow', value)}
              />
              <ListField
                label={t('settings.agentEditor.toolPolicyDeny')}
                value={draft.toolPolicyDeny}
                disabled={busy}
                onChange={(value) => update('toolPolicyDeny', value)}
              />
            </div>
          ) : null}

          {activeTab === 'coordination' ? (
            <div className="agent-definition-form-grid">
              <h3 className="agent-definition-form-section">
                {t('settings.agentEditor.spawnPolicy')}
              </h3>
              <ToggleField
                label={t('settings.agentEditor.canSpawn')}
                checked={draft.canSpawn}
                disabled={busy}
                onChange={(value) => update('canSpawn', value)}
              />
              <NumberField
                label={t('settings.agentEditor.maxSpawnDepth')}
                value={draft.maxSpawnDepth}
                min={0}
                step={1}
                disabled={busy || !draft.canSpawn}
                error={fieldError(errors, 'maxSpawnDepth', t)}
                onChange={(value) => update('maxSpawnDepth', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.spawnMaxActiveRuns')}
                value={draft.spawnMaxActiveRuns}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'spawnMaxActiveRuns', t)}
                onChange={(value) => update('spawnMaxActiveRuns', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.spawnMaxChildren')}
                value={draft.spawnMaxChildrenPerRequester}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'spawnMaxChildrenPerRequester', t)}
                onChange={(value) => update('spawnMaxChildrenPerRequester', value)}
              />
              <ListField
                className="wide"
                label={t('settings.agentEditor.spawnAllowedSubagents')}
                value={draft.spawnAllowedSubagents}
                disabled={busy}
                onChange={(value) => update('spawnAllowedSubagents', value)}
              />
              <ToggleField
                label={t('settings.agentEditor.agentToAgent')}
                checked={draft.agentToAgentEnabled}
                disabled={busy}
                onChange={(value) => update('agentToAgentEnabled', value)}
              />
              <ListField
                label={t('settings.agentEditor.agentAllowlist')}
                value={draft.agentToAgentAllowlist}
                disabled={busy || !draft.agentToAgentEnabled}
                onChange={(value) => update('agentToAgentAllowlist', value)}
              />
              <ToggleField
                label={t('settings.agentEditor.discoverable')}
                checked={draft.discoverable}
                disabled={busy}
                onChange={(value) => update('discoverable', value)}
              />
              <NumberField
                label={t('settings.agentEditor.maxRetries')}
                value={draft.maxRetries}
                min={0}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'maxRetries', t)}
                onChange={(value) => update('maxRetries', value)}
              />
              <h3 className="agent-definition-form-section">
                {t('settings.agentEditor.sessionPolicy')}
              </h3>
              <EditorField label={t('settings.agentEditor.sessionDmScope')}>
                <select
                  value={draft.sessionPolicyDmScope}
                  disabled={busy}
                  onChange={(event) => {
                    const value = event.target.value;
                    update(
                      'sessionPolicyDmScope',
                      value === 'per_user' || value === 'per_chat' || value === 'global'
                        ? value
                        : '',
                    );
                  }}
                >
                  <option value="">{t('settings.agentEditor.useDefault')}</option>
                  <option value="per_user">{t('settings.agentEditor.dmScopePerUser')}</option>
                  <option value="per_chat">{t('settings.agentEditor.dmScopePerChat')}</option>
                  <option value="global">{t('settings.agentEditor.dmScopeGlobal')}</option>
                </select>
              </EditorField>
              <OptionalNumberField
                label={t('settings.agentEditor.sessionMaxMessages')}
                value={draft.sessionPolicyMaxMessages}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'sessionPolicyMaxMessages', t)}
                onChange={(value) => update('sessionPolicyMaxMessages', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.sessionIdleResetMinutes')}
                value={draft.sessionPolicyIdleResetMinutes}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'sessionPolicyIdleResetMinutes', t)}
                onChange={(value) => update('sessionPolicyIdleResetMinutes', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.sessionDailyResetHour')}
                value={draft.sessionPolicyDailyResetHour}
                min={0}
                max={23}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'sessionPolicyDailyResetHour', t)}
                onChange={(value) => update('sessionPolicyDailyResetHour', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.sessionTtlHours')}
                value={draft.sessionPolicyTtlHours}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'sessionPolicyTtlHours', t)}
                onChange={(value) => update('sessionPolicyTtlHours', value)}
              />
              <h3 className="agent-definition-form-section">
                {t('settings.agentEditor.delegateConfig')}
              </h3>
              <EditorField label={t('settings.agentEditor.delegateCapabilityTier')}>
                <select
                  value={draft.delegateCapabilityTier}
                  disabled={busy}
                  onChange={(event) => {
                    const value = event.target.value;
                    update(
                      'delegateCapabilityTier',
                      value === 'full' ||
                        value === 'read_write' ||
                        value === 'read_only' ||
                        value === 'none'
                        ? value
                        : '',
                    );
                  }}
                >
                  <option value="">{t('settings.agentEditor.useDefault')}</option>
                  <option value="full">{t('settings.agentEditor.capabilityFull')}</option>
                  <option value="read_write">
                    {t('settings.agentEditor.capabilityReadWrite')}
                  </option>
                  <option value="read_only">
                    {t('settings.agentEditor.capabilityReadOnly')}
                  </option>
                  <option value="none">{t('settings.agentEditor.capabilityNone')}</option>
                </select>
              </EditorField>
              <OptionalNumberField
                label={t('settings.agentEditor.delegateMaxDepth')}
                value={draft.delegateMaxDelegationDepth}
                min={0}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'delegateMaxDelegationDepth', t)}
                onChange={(value) => update('delegateMaxDelegationDepth', value)}
              />
              <OptionalNumberField
                label={t('settings.agentEditor.delegateBudgetTokens')}
                value={draft.delegateBudgetLimitTokens}
                min={1}
                step={1}
                disabled={busy}
                error={fieldError(errors, 'delegateBudgetLimitTokens', t)}
                onChange={(value) => update('delegateBudgetLimitTokens', value)}
              />
              <ListField
                className="wide"
                label={t('settings.agentEditor.delegateAllowedTools')}
                value={draft.delegateAllowedTools}
                disabled={busy}
                onChange={(value) => update('delegateAllowedTools', value)}
              />
            </div>
          ) : null}
        </div>

        {error ? (
          <div className="agent-definition-dialog-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{error}</span>
          </div>
        ) : null}

        <footer className="agent-definition-dialog-footer">
          <div>
            {definition && onDelete ? (
              confirmDelete ? (
                <div className="agent-definition-delete-confirmation">
                  <span>{t('settings.agentEditor.deleteConfirmation')}</span>
                  <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>
                    {t('common.cancel')}
                  </button>
                  <button type="button" className="danger" disabled={busy} onClick={onDelete}>
                    {t('settings.agentEditor.confirmDelete')}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="agent-definition-delete"
                  disabled={busy}
                  onClick={() => setConfirmDelete(true)}
                >
                  <TrashIcon /> {t('settings.agentEditor.delete')}
                </button>
              )
            ) : null}
          </div>
          <div>
            <button type="button" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </button>
            <button type="button" className="primary" disabled={busy} onClick={submit}>
              {busy ? <ReloadIcon className="managed-resource-spin" /> : <PersonIcon />}
              {t(definition ? 'common.save' : 'common.create')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function EditorField({
  label,
  error,
  className = '',
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`agent-definition-field ${className}`.trim()}>
      <span>{label}</span>
      {children}
      {error ? <small role="alert">{error}</small> : null}
    </label>
  );
}

function ListField({
  label,
  value,
  disabled,
  onChange,
  className = '',
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <EditorField label={label} className={className}>
      <textarea
        rows={4}
        value={value}
        disabled={disabled}
        placeholder={t('settings.agentEditor.listPlaceholder')}
        onChange={(event) => onChange(event.target.value)}
      />
    </EditorField>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  disabled,
  error,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max?: number;
  step: number;
  disabled: boolean;
  error?: string;
  onChange: (value: number) => void;
}) {
  return (
    <EditorField label={label} error={error}>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </EditorField>
  );
}

function ToggleField({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="agent-definition-toggle-field">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function OptionalNumberField({
  label,
  value,
  min,
  max,
  step,
  disabled,
  error,
  onChange,
}: {
  label: string;
  value: number | null;
  min: number;
  max?: number;
  step: number;
  disabled: boolean;
  error?: string;
  onChange: (value: number | null) => void;
}) {
  return (
    <EditorField label={label} error={error}>
      <input
        type="number"
        value={value ?? ''}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value === '' ? null : Number(event.target.value))
        }
      />
    </EditorField>
  );
}

function tabForField(field: keyof AgentDefinitionEditorDraft): EditorTab {
  if (
    field === 'name' ||
    field === 'displayName' ||
    field === 'systemPrompt' ||
    field === 'scopeId' ||
    field === 'triggerDescription' ||
    field === 'triggerKeywords' ||
    field === 'triggerExamples'
  ) {
    return 'identity';
  }
  if (
    field === 'model' ||
    field === 'temperature' ||
    field === 'maxTokens' ||
    field === 'maxIterations' ||
    field === 'fallbackModels'
  ) {
    return 'runtime';
  }
  if (
    field === 'allowedTools' ||
    field === 'allowedSkills' ||
    field === 'allowedMcpServers' ||
    field === 'toolPolicyPrecedence' ||
    field === 'toolPolicyAllow' ||
    field === 'toolPolicyDeny'
  ) {
    return 'capabilities';
  }
  return 'coordination';
}

function fieldError(
  errors: AgentDefinitionDraftErrors,
  field: keyof AgentDefinitionEditorDraft,
  t: (key: string) => string,
): string | undefined {
  const error = errors[field];
  return error ? t(`settings.agentEditor.error.${error}`) : undefined;
}
