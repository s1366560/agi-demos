import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Steps, Form, Input, InputNumber, Space, Descriptions } from 'antd';

import { LazyButton, LazySelect, useLazyMessage } from '@/components/ui/lazyAntd';

import { useClusters, useClusterActions } from '../../stores/cluster';
import { useInstanceActions } from '../../stores/instance';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { useWorkspaces, useWorkspaceStore } from '../../stores/workspace';

import type { InstanceCreate } from '../../services/instanceService';

export const CreateInstance: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm<Partial<InstanceCreate>>();
  const messageApi = useLazyMessage();

  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState<Partial<InstanceCreate>>({});

  const { createInstance } = useInstanceActions();
  const clusters = useClusters();
  const { listClusters } = useClusterActions();
  const workspaces = useWorkspaces();
  const loadWorkspaces = useWorkspaceStore((s) => s.loadWorkspaces);
  const tenantId = useTenantStore((s) => s.currentTenant?.id);
  const projectId = useProjectStore((s) => s.currentProject?.id);

  useEffect(() => {
    listClusters().catch((err: unknown) => {
      console.error('Failed to list clusters:', err);
    });
    if (tenantId && projectId) {
      loadWorkspaces(tenantId, projectId).catch((err: unknown) => {
        console.error('Failed to list workspaces:', err);
      });
    }
  }, [listClusters, loadWorkspaces, tenantId, projectId]);

  const handleNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const name = e.target.value;
      const isSlugTouched = form.isFieldTouched('slug');
      const currentSlug = form.getFieldValue('slug') as unknown;
      if (!isSlugTouched || typeof currentSlug !== 'string' || currentSlug.length === 0) {
        const slug = name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/(^-|-$)/g, '');
        form.setFieldsValue({ slug });
      }
    },
    [form]
  );

  const formatReviewValue = useCallback((value: unknown): string => {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
      return String(value);
    }
    if (value && typeof value === 'object') return JSON.stringify(value);
    return '';
  }, []);

  const stepsInfo = React.useMemo(
    () => [
      {
        id: 'basic',
        title: t('tenant.instances.create.steps.basic.title', 'Basic Info'),
        fields: ['name', 'slug', 'agent_display_name', 'agent_label', 'theme_color'],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="name"
              label={t('tenant.instances.create.basic.name', 'Name')}
              rules={[{ required: true }]}
            >
              <Input
                onChange={handleNameChange}
                placeholder={t('tenant.instances.create.placeholders.name', 'e.g. My Instance')}
              />
            </Form.Item>
            <Form.Item
              name="slug"
              label={t('tenant.instances.create.basic.slug', 'Slug')}
              rules={[{ required: true }]}
            >
              <Input
                placeholder={t('tenant.instances.create.placeholders.slug', 'e.g. my-instance')}
              />
            </Form.Item>
            <Form.Item
              name="agent_display_name"
              label={t('tenant.instances.create.basic.agent_display_name', 'Agent Display Name')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="agent_label"
              label={t('tenant.instances.create.basic.agent_label', 'Agent Label')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="theme_color"
              label={t('tenant.instances.create.basic.theme_color', 'Theme Color')}
            >
              <Input type="color" className="w-full h-10" />
            </Form.Item>
          </div>
        ),
      },
      {
        title: t('tenant.instances.create.steps.infra.title', 'Infrastructure'),
        fields: ['cluster_id', 'namespace', 'image_version', 'runtime', 'compute_provider'],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="cluster_id"
              label={t('tenant.instances.create.infra.cluster_id', 'Cluster')}
            >
              <LazySelect
                allowClear
                options={clusters.map((c) => ({ value: c.id, label: c.name }))}
              />
            </Form.Item>
            <Form.Item
              name="namespace"
              label={t('tenant.instances.create.infra.namespace', 'Namespace')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="image_version"
              label={t('tenant.instances.create.infra.image_version', 'Image Version')}
            >
              <Input />
            </Form.Item>
            <Form.Item name="runtime" label={t('tenant.instances.create.infra.runtime', 'Runtime')}>
              <LazySelect
                allowClear
                options={[
                  { value: 'docker', label: 'Docker' },
                  { value: 'kubernetes', label: 'Kubernetes' },
                  { value: 'local', label: 'Local' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="compute_provider"
              label={t('tenant.instances.create.infra.compute_provider', 'Compute Provider')}
            >
              <Input />
            </Form.Item>
          </div>
        ),
      },
      {
        title: t('tenant.instances.create.steps.resources.title', 'Resources'),
        fields: [
          'replicas',
          'cpu_request',
          'cpu_limit',
          'mem_request',
          'mem_limit',
          'service_type',
          'ingress_domain',
        ],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="replicas"
              label={t('tenant.instances.create.resources.replicas', 'Replicas')}
            >
              <InputNumber min={0} className="w-full" />
            </Form.Item>
            <Form.Item
              name="cpu_request"
              label={t('tenant.instances.create.resources.cpu_request', 'CPU Request')}
            >
              <Input
                placeholder={t('tenant.instances.create.placeholders.cpuRequest', 'e.g. 100m')}
              />
            </Form.Item>
            <Form.Item
              name="cpu_limit"
              label={t('tenant.instances.create.resources.cpu_limit', 'CPU Limit')}
            >
              <Input placeholder={t('tenant.instances.create.placeholders.cpuLimit', 'e.g. 1')} />
            </Form.Item>
            <Form.Item
              name="mem_request"
              label={t('tenant.instances.create.resources.mem_request', 'Memory Request')}
            >
              <Input
                placeholder={t('tenant.instances.create.placeholders.memRequest', 'e.g. 256Mi')}
              />
            </Form.Item>
            <Form.Item
              name="mem_limit"
              label={t('tenant.instances.create.resources.mem_limit', 'Memory Limit')}
            >
              <Input placeholder={t('tenant.instances.create.placeholders.memLimit', 'e.g. 1Gi')} />
            </Form.Item>
            <Form.Item
              name="service_type"
              label={t('tenant.instances.create.resources.service_type', 'Service Type')}
            >
              <LazySelect
                allowClear
                options={[
                  { value: 'ClusterIP', label: 'ClusterIP' },
                  { value: 'NodePort', label: 'NodePort' },
                  { value: 'LoadBalancer', label: 'LoadBalancer' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="ingress_domain"
              label={t('tenant.instances.create.resources.ingress_domain', 'Ingress Domain')}
            >
              <Input />
            </Form.Item>
          </div>
        ),
      },
      {
        title: t('tenant.instances.create.steps.storage.title', 'Storage & Quotas'),
        fields: ['storage_class', 'storage_size', 'quota_cpu', 'quota_memory', 'quota_max_pods'],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="storage_class"
              label={t('tenant.instances.create.storage.storage_class', 'Storage Class')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="storage_size"
              label={t('tenant.instances.create.storage.storage_size', 'Storage Size')}
            >
              <Input
                placeholder={t('tenant.instances.create.placeholders.storageSize', 'e.g. 10Gi')}
              />
            </Form.Item>
            <Form.Item
              name="quota_cpu"
              label={t('tenant.instances.create.storage.quota_cpu', 'Quota CPU')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="quota_memory"
              label={t('tenant.instances.create.storage.quota_memory', 'Quota Memory')}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="quota_max_pods"
              label={t('tenant.instances.create.storage.quota_max_pods', 'Quota Max Pods')}
            >
              <InputNumber min={0} className="w-full" />
            </Form.Item>
          </div>
        ),
      },
      {
        title: t('tenant.instances.create.steps.config.title', 'Configuration'),
        fields: ['workspace_id', 'env_vars', 'advanced_config', 'llm_providers'],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="workspace_id"
              label={t('tenant.instances.create.config.workspace', 'Associate with Workspace')}
            >
              <LazySelect
                allowClear
                placeholder={t(
                  'tenant.instances.create.placeholders.workspace',
                  'Select a workspace (optional)'
                )}
                options={workspaces.map((ws) => ({
                  label: ws.name,
                  value: ws.id,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="env_vars"
              label={t('tenant.instances.create.config.env_vars', 'Environment Variables (JSON)')}
            >
              <Input.TextArea
                rows={4}
                placeholder={t('tenant.instances.create.placeholders.envVars', '{"KEY": "value"}')}
              />
            </Form.Item>
            <Form.Item
              name="advanced_config"
              label={t('tenant.instances.create.config.advanced_config', 'Advanced Config (JSON)')}
            >
              <Input.TextArea
                rows={4}
                placeholder={t(
                  'tenant.instances.create.placeholders.advancedConfig',
                  '{"key": "value"}'
                )}
              />
            </Form.Item>
            <Form.Item
              name="llm_providers"
              label={t('tenant.instances.create.config.llm_providers', 'LLM Providers (JSON)')}
            >
              <Input.TextArea
                rows={4}
                placeholder={t(
                  'tenant.instances.create.placeholders.llmProviders',
                  '{"openai": {"api_key": "..."}}'
                )}
              />
            </Form.Item>
          </div>
        ),
      },
      {
        id: 'review',
        title: t('tenant.instances.create.steps.review.title', 'Review'),
        fields: [],
        content: (
          <div className="flex flex-col gap-4">
            <Descriptions bordered column={1} size="small">
              {Object.entries(formData as Record<string, unknown>).map(([key, value]) => {
                if (value === undefined || value === null || value === '') return null;
                const getLabel = (k: string) => {
                  const map: Record<string, string> = {
                    name: t('tenant.instances.create.basic.name', 'Name'),
                    slug: t('tenant.instances.create.basic.slug', 'Slug'),
                    agent_display_name: t(
                      'tenant.instances.create.basic.agent_display_name',
                      'Agent Display Name'
                    ),
                    agent_label: t('tenant.instances.create.basic.agent_label', 'Agent Label'),
                    theme_color: t('tenant.instances.create.basic.theme_color', 'Theme Color'),
                    cluster_id: t('tenant.instances.create.infra.cluster_id', 'Cluster'),
                    namespace: t('tenant.instances.create.infra.namespace', 'Namespace'),
                    image_version: t(
                      'tenant.instances.create.infra.image_version',
                      'Image Version'
                    ),
                    runtime: t('tenant.instances.create.infra.runtime', 'Runtime'),
                    compute_provider: t(
                      'tenant.instances.create.infra.compute_provider',
                      'Compute Provider'
                    ),
                    replicas: t('tenant.instances.create.resources.replicas', 'Replicas'),
                    cpu_request: t('tenant.instances.create.resources.cpu_request', 'CPU Request'),
                    cpu_limit: t('tenant.instances.create.resources.cpu_limit', 'CPU Limit'),
                    mem_request: t(
                      'tenant.instances.create.resources.mem_request',
                      'Memory Request'
                    ),
                    mem_limit: t('tenant.instances.create.resources.mem_limit', 'Memory Limit'),
                    service_type: t(
                      'tenant.instances.create.resources.service_type',
                      'Service Type'
                    ),
                    ingress_domain: t(
                      'tenant.instances.create.resources.ingress_domain',
                      'Ingress Domain'
                    ),
                    storage_class: t(
                      'tenant.instances.create.storage.storage_class',
                      'Storage Class'
                    ),
                    storage_size: t('tenant.instances.create.storage.storage_size', 'Storage Size'),
                    quota_cpu: t('tenant.instances.create.storage.quota_cpu', 'Quota CPU'),
                    quota_memory: t('tenant.instances.create.storage.quota_memory', 'Quota Memory'),
                    quota_max_pods: t(
                      'tenant.instances.create.storage.quota_max_pods',
                      'Quota Max Pods'
                    ),
                    env_vars: t(
                      'tenant.instances.create.config.env_vars',
                      'Environment Variables (JSON)'
                    ),
                    advanced_config: t(
                      'tenant.instances.create.config.advanced_config',
                      'Advanced Config (JSON)'
                    ),
                    llm_providers: t(
                      'tenant.instances.create.config.llm_providers',
                      'LLM Providers (JSON)'
                    ),
                    workspace_id: t('tenant.instances.create.config.workspace', 'Workspace'),
                  };
                  return map[k] || k;
                };
                return (
                  <Descriptions.Item key={key} label={getLabel(key)}>
                    {formatReviewValue(value)}
                  </Descriptions.Item>
                );
              })}
            </Descriptions>
          </div>
        ),
      },
    ],
    [t, clusters, handleNameChange, formData, workspaces, formatReviewValue]
  );

  const parseJsonField = useCallback((val: unknown): Record<string, unknown> | undefined => {
    if (!val) return undefined;
    if (typeof val === 'string') {
      try {
        const parsed: unknown = JSON.parse(val);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
          ? (parsed as Record<string, unknown>)
          : undefined;
      } catch {
        return undefined;
      }
    }
    return typeof val === 'object' && !Array.isArray(val)
      ? (val as Record<string, unknown>)
      : undefined;
  }, []);

  const handleNext = useCallback(() => {
    const step = stepsInfo[currentStep];
    if (!step) return;
    const fieldsToValidate = step.fields;
    if (fieldsToValidate.length > 0) {
      form
        .validateFields(fieldsToValidate)
        .then((values: unknown) => {
          const nextValues =
            values && typeof values === 'object' ? (values as Partial<InstanceCreate>) : {};
          setFormData((prev) => ({ ...prev, ...nextValues }));
          setCurrentStep((prev) => prev + 1);
        })
        .catch((err: unknown) => {
          console.error('Form validation failed:', err);
        });
    } else {
      setCurrentStep((prev) => prev + 1);
    }
  }, [currentStep, form, stepsInfo]);

  const handleBack = useCallback(() => {
    setCurrentStep((prev) => prev - 1);
  }, []);

  const handleSubmit = useCallback(() => {
    const finalData: InstanceCreate = {
      name: String(formData.name),
      slug: String(formData.slug),
      tenant_id: tenantId || 'default',
      ...formData,
    };

    if (finalData.env_vars)
      finalData.env_vars = parseJsonField(finalData.env_vars) as Record<string, unknown>;
    if (finalData.advanced_config)
      finalData.advanced_config = parseJsonField(finalData.advanced_config) as Record<
        string,
        unknown
      >;
    if (finalData.llm_providers)
      finalData.llm_providers = parseJsonField(finalData.llm_providers) as Record<string, unknown>;

    createInstance(finalData)
      .then(() => {
        messageApi?.success(t('tenant.instances.create.success', 'Instance created successfully'));
        void navigate('..');
      })
      .catch((err: unknown) => {
        console.error('Failed to create instance:', err);
        messageApi?.error(t('tenant.instances.create.error', 'Failed to create instance'));
      });
  }, [formData, createInstance, navigate, t, parseJsonField, messageApi, tenantId]);

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
      <h1 className="text-2xl font-bold">
        {t('tenant.instances.create.title', 'Create Instance')}
      </h1>

      <div className="bg-surface-light dark:bg-surface-dark rounded-lg p-8 border border-border-light dark:border-border-dark">
        <Steps
          current={currentStep}
          items={stepsInfo.map((s) => ({ title: s.title }))}
          className="mb-8"
        />

        <Form form={form} layout="vertical">
          <div aria-live="polite">
            {stepsInfo.map((step, index) => (
              <div
                key={step.id || step.title}
                style={{ display: currentStep === index ? 'block' : 'none' }}
              >
                {step.content}
              </div>
            ))}
          </div>
        </Form>

        <div className="flex justify-between mt-8 pt-4 border-t border-border-light dark:border-border-dark">
          <LazyButton onClick={handleBack} disabled={currentStep === 0}>
            {t('tenant.instances.create.actions.back', 'Back')}
          </LazyButton>
          <Space>
            <LazyButton
              onClick={() => {
                void navigate('..');
              }}
            >
              {t('tenant.instances.create.actions.cancel', 'Cancel')}
            </LazyButton>
            {currentStep < stepsInfo.length - 1 ? (
              <LazyButton type="primary" onClick={handleNext}>
                {t('tenant.instances.create.actions.next', 'Next')}
              </LazyButton>
            ) : (
              <LazyButton type="primary" onClick={handleSubmit}>
                {t('tenant.instances.create.actions.submit', 'Create')}
              </LazyButton>
            )}
          </Space>
        </div>
      </div>
    </div>
  );
};
