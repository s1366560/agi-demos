/**
 * AgentDefinitionModal - Modal for creating and editing agent definitions.
 *
 * Follows SubAgentModal pattern: Form.useForm(), tabbed layout,
 * resource fetching on open, confirmLoading bound to store submitting.
 */

import React, { useCallback, useEffect, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Tabs, InputNumber, Switch, Tag, message, Slider } from 'antd';

import { agentService } from '../../services/agentService';
import { mcpAPI } from '../../services/mcpService';
import { skillAPI } from '../../services/skillService';
import {
  useCreateDefinition,
  useUpdateDefinition,
  useDefinitionSubmitting,
} from '../../stores/agentDefinitions';
import { StateDisplay } from '../shared/ui/StateDisplay';

import type { SkillResponse, MCPServerResponse, ToolInfo } from '../../types/agent';
import type {
  AgentDefinition,
  CreateDefinitionRequest,
  UpdateDefinitionRequest,
} from '../../types/multiAgent';

const { TextArea } = Input;
const { Option } = Select;

export interface AgentDefinitionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  definition: AgentDefinition | null;
}

const LLM_MODELS = [
  { value: 'inherit', label: 'Inherit from Tenant Config' },
  { value: 'qwen-max', label: 'Qwen Max' },
  { value: 'qwen-plus', label: 'Qwen Plus' },
  { value: 'qwen-turbo', label: 'Qwen Turbo' },
  { value: 'gpt-4', label: 'GPT-4' },
  { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
  { value: 'claude-3-opus', label: 'Claude 3 Opus' },
  { value: 'claude-3-sonnet', label: 'Claude 3 Sonnet' },
  { value: 'gemini-pro', label: 'Gemini Pro' },
  { value: 'deepseek-chat', label: 'Deepseek Chat' },
];

export const AgentDefinitionModal: React.FC<AgentDefinitionModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  definition,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState('basic');

  // Trigger keywords/examples local state
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState('');

  // Available resources
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillResponse[]>([]);
  const [availableMcpServers, setAvailableMcpServers] = useState<MCPServerResponse[]>([]);
  const [loadingResources, setLoadingResources] = useState(false);

  const isSubmitting = useDefinitionSubmitting();
  const createDefinition = useCreateDefinition();
  const updateDefinition = useUpdateDefinition();

  const isEditMode = !!definition;

  // Track previous state to avoid unnecessary resets
  const prevDefinitionRef = useRef<AgentDefinition | null>(null);
  const prevIsOpenRef = useRef(false);

  // Fetch available resources when modal opens
  useEffect(() => {
    if (isOpen) {
      const fetchResources = async () => {
        setLoadingResources(true);
        try {
          const [toolsRes, skillsRes, mcpRes] = await Promise.all([
            agentService.listTools(),
            skillAPI.list({ limit: 100 }),
            mcpAPI.list({ limit: 100 }),
          ]);
          setAvailableTools(toolsRes.tools || []);
          setAvailableSkills(skillsRes.skills || []);
          setAvailableMcpServers(mcpRes || []);
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
      fetchResources();
    }
  }, [isOpen, t]);

  // Reset form when modal opens/closes or definition changes
  useEffect(() => {
    const definitionChanged = prevDefinitionRef.current?.id !== definition?.id;
    const openStateChanged = prevIsOpenRef.current !== isOpen;

    if (isOpen && (definitionChanged || openStateChanged)) {
      if (definition) {
        form.setFieldsValue({
          name: definition.name,
          display_name: definition.display_name ?? '',
          system_prompt: definition.system_prompt ?? '',
          model: definition.model ?? 'inherit',
          temperature: definition.temperature ?? 0.7,
          max_tokens: definition.max_tokens ?? 4096,
          max_iterations: definition.max_iterations ?? 10,
          allowed_tools: definition.allowed_tools ?? ['*'],
          allowed_skills: definition.allowed_skills ?? [],
          allowed_mcp_servers: definition.allowed_mcp_servers ?? [],
          can_spawn: definition.can_spawn,
          max_spawn_depth: definition.max_spawn_depth,
          agent_to_agent_enabled: definition.agent_to_agent_enabled,
          discoverable: definition.discoverable,
          max_retries: definition.max_retries,
          workspace_config: definition.workspace_config ?? { type: 'shared' },
          spawn_policy_max_active_runs: definition.metadata?.spawn_policy_max_active_runs,
          spawn_policy_max_children_per_requester:
            definition.metadata?.spawn_policy_max_children_per_requester,
          spawn_policy_allowed_subagents: definition.metadata?.spawn_policy_allowed_subagents,
          tool_policy_allow: definition.metadata?.tool_policy_allow,
          tool_policy_deny: definition.metadata?.tool_policy_deny,
        });
        setKeywords(definition.trigger?.keywords ?? []);
      } else {
        form.resetFields();
        setKeywords([]);
      }
      if (openStateChanged) {
        setTimeout(() => {
          setActiveTab('basic');
        }, 0);
      }
    }

    prevDefinitionRef.current = definition || null;
    prevIsOpenRef.current = isOpen;
  }, [isOpen, definition, form]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();

      if (isEditMode && definition) {
        const data: UpdateDefinitionRequest = {
          name: values.name,
          display_name: values.display_name,
          system_prompt: values.system_prompt,
          model: values.model === 'inherit' ? undefined : values.model,
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
          discoverable: values.discoverable,
          max_retries: values.max_retries,
          workspace_config: values.workspace_config,
          metadata: {
            ...(definition.metadata || {}),
            spawn_policy_max_active_runs: values.spawn_policy_max_active_runs,
            spawn_policy_max_children_per_requester: values.spawn_policy_max_children_per_requester,
            spawn_policy_allowed_subagents: values.spawn_policy_allowed_subagents,
            tool_policy_allow: values.tool_policy_allow,
            tool_policy_deny: values.tool_policy_deny,
          },
        };
        await updateDefinition(definition.id, data);
        message.success(
          t('tenant.agentDefinitions.messages.updateSuccess', 'Agent definition updated')
        );
      } else {
        const data: CreateDefinitionRequest = {
          name: values.name,
          display_name: values.display_name,
          system_prompt: values.system_prompt,
          model: values.model === 'inherit' ? undefined : values.model,
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
          discoverable: values.discoverable,
          max_retries: values.max_retries,
          workspace_config: values.workspace_config,
          metadata: {
            spawn_policy_max_active_runs: values.spawn_policy_max_active_runs,
            spawn_policy_max_children_per_requester: values.spawn_policy_max_children_per_requester,
            spawn_policy_allowed_subagents: values.spawn_policy_allowed_subagents,
            tool_policy_allow: values.tool_policy_allow,
            tool_policy_deny: values.tool_policy_deny,
          },
        };
        await createDefinition(data);
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
  }, [form, isEditMode, definition, keywords, createDefinition, updateDefinition, onSuccess, t]);

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
            <Input placeholder="e.g., customer_support" disabled={isEditMode} />
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
            <Input placeholder="e.g., Customer Support Agent" />
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

          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="model"
              label={t('tenant.agentDefinitions.modal.model', 'Model')}
              initialValue="inherit"
            >
              <Select>
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
              placeholder="Select tools"
              loading={loadingResources}
              filterOption={(input, option) =>
                (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
              }
              options={[
                { label: 'All Tools (*)', value: '*' },
                ...(availableTools || []).map((tool) => ({
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
              placeholder="Select skills (leave empty for none)"
              loading={loadingResources}
              filterOption={(input, option) =>
                (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
              }
              options={(availableSkills || []).map((s) => ({
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
              placeholder="Select servers (leave empty for none)"
              loading={loadingResources}
              filterOption={(input, option) =>
                (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
              }
              options={(availableMcpServers || []).map((s) => ({
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
                <InputNumber min={0} className="w-full" />
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
                <InputNumber min={0} className="w-full" />
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
                  <Option value="shared">Shared</Option>
                  <Option value="isolated">Isolated</Option>
                  <Option value="inherited">Inherited</Option>
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
                <Input placeholder="/path/to/dir" />
              </Form.Item>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentDefinitions.modal.toolPolicy', 'Tool Policy')}
            </h4>
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
      onOk={handleSubmit}
      okText={isEditMode ? t('common.save', 'Save') : t('common.create', 'Create')}
      cancelText={t('common.cancel', 'Cancel')}
      confirmLoading={isSubmitting}
      width={700}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        {loadingResources ? (
          <StateDisplay.Loading message="Loading resources..." card={false} />
        ) : (
          <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
        )}
      </Form>
    </Modal>
  );
};

export default AgentDefinitionModal;
