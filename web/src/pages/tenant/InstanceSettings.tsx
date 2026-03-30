/**
 * Instance Settings Page
 *
 * General configuration form for an instance plus danger zone for deletion.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input, Select } from 'antd';
import { Loader2, Trash2 } from 'lucide-react';

import { providerAPI } from '@/services/api';
import { instanceService } from '@/services/instanceService';
import type { InstanceLlmConfigUpdate } from '@/services/instanceService';

import { useLazyMessage, LazyPopconfirm, LazySpin } from '@/components/ui/lazyAntd';

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

  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [llmProviderId, setLlmProviderId] = useState<string | undefined>(undefined);
  const [llmModelName, setLlmModelName] = useState<string | undefined>(undefined);
  const [llmApiKeyOverride, setLlmApiKeyOverride] = useState('');
  const [hasApiKeyOverride, setHasApiKeyOverride] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [llmConfigLoading, setLlmConfigLoading] = useState(false);
  const [llmConfigSaving, setLlmConfigSaving] = useState(false);

  // Load instance detail and sync form state
  useEffect(() => {
    if (instanceId) {
      getInstance(instanceId)
        .then((inst) => {
          setCurrentInstance(inst);
          if (lastSyncedId.current !== inst.id) {
            lastSyncedId.current = inst.id;
            setName(inst.name);
            setDescription(
              ((inst as unknown as Record<string, unknown>).description as string) ?? ''
            );
            setIsDirty(false);
          }
        })
        .catch(() => {
          /* handled by store */
        });
    }
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
    providerAPI
      .list({ include_inactive: false })
      .then(setProviders)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!instanceId) return;
    setLlmConfigLoading(true);
    instanceService
      .getLlmConfig(instanceId)
      .then((cfg) => {
        setLlmProviderId(cfg.provider_id ?? undefined);
        setLlmModelName(cfg.model_name ?? undefined);
        setHasApiKeyOverride(cfg.has_api_key_override);
        setLlmApiKeyOverride('');
      })
      .catch(() => {
        message?.error(t('tenant.instances.settings.llmConfigLoadError'));
      })
      .finally(() => {
        setLlmConfigLoading(false);
      });
  }, [instanceId, message, t]);

  useEffect(() => {
    if (!llmProviderId) {
      setAvailableModels([]);
      return;
    }
    const selectedProvider = providers.find((p) => p.id === llmProviderId);
    if (!selectedProvider) return;
    providerAPI
      .listModels(selectedProvider.provider_type)
      .then((res) => {
        setAvailableModels(res.models.chat);
      })
      .catch(() => {
        setAvailableModels([]);
      });
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
    } catch {
      // handled by store
    }
  }, [instanceId, isDirty, name, description, updateInstance, message, t]);

  const handleDelete = useCallback(async () => {
    if (!instanceId) return;
    try {
      await deleteInstance(instanceId);
      message?.success(t('tenant.instances.settings.deleteSuccess'));
      navigate('../..', { relative: 'path' });
    } catch {
      // handled by store
    }
  }, [instanceId, deleteInstance, message, t, navigate]);

  const handleLlmProviderChange = useCallback((value: string) => {
    setLlmProviderId(value);
    setLlmModelName(undefined);
  }, []);

  const handleLlmConfigSave = useCallback(async () => {
    if (!instanceId) return;
    setLlmConfigSaving(true);
    try {
      const payload: InstanceLlmConfigUpdate = {
        provider_id: llmProviderId ?? null,
        model_name: llmModelName ?? null,
        api_key_override: llmApiKeyOverride || null,
      };
      const result = await instanceService.updateLlmConfig(instanceId, payload);
      setHasApiKeyOverride(result.has_api_key_override);
      setLlmApiKeyOverride('');
      message?.success(t('tenant.instances.settings.llmConfigUpdateSuccess'));
    } catch {
      message?.error(t('common.error'));
    } finally {
      setLlmConfigSaving(false);
    }
  }, [instanceId, llmProviderId, llmModelName, llmApiKeyOverride, message, t]);

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
        <p className="text-slate-500">{t('common.notFound')}</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto w-full flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.instances.settings.title')}
        </h1>
        <p className="text-sm text-slate-500 mt-1">{t('tenant.instances.settings.description')}</p>
      </div>

      {/* General Settings */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6">
          {t('tenant.instances.settings.generalSettings')}
        </h2>

        <div className="space-y-5">
          <div>
            <label
              htmlFor="instance-name"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
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
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
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
            <button
              type="button"
              onClick={handleSave}
              disabled={!isDirty || isSubmitting}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting && (
                <Loader2 size={16} className="animate-spin" />
              )}
              {t('common.save')}
            </button>
          </div>
        </div>
      </div>

      {/* LLM Configuration */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
          {t('tenant.instances.settings.llmConfig')}
        </h2>
        <p className="text-sm text-slate-500 mb-6">
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
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                {t('tenant.instances.settings.llmProvider')}
              </label>
              <Select
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
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                {t('tenant.instances.settings.llmModel')}
              </label>
              <Select
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
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                {t('tenant.instances.settings.llmApiKeyOverride')}
              </label>
              <Input.Password
                id="llm-api-key"
                value={llmApiKeyOverride}
                onChange={(e) => {
                  setLlmApiKeyOverride(e.target.value);
                }}
                placeholder={t('tenant.instances.settings.llmApiKeyOverridePlaceholder')}
              />
              <p className="text-xs text-slate-400 mt-1">
                {t('tenant.instances.settings.llmApiKeyOverrideHint')}
              </p>
              {hasApiKeyOverride && (
                <p className="text-xs text-green-600 dark:text-green-400 mt-1">
                  {t('tenant.instances.settings.llmApiKeySet')}
                </p>
              )}
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleLlmConfigSave}
                disabled={llmConfigSaving}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {llmConfigSaving && (
                  <Loader2 size={16} className="animate-spin" />
                )}
                {t('common.save')}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Danger Zone */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-red-200 dark:border-red-900/50 p-6">
        <h2 className="text-lg font-semibold text-red-600 dark:text-red-400 mb-2">
          {t('tenant.instances.settings.dangerZone')}
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
          {t('tenant.instances.settings.dangerZoneDescription')}
        </p>

        <div className="flex items-center justify-between p-4 border border-red-200 dark:border-red-900/50 rounded-lg">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-white">
              {t('tenant.instances.settings.deleteInstance')}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
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
            <button
              type="button"
              disabled={isSubmitting}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              <Trash2 size={16} />
              {t('common.delete')}
            </button>
          </LazyPopconfirm>
        </div>
      </div>
    </div>
  );
};
