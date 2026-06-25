/**
 * AgentDefinitionModal - Modal for creating and editing agent definitions.
 *
 * Follows SubAgentModal pattern: Form.useForm(), tabbed layout,
 * resource fetching on open, confirmLoading bound to store submitting.
 */

import React, { useCallback, useEffect, useState, useRef, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Tabs, InputNumber, Switch, Tag, message, Slider } from 'antd';

import { acpService } from '../../services/acpService';
import { agentService } from '../../services/agentService';
import { mcpAPI } from '../../services/mcpService';
import { skillAPI } from '../../services/skillService';
import {
  useCreateDefinition,
  useUpdateDefinition,
  useDefinitionSubmitting,
} from '../../stores/agentDefinitions';
import { StateDisplay } from '../shared/ui/StateDisplay';

import {
  buildDelegateConfig,
  buildSessionPolicy,
  buildSpawnPolicy,
  buildToolPolicy,
  normalizeStringList,
} from './agentDefinitionPolicyForm';

import type { SkillResponse, MCPServerResponse, ToolInfo } from '../../types/agent';
import type { TenantExternalACPAgent } from '../../types/acp';
import type {
  AgentDefinition,
  AgentDefinitionDelegateCapabilityTier,
  AgentDefinitionDmScope,
  AgentExecutionBackendType,
  CreateDefinitionRequest,
  UpdateDefinitionRequest,
  WorkspaceConfig,
} from '../../types/multiAgent';
import type { DefaultOptionType } from 'antd/es/select';

const { TextArea } = Input;
const { Option } = Select;
const TENANT_SCOPE_VALUE = '__tenant__';

export interface AgentDefinitionProjectOption {
  id: string;
  name: string;
}

export interface AgentDefinitionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  definition: AgentDefinition | null;
  projectOptions?: AgentDefinitionProjectOption[] | undefined;
  initialProjectId?: string | null | undefined;
  tenantId?: string | null | undefined;
}

interface WorkspaceConfigFormValues {
  type?: 'shared' | 'isolated' | 'inherited';
  base_dir?: string;
  base_path?: string;
  sandbox_scope?: 'session' | 'agent' | 'shared';
  max_size_mb?: number;
  persona_files?: string[];
  shared_files?: string[];
  auto_cleanup?: boolean;
  retention_days?: number;
}

interface AgentDefinitionFormValues {
  name: string;
  display_name: string;
  system_prompt: string;
  scope_id?: string | undefined;
  model: string;
  fallback_models?: string[] | undefined;
  temperature?: number | undefined;
  max_tokens?: number | undefined;
  max_iterations?: number | undefined;
  allowed_tools?: string[] | undefined;
  allowed_skills?: string[] | undefined;
  allowed_mcp_servers?: string[] | undefined;
  can_spawn?: boolean | undefined;
  max_spawn_depth?: number | undefined;
  agent_to_agent_enabled?: boolean | undefined;
  agent_to_agent_allowlist?: string[] | null | undefined;
  discoverable?: boolean | undefined;
  max_retries?: number | undefined;
  execution_backend_type?: AgentExecutionBackendType | undefined;
  execution_backend_acp_agent_key?: string | undefined;
  workspace_config?: WorkspaceConfigFormValues | undefined;
  spawn_policy_max_active_runs?: number | undefined;
  spawn_policy_max_children_per_requester?: number | undefined;
  spawn_policy_allowed_subagents?: string[] | undefined;
  tool_policy_allow?: string[] | undefined;
  tool_policy_deny?: string[] | undefined;
  tool_policy_precedence?: 'allow_first' | 'deny_first' | undefined;
  session_policy_dm_scope?: AgentDefinitionDmScope | undefined;
  session_policy_max_messages?: number | undefined;
  session_policy_idle_reset_minutes?: number | undefined;
  session_policy_daily_reset_hour?: number | undefined;
  session_policy_ttl_hours?: number | undefined;
  delegate_config_capability_tier?: AgentDefinitionDelegateCapabilityTier | undefined;
  delegate_config_max_delegation_depth?: number | undefined;
  delegate_config_allowed_tools?: string[] | undefined;
  delegate_config_budget_limit_tokens?: number | undefined;
}

function getMetadataNumber(metadata: Record<string, unknown>, key: string): number | undefined {
  const value = metadata[key];
  return typeof value === 'number' ? value : undefined;
}

function getMetadataStringArray(
  metadata: Record<string, unknown>,
  key: string
): string[] | undefined {
  const value = metadata[key];
  return Array.isArray(value) && value.every((item): item is string => typeof item === 'string')
    ? value
    : undefined;
}

function stripLegacyPolicyMetadata(
  metadata: Record<string, unknown> | undefined
): Record<string, unknown> | undefined {
  if (!metadata) {
    return undefined;
  }

  const next = { ...metadata };
  delete next.spawn_policy_max_active_runs;
  delete next.spawn_policy_max_children_per_requester;
  delete next.spawn_policy_allowed_subagents;
  delete next.tool_policy_allow;
  delete next.tool_policy_deny;
  return next;
}

function toWorkspaceConfigFormValues(
  workspaceConfig: WorkspaceConfig | null
): WorkspaceConfigFormValues {
  if (!workspaceConfig) {
    return { type: 'shared' };
  }

  const values: WorkspaceConfigFormValues = {};
  if (workspaceConfig.type !== undefined) values.type = workspaceConfig.type;
  if (workspaceConfig.base_dir !== undefined) values.base_dir = workspaceConfig.base_dir;
  if (workspaceConfig.base_path !== undefined) values.base_path = workspaceConfig.base_path;
  if (workspaceConfig.sandbox_scope !== undefined) {
    values.sandbox_scope = workspaceConfig.sandbox_scope;
  }
  if (workspaceConfig.max_size_mb !== undefined) values.max_size_mb = workspaceConfig.max_size_mb;
  if (workspaceConfig.persona_files !== undefined) {
    values.persona_files = workspaceConfig.persona_files;
  }
  if (workspaceConfig.shared_files !== undefined)
    values.shared_files = workspaceConfig.shared_files;
  if (workspaceConfig.auto_cleanup !== undefined)
    values.auto_cleanup = workspaceConfig.auto_cleanup;
  if (workspaceConfig.retention_days !== undefined) {
    values.retention_days = workspaceConfig.retention_days;
  }
  return values;
}

function filterSelectOption(input: string, option?: DefaultOptionType): boolean {
  const label = typeof option?.label === 'string' ? option.label : '';
  return label.toLowerCase().includes(input.toLowerCase());
}

const LLM_MODELS = [
  { value: 'inherit', label: 'Inherit from Tenant Config' },
  { value: 'qwen-max', label: 'Qwen Max' },
  { value: 'qwen-plus', label: 'Qwen Plus' },
  { value: 'gpt-4', label: 'GPT-4' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet' },
  { value: 'deepseek-chat', label: 'Deepseek Chat' },
  { value: 'gemini-pro', label: 'Gemini Pro' },
];

export const AgentDefinitionModal: React.FC<AgentDefinitionModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  definition,
  projectOptions = [],
  initialProjectId = null,
  tenantId = null,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm<AgentDefinitionFormValues>();
  const [activeTab, setActiveTab] = useState('basic');

  // Trigger keywords/examples local state
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState('');

  // Available resources
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillResponse[]>([]);
  const [availableMcpServers, setAvailableMcpServers] = useState<MCPServerResponse[]>([]);
  const [availableAcpAgents, setAvailableAcpAgents] = useState<TenantExternalACPAgent[]>([]);
  const [loadingResources, setLoadingResources] = useState(false);

  const isSubmitting = useDefinitionSubmitting();
  const createDefinition = useCreateDefinition();
  const updateDefinition = useUpdateDefinition();
  const executionBackendType = Form.useWatch('execution_backend_type', form) ?? 'memstack';
  const isExternalAcpBackend = executionBackendType === 'acp_external';

  const isEditMode = !!definition;
  const scopeOptions = useMemo(() => {
    const seen = new Set<string>();
    const options = [
      {
        label: t('tenant.agentDefinitions.scope.tenant', { defaultValue: 'Tenant scope' }),
        value: TENANT_SCOPE_VALUE,
      },
      ...projectOptions
        .filter((project) => {
          if (seen.has(project.id)) {
            return false;
          }
          seen.add(project.id);
          return true;
        })
        .map((project) => ({
          label: project.name,
          value: project.id,
        })),
    ];

    if (
      definition?.project_id &&
      !options.some((option) => option.value === definition.project_id)
    ) {
      options.push({
        label: definition.project_id,
        value: definition.project_id,
      });
    }

    return options;
  }, [definition?.project_id, projectOptions, t]);
  const acpAgentOptions = useMemo(
    () =>
      availableAcpAgents
        .filter((agent) => agent.enabled)
        .map((agent) => ({
          label: `${agent.name} (${agent.agentKey})`,
          value: agent.agentKey,
          disabled: !agent.available,
        })),
    [availableAcpAgents]
  );

  // Track previous state to avoid unnecessary resets
  const prevDefinitionRef = useRef<AgentDefinition | null>(null);
  const prevIsOpenRef = useRef(false);

  // Fetch available resources when modal opens
  useEffect(() => {
    if (isOpen) {
      const fetchResources = async () => {
        setLoadingResources(true);
        try {
          const [toolsRes, skillsRes, mcpRes, acpAgents] = await Promise.all([
            agentService.listTools(),
            skillAPI.list(tenantId ? { limit: 100, tenant_id: tenantId } : { limit: 100 }),
            mcpAPI.list({ limit: 100 }),
            tenantId ? acpService.listAgents(tenantId) : Promise.resolve([]),
          ]);
          setAvailableTools(toolsRes.tools);
          setAvailableSkills(skillsRes.skills);
          setAvailableMcpServers(mcpRes);
          setAvailableAcpAgents(acpAgents);
        } catch (error) {
          console.error('Failed to fetch resources:', error);
          message.error(
            t(
              'tenant.agentDefinitions.modal.resourceFetchError',
              'Failed to load available resources'
            )
          );
        } finally {
          setLoadingResources(false);
        }
      };
      void fetchResources();
    }
  }, [isOpen, tenantId, t]);

  // Reset form when modal opens/closes or definition changes
  useEffect(() => {
    const definitionChanged = prevDefinitionRef.current?.id !== definition?.id;
    const openStateChanged = prevIsOpenRef.current !== isOpen;

    if (isOpen && (definitionChanged || openStateChanged)) {
      if (definition) {
        const metadata = definition.metadata;
        const fieldValues: Partial<AgentDefinitionFormValues> = {
          name: definition.name,
          display_name: definition.display_name ?? '',
          system_prompt: definition.system_prompt ?? '',
          scope_id: definition.project_id ?? TENANT_SCOPE_VALUE,
          model: definition.model ?? 'inherit',
          fallback_models: [...definition.fallback_models],
          temperature: definition.temperature ?? 0.7,
          max_tokens: definition.max_tokens ?? 4096,
          max_iterations: definition.max_iterations,
          allowed_tools: definition.allowed_tools ?? ['*'],
          allowed_skills: definition.allowed_skills ?? [],
          allowed_mcp_servers: definition.allowed_mcp_servers ?? [],
          can_spawn: definition.can_spawn,
          max_spawn_depth: definition.spawn_policy?.max_depth ?? definition.max_spawn_depth,
          agent_to_agent_enabled: definition.agent_to_agent_enabled,
          discoverable: definition.discoverable,
          max_retries: definition.max_retries,
          execution_backend_type: definition.execution_backend?.type ?? 'memstack',
          execution_backend_acp_agent_key: definition.execution_backend?.acp_agent_key,
          workspace_config: toWorkspaceConfigFormValues(definition.workspace_config),
        };

        if (definition.agent_to_agent_allowlist !== null) {
          fieldValues.agent_to_agent_allowlist = definition.agent_to_agent_allowlist;
        }

        const spawnMaxActiveRuns =
          definition.spawn_policy?.max_active_runs ??
          getMetadataNumber(metadata, 'spawn_policy_max_active_runs');
        if (spawnMaxActiveRuns !== undefined) {
          fieldValues.spawn_policy_max_active_runs = spawnMaxActiveRuns;
        }

        const spawnMaxChildrenPerRequester =
          definition.spawn_policy?.max_children_per_requester ??
          getMetadataNumber(metadata, 'spawn_policy_max_children_per_requester');
        if (spawnMaxChildrenPerRequester !== undefined) {
          fieldValues.spawn_policy_max_children_per_requester = spawnMaxChildrenPerRequester;
        }

        const allowedSubagents =
          definition.spawn_policy?.allowed_subagents ??
          getMetadataStringArray(metadata, 'spawn_policy_allowed_subagents');
        if (allowedSubagents !== undefined) {
          fieldValues.spawn_policy_allowed_subagents = allowedSubagents;
        }

        const toolPolicyAllow =
          definition.tool_policy?.allow ?? getMetadataStringArray(metadata, 'tool_policy_allow');
        if (toolPolicyAllow !== undefined) {
          fieldValues.tool_policy_allow = toolPolicyAllow;
        }

        const toolPolicyDeny =
          definition.tool_policy?.deny ?? getMetadataStringArray(metadata, 'tool_policy_deny');
        if (toolPolicyDeny !== undefined) {
          fieldValues.tool_policy_deny = toolPolicyDeny;
        }
        fieldValues.tool_policy_precedence = definition.tool_policy?.precedence ?? 'deny_first';

        if (definition.session_policy) {
          fieldValues.session_policy_dm_scope = definition.session_policy.dm_scope ?? 'per_user';
          if (
            definition.session_policy.max_messages !== null &&
            definition.session_policy.max_messages !== undefined
          ) {
            fieldValues.session_policy_max_messages = definition.session_policy.max_messages;
          }
          if (
            definition.session_policy.idle_reset_minutes !== null &&
            definition.session_policy.idle_reset_minutes !== undefined
          ) {
            fieldValues.session_policy_idle_reset_minutes =
              definition.session_policy.idle_reset_minutes;
          }
          if (
            definition.session_policy.daily_reset_hour !== null &&
            definition.session_policy.daily_reset_hour !== undefined
          ) {
            fieldValues.session_policy_daily_reset_hour =
              definition.session_policy.daily_reset_hour;
          }
          if (
            definition.session_policy.session_ttl_hours !== null &&
            definition.session_policy.session_ttl_hours !== undefined
          ) {
            fieldValues.session_policy_ttl_hours = definition.session_policy.session_ttl_hours;
          }
        }

        if (definition.delegate_config) {
          fieldValues.delegate_config_capability_tier =
            definition.delegate_config.capability_tier ?? 'read_only';
          if (definition.delegate_config.max_delegation_depth !== undefined) {
            fieldValues.delegate_config_max_delegation_depth =
              definition.delegate_config.max_delegation_depth;
          }
          if (
            definition.delegate_config.allowed_tools !== null &&
            definition.delegate_config.allowed_tools !== undefined
          ) {
            fieldValues.delegate_config_allowed_tools = definition.delegate_config.allowed_tools;
          }
          if (
            definition.delegate_config.budget_limit_tokens !== null &&
            definition.delegate_config.budget_limit_tokens !== undefined
          ) {
            fieldValues.delegate_config_budget_limit_tokens =
              definition.delegate_config.budget_limit_tokens;
          }
        }

        form.setFieldsValue(fieldValues as Parameters<typeof form.setFieldsValue>[0]);
        setKeywords(definition.trigger?.keywords ?? []);
      } else {
        form.resetFields();
        form.setFieldsValue({
          scope_id: initialProjectId ?? TENANT_SCOPE_VALUE,
          execution_backend_type: 'memstack',
        });
        setKeywords([]);
      }
      if (openStateChanged) {
        setTimeout(() => {
          setActiveTab('basic');
        }, 0);
      }
    }

    prevDefinitionRef.current = definition ?? null;
    prevIsOpenRef.current = isOpen;
  }, [isOpen, definition, form, initialProjectId]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const spawnPolicy = buildSpawnPolicy(values, Boolean(definition?.spawn_policy));
      const toolPolicy = buildToolPolicy(values, Boolean(definition?.tool_policy));
      const sessionPolicy = buildSessionPolicy(values, Boolean(definition?.session_policy));
      const delegateConfig = buildDelegateConfig(values, Boolean(definition?.delegate_config));

      if (definition) {
        const data: UpdateDefinitionRequest = {
          name: values.name,
          display_name: values.display_name,
          system_prompt: values.system_prompt,
          model: values.model,
          fallback_models: normalizeStringList(values.fallback_models) ?? [],
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          max_iterations: values.max_iterations,
          trigger_keywords: keywords.length > 0 ? keywords : undefined,
          allowed_tools: values.allowed_tools,
          allowed_skills: values.allowed_skills,
          allowed_mcp_servers: values.allowed_mcp_servers,
          can_spawn: values.can_spawn,
          max_spawn_depth: values.max_spawn_depth,
          agent_to_agent_enabled: values.agent_to_agent_enabled,
          agent_to_agent_allowlist: values.agent_to_agent_allowlist,
          discoverable: values.discoverable,
          max_retries: values.max_retries,
          workspace_config: values.workspace_config,
          spawn_policy: spawnPolicy,
          tool_policy: toolPolicy,
          session_policy: sessionPolicy,
          delegate_config: delegateConfig,
          execution_backend:
            values.execution_backend_type === 'acp_external'
              ? {
                  type: 'acp_external',
                  acp_agent_key: values.execution_backend_acp_agent_key,
                }
              : { type: 'memstack' },
          metadata: stripLegacyPolicyMetadata(definition.metadata) ?? {},
        };
        if (tenantId) {
          await updateDefinition(definition.id, data, { tenant_id: tenantId });
        } else {
          await updateDefinition(definition.id, data);
        }
        message.success(
          t('tenant.agentDefinitions.messages.updateSuccess', 'Agent definition updated')
        );
      } else {
        const data: CreateDefinitionRequest = {
          name: values.name,
          display_name: values.display_name,
          system_prompt: values.system_prompt,
          project_id: values.scope_id === TENANT_SCOPE_VALUE ? undefined : values.scope_id,
          model: values.model === 'inherit' ? undefined : values.model,
          fallback_models: normalizeStringList(values.fallback_models) ?? [],
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          max_iterations: values.max_iterations,
          trigger_keywords: keywords.length > 0 ? keywords : undefined,
          allowed_tools: values.allowed_tools,
          allowed_skills: values.allowed_skills,
          allowed_mcp_servers: values.allowed_mcp_servers,
          can_spawn: values.can_spawn,
          max_spawn_depth: values.max_spawn_depth,
          agent_to_agent_enabled: values.agent_to_agent_enabled,
          agent_to_agent_allowlist: values.agent_to_agent_allowlist,
          discoverable: values.discoverable,
          max_retries: values.max_retries,
          workspace_config: values.workspace_config,
          spawn_policy: spawnPolicy,
          tool_policy: toolPolicy,
          session_policy: sessionPolicy,
          delegate_config: delegateConfig,
          execution_backend:
            values.execution_backend_type === 'acp_external'
              ? {
                  type: 'acp_external',
                  acp_agent_key: values.execution_backend_acp_agent_key,
                }
              : { type: 'memstack' },
        };
        if (tenantId) {
          await createDefinition(data, { tenant_id: tenantId });
        } else {
          await createDefinition(data);
        }
        message.success(
          t('tenant.agentDefinitions.messages.createSuccess', 'Agent definition created')
        );
      }
      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: Array<{ name?: string[] | undefined }> | undefined };
      if (err.errorFields) {
        const firstErrorField = err.errorFields[0]?.name?.[0];
        if (firstErrorField) {
          if (['name', 'display_name', 'system_prompt', 'model'].includes(firstErrorField)) {
            setActiveTab('basic');
          } else if (
            ['allowed_tools', 'max_tokens', 'temperature', 'max_iterations'].includes(
              firstErrorField
            )
          ) {
            setActiveTab('permissions');
          }
        }
      }
    }
  }, [form, definition, keywords, createDefinition, updateDefinition, onSuccess, tenantId, t]);

  // Keyword handlers
  const handleAddKeyword = useCallback(() => {
    if (keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
      setKeywords([...keywords, keywordInput.trim()]);
      setKeywordInput('');
    }
  }, [keywordInput, keywords]);

  const handleRemoveKeyword = useCallback(
    (keyword: string) => {
      setKeywords(keywords.filter((k) => k !== keyword));
    },
    [keywords]
  );

  const tabItems = [
    {
      key: 'basic',
      label: t('tenant.agentDefinitions.modal.basicInfo', 'Basic Info'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="name"
            label={t('tenant.agentDefinitions.modal.name', 'Name')}
            rules={[
              {
                required: true,
                message: t('tenant.agentDefinitions.modal.nameRequired', 'Name is required'),
              },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: t(
                  'tenant.agentDefinitions.modal.namePattern',
                  'Lowercase letters, digits, underscores. Must start with letter.'
                ),
              },
            ]}
          >
            <Input
              placeholder={t('tenant.agentDefinitions.modal.namePlaceholder')}
              disabled={isEditMode}
            />
          </Form.Item>

          <Form.Item
            name="display_name"
            label={t('tenant.agentDefinitions.modal.displayName', 'Display Name')}
            rules={[
              {
                required: true,
                message: t(
                  'tenant.agentDefinitions.modal.displayNameRequired',
                  'Display name is required'
                ),
              },
            ]}
          >
            <Input placeholder={t('tenant.agentDefinitions.modal.displayNamePlaceholder')} />
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label={t('tenant.agentDefinitions.modal.systemPrompt', 'System Prompt')}
            rules={[
              {
                required: true,
                message: t(
                  'tenant.agentDefinitions.modal.systemPromptRequired',
                  'System prompt is required'
                ),
              },
            ]}
          >
            <TextArea
              rows={6}
              placeholder={t(
                'tenant.agentDefinitions.modal.systemPromptPlaceholder',
                "Define the agent's role, capabilities, and behavior..."
              )}
            />
          </Form.Item>

          <Form.Item
            name="scope_id"
            label={t('tenant.agentDefinitions.modal.scope', { defaultValue: 'Scope' })}
            initialValue={initialProjectId ?? TENANT_SCOPE_VALUE}
          >
            <Select
              disabled={isEditMode}
              showSearch={{ filterOption: filterSelectOption }}
              options={scopeOptions}
            />
          </Form.Item>

          <Form.Item
            name="execution_backend_type"
            label={t('tenant.agentDefinitions.modal.executionBackend', {
              defaultValue: 'Execution Backend',
            })}
            initialValue="memstack"
          >
            <Select
              options={[
                {
                  label: t('tenant.agentDefinitions.modal.executionBackendMemstack', {
                    defaultValue: 'MemStack Native',
                  }),
                  value: 'memstack',
                },
                {
                  label: t('tenant.agentDefinitions.modal.executionBackendAcp', {
                    defaultValue: 'External ACP Agent',
                  }),
                  value: 'acp_external',
                },
              ]}
            />
          </Form.Item>

          {isExternalAcpBackend && (
            <Form.Item
              name="execution_backend_acp_agent_key"
              label={t('tenant.agentDefinitions.modal.externalAcpAgent', {
                defaultValue: 'External ACP Agent',
              })}
              rules={[
                {
                  required: true,
                  message: t('tenant.agentDefinitions.modal.externalAcpAgentRequired', {
                    defaultValue: 'Select an external ACP agent',
                  }),
                },
              ]}
            >
              <Select
                showSearch={{ filterOption: filterSelectOption }}
                loading={loadingResources}
                options={acpAgentOptions}
                placeholder={t('tenant.agentDefinitions.modal.externalAcpAgentPlaceholder', {
                  defaultValue: 'Select an external ACP agent',
                })}
              />
            </Form.Item>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="model"
              label={t('tenant.agentDefinitions.modal.model', 'Model')}
              initialValue="inherit"
            >
              <Select disabled={isExternalAcpBackend}>
                {LLM_MODELS.map((model) => (
                  <Option key={model.value} value={model.value}>
                    {model.label}
                  </Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item
              name="max_retries"
              label={t('tenant.agentDefinitions.modal.maxRetries', 'Max Retries')}
              initialValue={3}
            >
              <InputNumber min={0} max={10} className="w-full" />
            </Form.Item>
          </div>

          <Form.Item
            name="fallback_models"
            label={t('tenant.agentDefinitions.modal.fallbackModels', 'Fallback Models')}
            tooltip={t(
              'tenant.agentDefinitions.modal.fallbackModelsTooltip',
              'Models to try in order if the primary model cannot complete a request.'
            )}
          >
            <Select
              mode="tags"
              allowClear
              placeholder={t(
                'tenant.agentDefinitions.modal.fallbackModelsPlaceholder',
                'Add fallback model IDs'
              )}
              options={LLM_MODELS.filter((model) => model.value !== 'inherit').map((model) => ({
                label: model.label,
                value: model.value,
              }))}
            />
          </Form.Item>
        </div>
      ),
    },
    {
      key: 'trigger',
      label: t('tenant.agentDefinitions.modal.triggerConfig', 'Trigger & Routing'),
      children: (
        <div className="space-y-4">
          <div>
            <span className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.agentDefinitions.modal.triggerKeywords', 'Trigger Keywords')}
            </span>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder={t('tenant.agentDefinitions.modal.addKeyword', 'Add keyword...')}
                value={keywordInput}
                onChange={(e) => {
                  setKeywordInput(e.target.value);
                }}
                onPressEnter={handleAddKeyword}
              />
              <button
                type="button"
                onClick={handleAddKeyword}
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors"
              >
                {t('common.add', 'Add')}
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {keywords.map((keyword) => (
                <Tag
                  key={keyword}
                  closable
                  onClose={() => {
                    handleRemoveKeyword(keyword);
                  }}
                  className="px-2 py-1"
                >
                  {keyword}
                </Tag>
              ))}
              {keywords.length === 0 && (
                <span className="text-sm text-slate-400">
                  {t('tenant.agentDefinitions.modal.noKeywords', 'No keywords added')}
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-200 dark:border-slate-700">
            <Form.Item
              name="discoverable"
              label={t('tenant.agentDefinitions.modal.discoverable', 'Discoverable')}
              valuePropName="checked"
              initialValue={true}
            >
              <Switch />
            </Form.Item>

            <Form.Item
              name="agent_to_agent_enabled"
              label={t('tenant.agentDefinitions.modal.agentToAgent', 'Agent-to-Agent')}
              valuePropName="checked"
              initialValue={false}
            >
              <Switch />
            </Form.Item>
          </div>

          <Form.Item
            name="agent_to_agent_allowlist"
            label={t('tenant.agentDefinitions.modal.agentToAgentAllowlist', 'A2A Allowlist')}
            tooltip={t(
              'tenant.agentDefinitions.modal.agentToAgentAllowlistTooltip',
              'Allowed sender agent IDs or names. Leave untouched on create to use the default trusted built-in senders; use an empty list to deny all.'
            )}
          >
            <Select
              mode="tags"
              placeholder={t(
                'tenant.agentDefinitions.modal.agentToAgentAllowlistPlaceholder',
                'Add agent IDs or names'
              )}
            />
          </Form.Item>

          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="can_spawn"
              label={t('tenant.agentDefinitions.modal.canSpawn', 'Can Spawn Children')}
              valuePropName="checked"
              initialValue={false}
            >
              <Switch />
            </Form.Item>

            <Form.Item
              name="max_spawn_depth"
              label={t('tenant.agentDefinitions.modal.maxSpawnDepth', 'Max Spawn Depth')}
              initialValue={3}
            >
              <InputNumber min={0} max={10} className="w-full" />
            </Form.Item>
          </div>
        </div>
      ),
    },
    {
      key: 'permissions',
      label: t('tenant.agentDefinitions.modal.permissions', 'Permissions & Resources'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="allowed_tools"
            label={t('tenant.agentDefinitions.modal.allowedTools', 'Allowed Tools')}
            tooltip={t(
              'tenant.agentDefinitions.modal.allowedToolsTooltip',
              'Tools this agent can use. Select * for all.'
            )}
            initialValue={['*']}
          >
            <Select
              mode="multiple"
              placeholder={t('tenant.agentDefinitions.modal.allowedToolsPlaceholder')}
              loading={loadingResources}
              showSearch={{ filterOption: filterSelectOption }}
              options={[
                { label: t('tenant.agentDefinitions.modal.allToolsOption'), value: '*' },
                ...availableTools.map((tool) => ({
                  label: tool.name,
                  value: tool.name,
                  title: tool.description,
                })),
              ]}
            />
          </Form.Item>

          <Form.Item
            name="allowed_skills"
            label={t('tenant.agentDefinitions.modal.allowedSkills', 'Allowed Skills')}
            tooltip={t(
              'tenant.agentDefinitions.modal.allowedSkillsTooltip',
              'Skills this agent can activate.'
            )}
          >
            <Select
              mode="multiple"
              placeholder={t('tenant.agentDefinitions.modal.allowedSkillsPlaceholder')}
              loading={loadingResources}
              showSearch={{ filterOption: filterSelectOption }}
              options={availableSkills.map((s) => ({
                label: s.name,
                value: s.id,
                title: s.description,
              }))}
            />
          </Form.Item>

          <Form.Item
            name="allowed_mcp_servers"
            label={t('tenant.agentDefinitions.modal.allowedMcpServers', 'MCP Servers')}
            tooltip={t(
              'tenant.agentDefinitions.modal.allowedMcpServersTooltip',
              'MCP servers this agent can access.'
            )}
          >
            <Select
              mode="multiple"
              placeholder={t('tenant.agentDefinitions.modal.allowedMcpServersPlaceholder')}
              loading={loadingResources}
              showSearch={{ filterOption: filterSelectOption }}
              options={availableMcpServers.map((s) => ({
                label: s.name,
                value: s.name,
                title: s.description ?? '',
              }))}
            />
          </Form.Item>

          <div className="grid grid-cols-3 gap-4">
            <Form.Item
              name="max_tokens"
              label={t('tenant.agentDefinitions.modal.maxTokens', 'Max Tokens')}
              initialValue={4096}
            >
              <InputNumber min={100} max={32000} className="w-full" />
            </Form.Item>

            <Form.Item
              name="temperature"
              label={t('tenant.agentDefinitions.modal.temperature', 'Temperature')}
              initialValue={0.7}
            >
              <Slider min={0} max={2} step={0.1} />
            </Form.Item>

            <Form.Item
              name="max_iterations"
              label={t('tenant.agentDefinitions.modal.maxIterations', 'Max Iterations')}
              initialValue={10}
            >
              <InputNumber min={1} max={50} className="w-full" />
            </Form.Item>
          </div>
        </div>
      ),
    },
    {
      key: 'sandbox',
      label: t('tenant.agentDefinitions.modal.sandboxIsolation', 'Sandbox & Isolation'),
      children: (
        <div className="space-y-6">
          <div>
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.spawnPolicy', 'Spawn Policy')}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <Form.Item
                name="spawn_policy_max_active_runs"
                label={t('tenant.agentDefinitions.modal.maxActiveRuns', 'Max Active Runs')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.maxActiveRunsTooltip',
                  'Maximum number of active subagent runs'
                )}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
              <Form.Item
                name="spawn_policy_max_children_per_requester"
                label={t(
                  'tenant.agentDefinitions.modal.maxChildrenPerRequester',
                  'Max Children Per Requester'
                )}
                tooltip={t(
                  'tenant.agentDefinitions.modal.maxChildrenPerRequesterTooltip',
                  'Maximum subagents allowed per requester'
                )}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
            </div>
            <Form.Item
              name="spawn_policy_allowed_subagents"
              label={t('tenant.agentDefinitions.modal.allowedSubagents', 'Allowed Subagents')}
              tooltip={t(
                'tenant.agentDefinitions.modal.allowedSubagentsTooltip',
                'Allowed subagent names or IDs'
              )}
            >
              <Select mode="tags" placeholder={t('common.add', 'Add...')} />
            </Form.Item>
          </div>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.workspaceConfig', 'Workspace Config')}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <Form.Item
                name={['workspace_config', 'type']}
                label={t('tenant.agentDefinitions.modal.workspaceType', 'Workspace Type')}
                initialValue="shared"
              >
                <Select>
                  <Option value="shared">
                    {t('tenant.agentDefinitions.modal.workspaceTypes.shared', 'Shared')}
                  </Option>
                  <Option value="isolated">
                    {t('tenant.agentDefinitions.modal.workspaceTypes.isolated', 'Isolated')}
                  </Option>
                  <Option value="inherited">
                    {t('tenant.agentDefinitions.modal.workspaceTypes.inherited', 'Inherited')}
                  </Option>
                </Select>
              </Form.Item>
              <Form.Item
                name={['workspace_config', 'base_dir']}
                label={t('tenant.agentDefinitions.modal.workspaceBaseDir', 'Base Directory')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.workspaceBaseDirTooltip',
                  'Custom workspace directory path'
                )}
              >
                <Input
                  placeholder={t('tenant.agentDefinitions.modal.workspaceBaseDirPlaceholder')}
                />
              </Form.Item>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.sessionPolicy', 'Session Policy')}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <Form.Item
                name="session_policy_dm_scope"
                label={t('tenant.agentDefinitions.modal.dmScope', 'DM Scope')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.dmScopeTooltip',
                  'Controls how direct-message conversations share or isolate session state.'
                )}
              >
                <Select
                  allowClear
                  placeholder={t('tenant.agentDefinitions.modal.dmScopePlaceholder', 'Use default')}
                >
                  <Option value="per_user">
                    {t('tenant.agentDefinitions.modal.dmScopePerUser', 'Per user')}
                  </Option>
                  <Option value="per_chat">
                    {t('tenant.agentDefinitions.modal.dmScopePerChat', 'Per chat')}
                  </Option>
                  <Option value="global">
                    {t('tenant.agentDefinitions.modal.dmScopeGlobal', 'Global')}
                  </Option>
                </Select>
              </Form.Item>
              <Form.Item
                name="session_policy_max_messages"
                label={t('tenant.agentDefinitions.modal.maxMessages', 'Max Messages')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.maxMessagesTooltip',
                  'Maximum messages before the session is trimmed.'
                )}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
              <Form.Item
                name="session_policy_idle_reset_minutes"
                label={t('tenant.agentDefinitions.modal.idleResetMinutes', 'Idle Reset Minutes')}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
              <Form.Item
                name="session_policy_daily_reset_hour"
                label={t('tenant.agentDefinitions.modal.dailyResetHour', 'Daily Reset Hour')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.dailyResetHourTooltip',
                  'UTC hour from 0 to 23. Leave empty for no daily reset.'
                )}
              >
                <InputNumber min={0} max={23} className="w-full" />
              </Form.Item>
              <Form.Item
                name="session_policy_ttl_hours"
                label={t('tenant.agentDefinitions.modal.sessionTtlHours', 'Session TTL Hours')}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.delegateConfig', 'Delegate Config')}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <Form.Item
                name="delegate_config_capability_tier"
                label={t('tenant.agentDefinitions.modal.delegateCapabilityTier', 'Capability Tier')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.delegateCapabilityTierTooltip',
                  'Capability tier granted to delegated work.'
                )}
              >
                <Select
                  allowClear
                  placeholder={t(
                    'tenant.agentDefinitions.modal.delegateCapabilityTierPlaceholder',
                    'Use default'
                  )}
                >
                  <Option value="full">
                    {t('tenant.agentDefinitions.modal.delegateCapabilityFull', 'Full')}
                  </Option>
                  <Option value="read_write">
                    {t('tenant.agentDefinitions.modal.delegateCapabilityReadWrite', 'Read/write')}
                  </Option>
                  <Option value="read_only">
                    {t('tenant.agentDefinitions.modal.delegateCapabilityReadOnly', 'Read-only')}
                  </Option>
                  <Option value="none">
                    {t('tenant.agentDefinitions.modal.delegateCapabilityNone', 'None')}
                  </Option>
                </Select>
              </Form.Item>
              <Form.Item
                name="delegate_config_max_delegation_depth"
                label={t(
                  'tenant.agentDefinitions.modal.maxDelegationDepth',
                  'Max Delegation Depth'
                )}
              >
                <InputNumber min={0} className="w-full" />
              </Form.Item>
              <Form.Item
                name="delegate_config_budget_limit_tokens"
                label={t(
                  'tenant.agentDefinitions.modal.delegateBudgetLimitTokens',
                  'Budget Limit Tokens'
                )}
              >
                <InputNumber min={1} className="w-full" />
              </Form.Item>
            </div>
            <Form.Item
              name="delegate_config_allowed_tools"
              label={t('tenant.agentDefinitions.modal.delegateAllowedTools', 'Delegate Tools')}
              tooltip={t(
                'tenant.agentDefinitions.modal.delegateAllowedToolsTooltip',
                'Tool names this agent may grant to delegated work. Leave empty to inherit the tier boundary.'
              )}
            >
              <Select
                mode="tags"
                allowClear
                placeholder={t('tenant.agentDefinitions.modal.delegateAllowedToolsPlaceholder')}
                loading={loadingResources}
                showSearch={{ filterOption: filterSelectOption }}
                options={availableTools.map((tool) => ({
                  label: tool.name,
                  value: tool.name,
                  title: tool.description,
                }))}
              />
            </Form.Item>
          </div>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.toolPolicy', 'Tool Policy')}
            </h4>
            <Form.Item
              name="tool_policy_precedence"
              label={t('tenant.agentDefinitions.modal.toolPolicyPrecedence', 'Precedence')}
              initialValue="deny_first"
            >
              <Select>
                <Option value="deny_first">
                  {t('tenant.agentDefinitions.modal.toolPolicyPrecedenceDenyFirst', 'Deny first')}
                </Option>
                <Option value="allow_first">
                  {t('tenant.agentDefinitions.modal.toolPolicyPrecedenceAllowFirst', 'Allow first')}
                </Option>
              </Select>
            </Form.Item>
            <div className="grid grid-cols-2 gap-4">
              <Form.Item
                name="tool_policy_allow"
                label={t('tenant.agentDefinitions.modal.toolPolicyAllow', 'Allow List')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.toolPolicyAllowTooltip',
                  'Allowed tool patterns'
                )}
              >
                <Select mode="tags" placeholder={t('common.add', 'Add...')} />
              </Form.Item>
              <Form.Item
                name="tool_policy_deny"
                label={t('tenant.agentDefinitions.modal.toolPolicyDeny', 'Deny List')}
                tooltip={t(
                  'tenant.agentDefinitions.modal.toolPolicyDenyTooltip',
                  'Denied tool patterns'
                )}
              >
                <Select mode="tags" placeholder={t('common.add', 'Add...')} />
              </Form.Item>
            </div>
          </div>
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={
        isEditMode
          ? t('tenant.agentDefinitions.modal.editTitle', 'Edit Agent Definition')
          : t('tenant.agentDefinitions.modal.createTitle', 'Create Agent Definition')
      }
      open={isOpen}
      onCancel={onClose}
      onOk={() => {
        void handleSubmit();
      }}
      okText={isEditMode ? t('common.save', 'Save') : t('common.create', 'Create')}
      cancelText={t('common.cancel', 'Cancel')}
      confirmLoading={isSubmitting}
      width={700}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        {loadingResources ? (
          <StateDisplay.Loading
            message={t('tenant.agentDefinitions.modal.loadingResources')}
            card={false}
          />
        ) : (
          <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
        )}
      </Form>
    </Modal>
  );
};

export default AgentDefinitionModal;
