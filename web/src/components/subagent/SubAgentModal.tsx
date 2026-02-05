/**
 * SubAgent Modal Component
 *
 * Modal for creating and editing SubAgents with tabbed form layout.
 */

import React, { useCallback, useEffect, useState, useRef } from "react";

import { useTranslation } from "react-i18next";

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
} from "antd";

import { useSubAgentStore, useSubAgentSubmitting } from "../../stores/subagent";

import type {
  SubAgentResponse,
  SubAgentCreate,
  SubAgentUpdate,
} from "../../types/agent";
import type { Color } from "antd/es/color-picker";

const { TextArea } = Input;
const { Option } = Select;

interface SubAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  subagent: SubAgentResponse | null;
}

// Available LLM models
const LLM_MODELS = [
  { value: "inherit", label: "Inherit from Tenant Config" },
  { value: "qwen-max", label: "Qwen Max" },
  { value: "qwen-plus", label: "Qwen Plus" },
  { value: "qwen-turbo", label: "Qwen Turbo" },
  { value: "gpt-4", label: "GPT-4" },
  { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
  { value: "claude-3-opus", label: "Claude 3 Opus" },
  { value: "claude-3-sonnet", label: "Claude 3 Sonnet" },
  { value: "gemini-pro", label: "Gemini Pro" },
  { value: "deepseek-chat", label: "Deepseek Chat" },
];

// Color presets
const COLOR_PRESETS = [
  "#3B82F6", // Blue
  "#10B981", // Green
  "#F59E0B", // Yellow
  "#EF4444", // Red
  "#8B5CF6", // Purple
  "#EC4899", // Pink
  "#06B6D4", // Cyan
  "#F97316", // Orange
];

export const SubAgentModal: React.FC<SubAgentModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  subagent,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState("basic");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [examples, setExamples] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState("");
  const [exampleInput, setExampleInput] = useState("");
  const [selectedColor, setSelectedColor] = useState("#3B82F6");

  const isSubmitting = useSubAgentSubmitting();
  const { createSubAgent, updateSubAgent } = useSubAgentStore();

  const isEditMode = !!subagent;

  // Track previous state to only update when values actually change
  const prevSubagentRef = useRef<SubAgentResponse | null>(null);
  const prevIsOpenRef = useRef(false);

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
          allowed_tools: subagent.allowed_tools.join(", "),
          allowed_skills: subagent.allowed_skills.join(", "),
        });
      } else {
        // Create mode - reset form
        form.resetFields();
      }
      // Defer tab update to avoid synchronous setState in effect
      if (openStateChanged) {
        setTimeout(() => setActiveTab("basic"), 0);
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
      }, 0);
    } else if (isOpen && !subagent && subagentChanged) {
      setTimeout(() => {
        setKeywords([]);
        setExamples([]);
        setSelectedColor("#3B82F6");
      }, 0);
    }
  }, [isOpen, subagent]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();

      // Parse tools and skills from comma-separated string
      const parseList = (str: string | undefined): string[] => {
        if (!str) return [];
        return str
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      };

      const data: SubAgentCreate | SubAgentUpdate = {
        name: values.name,
        display_name: values.display_name,
        system_prompt: values.system_prompt,
        trigger_description: values.trigger_description,
        trigger_keywords: keywords,
        trigger_examples: examples,
        model: values.model || "inherit",
        color: selectedColor,
        max_tokens: values.max_tokens || 4096,
        temperature: values.temperature ?? 0.7,
        max_iterations: values.max_iterations || 10,
        allowed_tools: parseList(values.allowed_tools) || ["*"],
        allowed_skills: parseList(values.allowed_skills),
      };

      if (isEditMode && subagent) {
        await updateSubAgent(subagent.id, data);
        message.success(t("tenant.subagents.updateSuccess"));
      } else {
        await createSubAgent(data as SubAgentCreate);
        message.success(t("tenant.subagents.createSuccess"));
      }

      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: Array<{ name?: string[] }> };
      if (err.errorFields) {
        // Form validation error - switch to the tab with the error
        const firstErrorField = err.errorFields[0]?.name?.[0];
        if (firstErrorField) {
          if (
            ["name", "display_name", "system_prompt", "model"].includes(
              firstErrorField
            )
          ) {
            setActiveTab("basic");
          } else if (["trigger_description"].includes(firstErrorField)) {
            setActiveTab("trigger");
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
    createSubAgent,
    updateSubAgent,
    onSuccess,
    t,
  ]);

  // Handle keyword addition
  const handleAddKeyword = useCallback(() => {
    if (keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
      setKeywords([...keywords, keywordInput.trim()]);
      setKeywordInput("");
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
      setExampleInput("");
    }
  }, [exampleInput, examples]);

  // Handle example removal
  const handleRemoveExample = useCallback(
    (example: string) => {
      setExamples(examples.filter((e) => e !== example));
    },
    [examples]
  );

  // Handle color change
  const handleColorChange = useCallback((color: Color) => {
    setSelectedColor(color.toHexString());
  }, []);

  // Tab items
  const tabItems = [
    {
      key: "basic",
      label: t("tenant.subagents.modal.basicInfo"),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="name"
            label={t("tenant.subagents.modal.name")}
            rules={[
              {
                required: true,
                message: t("tenant.subagents.modal.nameRequired"),
              },
              {
                pattern: /^[a-z][a-z0-9_]*$/,
                message: t("tenant.subagents.modal.namePattern"),
              },
            ]}
          >
            <Input placeholder="e.g., code_reviewer" disabled={isEditMode} />
          </Form.Item>

          <Form.Item
            name="display_name"
            label={t("tenant.subagents.modal.displayName")}
            rules={[
              {
                required: true,
                message: t("tenant.subagents.modal.displayNameRequired"),
              },
            ]}
          >
            <Input placeholder="e.g., Code Reviewer" />
          </Form.Item>

          <Form.Item
            name="system_prompt"
            label={t("tenant.subagents.modal.systemPrompt")}
            rules={[
              {
                required: true,
                message: t("tenant.subagents.modal.systemPromptRequired"),
              },
            ]}
          >
            <TextArea
              rows={6}
              placeholder={t("tenant.subagents.modal.systemPromptPlaceholder")}
            />
          </Form.Item>

          <div className="grid grid-cols-2 gap-4">
            <Form.Item
              name="model"
              label={t("tenant.subagents.modal.model")}
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

            <Form.Item label={t("tenant.subagents.modal.color")}>
              <div className="flex items-center gap-2">
                <ColorPicker
                  value={selectedColor}
                  onChange={handleColorChange}
                  presets={[{ label: "Presets", colors: COLOR_PRESETS }]}
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
      key: "trigger",
      label: t("tenant.subagents.modal.triggerConfig"),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="trigger_description"
            label={t("tenant.subagents.modal.triggerDescription")}
            rules={[
              {
                required: true,
                message: t("tenant.subagents.modal.triggerDescriptionRequired"),
              },
            ]}
          >
            <TextArea
              rows={3}
              placeholder={t(
                "tenant.subagents.modal.triggerDescriptionPlaceholder"
              )}
            />
          </Form.Item>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t("tenant.subagents.modal.triggerKeywords")}
            </label>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder={t("tenant.subagents.modal.addKeyword")}
                value={keywordInput}
                onChange={(e) => setKeywordInput(e.target.value)}
                onPressEnter={handleAddKeyword}
              />
              <button
                type="button"
                onClick={handleAddKeyword}
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors"
              >
                {t("common.add")}
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {keywords.map((keyword, idx) => (
                <Tag
                  key={idx}
                  closable
                  onClose={() => handleRemoveKeyword(keyword)}
                  className="px-2 py-1"
                >
                  {keyword}
                </Tag>
              ))}
              {keywords.length === 0 && (
                <span className="text-sm text-slate-400">
                  {t("tenant.subagents.modal.noKeywords")}
                </span>
              )}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t("tenant.subagents.modal.triggerExamples")}
            </label>
            <div className="flex gap-2 mb-2">
              <Input
                placeholder={t("tenant.subagents.modal.addExample")}
                value={exampleInput}
                onChange={(e) => setExampleInput(e.target.value)}
                onPressEnter={handleAddExample}
              />
              <button
                type="button"
                onClick={handleAddExample}
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors"
              >
                {t("common.add")}
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
                    onClick={() => handleRemoveExample(example)}
                    className="text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <span className="material-symbols-outlined text-lg">
                      close
                    </span>
                  </button>
                </div>
              ))}
              {examples.length === 0 && (
                <span className="text-sm text-slate-400">
                  {t("tenant.subagents.modal.noExamples")}
                </span>
              )}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "permissions",
      label: t("tenant.subagents.modal.permissions"),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="allowed_tools"
            label={t("tenant.subagents.modal.allowedTools")}
            tooltip={t("tenant.subagents.modal.allowedToolsTooltip")}
            initialValue="*"
          >
            <Input placeholder="* (all) or tool1, tool2, tool3" />
          </Form.Item>

          <Form.Item
            name="allowed_skills"
            label={t("tenant.subagents.modal.allowedSkills")}
            tooltip={t("tenant.subagents.modal.allowedSkillsTooltip")}
          >
            <Input placeholder="skill1, skill2 (leave empty for none)" />
          </Form.Item>

          <div className="grid grid-cols-3 gap-4">
            <Form.Item
              name="max_tokens"
              label={t("tenant.subagents.modal.maxTokens")}
              initialValue={4096}
            >
              <InputNumber min={100} max={32000} className="w-full" />
            </Form.Item>

            <Form.Item
              name="temperature"
              label={t("tenant.subagents.modal.temperature")}
              initialValue={0.7}
            >
              <Slider min={0} max={2} step={0.1} />
            </Form.Item>

            <Form.Item
              name="max_iterations"
              label={t("tenant.subagents.modal.maxIterations")}
              initialValue={10}
            >
              <InputNumber min={1} max={50} className="w-full" />
            </Form.Item>
          </div>
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={
        isEditMode
          ? t("tenant.subagents.modal.editTitle")
          : t("tenant.subagents.modal.createTitle")
      }
      open={isOpen}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={isEditMode ? t("common.save") : t("common.create")}
      cancelText={t("common.cancel")}
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
