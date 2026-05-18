/**
 * Skill Modal Component
 *
 * Modal for creating and editing Skills with tabbed form layout.
 */

import { useCallback, useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Tabs, Tag, message } from 'antd';
import { Info } from 'lucide-react';

import { useSkillStore, useSkillSubmitting } from '../../stores/skill';

import type { SkillResponse, SkillCreate, SkillUpdate } from '../../types/agent';

const { TextArea } = Input;

const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';

const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

type SkillScopeValue = 'tenant' | 'project';

interface SkillFormValues {
  name: string;
  description: string;
  scope: SkillScopeValue;
  project_id?: string;
  full_content?: string;
  metadata?: string;
  license?: string;
  compatibility?: string;
  allowed_tools_raw?: string;
  spec_version?: string;
}

function compact(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function parseMetadata(value: string | undefined): Record<string, unknown> | undefined {
  const trimmed = value?.trim();
  if (!trimmed) {
    return undefined;
  }
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function formatMetadata(metadata: Record<string, unknown> | undefined): string {
  return JSON.stringify(metadata ?? {}, null, 2);
}

interface SkillModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  skill: SkillResponse | null;
}

export const SkillModal: FC<SkillModalProps> = ({ isOpen, onClose, onSuccess, skill }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const scopeValue = Form.useWatch('scope', form) as SkillScopeValue | undefined;
  const [activeTab, setActiveTab] = useState('basic');
  const [tools, setTools] = useState<string[]>([]);
  const [toolInput, setToolInput] = useState('');

  const isSubmitting = useSkillSubmitting();
  const { createSkill, updateSkill } = useSkillStore();

  const isEditMode = !!skill;

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    if (skill) {
      form.setFieldsValue({
        name: skill.name,
        description: skill.description,
        scope: skill.scope === 'project' ? 'project' : 'tenant',
        project_id: skill.project_id ?? undefined,
        full_content: skill.full_content ?? '',
        metadata: formatMetadata(skill.metadata),
        license: skill.license ?? '',
        compatibility: skill.compatibility ?? '',
        allowed_tools_raw: skill.allowed_tools_raw ?? skill.tools.join(' '),
        spec_version: skill.spec_version,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        scope: 'tenant',
        full_content: '',
        metadata: '{}',
        license: '',
        compatibility: '',
        allowed_tools_raw: '',
        spec_version: '1.0',
      });
    }

    const resetTimer = window.setTimeout(() => {
      setActiveTab('basic');
      setToolInput('');
      setTools(skill?.tools ?? []);
    }, 0);

    return () => {
      window.clearTimeout(resetTimer);
    };
  }, [isOpen, skill, form]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = (await form.validateFields()) as SkillFormValues;

      // Validate that at least one tool exists
      if (tools.length === 0) {
        message.error(t('tenant.skills.modal.requireTools'));
        setActiveTab('tools');
        return;
      }

      const metadata = parseMetadata(values.metadata);
      const allowedToolsRaw = compact(values.allowed_tools_raw) ?? tools.join(' ');
      const commonData = {
        name: values.name,
        description: values.description,
        tools,
        full_content: compact(values.full_content),
        metadata,
        license: compact(values.license) ?? null,
        compatibility: compact(values.compatibility) ?? null,
        allowed_tools_raw: allowedToolsRaw,
        spec_version: compact(values.spec_version) ?? '1.0',
      };

      if (skill) {
        await updateSkill(skill.id, commonData as SkillUpdate);
        message.success(t('tenant.skills.updateSuccess'));
      } else {
        const data: SkillCreate = {
          ...commonData,
          scope: values.scope,
          project_id: values.scope === 'project' ? compact(values.project_id) : undefined,
        };
        await createSkill(data);
        message.success(t('tenant.skills.createSuccess'));
      }

      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: Array<{ name?: string[] | undefined }> | undefined };
      if (err.errorFields) {
        // Form validation error - switch to the tab with the error
        const firstErrorField = err.errorFields[0]?.name?.[0];
        if (
          firstErrorField &&
          ['name', 'description', 'scope', 'project_id'].includes(firstErrorField)
        ) {
          setActiveTab('basic');
        } else if (
          firstErrorField &&
          ['full_content', 'allowed_tools_raw'].includes(firstErrorField)
        ) {
          setActiveTab('package');
        } else if (
          firstErrorField &&
          ['metadata', 'license', 'compatibility', 'spec_version'].includes(firstErrorField)
        ) {
          setActiveTab('metadata');
        }
      }
      // API errors handled by store
    }
  }, [form, skill, tools, createSkill, updateSkill, onSuccess, t]);

  // Handle tool addition
  const handleAddTool = useCallback(() => {
    const normalizedTool = toolInput.trim();
    if (normalizedTool) {
      setTools((currentTools) =>
        currentTools.includes(normalizedTool) ? currentTools : [...currentTools, normalizedTool]
      );
      setToolInput('');
    }
  }, [toolInput]);

  // Handle tool removal
  const handleRemoveTool = useCallback((tool: string) => {
    setTools((currentTools) => currentTools.filter((item) => item !== tool));
  }, []);

  const metadataRules = [
    {
      validator: (_: unknown, value: string | undefined) => {
        try {
          const parsed = parseMetadata(value);
          if (parsed !== undefined && (Array.isArray(parsed) || typeof parsed !== 'object')) {
            throw new Error('metadata must be an object');
          }
          return Promise.resolve();
        } catch {
          return Promise.reject(new Error(t('tenant.skills.modal.metadataInvalid')));
        }
      },
    },
  ];

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
                pattern: SKILL_NAME_PATTERN,
                message: t('tenant.skills.modal.namePattern'),
              },
            ]}
          >
            <Input placeholder={t('tenant.skills.modal.namePlaceholder')} disabled={isEditMode} />
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

          <div className="grid gap-4 md:grid-cols-2">
            <Form.Item
              name="scope"
              label={t('tenant.skills.modal.scope')}
              rules={[
                {
                  required: true,
                  message: t('tenant.skills.modal.scopeRequired'),
                },
              ]}
            >
              <Select
                disabled={isEditMode}
                options={[
                  { value: 'tenant', label: t('tenant.skills.modal.scopeTenant') },
                  { value: 'project', label: t('tenant.skills.modal.scopeProject') },
                ]}
              />
            </Form.Item>

            <Form.Item
              name="project_id"
              label={t('tenant.skills.modal.projectId')}
              rules={[
                {
                  required: scopeValue === 'project',
                  message: t('tenant.skills.modal.projectIdRequired'),
                },
              ]}
            >
              <Input
                placeholder={t('tenant.skills.modal.projectIdPlaceholder')}
                disabled={isEditMode || scopeValue !== 'project'}
              />
            </Form.Item>
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
            <label
              htmlFor="skill-tool-input"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.skills.modal.allowedTools')}
              <span className="text-red-500 ml-1">*</span>
            </label>
            <div className="mb-3 flex gap-2">
              <Input
                id="skill-tool-input"
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
                className="inline-flex h-8 items-center justify-center rounded-[4px] bg-[oklch(0.24_0.01_255)] px-3 text-sm font-medium text-[oklch(0.98_0.004_255)] transition-colors hover:bg-[oklch(0.31_0.012_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:bg-[oklch(0.9_0.006_255)] dark:text-[oklch(0.17_0.006_255)] dark:hover:bg-[oklch(0.98_0.004_255)]"
              >
                {t('common.add')}
              </button>
            </div>
            <div className={`min-h-24 rounded-[6px] p-3 ${surface}`}>
              <div className="flex flex-wrap gap-2">
                {tools.map((tool) => (
                  <Tag
                    key={tool}
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
                  <div className="w-full py-6 text-center text-sm text-slate-400">
                    {t('tenant.skills.modal.noTools')}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-[6px] border border-[oklch(0.82_0.05_250)] bg-[oklch(0.97_0.018_250)] p-4 dark:border-[oklch(0.38_0.06_250)] dark:bg-[oklch(0.22_0.03_250)]">
            <div className="flex items-start gap-2">
              <Info
                size={18}
                className="mt-0.5 text-[oklch(0.48_0.16_250)] dark:text-[oklch(0.72_0.12_250)]"
              />
              <div className="text-sm text-[oklch(0.4_0.11_250)] dark:text-[oklch(0.78_0.08_250)]">
                {t('tenant.skills.modal.toolsHint')}
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'package',
      label: t('tenant.skills.modal.package'),
      children: (
        <div className="space-y-4">
          <Form.Item name="allowed_tools_raw" label={t('tenant.skills.modal.allowedToolsRaw')}>
            <Input placeholder={t('tenant.skills.modal.allowedToolsRawPlaceholder')} />
          </Form.Item>
          <Form.Item name="full_content" label={t('tenant.skills.modal.fullContent')}>
            <TextArea
              rows={12}
              placeholder={t('tenant.skills.modal.fullContentPlaceholder')}
              className="font-mono text-xs"
            />
          </Form.Item>
          <div className={`rounded-[6px] p-3 text-sm ${surface} ${mutedText}`}>
            {t('tenant.skills.modal.fullContentHint')}
          </div>
        </div>
      ),
    },
    {
      key: 'metadata',
      label: t('tenant.skills.modal.metadata'),
      children: (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Form.Item name="spec_version" label={t('tenant.skills.modal.specVersion')}>
              <Input placeholder="1.0" />
            </Form.Item>
            <Form.Item name="license" label={t('tenant.skills.modal.license')}>
              <Input placeholder={t('tenant.skills.modal.licensePlaceholder')} />
            </Form.Item>
          </div>
          <Form.Item name="compatibility" label={t('tenant.skills.modal.compatibility')}>
            <TextArea rows={3} placeholder={t('tenant.skills.modal.compatibilityPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="metadata"
            label={t('tenant.skills.modal.metadataJson')}
            rules={metadataRules}
          >
            <TextArea rows={9} className="font-mono text-xs" />
          </Form.Item>
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={isEditMode ? t('tenant.skills.modal.editTitle') : t('tenant.skills.modal.createTitle')}
      open={isOpen}
      onCancel={onClose}
      onOk={() => {
        void handleSubmit();
      }}
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
