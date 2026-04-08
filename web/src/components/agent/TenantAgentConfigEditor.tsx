import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Alert,
  Form,
  Input,
  InputNumber,
  Modal,
  Spin,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';

import { agentConfigService, TenantAgentConfigError } from '@/services/agentConfigService';

import {
  buildRuntimeHooks,
  formatToolList,
  getHookSchemaProperties,
  hookKey,
  isHookCustomized,
  parseToolList,
  serializeRuntimeHooks,
} from './tenantAgentConfigHelpers';

import type {
  HookCatalogEntry,
  RuntimeHookConfig,
  TenantAgentConfig,
  UpdateTenantAgentConfigRequest,
} from '@/types/agent';

const { TextArea } = Input;
const { Text } = Typography;

interface TenantAgentConfigEditorProps {
  tenantId: string;
  open: boolean;
  onClose: () => void;
  onSave?: (() => void) | undefined;
  initialConfig?: TenantAgentConfig | undefined;
}

interface FormValues {
  llm_model?: string | undefined;
  llm_temperature?: number | undefined;
  pattern_learning_enabled?: boolean | undefined;
  multi_level_thinking_enabled?: boolean | undefined;
  max_work_plan_steps?: number | undefined;
  tool_timeout_seconds?: number | undefined;
  enabled_tools: string;
  disabled_tools: string;
}

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-700 dark:text-slate-200">
        {title}
      </h3>
      <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
    </div>
  );
}

function SettingCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white px-4 py-4 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-900 dark:text-white">{title}</p>
          <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
        </div>
        <div className="flex-shrink-0">{children}</div>
      </div>
    </div>
  );
}

export function TenantAgentConfigEditor({
  tenantId,
  open,
  onClose,
  onSave,
  initialConfig,
}: TenantAgentConfigEditorProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<FormValues>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);
  const [multiAgentEnabled, setMultiAgentEnabled] = useState(false);
  const [hookCatalog, setHookCatalog] = useState<HookCatalogEntry[]>([]);
  const [hookCatalogError, setHookCatalogError] = useState<string | null>(null);
  const [runtimeHooks, setRuntimeHooks] = useState<RuntimeHookConfig[]>([]);
  const [unmanagedRuntimeHooks, setUnmanagedRuntimeHooks] = useState<RuntimeHookConfig[]>([]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const loadConfig = async () => {
      setLoading(true);
      setError(null);

      try {
        const config = initialConfig ? initialConfig : await agentConfigService.getConfig(tenantId);
        let catalog: HookCatalogEntry[] = [];
        let nextHookCatalogError: string | null = null;

        try {
          catalog = await agentConfigService.getHookCatalog(tenantId);
        } catch {
          nextHookCatalogError = t(
            'tenant.agentConfigEditor.runtimeHooks.catalogUnavailableDescription'
          );
        }

        const catalogKeys = new Set(catalog.map((entry) => hookKey(entry)));

        setMultiAgentEnabled(config.multi_agent_enabled);
        setHookCatalog(catalog);
        setHookCatalogError(nextHookCatalogError);
        setRuntimeHooks(buildRuntimeHooks(config, catalog));
        setUnmanagedRuntimeHooks(
          config.runtime_hooks.filter((hook) => !catalogKeys.has(hookKey(hook)))
        );
        form.setFieldsValue({
          llm_model: config.llm_model,
          llm_temperature: config.llm_temperature,
          pattern_learning_enabled: config.pattern_learning_enabled,
          multi_level_thinking_enabled: config.multi_level_thinking_enabled,
          max_work_plan_steps: config.max_work_plan_steps,
          tool_timeout_seconds: config.tool_timeout_seconds,
          enabled_tools: formatToolList(config.enabled_tools),
          disabled_tools: formatToolList(config.disabled_tools),
        });
        setHasChanges(false);
      } catch (err) {
        const messageText =
          err instanceof TenantAgentConfigError
            ? err.message
            : t('tenant.agentConfigEditor.loadError');
        setError(messageText);
        if (err instanceof TenantAgentConfigError && err.statusCode === 403) {
          message.error(t('tenant.agentConfigEditor.accessDenied'));
          onClose();
        }
      } finally {
        setLoading(false);
      }
    };

    void loadConfig();
  }, [open, tenantId, initialConfig, form, onClose, t]);

  const onValuesChange = useCallback(() => {
    setHasChanges(true);
  }, []);

  const updateRuntimeHook = useCallback(
    (key: string, updater: (current: RuntimeHookConfig) => RuntimeHookConfig) => {
      setRuntimeHooks((previous) =>
        previous.map((hook) => (hookKey(hook) === key ? updater(hook) : hook))
      );
      setHasChanges(true);
    },
    []
  );

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      setError(null);

      const request: UpdateTenantAgentConfigRequest = {
        llm_model: values.llm_model?.trim(),
        llm_temperature: values.llm_temperature,
        pattern_learning_enabled: values.pattern_learning_enabled,
        multi_level_thinking_enabled: values.multi_level_thinking_enabled,
        max_work_plan_steps: values.max_work_plan_steps,
        tool_timeout_seconds: values.tool_timeout_seconds,
        enabled_tools: parseToolList(values.enabled_tools),
        disabled_tools: parseToolList(values.disabled_tools),
        runtime_hooks: [
          ...unmanagedRuntimeHooks,
          ...serializeRuntimeHooks(runtimeHooks, hookCatalog),
        ],
      };

      await agentConfigService.updateConfig(tenantId, request);

      message.success(t('tenant.agentConfigEditor.saveSuccess'));
      setHasChanges(false);
      onSave?.();
      onClose();
    } catch (err) {
      if (err instanceof TenantAgentConfigError) {
        setError(err.message);
        if (err.statusCode === 403) {
          message.error(t('tenant.agentConfigEditor.accessDenied'));
          onClose();
        } else if (err.statusCode === 422) {
          message.error(t('tenant.agentConfigEditor.validationError'));
        }
      } else {
        setError(t('tenant.agentConfigEditor.saveError'));
        message.error(t('tenant.agentConfigEditor.saveErrorToast'));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!hasChanges) {
      onClose();
      return;
    }

    Modal.confirm({
      title: t('tenant.agentConfigEditor.discardChangesTitle'),
      content: t('tenant.agentConfigEditor.discardChangesDescription'),
      okText: t('tenant.agentConfigEditor.actions.discard'),
      okButtonProps: { danger: true },
      cancelText: t('tenant.agentConfigEditor.actions.keepEditing'),
      onOk: onClose,
    });
  };

  return (
    <Modal
      title={
        <div className="pr-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
            {t('tenant.agentConfigEditor.eyebrow')}
          </p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-slate-950">
            {t('tenant.agentConfigEditor.title')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {t('tenant.agentConfigEditor.description')}
          </p>
        </div>
      }
      open={open}
      onCancel={handleCancel}
      onOk={() => {
        void handleSave();
      }}
      okText={t('tenant.agentConfigEditor.actions.save')}
      cancelText={t('tenant.agentConfigEditor.actions.close')}
      okButtonProps={{ loading: saving }}
      cancelButtonProps={{ disabled: saving }}
      width={960}
      destroyOnHidden
    >
      {error ? (
        <Alert
          type="error"
          title={t('tenant.agentConfigEditor.alertTitle')}
          description={error}
          showIcon
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onValuesChange={onValuesChange} autoComplete="off">
          <div className="space-y-5">
            <section className="rounded-3xl border border-slate-200/80 bg-slate-50/80 p-5 dark:border-slate-800 dark:bg-slate-900/70">
              <SectionHeader
                title={t('tenant.agentConfigEditor.sections.modelReasoning.title')}
                description={t('tenant.agentConfigEditor.sections.modelReasoning.description')}
              />
              <div className="grid gap-4 md:grid-cols-2">
                <Form.Item
                  label={t('tenant.agentConfigEditor.sections.modelReasoning.modelIdentifier')}
                  name="llm_model"
                  extra={t('tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierHint')}
                  rules={[
                    {
                      validator: (_rule, value: string | undefined) => {
                        if (value?.trim()) {
                          return Promise.resolve();
                        }

                        return Promise.reject(
                          new Error(
                            t(
                              'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierRequired'
                            )
                          )
                        );
                      },
                    },
                  ]}
                >
                  <Input
                    placeholder={t(
                      'tenant.agentConfigEditor.sections.modelReasoning.modelIdentifierPlaceholder'
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t('tenant.agentConfigEditor.sections.modelReasoning.temperature')}
                  name="llm_temperature"
                  extra={t('tenant.agentConfigEditor.sections.modelReasoning.temperatureHint')}
                  rules={[
                    {
                      required: true,
                      message: t(
                        'tenant.agentConfigEditor.sections.modelReasoning.temperatureRequired'
                      ),
                    },
                    {
                      type: 'number',
                      min: 0,
                      max: 2,
                      message: t(
                        'tenant.agentConfigEditor.sections.modelReasoning.temperatureRange'
                      ),
                    },
                  ]}
                >
                  <InputNumber min={0} max={2} step={0.1} precision={1} style={{ width: '100%' }} />
                </Form.Item>

                <SettingCard
                  title={t('tenant.agentConfigEditor.sections.modelReasoning.patternLearning')}
                  description={t(
                    'tenant.agentConfigEditor.sections.modelReasoning.patternLearningDescription'
                  )}
                >
                  <Form.Item name="pattern_learning_enabled" valuePropName="checked" noStyle>
                    <Switch
                      aria-label={t(
                        'tenant.agentConfigEditor.sections.modelReasoning.patternLearningToggle'
                      )}
                    />
                  </Form.Item>
                </SettingCard>

                <SettingCard
                  title={t('tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinking')}
                  description={t(
                    'tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinkingDescription'
                  )}
                >
                  <Form.Item name="multi_level_thinking_enabled" valuePropName="checked" noStyle>
                    <Switch
                      aria-label={t(
                        'tenant.agentConfigEditor.sections.modelReasoning.multiLevelThinkingToggle'
                      )}
                    />
                  </Form.Item>
                </SettingCard>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200/80 bg-slate-50/80 p-5 dark:border-slate-800 dark:bg-slate-900/70">
              <SectionHeader
                title={t('tenant.agentConfigEditor.sections.executionGuardrails.title')}
                description={t('tenant.agentConfigEditor.sections.executionGuardrails.description')}
              />
              <div className="grid gap-4 md:grid-cols-2">
                <Form.Item
                  label={t(
                    'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanSteps'
                  )}
                  name="max_work_plan_steps"
                  extra={t(
                    'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanStepsHint'
                  )}
                  rules={[
                    {
                      required: true,
                      message: t(
                        'tenant.agentConfigEditor.sections.executionGuardrails.maxWorkPlanStepsRequired'
                      ),
                    },
                    {
                      type: 'number',
                      min: 1,
                      message: t('tenant.agentConfigEditor.sections.executionGuardrails.minValue'),
                    },
                  ]}
                >
                  <InputNumber min={1} max={50} style={{ width: '100%' }} />
                </Form.Item>

                <Form.Item
                  label={t('tenant.agentConfigEditor.sections.executionGuardrails.toolTimeout')}
                  name="tool_timeout_seconds"
                  extra={t('tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutHint')}
                  rules={[
                    {
                      required: true,
                      message: t(
                        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutRequired'
                      ),
                    },
                    {
                      type: 'number',
                      min: 1,
                      message: t(
                        'tenant.agentConfigEditor.sections.executionGuardrails.toolTimeoutMin'
                      ),
                    },
                  ]}
                >
                  <InputNumber min={1} max={300} style={{ width: '100%' }} />
                </Form.Item>
              </div>

              <div className="rounded-2xl border border-slate-200/80 bg-white px-4 py-4 dark:border-slate-800 dark:bg-slate-950">
                <p className="text-sm font-medium text-slate-900 dark:text-white">
                  {t('tenant.agentConfigEditor.sections.executionGuardrails.multiAgentRouting')}
                </p>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t(
                    'tenant.agentConfigEditor.sections.executionGuardrails.multiAgentRoutingDescription'
                  )}{' '}
                  <code>MULTI_AGENT_ENABLED</code>.
                </p>
                <div className="mt-3">
                  <Tag color={multiAgentEnabled ? 'green' : 'default'}>
                    {multiAgentEnabled ? t('common.status.enabled') : t('common.status.disabled')}
                  </Tag>
                </div>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200/80 bg-slate-50/80 p-5 dark:border-slate-800 dark:bg-slate-900/70">
              <SectionHeader
                title={t('tenant.agentConfigEditor.sections.toolPolicy.title')}
                description={t('tenant.agentConfigEditor.sections.toolPolicy.description')}
              />
              <div className="grid gap-4 md:grid-cols-2">
                <Form.Item
                  label={t('tenant.agentConfigEditor.sections.toolPolicy.enabledTools')}
                  name="enabled_tools"
                  extra={t('tenant.agentConfigEditor.sections.toolPolicy.enabledToolsHint')}
                >
                  <TextArea
                    rows={4}
                    placeholder={t('tenant.agentConfigEditor.sections.toolPolicy.toolPlaceholder')}
                  />
                </Form.Item>

                <Form.Item
                  label={t('tenant.agentConfigEditor.sections.toolPolicy.disabledTools')}
                  name="disabled_tools"
                  extra={t('tenant.agentConfigEditor.sections.toolPolicy.disabledToolsHint')}
                >
                  <TextArea
                    rows={4}
                    placeholder={t('tenant.agentConfigEditor.sections.toolPolicy.toolPlaceholder')}
                  />
                </Form.Item>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200/80 bg-slate-50/80 p-5 dark:border-slate-800 dark:bg-slate-900/70">
              <SectionHeader
                title={t('tenant.agentConfigEditor.runtimeHooks.title')}
                description={t('tenant.agentConfigEditor.runtimeHooks.description')}
              />

              {hookCatalogError ? (
                <Alert
                  type="warning"
                  title={t('tenant.agentConfigEditor.runtimeHooks.catalogUnavailableTitle')}
                  description={hookCatalogError}
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              ) : null}

              <div className="space-y-4">
                {hookCatalog.map((entry) => {
                  const key = hookKey(entry);
                  const currentHook = runtimeHooks.find((hook) => hookKey(hook) === key);
                  if (!currentHook) {
                    return null;
                  }

                  const schemaProperties = getHookSchemaProperties(entry);
                  const customized = isHookCustomized(currentHook, entry);
                  const headingId = `${key}-heading`;

                  return (
                    <div
                      key={key}
                      className="rounded-2xl border border-slate-200/80 bg-white p-5 dark:border-slate-800 dark:bg-slate-950"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Text strong id={headingId}>
                              {entry.display_name}
                            </Text>
                            <Tag color={customized ? 'blue' : 'default'}>
                              {customized
                                ? t('tenant.agentConfigEditor.runtimeHooks.override')
                                : t('tenant.agentConfigEditor.runtimeHooks.catalogDefault')}
                            </Tag>
                            <Tag color={currentHook.enabled ? 'green' : 'default'}>
                              {currentHook.enabled
                                ? t('common.status.enabled')
                                : t('common.status.disabled')}
                            </Tag>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                            {entry.description ||
                              t('tenant.agentConfigEditor.runtimeHooks.defaultHookDescription')}
                          </p>
                          <p className="mt-2 text-xs uppercase tracking-[0.14em] text-slate-400">
                            {entry.plugin_name} / {entry.hook_name}
                          </p>
                        </div>

                        <div className="flex items-center gap-3">
                          <Switch
                            aria-labelledby={headingId}
                            checked={currentHook.enabled}
                            onChange={(checked) => {
                              updateRuntimeHook(key, (hook) => ({ ...hook, enabled: checked }));
                            }}
                          />
                          {customized ? (
                            <button
                              type="button"
                              aria-label={t(
                                'tenant.agentConfigEditor.runtimeHooks.useDefaultsAria',
                                {
                                  name: entry.display_name,
                                }
                              )}
                              onClick={() => {
                                updateRuntimeHook(key, () => ({
                                  plugin_name: entry.plugin_name,
                                  hook_name: entry.hook_name,
                                  enabled: entry.default_enabled,
                                  priority: entry.default_priority,
                                  settings: { ...entry.default_settings },
                                }));
                              }}
                              className="inline-flex min-h-10 items-center rounded-full border border-slate-200 px-4 text-sm font-medium text-slate-600 transition-colors duration-150 hover:border-slate-300 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:border-slate-800 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white"
                            >
                              {t('tenant.agentConfigEditor.runtimeHooks.useDefaults')}
                            </button>
                          ) : null}
                        </div>
                      </div>

                      <div className="mt-5 grid gap-4 md:grid-cols-2">
                        <div>
                          <Text strong>{t('tenant.agentConfigEditor.runtimeHooks.priority')}</Text>
                          <div className="mt-2">
                            <InputNumber
                              aria-label={t('tenant.agentConfigEditor.runtimeHooks.priorityAria', {
                                name: entry.display_name,
                              })}
                              style={{ width: '100%' }}
                              value={currentHook.priority ?? null}
                              placeholder={String(entry.default_priority)}
                              onChange={(value) => {
                                updateRuntimeHook(key, (hook) => ({
                                  ...hook,
                                  priority: typeof value === 'number' ? value : null,
                                }));
                              }}
                            />
                          </div>
                          <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                            {t('tenant.agentConfigEditor.runtimeHooks.catalogDefaultPriority', {
                              value: entry.default_priority,
                            })}
                          </div>
                        </div>

                        {Object.entries(schemaProperties).map(([settingKey, property]) => {
                          const title =
                            typeof property.title === 'string' ? property.title : settingKey;
                          const description =
                            typeof property.description === 'string'
                              ? property.description
                              : undefined;
                          const defaultValue = entry.default_settings[settingKey];
                          const currentValue = currentHook.settings[settingKey];
                          const valueType =
                            typeof property.type === 'string' ? property.type : 'string';
                          const inputLabel = `${entry.display_name} ${title}`;

                          if (valueType === 'boolean') {
                            return (
                              <div key={settingKey}>
                                <div className="flex items-center justify-between gap-3">
                                  <div>
                                    <Text strong>{title}</Text>
                                    {description ? (
                                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                        {description}
                                      </div>
                                    ) : null}
                                  </div>
                                  <Switch
                                    aria-label={inputLabel}
                                    checked={Boolean(currentValue)}
                                    onChange={(checked) => {
                                      updateRuntimeHook(key, (hook) => ({
                                        ...hook,
                                        settings: {
                                          ...hook.settings,
                                          [settingKey]: checked,
                                        },
                                      }));
                                    }}
                                  />
                                </div>
                              </div>
                            );
                          }

                          if (valueType === 'number' || valueType === 'integer') {
                            return (
                              <div key={settingKey}>
                                <Text strong>{title}</Text>
                                <div className="mt-2">
                                  <InputNumber
                                    aria-label={inputLabel}
                                    style={{ width: '100%' }}
                                    value={typeof currentValue === 'number' ? currentValue : null}
                                    onChange={(value) => {
                                      updateRuntimeHook(key, (hook) => ({
                                        ...hook,
                                        settings: {
                                          ...hook.settings,
                                          [settingKey]:
                                            typeof value === 'number' ? value : (defaultValue ?? 0),
                                        },
                                      }));
                                    }}
                                  />
                                </div>
                                {description ? (
                                  <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                    {description}
                                  </div>
                                ) : null}
                              </div>
                            );
                          }

                          return (
                            <div key={settingKey} className="md:col-span-2">
                              <Text strong>{title}</Text>
                              <div className="mt-2">
                                <TextArea
                                  aria-label={inputLabel}
                                  rows={3}
                                  value={typeof currentValue === 'string' ? currentValue : ''}
                                  onChange={(event) => {
                                    updateRuntimeHook(key, (hook) => ({
                                      ...hook,
                                      settings: {
                                        ...hook.settings,
                                        [settingKey]: event.target.value,
                                      },
                                    }));
                                  }}
                                />
                              </div>
                              {description ? (
                                <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                  {description}
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>

                      {Object.keys(schemaProperties).length === 0 ? (
                        <p className="mt-4 text-sm leading-6 text-slate-500 dark:text-slate-400">
                          {t('tenant.agentConfigEditor.runtimeHooks.noExtraSettings')}
                        </p>
                      ) : null}
                    </div>
                  );
                })}
              </div>

              {!hookCatalogError && hookCatalog.length === 0 ? (
                <p className="mt-4 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t('tenant.agentConfigEditor.runtimeHooks.empty')}
                </p>
              ) : null}
            </section>
          </div>
        </Form>
      </Spin>
    </Modal>
  );
}

export default TenantAgentConfigEditor;
