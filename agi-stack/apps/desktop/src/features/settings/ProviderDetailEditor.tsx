import { useEffect, useMemo, useState } from 'react';
import { Badge, Button, Text } from '@radix-ui/themes';
import {
  CheckCircledIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  LlmProviderMutationInput,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';
import {
  providerDraftFromProvider,
  providerDraftIsValid,
  providerMutationFromDraft,
  providerValidationSignal,
  type ProviderEditorDraft,
} from './providerManagementModel';
import './ProviderDetailEditor.css';

type ProviderDetailEditorProps = {
  provider: ManagedLlmProvider;
  mode: RuntimeMode;
  canManage: boolean;
  onSave: (
    provider: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ) => Promise<ManagedLlmProvider>;
  onValidate: (providerId: string) => Promise<LlmProviderValidationOutcome>;
};

function statusColor(status: string | null | undefined): 'green' | 'red' | 'amber' | 'gray' {
  if (status === 'healthy' || status === 'configuration_valid') return 'green';
  if (status === 'unhealthy' || status === 'failed' || status === 'error') return 'red';
  if (status === 'needs_credentials' || status === 'not_configured') return 'amber';
  return 'gray';
}

export function ProviderDetailEditor({
  provider,
  mode,
  canManage,
  onSave,
  onValidate,
}: ProviderDetailEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<ProviderEditorDraft>(() =>
    providerDraftFromProvider(provider),
  );
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<LlmProviderValidationOutcome | null>(null);

  useEffect(() => {
    setDraft(providerDraftFromProvider(provider));
    setError(null);
    setValidation(null);
  }, [provider]);

  const mutation = useMemo(() => providerMutationFromDraft(draft), [draft]);
  const dirty = useMemo(
    () =>
      JSON.stringify({ ...mutation, apiKey: undefined }) !==
        JSON.stringify({
          ...providerMutationFromDraft(providerDraftFromProvider(provider)),
          apiKey: undefined,
        }) || Boolean(mutation.apiKey),
    [mutation, provider],
  );

  const updateDraft = <Key extends keyof ProviderEditorDraft>(
    key: Key,
    value: ProviderEditorDraft[Key],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const save = async () => {
    setSaving(true);
    setError(null);
    setValidation(null);
    try {
      const updated = await onSave(provider, mutation);
      setDraft(providerDraftFromProvider(updated));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setDraft((current) => ({ ...current, apiKey: '' }));
    } finally {
      setSaving(false);
    }
  };

  const validate = async () => {
    setValidating(true);
    setError(null);
    try {
      setValidation(await onValidate(provider.id));
    } catch (caught) {
      setValidation(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setValidating(false);
    }
  };

  const validationSignal = validation ? providerValidationSignal(validation) : null;

  return (
    <aside className="provider-detail-editor">
      <header className="provider-detail-heading">
        <span className="settings-resource-icon">
          <CubeIcon />
        </span>
        <div>
          <Text size="1" color="gray">
            {t('settings.providerConnection').toUpperCase()}
          </Text>
          <h2>{provider.name || provider.provider_type}</h2>
          <p>{t('settings.providerConnectionDescription')}</p>
        </div>
        <Badge color={statusColor(provider.health_status)} variant="soft">
          {provider.health_status || t('settings.notChecked')}
        </Badge>
      </header>

      {!canManage ? (
        <div className="provider-readonly-notice">
          <LockClosedIcon />
          <span>
            <strong>{t('settings.providerReadOnly')}</strong>
            <small>{t('settings.providerReadOnlyDescription')}</small>
          </span>
        </div>
      ) : null}

      <form
        className="provider-editor-form"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="provider-editor-grid">
          <label>
            <span>{t('settings.providerName')}</span>
            <input
              value={draft.name}
              disabled={!canManage || saving}
              onChange={(event) => updateDraft('name', event.target.value)}
            />
          </label>
          <label>
            <span>{t('settings.providerType')}</span>
            <input
              value={draft.providerType}
              list="provider-type-options"
              disabled={!canManage || saving}
              onChange={(event) => updateDraft('providerType', event.target.value)}
            />
            <datalist id="provider-type-options">
              <option value="openai" />
              <option value="openai_compatible" />
              <option value="anthropic" />
              {mode === 'cloud' ? <option value="ollama" /> : null}
              {mode === 'cloud' ? <option value="openrouter" /> : null}
            </datalist>
          </label>
          <label>
            <span>{t('settings.authMethod')}</span>
            <select
              value={draft.authMethod}
              disabled={!canManage || saving || mode === 'cloud'}
              onChange={(event) =>
                updateDraft('authMethod', event.target.value === 'none' ? 'none' : 'api_key')
              }
            >
              <option value="api_key">API key</option>
              <option value="none">{t('settings.noAuthentication')}</option>
            </select>
          </label>
          <label className="provider-editor-wide">
            <span>{t('settings.endpoint')}</span>
            <input
              type="url"
              value={draft.baseUrl}
              placeholder="https://api.example.com/v1"
              disabled={!canManage || saving}
              onChange={(event) => updateDraft('baseUrl', event.target.value)}
            />
          </label>
          <label>
            <span>{t('settings.primaryModel')}</span>
            <input
              value={draft.primaryModel}
              placeholder="provider/model-id"
              disabled={!canManage || saving}
              onChange={(event) => updateDraft('primaryModel', event.target.value)}
            />
          </label>
          <label>
            <span>{t('settings.apiKey')}</span>
            <input
              type="password"
              value={draft.apiKey}
              autoComplete="new-password"
              placeholder={t('settings.apiKeyPlaceholder')}
              disabled={!canManage || saving || draft.authMethod === 'none'}
              onChange={(event) => updateDraft('apiKey', event.target.value)}
            />
            <small>{t('settings.apiKeyHelp')}</small>
          </label>
          <label className="provider-editor-wide">
            <span>{t('settings.allowedModels')}</span>
            <textarea
              rows={4}
              value={draft.allowedModels}
              placeholder={t('settings.allowedModelsPlaceholder')}
              disabled={!canManage || saving}
              onChange={(event) => updateDraft('allowedModels', event.target.value)}
            />
            <small>{t('settings.allowedModelsHelp')}</small>
          </label>
        </div>

        <label className="provider-active-toggle">
          <input
            type="checkbox"
            checked={draft.active}
            disabled={!canManage || saving}
            onChange={(event) => updateDraft('active', event.target.checked)}
          />
          <span>
            <strong>{t('settings.providerEnabled')}</strong>
            <small>{t('settings.providerEnabledDescription')}</small>
          </span>
        </label>

        <div className="provider-editor-facts">
          <span>{t('settings.revision')}: {provider.revision ?? 0}</span>
          <span>
            {t('settings.credentials')}:{' '}
            {provider.credential_configured
              ? t('settings.configuredInMemory')
              : t('settings.credentialsRequired')}
          </span>
          <span>
            {t('settings.runtimeSelection')}:{' '}
            {provider.runtime_selected ? t('settings.selected') : t('settings.notSelected')}
          </span>
        </div>

        {validation ? (
          <div className={`provider-validation-result ${validation.probed ? 'probed' : 'local'}`}>
            {validationSignal?.kind === 'external_probe' ? (
              <CheckCircledIcon />
            ) : (
              <ExclamationTriangleIcon />
            )}
            <span>
              <strong>
                {t(
                  validationSignal?.kind === 'external_probe'
                    ? 'settings.externalProbeResult'
                    : 'settings.configurationOnlyResult',
                )}
              </strong>
              <small>{validation.detail || validation.status}</small>
            </span>
            <Badge color={statusColor(validation.status)} variant="soft">
              {validation.status}
            </Badge>
          </div>
        ) : null}

        {error ? (
          <div className="provider-editor-error" role="alert">
            <ExclamationTriangleIcon />
            <span>{error}</span>
          </div>
        ) : null}

        {canManage ? (
          <footer className="provider-editor-actions">
            <Button
              type="button"
              variant="soft"
              loading={validating}
              disabled={saving || validating}
              onClick={() => void validate()}
            >
              <ReloadIcon />
              {t(mode === 'local' ? 'settings.validateConfiguration' : 'settings.testConnection')}
            </Button>
            <Button
              type="submit"
              loading={saving}
              disabled={!dirty || !providerDraftIsValid(draft) || saving || validating}
            >
              {t('settings.saveProvider')}
            </Button>
          </footer>
        ) : null}
      </form>
    </aside>
  );
}
