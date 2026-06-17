/**
 * Instance Settings Page
 *
 * General configuration form for an instance plus danger zone for deletion.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input } from 'antd';
import { Loader2, Trash2 } from 'lucide-react';

import { providerAPI } from '@/services/api';
import { instanceService } from '@/services/instanceService';
import type { InstanceLlmConfigUpdate } from '@/services/instanceService';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySpin,
  LazyButton,
  LazySelect,
} from '@/components/ui/lazyAntd';

import {
  useCurrentInstance,
  useInstanceLoading,
  useInstanceSubmitting,
  useInstanceError,
  useInstanceActions,
} from '../../stores/instance';

import type { ProviderConfig } from '@/types/memory';

const { TextArea } = Input;

export const InstanceSettings: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const navigate = useNavigate();
  const { instanceId } = useParams<{ instanceId: string }>();

  const detail = useCurrentInstance();
  const isLoading = useInstanceLoading();
  const isSubmitting = useInstanceSubmitting();
  const error = useInstanceError();
  const { getInstance, setCurrentInstance, updateInstance, deleteInstance, clearError } =
    useInstanceActions();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isDirty, setIsDirty] = useState(false);
  const lastSyncedId = useRef<string | null>(null);
  const detailRequestId = useRef(0);

  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [llmProviderId, setLlmProviderId] = useState<string | undefined>(undefined);
  const [llmModelName, setLlmModelName] = useState<string | undefined>(undefined);
  const [llmApiKeyOverride, setLlmApiKeyOverride] = useState('');
  const [hasApiKeyOverride, setHasApiKeyOverride] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [llmConfigLoading, setLlmConfigLoading] = useState(false);
  const [llmConfigSaving, setLlmConfigSaving] = useState(false);
  const providersRequestId = useRef(0);
  const llmConfigRequestId = useRef(0);
  const modelsRequestId = useRef(0);

  // Load instance detail and sync form state
  useEffect(() => {
    if (!instanceId) {
      detailRequestId.current += 1;
      return;
    }

    const requestId = ++detailRequestId.current;
    getInstance(instanceId)
      .then((inst) => {
        if (detailRequestId.current !== requestId) return;

        setCurrentInstance(inst);
        if (lastSyncedId.current !== inst.id) {
          lastSyncedId.current = inst.id;
          setName(inst.name);
          setDescription(inst.description ?? '');
          setIsDirty(false);
        }
      })
      .catch((err: unknown) => {
        if (detailRequestId.current !== requestId) return;
        console.error('Failed to get instance details:', err);
      });

    return () => {
      detailRequestId.current += 1;
    };
  }, [instanceId, getInstance, setCurrentInstance]);

  useEffect(() => {
    return () => {
      clearError();
    };
  }, [clearError]);

  useEffect(() => {
    if (error) {
      message?.error(error);
      clearError();
    }
  }, [error, message, clearError]);

  useEffect(() => {
    const requestId = ++providersRequestId.current;
    providerAPI
      .list({ include_inactive: false })
      .then((result) => {
        if (providersRequestId.current !== requestId) return;
        setProviders(result);
      })
      .catch((err: unknown) => {
        if (providersRequestId.current !== requestId) return;
        console.error('Failed to list providers:', err);
      });

    return () => {
      providersRequestId.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!instanceId) {
      llmConfigRequestId.current += 1;
      setLlmConfigLoading(false);
      return;
    }

    const requestId = ++llmConfigRequestId.current;
    setLlmConfigLoading(true);
    instanceService
      .getLlmConfig(instanceId)
      .then((cfg) => {
        if (llmConfigRequestId.current !== requestId) return;

        setLlmProviderId(cfg.provider_id ?? undefined);
        setLlmModelName(cfg.model_name ?? undefined);
        setHasApiKeyOverride(cfg.has_api_key_override);
        setLlmApiKeyOverride('');
      })
      .catch((err: unknown) => {
        if (llmConfigRequestId.current !== requestId) return;

        console.error('Failed to get LLM config:', err);
        message?.error(t('tenant.instances.settings.llmConfigLoadError'));
      })
      .finally(() => {
        if (llmConfigRequestId.current !== requestId) return;
        setLlmConfigLoading(false);
      });

    return () => {
      llmConfigRequestId.current += 1;
    };
  }, [instanceId, message, t]);

  useEffect(() => {
    if (!llmProviderId) {
      modelsRequestId.current += 1;
      setAvailableModels([]);
      return;
    }
    const selectedProvider = providers.find((p) => p.id === llmProviderId);
    if (!selectedProvider) {
      modelsRequestId.current += 1;
      setAvailableModels([]);
      return;
    }

    const requestId = ++modelsRequestId.current;
    providerAPI
      .listModels(selectedProvider.provider_type)
      .then((res) => {
        if (modelsRequestId.current !== requestId) return;
        setAvailableModels(res.models.chat);
      })
      .catch((err: unknown) => {
        if (modelsRequestId.current !== requestId) return;
        console.error('Failed to list models:', err);
        setAvailableModels([]);
      });

    return () => {
      modelsRequestId.current += 1;
    };
  }, [llmProviderId, providers]);

  const handleNameChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setName(e.target.value);
    setIsDirty(true);
  }, []);

  const handleDescriptionChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDescription(e.target.value);
    setIsDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!instanceId || !isDirty) return;
    try {
      await updateInstance(instanceId, { name, description });
      message?.success(t('tenant.instances.settings.updateSuccess'));
      setIsDirty(false);
    } catch (err) {
      console.error('Failed to update instance:', err);
    }
  }, [instanceId, isDirty, name, description, updateInstance, message, t]);

  const handleDelete = useCallback(async () => {
    if (!instanceId) return;
    try {
      await deleteInstance(instanceId);
      message?.success(t('tenant.instances.settings.deleteSuccess'));
      void navigate('../..');
    } catch (err) {
      console.error('Failed to delete instance:', err);
    }
  }, [instanceId, deleteInstance, message, t, navigate]);

  const handleLlmProviderChange = useCallback((value: string | null | undefined) => {
    setLlmProviderId(value ?? undefined);
    setLlmModelName(undefined);
  }, []);

  const saveLlmConfig = useCallback(
    async (apiKeyOverride: string | null | undefined) => {
      if (!instanceId) return;
      setLlmConfigSaving(true);
      try {
        const payload: InstanceLlmConfigUpdate = {
          provider_id: llmProviderId ?? null,
          model_name: llmModelName ?? null,
        };
        if (apiKeyOverride !== undefined) {
          payload.api_key_override = apiKeyOverride;
        }
        const result = await instanceService.updateLlmConfig(instanceId, payload);
        setHasApiKeyOverride(result.has_api_key_override);
        setLlmApiKeyOverride('');
        message?.success(t('tenant.instances.settings.llmConfigUpdateSuccess'));
      } catch (err) {
        console.error('Failed to update LLM config:', err);
        message?.error(t('common.error'));
      } finally {
        setLlmConfigSaving(false);
      }
    },
    [instanceId, llmProviderId, llmModelName, message, t]
  );

  const handleLlmConfigSave = useCallback(async () => {
    if (!instanceId) return;
    const nextOverride = llmApiKeyOverride.trim();
    await saveLlmConfig(nextOverride ? nextOverride : undefined);
  }, [instanceId, llmApiKeyOverride, saveLlmConfig]);

  const handleClearLlmApiKeyOverride = useCallback(async () => {
    if (!instanceId || !hasApiKeyOverride) return;
    await saveLlmConfig(null);
  }, [hasApiKeyOverride, instanceId, saveLlmConfig]);

  if (isLoading && !detail) {
    return (
      <div className="flex items-center justify-center h-64">
        <LazySpin size="large" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-text-muted">{t('common.notFound')}</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-6">
      {/* General Settings */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-6">
        <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse mb-6">
          {t('tenant.instances.settings.generalSettings')}
        </h2>

        <div className="space-y-5">
          <div>
            <label
              htmlFor="instance-name"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
            >
              {t('tenant.instances.create.basic.name')}
            </label>
            <Input
              id="instance-name"
              value={name}
              onChange={handleNameChange}
              placeholder={t('tenant.instances.create.basic.name')}
              maxLength={100}
            />
          </div>

          <div>
            <label
              htmlFor="instance-description"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
            >
              {t('tenant.instances.settings.descriptionLabel')}
            </label>
            <TextArea
              id="instance-description"
              value={description}
              onChange={handleDescriptionChange}
              placeholder={t('tenant.instances.settings.descriptionPlaceholder')}
              rows={4}
              maxLength={500}
              showCount
            />
          </div>

          <div className="flex justify-end">
            <LazyButton
              type="primary"
              onClick={handleSave}
              disabled={!isDirty || isSubmitting}
              icon={isSubmitting ? <Loader2 size={16} className="animate-spin" /> : undefined}
            >
              {t('common.save')}
            </LazyButton>
          </div>
        </div>
      </div>

      {/* LLM Configuration */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-6">
        <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse mb-1">
          {t('tenant.instances.settings.llmConfig')}
        </h2>
        <p className="text-sm text-text-muted mb-6">
          {t('tenant.instances.settings.llmConfigDescription')}
        </p>

        {llmConfigLoading ? (
          <div className="flex items-center justify-center h-32">
            <LazySpin />
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <label
                htmlFor="llm-provider"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.settings.llmProvider')}
              </label>
              <LazySelect
                id="llm-provider"
                className="w-full"
                value={llmProviderId ?? null}
                onChange={handleLlmProviderChange}
                placeholder={t('tenant.instances.settings.llmProviderPlaceholder')}
                allowClear
                options={providers.map((p) => ({
                  label: p.name,
                  value: p.id,
                }))}
              />
            </div>

            <div>
              <label
                htmlFor="llm-model"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.settings.llmModel')}
              </label>
              <LazySelect
                id="llm-model"
                className="w-full"
                value={llmModelName}
                onChange={setLlmModelName}
                placeholder={t('tenant.instances.settings.llmModelPlaceholder')}
                allowClear
                disabled={!llmProviderId}
                options={availableModels.map((m) => ({
                  label: m,
                  value: m,
                }))}
              />
            </div>

            <div>
              <label
                htmlFor="llm-api-key"
                className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
              >
                {t('tenant.instances.settings.llmApiKeyOverride')}
              </label>
              <Input.Password
                id="llm-api-key"
                value={llmApiKeyOverride}
                onChange={(e) => {
                  setLlmApiKeyOverride(e.target.value);
                }}
                placeholder={
                  hasApiKeyOverride
                    ? t('tenant.instances.settings.llmApiKeyOverridePlaceholderExisting')
                    : t('tenant.instances.settings.llmApiKeyOverridePlaceholder')
                }
              />
              <p className="text-xs text-text-muted mt-1">
                {hasApiKeyOverride
                  ? t('tenant.instances.settings.llmApiKeyOverrideHintExisting')
                  : t('tenant.instances.settings.llmApiKeyOverrideHint')}
              </p>
              {hasApiKeyOverride && (
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="m-0 text-xs text-success-dark dark:text-success-light">
                    {t('tenant.instances.settings.llmApiKeySet')}
                  </p>
                  <LazyButton
                    danger
                    size="small"
                    onClick={handleClearLlmApiKeyOverride}
                    disabled={llmConfigSaving}
                  >
                    {t('tenant.instances.settings.llmApiKeyClearOverride')}
                  </LazyButton>
                </div>
              )}
            </div>

            <div className="flex justify-end">
              <LazyButton
                type="primary"
                onClick={handleLlmConfigSave}
                disabled={llmConfigSaving}
                icon={llmConfigSaving ? <Loader2 size={16} className="animate-spin" /> : undefined}
              >
                {t('common.save')}
              </LazyButton>
            </div>
          </div>
        )}
      </div>

      {/* Danger Zone */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-error dark:border-error/50 p-6">
        <h2 className="text-lg font-semibold text-error-dark dark:text-error-light mb-2">
          {t('tenant.instances.settings.dangerZone')}
        </h2>
        <p className="text-sm text-text-secondary dark:text-text-muted mb-4">
          {t('tenant.instances.settings.dangerZoneDescription')}
        </p>

        <div className="flex items-center justify-between p-4 border border-error dark:border-error/50 rounded-lg">
          <div>
            <p className="text-sm font-medium text-text-primary dark:text-text-inverse">
              {t('tenant.instances.settings.deleteInstance')}
            </p>
            <p className="text-xs text-text-muted dark:text-text-muted mt-0.5">
              {t('tenant.instances.settings.deleteInstanceDescription')}
            </p>
          </div>
          <LazyPopconfirm
            title={t('tenant.instances.settings.deleteConfirm')}
            onConfirm={handleDelete}
            okText={t('common.delete')}
            cancelText={t('common.cancel')}
            okButtonProps={{ danger: true }}
          >
            <LazyButton type="primary" danger disabled={isSubmitting} icon={<Trash2 size={16} />}>
              {t('common.delete')}
            </LazyButton>
          </LazyPopconfirm>
        </div>
      </div>
    </div>
  );
};
