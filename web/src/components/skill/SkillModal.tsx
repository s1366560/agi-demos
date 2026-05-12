/**
 * Skill Modal Component
 *
 * Modal for creating and editing Skills with tabbed form layout.
 */

import { useCallback, useEffect, useState, useRef } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Tabs, Tag, message } from 'antd';
import { Info } from 'lucide-react';

import { useSkillStore, useSkillSubmitting } from '../../stores/skill';

import type { SkillResponse, SkillCreate, SkillUpdate } from '../../types/agent';

const { TextArea } = Input;

interface SkillModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  skill: SkillResponse | null;
}

export const SkillModal: FC<SkillModalProps> = ({ isOpen, onClose, onSuccess, skill }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [activeTab, setActiveTab] = useState('basic');
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

  // Update tools when skill changes (separate effect)
  useEffect(() => {
    const skillChanged = prevSkillRef.current?.id !== skill?.id;

    if (isOpen && skill && skillChanged) {
      // Defer all state updates to avoid synchronous setState in effect
      setTimeout(() => {
        setTools(skill.tools);
        setToolInput('');
      }, 0);
    } else if (isOpen && !skill && skillChanged) {
      setTimeout(() => {
        setTools([]);
        setToolInput('');
      }, 0);
    }
  }, [isOpen, skill]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();

      // Validate that at least one tool exists
      if (tools.length === 0) {
        message.error(t('tenant.skills.modal.requireTools'));
        setActiveTab('tools');
        return;
      }

      const data: SkillCreate | SkillUpdate = {
        name: values.name,
        description: values.description,
        tools: tools,
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
        if (firstErrorField && ['name', 'description'].includes(firstErrorField)) {
          setActiveTab('basic');
        }
      }
      // API errors handled by store
    }
  }, [form, isEditMode, skill, tools, createSkill, updateSkill, onSuccess, t]);

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
                className="px-3 py-1 bg-primary-600 text-white rounded hover:bg-primary-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 whitespace-nowrap"
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
              <Info size={18} className="text-blue-600 dark:text-blue-400 mt-0.5" />
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
