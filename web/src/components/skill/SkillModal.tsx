/**
 * Skill Modal Component
 *
 * Modal for editing AgentSkills.io SKILL.md packages.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Switch, message } from 'antd';
import { Braces, FileText, Info, ShieldCheck } from 'lucide-react';

import { useSkillStore, useSkillSubmitting } from '../../stores/skill';

import {
  buildSkillContent,
  compact,
  extractSkillBody,
  formatAllowedToolsForEdit,
  formatMetadata,
  parseAllowedTools,
  parseMetadata,
  SKILL_NAME_PATTERN,
  type SkillPackageFormValues,
} from './skillPackageFormModel';

import type { SkillResponse, SkillUpdate } from '../../types/agent';

const { TextArea } = Input;

const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';

type SkillScopeValue = 'tenant' | 'project';

interface SkillFormValues extends SkillPackageFormValues {
  name: string;
  description: string;
  scope: SkillScopeValue;
}

interface SkillModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  skill: SkillResponse;
  tenantId?: string | null | undefined;
}

export const SkillModal: FC<SkillModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  skill,
  tenantId,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const scopeValue = Form.useWatch('scope', form) as SkillScopeValue | undefined;
  const watchedValues = Form.useWatch([], form) as SkillFormValues | undefined;
  const [showAdvanced, setShowAdvanced] = useState(false);

  const isSubmitting = useSkillSubmitting();
  const { updateSkill } = useSkillStore();

  const previewContent = useMemo(() => {
    const values = watchedValues ?? (form.getFieldsValue(true) as SkillFormValues);
    if (!values.name || !values.description) {
      return t('tenant.skills.modal.previewEmpty');
    }
    try {
      return buildSkillContent(values);
    } catch {
      return t('tenant.skills.modal.previewInvalid');
    }
  }, [form, t, watchedValues]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    form.setFieldsValue({
      name: skill.name,
      description: skill.description,
      scope: skill.scope === 'project' ? 'project' : 'tenant',
      project_id: skill.project_id ?? undefined,
      body: extractSkillBody(skill.full_content, skill.name),
      metadata: formatMetadata(skill.metadata),
      license: skill.license ?? '',
      compatibility: skill.compatibility ?? '',
      allowed_tools_raw: formatAllowedToolsForEdit(skill),
      spec_version: skill.spec_version,
    });

    const resetTimer = window.setTimeout(() => {
      setShowAdvanced(false);
    }, 0);

    return () => {
      window.clearTimeout(resetTimer);
    };
  }, [isOpen, skill, form]);

  // Handle form submission
  const handleSubmit = useCallback(async () => {
    try {
      const values = (await form.validateFields()) as SkillFormValues;
      const metadata = parseMetadata(values.metadata);
      const allowedToolsRaw = compact(values.allowed_tools_raw);
      const tools = parseAllowedTools(values.allowed_tools_raw);
      const fullContent = buildSkillContent(values);
      const commonData = {
        name: values.name,
        description: values.description,
        tools,
        full_content: fullContent,
        metadata: metadata ?? {},
        license: compact(values.license) ?? null,
        compatibility: compact(values.compatibility) ?? null,
        allowed_tools_raw: allowedToolsRaw ?? null,
        spec_version: compact(values.spec_version) ?? '1.0',
      };

      if (tenantId) {
        await updateSkill(skill.id, commonData as SkillUpdate, { tenant_id: tenantId });
      } else {
        await updateSkill(skill.id, commonData as SkillUpdate);
      }
      message.success(t('tenant.skills.updateSuccess'));

      onSuccess();
    } catch {
      // API errors handled by store
    }
  }, [form, skill, tenantId, updateSkill, onSuccess, t]);

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

  return (
    <Modal
      title={t('tenant.skills.modal.editTitle')}
      open={isOpen}
      onCancel={onClose}
      onOk={() => {
        void handleSubmit();
      }}
      okText={t('common.save')}
      cancelText={t('common.cancel')}
      confirmLoading={isSubmitting}
      width={1080}
      destroyOnHidden
    >
      <div className={`mb-4 rounded-[6px] p-4 ${surface}`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className={`flex items-center gap-2 text-sm font-semibold ${pageText}`}>
              <FileText size={16} />
              {t('tenant.skills.modal.specPanelTitle')}
            </div>
            <p className={`mt-1 max-w-3xl text-sm leading-6 ${mutedText}`}>
              {t('tenant.skills.modal.specPanelDescription')}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {['name', 'description', 'SKILL.md'].map((item) => (
              <span
                key={item}
                className="inline-flex h-6 items-center rounded-full border border-[oklch(0.86_0.006_255)] px-2 text-[11px] font-medium text-[oklch(0.42_0.01_255)] dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.78_0.006_255)]"
              >
                {item}
              </span>
            ))}
          </div>
        </div>
      </div>

      <Form form={form} layout="vertical" className="mt-4">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="space-y-5">
            <section className="space-y-4">
              <div className="flex items-center gap-2">
                <ShieldCheck size={16} className="text-[oklch(0.48_0.01_255)]" />
                <h3 className={`text-sm font-semibold ${pageText}`}>
                  {t('tenant.skills.modal.frontmatter')}
                </h3>
              </div>

              <Form.Item
                name="name"
                label={t('tenant.skills.modal.name')}
                rules={[
                  {
                    required: true,
                    message: t('tenant.skills.modal.nameRequired'),
                  },
                  {
                    max: 64,
                    message: t('tenant.skills.modal.nameMax'),
                  },
                  {
                    pattern: SKILL_NAME_PATTERN,
                    message: t('tenant.skills.modal.namePattern'),
                  },
                ]}
              >
                <Input placeholder={t('tenant.skills.modal.namePlaceholder')} disabled />
              </Form.Item>

              <Form.Item
                name="description"
                label={t('tenant.skills.modal.description')}
                rules={[
                  {
                    required: true,
                    message: t('tenant.skills.modal.descriptionRequired'),
                  },
                  {
                    max: 1024,
                    message: t('tenant.skills.modal.descriptionMax'),
                  },
                ]}
              >
                <TextArea rows={3} placeholder={t('tenant.skills.modal.descriptionPlaceholder')} />
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
                    disabled
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
                    disabled={scopeValue !== 'project'}
                  />
                </Form.Item>
              </div>

              <Form.Item name="allowed_tools_raw" label={t('tenant.skills.modal.allowedToolsRaw')}>
                <Input placeholder={t('tenant.skills.modal.allowedToolsRawPlaceholder')} />
              </Form.Item>

              <div className="rounded-[6px] border border-[oklch(0.82_0.05_250)] bg-[oklch(0.97_0.018_250)] p-3 dark:border-[oklch(0.38_0.06_250)] dark:bg-[oklch(0.22_0.03_250)]">
                <div className="flex items-start gap-2">
                  <Info
                    size={16}
                    className="mt-0.5 text-[oklch(0.48_0.16_250)] dark:text-[oklch(0.72_0.12_250)]"
                  />
                  <div className="text-sm leading-5 text-[oklch(0.4_0.11_250)] dark:text-[oklch(0.78_0.08_250)]">
                    {t('tenant.skills.modal.toolsHint')}
                  </div>
                </div>
              </div>

              <Form.Item name="body" label={t('tenant.skills.modal.body')}>
                <TextArea
                  rows={10}
                  placeholder={t('tenant.skills.modal.bodyPlaceholder')}
                  className="font-mono text-xs"
                />
              </Form.Item>

              <div className="flex items-center justify-between rounded-[6px] border border-[oklch(0.9_0.006_255)] px-3 py-2 dark:border-[oklch(0.28_0.006_255)]">
                <div>
                  <div className={`text-sm font-medium ${pageText}`}>
                    {t('tenant.skills.modal.advanced')}
                  </div>
                  <div className={`text-xs ${mutedText}`}>
                    {t('tenant.skills.modal.advancedHint')}
                  </div>
                </div>
                <Switch checked={showAdvanced} onChange={setShowAdvanced} />
              </div>

              {showAdvanced ? (
                <section className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <Form.Item name="spec_version" label={t('tenant.skills.modal.specVersion')}>
                      <Input placeholder="1.0" />
                    </Form.Item>
                    <Form.Item name="license" label={t('tenant.skills.modal.license')}>
                      <Input placeholder={t('tenant.skills.modal.licensePlaceholder')} />
                    </Form.Item>
                  </div>
                  <Form.Item
                    name="compatibility"
                    label={t('tenant.skills.modal.compatibility')}
                    rules={[
                      {
                        max: 500,
                        message: t('tenant.skills.modal.compatibilityMax'),
                      },
                    ]}
                  >
                    <TextArea
                      rows={3}
                      placeholder={t('tenant.skills.modal.compatibilityPlaceholder')}
                    />
                  </Form.Item>
                  <Form.Item
                    name="metadata"
                    label={t('tenant.skills.modal.metadataJson')}
                    rules={metadataRules}
                  >
                    <TextArea rows={9} className="font-mono text-xs" />
                  </Form.Item>
                </section>
              ) : null}
            </section>
          </div>

          <aside className="min-w-0">
            <div className={`sticky top-4 rounded-[6px] p-0 ${surface}`}>
              <div className="flex items-center justify-between border-b border-[oklch(0.9_0.006_255)] px-3 py-2 dark:border-[oklch(0.28_0.006_255)]">
                <div className={`flex items-center gap-2 text-sm font-semibold ${pageText}`}>
                  <Braces size={15} />
                  {t('tenant.skills.modal.preview')}
                </div>
                <span className={`text-[11px] font-medium uppercase ${mutedText}`}>SKILL.md</span>
              </div>
              <pre className="max-h-[620px] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5 text-[oklch(0.28_0.01_255)] dark:text-[oklch(0.84_0.006_255)]">
                {previewContent}
              </pre>
            </div>
          </aside>
        </div>
      </Form>
    </Modal>
  );
};

export default SkillModal;
