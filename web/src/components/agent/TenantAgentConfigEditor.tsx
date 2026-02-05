/**
 * Tenant Agent Configuration Editor Component (T101, T089)
 *
 * Modal form for editing tenant-level agent configuration.
 * Only accessible to tenant administrators (FR-022).
 *
 * Features:
 * - Edit all configurable agent settings
 * - Input validation with error display
 * - Confirm before saving changes
 * - Loading states during save
 * - Success/error notifications
 * - Cancel with confirmation if changes made
 *
 * Access Control:
 * - Only tenant admins can access
 * - Returns 403 Forbidden for non-admin users
 */

import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Spin,
  Space,
  Tag,
  Typography,
  message,
} from "antd";

import {
  agentConfigService,
  TenantAgentConfigError,
} from "@/services/agentConfigService";

import type {
  TenantAgentConfig,
  UpdateTenantAgentConfigRequest,
} from "@/types/agent";

const { Option } = Select;
const { TextArea } = Input;
const { Text } = Typography;

interface TenantAgentConfigEditorProps {
  /**
   * Tenant ID to edit configuration for
   */
  tenantId: string;

  /**
   * Whether the modal is open
   */
  open: boolean;

  /**
   * Callback when modal is closed
   */
  onClose: () => void;

  /**
   * Callback after successful save
   * Parent should reload config in view component
   */
  onSave?: () => void;

  /**
   * Optional initial config to populate form
   * If not provided, will fetch from API
   */
  initialConfig?: TenantAgentConfig;
}

/**
 * Parse tool list from comma-separated string
 */
function parseToolList(value: string | undefined): string[] {
  if (!value || !value.trim()) {
    return [];
  }
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Format tool list as comma-separated string
 */
function formatToolList(tools: string[]): string {
  return tools.join(", ");
}

/**
 * Available LLM models for selection
 * In production, this could be fetched from API
 */
const AVAILABLE_LLM_MODELS = [
  { value: "default", label: "Default (System Setting)" },
  { value: "gpt-4", label: "GPT-4" },
  { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
  { value: "claude-3-opus", label: "Claude 3 Opus" },
  { value: "claude-3-sonnet", label: "Claude 3 Sonnet" },
  { value: "gemini-pro", label: "Gemini Pro" },
];

/**
 * Component for editing tenant agent configuration
 */
export function TenantAgentConfigEditor({
  tenantId,
  open,
  onClose,
  onSave,
  initialConfig,
}: TenantAgentConfigEditorProps) {
  // Form values include string versions of tool lists (comma-separated)
  interface FormValues {
    llm_model?: string;
    llm_temperature?: number;
    pattern_learning_enabled?: boolean;
    multi_level_thinking_enabled?: boolean;
    max_work_plan_steps?: number;
    tool_timeout_seconds?: number;
    enabled_tools: string;
    disabled_tools: string;
  }

  const [form] = Form.useForm<FormValues>();

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  // Load initial config if not provided
  useEffect(() => {
    if (!open) return;

    const loadConfig = async () => {
      setLoading(true);
      setError(null);
      try {
        const config =
          initialConfig || (await agentConfigService.getConfig(tenantId));
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
        const errorMsg =
          err instanceof TenantAgentConfigError
            ? err.message
            : "Failed to load configuration";
        setError(errorMsg);
        if (err instanceof TenantAgentConfigError && err.statusCode === 403) {
          message.error(
            "You do not have permission to edit tenant configuration"
          );
          onClose();
        }
      } finally {
        setLoading(false);
      }
    };

    loadConfig();
  }, [open, tenantId, initialConfig, form, onClose]);

  // Track form changes
  const onValuesChange = useCallback(() => {
    setHasChanges(true);
  }, []);

  // Handle save
  const handleSave = async () => {
    try {
      const values = (await form.validateFields()) as FormValues;
      setSaving(true);
      setError(null);

      // Convert tool strings to arrays
      const request: UpdateTenantAgentConfigRequest = {
        llm_model: values.llm_model,
        llm_temperature: values.llm_temperature,
        pattern_learning_enabled: values.pattern_learning_enabled,
        multi_level_thinking_enabled: values.multi_level_thinking_enabled,
        max_work_plan_steps: values.max_work_plan_steps,
        tool_timeout_seconds: values.tool_timeout_seconds,
        enabled_tools: parseToolList(values.enabled_tools),
        disabled_tools: parseToolList(values.disabled_tools),
      };

      // Remove undefined values
      Object.keys(request).forEach((key) => {
        if (
          request[key as keyof UpdateTenantAgentConfigRequest] === undefined
        ) {
          delete request[key as keyof UpdateTenantAgentConfigRequest];
        }
      });

      await agentConfigService.updateConfig(tenantId, request);

      message.success("Configuration updated successfully");
      setHasChanges(false);
      onSave?.();
      onClose();
    } catch (err) {
      if (err instanceof TenantAgentConfigError) {
        setError(err.message);
        if (err.statusCode === 403) {
          message.error(
            "You do not have permission to edit tenant configuration"
          );
          onClose();
        } else if (err.statusCode === 422) {
          message.error(
            "Invalid configuration values. Please check your inputs."
          );
        }
      } else {
        setError("Failed to save configuration");
        message.error("Failed to save configuration");
      }
    } finally {
      setSaving(false);
    }
  };

  // Handle cancel with confirmation if there are changes
  const handleCancel = () => {
    if (hasChanges) {
      Modal.confirm({
        title: "Discard Changes?",
        content: "You have unsaved changes. Are you sure you want to close?",
        okText: "Discard",
        okButtonProps: { danger: true },
        cancelText: "Keep Editing",
        onOk: onClose,
      });
    } else {
      onClose();
    }
  };

  return (
    <Modal
      title="Edit Agent Configuration"
      open={open}
      onCancel={handleCancel}
      onOk={handleSave}
      okText="Save Changes"
      okButtonProps={{ loading: saving }}
      cancelButtonProps={{ disabled: saving }}
      width={700}
      destroyOnHidden
    >
      {error && (
        <Alert
          type="error"
          message="Error"
          description={error}
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      <Spin spinning={loading}>
        <Form
          form={form}
          layout="vertical"
          onValuesChange={onValuesChange}
          autoComplete="off"
        >
          {/* LLM Settings Section */}
          <Alert
            type="info"
            message="LLM Settings"
            description="Configure the language model used by the agent."
            showIcon
            style={{ marginBottom: 16 }}
          />

          <Form.Item
            label="LLM Model"
            name="llm_model"
            tooltip="The language model to use for agent responses"
          >
            <Select placeholder="Select LLM model">
              {AVAILABLE_LLM_MODELS.map((model) => (
                <Option key={model.value} value={model.value}>
                  {model.label}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            label="Temperature"
            name="llm_temperature"
            tooltip="Controls randomness: 0 = more focused, 2 = more creative"
            rules={[
              { required: true, message: "Temperature is required" },
              {
                type: "number",
                min: 0,
                max: 2,
                message: "Temperature must be between 0 and 2",
              },
            ]}
          >
            <InputNumber
              min={0}
              max={2}
              step={0.1}
              precision={1}
              style={{ width: "100%" }}
              placeholder="0.7"
            />
          </Form.Item>

          {/* Agent Features Section */}
          <Alert
            type="info"
            message="Agent Features"
            description="Enable or disable advanced agent capabilities."
            showIcon
            style={{ marginBottom: 16, marginTop: 16 }}
          />

          <Form.Item
            name="pattern_learning_enabled"
            valuePropName="checked"
            tooltip="Allow the agent to learn from workflow patterns"
          >
            <Checkbox>Enable Pattern Learning</Checkbox>
          </Form.Item>

          <Form.Item
            name="multi_level_thinking_enabled"
            valuePropName="checked"
            tooltip="Enable work-level and task-level thinking for complex queries"
          >
            <Checkbox>Enable Multi-Level Thinking</Checkbox>
          </Form.Item>

          {/* Limits Section */}
          <Alert
            type="info"
            message="Execution Limits"
            description="Configure limits for agent execution."
            showIcon
            style={{ marginBottom: 16, marginTop: 16 }}
          />

          <Form.Item
            label="Max Work Plan Steps"
            name="max_work_plan_steps"
            tooltip="Maximum number of steps in a work plan"
            rules={[
              { required: true, message: "Max steps is required" },
              { type: "number", min: 1, message: "Must be at least 1" },
            ]}
          >
            <InputNumber
              min={1}
              max={50}
              style={{ width: "100%" }}
              placeholder="10"
            />
          </Form.Item>

          <Form.Item
            label="Tool Timeout (seconds)"
            name="tool_timeout_seconds"
            tooltip="Default timeout for tool execution"
            rules={[
              { required: true, message: "Timeout is required" },
              { type: "number", min: 1, message: "Must be at least 1 second" },
            ]}
          >
            <InputNumber
              min={1}
              max={300}
              style={{ width: "100%" }}
              placeholder="30"
            />
          </Form.Item>

          {/* Tool Configuration Section */}
          <Alert
            type="info"
            message="Tool Configuration"
            description="Explicitly enable or disable specific tools. Leave empty to use defaults."
            showIcon
            style={{ marginBottom: 16, marginTop: 16 }}
          />

          <Form.Item
            label="Enabled Tools"
            name="enabled_tools"
            tooltip="Comma-separated list of tools to explicitly enable. Leave empty to enable all."
          >
            <TextArea
              rows={2}
              placeholder="e.g., search, calculator, memory_lookup"
            />
          </Form.Item>

          <Form.Item
            label="Disabled Tools"
            name="disabled_tools"
            tooltip="Comma-separated list of tools to explicitly disable."
          >
            <TextArea rows={2} placeholder="e.g., web_browse, code_execute" />
          </Form.Item>

          {/* Info about available tools */}
          <div style={{ marginTop: 16 }}>
            <Space orientation="vertical" size="small">
              <Text type="secondary">Available tools:</Text>
              <div className="flex flex-wrap gap-1">
                {["search", "memory_lookup", "calculator", "web_browse"].map(
                  (tool) => (
                    <Tag key={tool}>{tool}</Tag>
                  )
                )}
                <Tag>...</Tag>
              </div>
            </Space>
          </div>
        </Form>
      </Spin>
    </Modal>
  );
}

export default TenantAgentConfigEditor;
