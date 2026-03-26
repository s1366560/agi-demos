/**
 * SubAgent Modal Component
 *
 * Modal for creating and editing SubAgents with tabbed form layout.
 */

import React, { useCallback, useEffect, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Modal,
  Form,
  Input,
  Select,
  Tabs,
  InputNumber,
  ColorPicker,
  Tag,
  message,
  Slider,
  Radio,
} from 'antd';
import { X } from 'lucide-react';

import { agentService } from '../../services/agentService';
import { mcpAPI } from '../../services/mcpService';
import { skillAPI } from '../../services/skillService';
import { useSubAgentStore, useSubAgentSubmitting } from '../../stores/subagent';

import type {
  SubAgentResponse,
  SubAgentCreate,
  SubAgentUpdate,
  SkillResponse,
  MCPServerResponse,
  ToolInfo,
  SpawnPolicyConfig,
  ToolPolicyConfig,
  AgentIdentityConfig,
} from '../../types/agent';
import type { Color } from 'antd/es/color-picker';

const { TextArea } = Input;
const { Option } = Select;

interface SubAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  subagent: SubAgentResponse | null;
  subagents?: SubAgentResponse[];
}

// Available LLM models
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

// Color presets
const COLOR_PRESETS = [
  '#3B82F6', // Blue
  '#10B981', // Green
  '#F59E0B', // Yellow
  '#EF4444', // Red
  '#8B5CF6', // Purple
  '#EC4899', // Pink
  '#06B6D4', // Cyan
  '#F97316', // Orange
];

export const SubAgentModal: React.FC<SubAgentModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  subagent,
  subagents = [],
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState('basic');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [examples, setExamples] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState('');
  const [exampleInput, setExampleInput] = useState('');
  const [selectedColor, setSelectedColor] = useState('#3B82F6');

  // Spawn Policy state
  const [spawnPolicy, setSpawnPolicy] = useState<SpawnPolicyConfig>({
    max_depth: 2,
    max_active_runs: 16,
    max_children_per_requester: 8,
    allowed_subagents: null,
  });

  // Tool Policy state
  const [toolPolicy, setToolPolicy] = useState<ToolPolicyConfig>({
    allow: [],
    deny: [],
    precedence: 'deny_first',
  });

  // Identity state
  const [identityDescription, setIdentityDescription] = useState('');
  const [identityMetadata, setIdentityMetadata] = useState<[string, string][]>([]);

  // Available resources state
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillResponse[]>([]);
  const [availableMcpServers, setAvailableMcpServers] = useState<MCPServerResponse[]>([]);
  const [loadingResources, setLoadingResources] = useState(false);

  const isSubmitting = useSubAgentSubmitting();
  const { createSubAgent, updateSubAgent } = useSubAgentStore();

  const isEditMode = !!subagent;

  // Track previous state to only update when values actually change
  const prevSubagentRef = useRef<SubAgentResponse | null>(null);
  const prevIsOpenRef = useRef(false);

  // Fetch available resources
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
          setAvailableSkills(skillsRes.skills || []); // skillAPI returns { skills: [], total: number }
          setAvailableMcpServers(mcpRes || []); // mcpAPI returns MCPServerResponse[]
        } catch (error) {
          console.error('Failed to fetch resources:', error);
          message.error(
            t('tenant.subagents.modal.resourceFetchError', 'Failed to load available tools/skills')
          );
        } finally {
          setLoadingResources(false);
        }
      };

      fetchResources();
    }
  }, [isOpen, t]);

  // Reset form when modal opens/closes or subagent changes
  useEffect(() => {
    const subagentChanged = prevSubagentRef.current?.id !== subagent?.id;
    const openStateChanged = prevIsOpenRef.current !== isOpen;

    if (isOpen && (subagentChanged || openStateChanged)) {
      if (subagent) {
        // Edit mode - populate form
        form.setFieldsValue({
          name: subagent.name,
          display_name: subagent.display_name,
          system_prompt: subagent.system_prompt,
          trigger_description: subagent.trigger.description,
          model: subagent.model,
          max_tokens: subagent.max_tokens,
          temperature: subagent.temperature,
          max_iterations: subagent.max_iterations,
          allowed_tools: subagent.allowed_tools,
          allowed_skills: subagent.allowed_skills,
          allowed_mcp_servers: subagent.allowed_mcp_servers || [],
        });
      } else {
        // Create mode - reset form
        form.resetFields();
      }
      // Defer tab update to avoid synchronous setState in effect
      if (openStateChanged) {
        setTimeout(() => {
          setActiveTab('basic');
        }, 0);
      }
    }

    prevSubagentRef.current = subagent || null;
    prevIsOpenRef.current = isOpen;
  }, [isOpen, subagent, form]);

  // Update keywords, examples, and color when subagent changes (separate effect)
  useEffect(() => {
    const subagentChanged = prevSubagentRef.current?.id !== subagent?.id;

    if (isOpen && subagent && subagentChanged) {
      // Defer all state updates to avoid synchronous setState in effect
      setTimeout(() => {
        setKeywords(subagent.trigger.keywords);
        setExamples(subagent.trigger.examples);
        setSelectedColor(subagent.color);
        // Load spawn policy
        if (subagent.spawn_policy) {
          setSpawnPolicy(subagent.spawn_policy);
        } else {
          setSpawnPolicy({
            max_depth: 2,
            max_active_runs: 16,
            max_children_per_requester: 8,
            allowed_subagents: null,
          });
        }
        // Load tool policy
        if (subagent.tool_policy) {
          setToolPolicy(subagent.tool_policy);
        } else {
          setToolPolicy({
            allow: [],
            deny: [],
            precedence: 'deny_first',
          });
        }
        // Load identity
        if (subagent.identity) {
          setIdentityDescription(subagent.identity.description || '');
          const meta = subagent.identity.metadata || {};
          setIdentityMetadata(Object.entries(meta));
        } else {
          setIdentityDescription('');
          setIdentityMetadata([]);
        }
      }, 0);
    } else if (isOpen && !subagent && subagentChanged) {
      setTimeout(() => {
        setKeywords([]);
        setExamples([]);
        setSelectedColor('#3B82F6');
        setSpawnPolicy({
          max_depth: 2,
          max_active_runs: 16,
          max_children_per_requester: 8,
          allowed_subagents: null,
        });
        setToolPolicy({
          allow: [],
          deny: [],
          precedence: 'deny_first',
        });
        setIdentityDescription('');
        setIdentityMetadata([]);
      }, 0);
    }
  }, [isOpen, subagent]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();

      // Build identity config if description is provided
      const identityConfig: Partial<AgentIdentityConfig> | undefined = identityDescription
        ? {
            name: values.display_name || values.name,
            description: identityDescription,
            metadata: Object.fromEntries(identityMetadata.filter(([k]) => k.trim())),
          }
        : undefined;

      const data: SubAgentCreate | SubAgentUpdate = {
        name: values.name,
        display_name: values.display_name,
        system_prompt: values.system_prompt,
        trigger_description: values.trigger_description,
        trigger_keywords: keywords,
        trigger_examples: examples,
        model: values.model || 'inherit',
        color: selectedColor,
        max_tokens: values.max_tokens || 4096,
        temperature: values.temperature ?? 0.7,
        max_iterations: values.max_iterations || 10,
        allowed_tools: values.allowed_tools || ['*'],
        allowed_skills: values.allowed_skills || [],
        allowed_mcp_servers: values.allowed_mcp_servers || [],
        // Add policy fields
        spawn_policy: spawnPolicy,
        tool_policy: toolPolicy,
        identity: identityConfig,
      };

      if (isEditMode && subagent) {
        await updateSubAgent(subagent.id, data);
        message.success(t('tenant.subagents.updateSuccess'));
      } else {
        await createSubAgent(data as SubAgentCreate);
        message.success(t('tenant.subagents.createSuccess'));
      }

      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: Array<{ name?: string[] | undefined }> | undefined };
      if (err.errorFields) {
        // Form validation error - switch to the tab with the error
        const firstErrorField = err.errorFields[0]?.name?.[0];
        if (firstErrorField) {
          if (['name', 'display_name', 'system_prompt', 'model'].includes(firstErrorField)) {
            setActiveTab('basic');
          } else if (['trigger_description'].includes(firstErrorField)) {
            setActiveTab('trigger');
          }
        }
      }
      // API errors handled by store
    }
  }, [
    form,
    isEditMode,
    subagent,
    keywords,
    examples,
    selectedColor,
    spawnPolicy,
    toolPolicy,
    identityDescription,
    identityMetadata,
    createSubAgent,
    updateSubAgent,
    onSuccess,
    t,
  ]);

  // Handle keyword addition
  const handleAddKeyword = useCallback(() => {
    if (keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
      setKeywords([...keywords, keywordInput.trim()]);
      setKeywordInput('');
    }
  }, [keywordInput, keywords]);

  // Handle keyword removal
  const handleRemoveKeyword = useCallback(
    (keyword: string) => {
      setKeywords(keywords.filter((k) => k !== keyword));
    },
    [keywords]
  );

  // Handle example addition
  const handleAddExample = useCallback(() => {
    if (exampleInput.trim() && !examples.includes(exampleInput.trim())) {
      setExamples([...examples, exampleInput.trim()]);
      setExampleInput('');
    }
  }, [exampleInput, examples]);

  // Handle example removal
  const handleRemoveExample = useCallback(
    (example: string) => {
      setExamples(examples.filter((e) => e !== example));
    },
    [examples]
  );

  // Keyword Test State
  const [testQuery, setTestQuery] = useState('');
  const [testResult, setTestResult] = useState<{
    matched: boolean;
    keyword?: string | undefined;
  } | null>(null);

  const handleTestKeyword = useCallback(() => {
    if (!testQuery.trim()) {
      setTestResult(null);
      return;
    }
    const queryLower = testQuery.toLowerCase();
    const queryWords = queryLower.split(/\s+/);

    // Backend logic: strict word matching
    // Check if any keyword matches exactly one of the words in the query
    const matchedKeyword = keywords.find((k) => {
      const kLower = k.toLowerCase();
      return queryWords.includes(kLower);
    });

    if (matchedKeyword) {
      setTestResult({ matched: true, keyword: matchedKeyword });
    } else {
      setTestResult({ matched: false });
    }
  }, [testQuery, keywords]);

  // Handle color change
  const handleColorChange = useCallback((color: Color) => {
    setSelectedColor(color.toHexString());
  }, []);

  // Tab items
  const tabItems = [
    {
      key: 'basic',
      label: t('tenant.subagents.modal.basicInfo'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="name"
            label={t('tenant.subagents.modal.name')}
            rules={[
              {
                required: true,
                message: t('tenant.subagents.modal.nameRequired'),
              },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: t('tenant.subagents.modal.namePattern'),
              },
            ]}
          >
            <Input placeholder="e.g., code_reviewer" disabled={isEditMode} />
          </Form.Item>

          <Form.Item
            name="display_name"
            label={t('tenant.subagents.modal.displayName')}
            rules={[
              {
                required: true,
                message: t('tenant.subagents.modal.displayNameRequired'),
              },
            ]}
          >
            <Input placeholder="e.g., Code Reviewer" />
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label={t('tenant.subagents.modal.systemPrompt')}
            rules={[
              {
                required: true,
                message: t('tenant.subagents.modal.systemPromptRequired'),
              },
            ]}
          >
            <TextArea rows={6} placeholder={t('tenant.subagents.modal.systemPromptPlaceholder')} />
          </Form.Item>

          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="model"
              label={t('tenant.subagents.modal.model')}
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

            <Form.Item label={t('tenant.subagents.modal.color')}>
              <div className="flex items-center gap-2">
                <ColorPicker
                  value={selectedColor}
                  onChange={handleColorChange}
                  presets={[{ label: 'Presets', colors: COLOR_PRESETS }]}
                />
                <div
                  className="w-8 h-8 rounded-lg border border-slate-200 dark:border-slate-600"
                  style={{ backgroundColor: selectedColor }}
                />
              </div>
            </Form.Item>
          </div>
        </div>
      ),
    },
    {
      key: 'trigger',
      label: t('tenant.subagents.modal.triggerConfig'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="trigger_description"
            label={t('tenant.subagents.modal.triggerDescription')}
            rules={[
              {
                required: true,
                message: t('tenant.subagents.modal.triggerDescriptionRequired'),
              },
            ]}
          >
            <TextArea
              rows={3}
              placeholder={t('tenant.subagents.modal.triggerDescriptionPlaceholder')}
            />
          </Form.Item>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.subagents.modal.triggerKeywords')}
            </label>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder={t('tenant.subagents.modal.addKeyword')}
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
                {t('common.add')}
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {keywords.map((keyword, idx) => (
                <Tag
                  key={idx}
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
                  {t('tenant.subagents.modal.noKeywords')}
                </span>
              )}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.subagents.modal.triggerExamples')}
            </label>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder={t('tenant.subagents.modal.addExample')}
                value={exampleInput}
                onChange={(e) => {
                  setExampleInput(e.target.value);
                }}
                onPressEnter={handleAddExample}
              />
              <button
                type="button"
                onClick={handleAddExample}
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors"
              >
                {t('common.add')}
              </button>
            </div>
            <div className="space-y-1">
              {examples.map((example, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2 bg-slate-50 dark:bg-slate-800 rounded"
                >
                  <span className="text-sm">{example}</span>
                  <button
                    type="button"
                    onClick={() => {
                      handleRemoveExample(example);
                    }}
                    className="text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
              {examples.length === 0 && (
                <span className="text-sm text-slate-400">
                  {t('tenant.subagents.modal.noExamples')}
                </span>
              )}
            </div>
          </div>

          {/* Keyword Tester */}
          <div className="pt-4 border-t border-slate-200 dark:border-slate-700 mt-4">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.subagents.modal.testKeywords', 'Test Keyword Match')}
            </label>
            <div className="flex gap-2">
              <Input
                placeholder="Enter query to test match..."
                value={testQuery}
                onChange={(e) => {
                  setTestQuery(e.target.value);
                  setTestResult(null); // Clear result on change
                }}
                onPressEnter={handleTestKeyword}
              />
              <button
                type="button"
                onClick={handleTestKeyword}
                className="px-3 py-1 bg-slate-200 dark:bg-slate-700 rounded hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
              >
                {t('common.test', 'Test')}
              </button>
            </div>
            {testResult && (
              <div
                className={`mt-2 text-sm ${
                  testResult.matched ? 'text-green-600 font-medium' : 'text-amber-600'
                }`}
              >
                {testResult.matched
                  ? `✅ Matches keyword: "${testResult.keyword}"`
                  : '⚠️ No exact keyword match found (Note: LLM may still route based on description)'}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'permissions',
      label: t('tenant.subagents.modal.permissions'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="allowed_tools"
            label={t('tenant.subagents.modal.allowedTools')}
            tooltip={t('tenant.subagents.modal.allowedToolsTooltip')}
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
                ...(availableTools || []).map((t) => ({
                  label: t.name,
                  value: t.name,
                  title: t.description,
                })),
              ]}
            />
          </Form.Item>

          <Form.Item
            name="allowed_skills"
            label={t('tenant.subagents.modal.allowedSkills')}
            tooltip={t('tenant.subagents.modal.allowedSkillsTooltip')}
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
            label={t('tenant.subagents.modal.allowedMcpServers', 'MCP Servers')}
            tooltip={t(
              'tenant.subagents.modal.allowedMcpServersTooltip',
              'Select MCP servers this SubAgent can access'
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
              label={t('tenant.subagents.modal.maxTokens')}
              initialValue={4096}
            >
              <InputNumber min={100} max={32000} className="w-full" />
            </Form.Item>

            <Form.Item
              name="temperature"
              label={t('tenant.subagents.modal.temperature')}
              initialValue={0.7}
            >
              <Slider min={0} max={2} step={0.1} />
            </Form.Item>

            <Form.Item
              name="max_iterations"
              label={t('tenant.subagents.modal.maxIterations')}
              initialValue={10}
            >
              <InputNumber min={1} max={50} className="w-full" />
            </Form.Item>
          </div>
        </div>
      ),
    },
    {
      key: 'spawn_policy',
      label: t('tenant.subagents.modal.spawnPolicy', 'Spawn Policy'),
      children: (
        <div className="space-y-4">
          <div className="mb-4 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t(
                'tenant.subagents.modal.spawnPolicyDescription',
                'Configure how this SubAgent can spawn and be spawned by other agents.'
              )}
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Form.Item label={t('tenant.subagents.modal.maxDepth', 'Max Depth')}>
              <InputNumber
                min={0}
                max={32}
                value={spawnPolicy.max_depth}
                onChange={(v) => {
                  setSpawnPolicy({ ...spawnPolicy, max_depth: v ?? 2 });
                }}
                className="w-full"
              />
              <span className="text-xs text-slate-500">
                {t('tenant.subagents.modal.maxDepthHint', 'Maximum nesting depth (0 = no nesting)')}
              </span>
            </Form.Item>

            <Form.Item label={t('tenant.subagents.modal.maxActiveRuns', 'Max Active Runs')}>
              <InputNumber
                min={1}
                max={32}
                value={spawnPolicy.max_active_runs}
                onChange={(v) => {
                  setSpawnPolicy({ ...spawnPolicy, max_active_runs: v ?? 16 });
                }}
                className="w-full"
              />
              <span className="text-xs text-slate-500">
                {t(
                  'tenant.subagents.modal.maxActiveRunsHint',
                  'Global cap on concurrent SubAgent runs'
                )}
              </span>
            </Form.Item>

            <Form.Item
              label={t('tenant.subagents.modal.maxChildren', 'Max Children per Requester')}
            >
              <InputNumber
                min={1}
                max={16}
                value={spawnPolicy.max_children_per_requester}
                onChange={(v) => {
                  setSpawnPolicy({ ...spawnPolicy, max_children_per_requester: v ?? 8 });
                }}
                className="w-full"
              />
              <span className="text-xs text-slate-500">
                {t('tenant.subagents.modal.maxChildrenHint', 'Per-parent cap on active children')}
              </span>
            </Form.Item>
          </div>

          <Form.Item label={t('tenant.subagents.modal.allowedSubagents', 'Allowed SubAgents')}>
            <Select
              mode="multiple"
              placeholder={t(
                'tenant.subagents.modal.allowedSubagentsPlaceholder',
                'Select SubAgents that can spawn this one (empty = all)'
              )}
              value={spawnPolicy.allowed_subagents || []}
              onChange={(v) => {
                setSpawnPolicy({ ...spawnPolicy, allowed_subagents: v.length > 0 ? v : null });
              }}
              filterOption={(input, option) =>
                (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
              }
              options={subagents
                .filter((sa) => sa.id !== subagent?.id)
                .map((sa) => ({
                  label: sa.display_name || sa.name,
                  value: sa.id,
                }))}
            />
          </Form.Item>
        </div>
      ),
    },
    {
      key: 'tool_policy',
      label: t('tenant.subagents.modal.toolPolicy', 'Tool Policy'),
      children: (
        <div className="space-y-4">
          <div className="mb-4 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t(
                'tenant.subagents.modal.toolPolicyDescription',
                'Configure which tools this SubAgent can use. Precedence determines how conflicts are resolved.'
              )}
            </p>
          </div>

          <Form.Item label={t('tenant.subagents.modal.precedence', 'Precedence')}>
            <Radio.Group
              value={toolPolicy.precedence}
              onChange={(e) => {
                setToolPolicy({ ...toolPolicy, precedence: e.target.value });
              }}
            >
              <Radio.Button value="deny_first">
                {t('tenant.subagents.modal.denyFirst', 'Deny First')}
              </Radio.Button>
              <Radio.Button value="allow_first">
                {t('tenant.subagents.modal.allowFirst', 'Allow First')}
              </Radio.Button>
            </Radio.Group>
            <div className="mt-2 text-xs text-slate-500">
              {toolPolicy.precedence === 'deny_first'
                ? t(
                    'tenant.subagents.modal.denyFirstHint',
                    'Deny wins on conflict; unlisted tools are allowed.'
                  )
                : t(
                    'tenant.subagents.modal.allowFirstHint',
                    'Allow wins on conflict; unlisted tools are allowed unless in deny.'
                  )}
            </div>
          </Form.Item>

          <div className="grid grid-cols-2 gap-4">
            <Form.Item label={t('tenant.subagents.modal.allowList', 'Allow List')}>
              <Select
                mode="multiple"
                placeholder={t(
                  'tenant.subagents.modal.allowListPlaceholder',
                  'Tools to explicitly allow'
                )}
                value={toolPolicy.allow}
                onChange={(v) => {
                  setToolPolicy({ ...toolPolicy, allow: v });
                }}
                filterOption={(input, option) =>
                  (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
                }
                options={[
                  { label: 'All Tools (*)', value: '*' },
                  ...(availableTools || []).map((t) => ({
                    label: t.name,
                    value: t.name,
                    title: t.description,
                  })),
                ]}
              />
            </Form.Item>

            <Form.Item label={t('tenant.subagents.modal.denyList', 'Deny List')}>
              <Select
                mode="multiple"
                placeholder={t(
                  'tenant.subagents.modal.denyListPlaceholder',
                  'Tools to explicitly deny'
                )}
                value={toolPolicy.deny}
                onChange={(v) => {
                  setToolPolicy({ ...toolPolicy, deny: v });
                }}
                filterOption={(input, option) =>
                  (option?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())
                }
                options={(availableTools || []).map((t) => ({
                  label: t.name,
                  value: t.name,
                  title: t.description,
                }))}
              />
            </Form.Item>
          </div>

          {/* Tool Policy Preview */}
          <div className="mt-4 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg">
            <div className="text-sm font-medium mb-2">
              {t('tenant.subagents.modal.policyPreview', 'Policy Preview')}
            </div>
            <div className="text-xs text-slate-600 dark:text-slate-400">
              {(() => {
                const allowedCount = availableTools.filter((t) => {
                  if (toolPolicy.precedence === 'deny_first') {
                    return !toolPolicy.deny.includes(t.name);
                  }
                  if (toolPolicy.allow.length > 0 && !toolPolicy.allow.includes('*')) {
                    return toolPolicy.allow.includes(t.name) && !toolPolicy.deny.includes(t.name);
                  }
                  return !toolPolicy.deny.includes(t.name);
                }).length;
                return t('tenant.subagents.modal.toolsAllowed', {
                  count: allowedCount,
                  total: availableTools.length,
                  defaultValue: `${allowedCount} of ${availableTools.length} tools allowed`,
                });
              })()}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'identity',
      label: t('tenant.subagents.modal.identity', 'Identity'),
      children: (
        <div className="space-y-4">
          <div className="mb-4 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t(
                'tenant.subagents.modal.identityDescription',
                'Configure the identity this SubAgent uses when spawning child agents. Leave empty to use defaults.'
              )}
            </p>
          </div>

          <Form.Item
            label={t('tenant.subagents.modal.identityDescription', 'Identity Description')}
          >
            <TextArea
              rows={3}
              placeholder={t(
                'tenant.subagents.modal.identityDescriptionPlaceholder',
                "Describe this SubAgent's role and personality when spawning child agents..."
              )}
              value={identityDescription}
              onChange={(e) => {
                setIdentityDescription(e.target.value);
              }}
            />
          </Form.Item>

          <Form.Item label={t('tenant.subagents.modal.metadata', 'Metadata')}>
            <div className="space-y-2">
              {identityMetadata.map(([key, value], index) => (
                <div key={index} className="flex gap-2 items-center">
                  <Input
                    placeholder={t('tenant.subagents.modal.metadataKey', 'Key')}
                    value={key}
                    onChange={(e) => {
                      const newMeta = [...identityMetadata];
                      newMeta[index] = [e.target.value, value];
                      setIdentityMetadata(newMeta);
                    }}
                    className="flex-1"
                  />
                  <Input
                    placeholder={t('tenant.subagents.modal.metadataValue', 'Value')}
                    value={value}
                    onChange={(e) => {
                      const newMeta = [...identityMetadata];
                      newMeta[index] = [key, e.target.value];
                      setIdentityMetadata(newMeta);
                    }}
                    className="flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setIdentityMetadata(identityMetadata.filter((_, i) => i !== index));
                    }}
                    className="p-2 text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => {
                  setIdentityMetadata([...identityMetadata, ['', '']]);
                }}
                className="text-sm text-primary-600 hover:text-primary-700"
              >
                + {t('tenant.subagents.modal.addMetadata', 'Add Metadata')}
              </button>
            </div>
          </Form.Item>
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={
        isEditMode ? t('tenant.subagents.modal.editTitle') : t('tenant.subagents.modal.createTitle')
      }
      open={isOpen}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={isEditMode ? t('common.save') : t('common.create')}
      cancelText={t('common.cancel')}
      confirmLoading={isSubmitting}
      width={700}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Form>
    </Modal>
  );
};

export default SubAgentModal;
