/**
 * Skill Modal Component
 *
 * Modal for creating and editing Skills with tabbed form layout.
 */

import React, { useCallback, useEffect, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Tabs, Tag, message, InputNumber } from 'antd';

import { useSkillStore, useSkillSubmitting } from '../../stores/skill';

import type { SkillResponse, SkillCreate, SkillUpdate, TriggerPattern } from '../../types/agent';

const { TextArea } = Input;
const { Option } = Select;

interface SkillModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  skill: SkillResponse | null;
}

// Available trigger types
const TRIGGER_TYPES = [
  { value: 'keyword', label: 'Keyword' },
  { value: 'semantic', label: 'Semantic' },
  { value: 'hybrid', label: 'Hybrid' },
];

export const SkillModal: React.FC<SkillModalProps> = ({ isOpen, onClose, onSuccess, skill }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState('basic');
  const [patterns, setPatterns] = useState<TriggerPattern[]>([]);
  const [patternInput, setPatternInput] = useState('');
  const [patternWeight, setPatternWeight] = useState(1.0);
  const [patternExamples, setPatternExamples] = useState<string[]>([]);
  const [currentExample, setCurrentExample] = useState('');
  const [tools, setTools] = useState<string[]>([]);
  const [toolInput, setToolInput] = useState('');

  const isSubmitting = useSkillSubmitting();
  const { createSkill, updateSkill } = useSkillStore();

  const isEditMode = !!skill;

  // Track previous state to only update when values actually change
  const prevSkillRef = useRef<SkillResponse | null>(null);
  const prevIsOpenRef = useRef(false);

  // Reset form when modal opens/closes or skill changes
  useEffect(() => {
    const skillChanged = prevSkillRef.current?.id !== skill?.id;
    const openStateChanged = prevIsOpenRef.current !== isOpen;

    if (isOpen && (skillChanged || openStateChanged)) {
      if (skill) {
        // Edit mode - populate form
        form.setFieldsValue({
          name: skill.name,
          description: skill.description,
          trigger_type: skill.trigger_type,
          prompt_template: skill.prompt_template,
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

    prevSkillRef.current = skill || null;
    prevIsOpenRef.current = isOpen;
  }, [isOpen, skill, form]);

  // Update patterns and tools when skill changes (separate effect)
  useEffect(() => {
    const skillChanged = prevSkillRef.current?.id !== skill?.id;

    if (isOpen && skill && skillChanged) {
      // Defer all state updates to avoid synchronous setState in effect
      setTimeout(() => {
        setPatterns(skill.trigger_patterns);
        setTools(skill.tools);
        setPatternInput('');
        setPatternWeight(1.0);
        setPatternExamples([]);
        setCurrentExample('');
        setToolInput('');
      }, 0);
    } else if (isOpen && !skill && skillChanged) {
      setTimeout(() => {
        setPatterns([]);
        setTools([]);
        setPatternInput('');
        setPatternWeight(1.0);
        setPatternExamples([]);
        setCurrentExample('');
        setToolInput('');
      }, 0);
    }
  }, [isOpen, skill]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();

      // Validate that at least one pattern exists
      if (patterns.length === 0) {
        message.error(t('tenant.skills.modal.requirePatterns'));
        setActiveTab('trigger');
        return;
      }

      // Validate that at least one tool exists
      if (tools.length === 0) {
        message.error(t('tenant.skills.modal.requireTools'));
        setActiveTab('tools');
        return;
      }

      const data: SkillCreate | SkillUpdate = {
        name: values.name,
        description: values.description,
        trigger_type: values.trigger_type || 'keyword',
        trigger_patterns: patterns,
        tools: tools,
        prompt_template: values.prompt_template || undefined,
      };

      if (isEditMode && skill) {
        await updateSkill(skill.id, data);
        message.success(t('tenant.skills.updateSuccess'));
      } else {
        await createSkill(data as SkillCreate);
        message.success(t('tenant.skills.createSuccess'));
      }

      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: Array<{ name?: string[] | undefined }> | undefined };
      if (err.errorFields) {
        // Form validation error - switch to the tab with the error
        const firstErrorField = err.errorFields[0]?.name?.[0];
        if (firstErrorField && ['name', 'description', 'trigger_type'].includes(firstErrorField)) {
          setActiveTab('basic');
        }
      }
      // API errors handled by store
    }
  }, [form, isEditMode, skill, patterns, tools, createSkill, updateSkill, onSuccess, t]);

  // Handle pattern addition
  const handleAddPattern = useCallback(() => {
    if (patternInput.trim()) {
      const newPattern: TriggerPattern = {
        pattern: patternInput.trim(),
        weight: patternWeight,
        examples: patternExamples,
      };
      setPatterns([...patterns, newPattern]);
      setPatternInput('');
      setPatternWeight(1.0);
      setPatternExamples([]);
    }
  }, [patternInput, patternWeight, patternExamples, patterns]);

  // Handle pattern removal
  const handleRemovePattern = useCallback(
    (index: number) => {
      setPatterns(patterns.filter((_, idx) => idx !== index));
    },
    [patterns]
  );

  // Handle example addition for current pattern
  const handleAddExample = useCallback(() => {
    if (currentExample.trim() && !patternExamples.includes(currentExample.trim())) {
      setPatternExamples([...patternExamples, currentExample.trim()]);
      setCurrentExample('');
    }
  }, [currentExample, patternExamples]);

  // Handle example removal for current pattern
  const handleRemoveExample = useCallback(
    (example: string) => {
      setPatternExamples(patternExamples.filter((e) => e !== example));
    },
    [patternExamples]
  );

  // Handle tool addition
  const handleAddTool = useCallback(() => {
    if (toolInput.trim() && !tools.includes(toolInput.trim())) {
      setTools([...tools, toolInput.trim()]);
      setToolInput('');
    }
  }, [toolInput, tools]);

  // Handle tool removal
  const handleRemoveTool = useCallback(
    (tool: string) => {
      setTools(tools.filter((t) => t !== tool));
    },
    [tools]
  );

  // Tab items
  const tabItems = [
    {
      key: 'basic',
      label: t('tenant.skills.modal.basicInfo'),
      children: (
        <div className="space-y-4">
          <Form.Item
            name="name"
            label={t('tenant.skills.modal.name')}
            rules={[
              {
                required: true,
                message: t('tenant.skills.modal.nameRequired'),
              },
              {
                pattern: /^[a-zA-Z][a-zA-Z0-9_-]*$/,
                message: t('tenant.skills.modal.namePattern'),
              },
            ]}
          >
            <Input placeholder="e.g., data_analysis_skill" disabled={isEditMode} />
          </Form.Item>

          <Form.Item
            name="description"
            label={t('tenant.skills.modal.description')}
            rules={[
              {
                required: true,
                message: t('tenant.skills.modal.descriptionRequired'),
              },
            ]}
          >
            <TextArea rows={4} placeholder={t('tenant.skills.modal.descriptionPlaceholder')} />
          </Form.Item>

          <Form.Item
            name="trigger_type"
            label={t('tenant.skills.modal.triggerType')}
            rules={[
              {
                required: true,
                message: t('tenant.skills.modal.triggerTypeRequired'),
              },
            ]}
            initialValue="keyword"
          >
            <Select>
              {TRIGGER_TYPES.map((type) => (
                <Option key={type.value} value={type.value}>
                  {type.label}
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="prompt_template"
            label={t('tenant.skills.modal.promptTemplate')}
            tooltip={t('tenant.skills.modal.promptTemplateTooltip')}
          >
            <TextArea rows={6} placeholder={t('tenant.skills.modal.promptTemplatePlaceholder')} />
          </Form.Item>
        </div>
      ),
    },
    {
      key: 'trigger',
      label: t('tenant.skills.modal.triggerConfig'),
      children: (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.skills.modal.triggerPatterns')}
              <span className="text-red-500 ml-1">*</span>
            </label>

            {/* Current Pattern Builder */}
            <div className="mb-4 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-slate-600 dark:text-slate-400 mb-1">
                    {t('tenant.skills.modal.patternText')}
                  </label>
                  <Input
                    placeholder={t('tenant.skills.modal.addPattern')}
                    value={patternInput}
                    onChange={(e) => {
                      setPatternInput(e.target.value);
                    }}
                  />
                </div>

                <div>
                  <label className="block text-sm text-slate-600 dark:text-slate-400 mb-1">
                    {t('tenant.skills.modal.patternWeight')} ({patternWeight.toFixed(1)})
                  </label>
                  <InputNumber
                    min={0}
                    max={1}
                    step={0.1}
                    value={patternWeight}
                    onChange={(val) => {
                      setPatternWeight(val || 1.0);
                    }}
                    className="w-full"
                  />
                </div>

                <div>
                  <label className="block text-sm text-slate-600 dark:text-slate-400 mb-1">
                    {t('tenant.skills.modal.patternExamples')}
                  </label>
                  <div className="flex gap-2 mb-2">
                    <Input
                      placeholder={t('tenant.skills.modal.addExample')}
                      value={currentExample}
                      onChange={(e) => {
                        setCurrentExample(e.target.value);
                      }}
                      onPressEnter={handleAddExample}
                    />
                    <button
                      type="button"
                      onClick={handleAddExample}
                      className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors whitespace-nowrap"
                    >
                      {t('common.add')}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {patternExamples.map((example, idx) => (
                      <Tag
                        key={idx}
                        closable
                        onClose={() => {
                          handleRemoveExample(example);
                        }}
                        className="px-2 py-1"
                      >
                        {example}
                      </Tag>
                    ))}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleAddPattern}
                  disabled={!patternInput.trim()}
                  className="w-full px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors disabled:bg-slate-300 disabled:cursor-not-allowed"
                >
                  {t('tenant.skills.modal.addPatternButton')}
                </button>
              </div>
            </div>

            {/* Existing Patterns List */}
            <div className="space-y-2">
              {patterns.map((pattern, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-white dark:bg-slate-700 rounded border border-slate-200 dark:border-slate-600"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <div className="font-medium text-slate-900 dark:text-slate-100">
                        {pattern.pattern}
                      </div>
                      <div className="text-sm text-slate-500 dark:text-slate-400">
                        {t('tenant.skills.modal.weight')}: {pattern.weight.toFixed(1)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        handleRemovePattern(idx);
                      }}
                      className="text-slate-400 hover:text-red-500 transition-colors"
                    >
                      <span className="material-symbols-outlined text-lg">close</span>
                    </button>
                  </div>
                  {pattern.examples && pattern.examples.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {pattern.examples.map((example, exIdx) => (
                        <Tag key={exIdx} className="text-xs">
                          {example}
                        </Tag>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {patterns.length === 0 && (
                <div className="text-center py-8 text-slate-400">
                  {t('tenant.skills.modal.noPatterns')}
                </div>
              )}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'tools',
      label: t('tenant.skills.modal.tools'),
      children: (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.skills.modal.allowedTools')}
              <span className="text-red-500 ml-1">*</span>
            </label>
            <div className="flex gap-2 mb-3">
              <Input
                placeholder={t('tenant.skills.modal.addTool')}
                value={toolInput}
                onChange={(e) => {
                  setToolInput(e.target.value);
                }}
                onPressEnter={handleAddTool}
              />
              <button
                type="button"
                onClick={handleAddTool}
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors whitespace-nowrap"
              >
                {t('common.add')}
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {tools.map((tool, idx) => (
                <Tag
                  key={idx}
                  closable
                  onClose={() => {
                    handleRemoveTool(tool);
                  }}
                  className="px-3 py-1.5 text-sm"
                >
                  {tool}
                </Tag>
              ))}
              {tools.length === 0 && (
                <div className="text-center w-full py-8 text-slate-400">
                  {t('tenant.skills.modal.noTools')}
                </div>
              )}
            </div>
          </div>

          <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <div className="flex items-start gap-2">
              <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-lg mt-0.5">
                info
              </span>
              <div className="text-sm text-blue-700 dark:text-blue-300">
                {t('tenant.skills.modal.toolsHint')}
              </div>
            </div>
          </div>
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={isEditMode ? t('tenant.skills.modal.editTitle') : t('tenant.skills.modal.createTitle')}
      open={isOpen}
      onCancel={onClose}
      onOk={handleSubmit}
      okText={isEditMode ? t('common.save') : t('common.create')}
      cancelText={t('common.cancel')}
      confirmLoading={isSubmitting}
      width={800}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Form>
    </Modal>
  );
};

export default SkillModal;
