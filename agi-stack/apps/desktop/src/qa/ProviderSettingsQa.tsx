import '@radix-ui/themes/styles.css';
import { Badge, Theme } from '@radix-ui/themes';
import { CubeIcon, GearIcon, LockClosedIcon, MagnifyingGlassIcon } from '@radix-ui/react-icons';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProviderDetailEditor } from '../features/settings/ProviderDetailEditor';
import '../features/settings/SettingsWindow.css';
import { I18nProvider } from '../i18n';
import type {
  LlmProviderMutationInput,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
} from '../types';
import '../styles.css';

declare global {
  var __providerSettingsQaRoot: Root | undefined;
}

const initialProvider: ManagedLlmProvider = {
  id: 'local-runtime',
  name: 'Local OpenAI gateway',
  provider_type: 'openai_compatible',
  auth_method: 'api_key',
  is_active: true,
  base_url: 'http://127.0.0.1:11434/v1',
  llm_model: 'qwen3-coder',
  allowed_models: ['qwen3-coder', 'qwen3-small'],
  health_status: 'needs_credentials',
  credential_configured: false,
  runtime_selected: true,
  revision: 7,
};

function ProviderSettingsQa() {
  const [provider, setProvider] = useState(initialProvider);

  const save = async (
    current: ManagedLlmProvider,
    mutation: LlmProviderMutationInput,
  ): Promise<ManagedLlmProvider> => {
    const updated: ManagedLlmProvider = {
      ...current,
      name: mutation.name,
      provider_type: mutation.providerType,
      auth_method: mutation.authMethod,
      base_url: mutation.baseUrl,
      llm_model: mutation.primaryModel,
      allowed_models: mutation.allowedModels,
      is_active: mutation.active,
      credential_configured: Boolean(mutation.apiKey),
      health_status: mutation.apiKey ? 'configuration_valid' : 'needs_credentials',
      revision: mutation.expectedRevision + 1,
    };
    setProvider(updated);
    return updated;
  };

  const validate = async (): Promise<LlmProviderValidationOutcome> => ({
    provider,
    status: provider.credential_configured ? 'configuration_valid' : 'needs_credentials',
    probed: false,
    detail: 'configuration validated locally; no external request was sent',
  });

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="settings-window-backdrop provider-settings-qa">
        <section className="settings-window-dialog">
          <header className="settings-window-titlebar">
            <div className="settings-window-brand">
              <span><GearIcon /></span>
              <div>
                <strong>Settings</strong>
                <small>Account, workspace, runtime, and Agent resources</small>
              </div>
            </div>
            <label className="settings-window-search">
              <MagnifyingGlassIcon />
              <input value="" readOnly placeholder="Search settings" />
            </label>
            <span />
          </header>
          <div className="settings-window-body">
            <aside className="settings-window-rail">
              <section className="settings-rail-group">
                <span>AI RESOURCES</span>
                <button className="active" type="button">
                  <CubeIcon />
                  <span><strong>Models</strong><small>Providers, models, and health</small></span>
                </button>
              </section>
              <div className="settings-window-scope">
                <LockClosedIcon />
                <span><strong>Local Desktop</strong><small>Local project</small></span>
              </div>
            </aside>
            <main className="settings-window-content">
              <div className="settings-page">
                <header className="settings-page-heading">
                  <div>
                    <span>MODELS</span>
                    <h1>Model management</h1>
                    <p>Configure Provider credentials first, then expose exact model IDs.</p>
                  </div>
                </header>
                <div className="settings-resource-workspace">
                  <div className="settings-resource-list">
                    <article className="settings-resource-row selected">
                      <button className="settings-resource-main" type="button">
                        <span className="settings-resource-icon"><CubeIcon /></span>
                        <div>
                          <strong>{provider.name}</strong>
                          <p>{provider.base_url}</p>
                          <div className="settings-resource-meta">
                            <span>{provider.provider_type}</span>
                            <span>{provider.llm_model}</span>
                          </div>
                        </div>
                      </button>
                      <aside>
                        <Badge color="amber" variant="soft">{provider.health_status}</Badge>
                      </aside>
                    </article>
                  </div>
                  <ProviderDetailEditor
                    provider={provider}
                    mode="local"
                    canManage
                    onSave={save}
                    onValidate={validate}
                  />
                </div>
              </div>
            </main>
          </div>
        </section>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__providerSettingsQaRoot ?? createRoot(root);
globalThis.__providerSettingsQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider><ProviderSettingsQa /></I18nProvider>
  </React.StrictMode>,
);
