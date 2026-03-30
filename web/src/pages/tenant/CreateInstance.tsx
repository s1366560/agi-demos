import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  Steps,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  message,
  Space,
  Descriptions,
} from 'antd';

import { useClusters, useClusterActions } from '../../stores/cluster';
import { useInstanceActions } from '../../stores/instance';

import type { InstanceCreate } from '../../services/instanceService';

export const CreateInstance: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm();

  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState<Record<string, any>>({});

  const { createInstance } = useInstanceActions();
  const clusters = useClusters();
  const { listClusters } = useClusterActions();

  useEffect(() => {
    listClusters().catch(() => {});
  }, [listClusters]);

  const handleNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const name = e.target.value;
      const isSlugTouched = form.isFieldTouched('slug');
      const currentSlug = form.getFieldValue('slug');
      if (!isSlugTouched || !currentSlug) {
        const slug = name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/(^-|-$)/g, '');
        form.setFieldsValue({ slug });
      }
    },
    [form]
  );

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
              <Input onChange={handleNameChange} placeholder="e.g. My Instance" />
            </Form.Item>
            <Form.Item
              name="slug"
              label={t('tenant.instances.create.basic.slug', 'Slug')}
              rules={[{ required: true }]}
            >
              <Input placeholder="e.g. my-instance" />
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
              <Select allowClear>
                {clusters.map((c) => (
                  <Select.Option key={c.id} value={c.id}>
                    {c.name}
                  </Select.Option>
                ))}
              </Select>
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
              <Select allowClear>
                <Select.Option value="docker">Docker</Select.Option>
                <Select.Option value="kubernetes">Kubernetes</Select.Option>
                <Select.Option value="local">Local</Select.Option>
              </Select>
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
              <Input placeholder="e.g. 100m" />
            </Form.Item>
            <Form.Item
              name="cpu_limit"
              label={t('tenant.instances.create.resources.cpu_limit', 'CPU Limit')}
            >
              <Input placeholder="e.g. 1" />
            </Form.Item>
            <Form.Item
              name="mem_request"
              label={t('tenant.instances.create.resources.mem_request', 'Memory Request')}
            >
              <Input placeholder="e.g. 256Mi" />
            </Form.Item>
            <Form.Item
              name="mem_limit"
              label={t('tenant.instances.create.resources.mem_limit', 'Memory Limit')}
            >
              <Input placeholder="e.g. 1Gi" />
            </Form.Item>
            <Form.Item
              name="service_type"
              label={t('tenant.instances.create.resources.service_type', 'Service Type')}
            >
              <Select allowClear>
                <Select.Option value="ClusterIP">ClusterIP</Select.Option>
                <Select.Option value="NodePort">NodePort</Select.Option>
                <Select.Option value="LoadBalancer">LoadBalancer</Select.Option>
              </Select>
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
              <Input placeholder="e.g. 10Gi" />
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
        fields: ['env_vars', 'advanced_config', 'llm_providers'],
        content: (
          <div className="flex flex-col gap-4">
            <Form.Item
              name="env_vars"
              label={t('tenant.instances.create.config.env_vars', 'Environment Variables (JSON)')}
            >
              <Input.TextArea rows={4} placeholder='{"KEY": "value"}' />
            </Form.Item>
            <Form.Item
              name="advanced_config"
              label={t('tenant.instances.create.config.advanced_config', 'Advanced Config (JSON)')}
            >
              <Input.TextArea rows={4} placeholder='{"key": "value"}' />
            </Form.Item>
            <Form.Item
              name="llm_providers"
              label={t('tenant.instances.create.config.llm_providers', 'LLM Providers (JSON)')}
            >
              <Input.TextArea rows={4} placeholder='{"openai": {"api_key": "..."}}' />
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
              {Object.entries(formData).map(([key, value]) => {
                if (value === undefined || value === null || value === '') return null;
                return (
                  <Descriptions.Item key={key} label={key}>
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </Descriptions.Item>
                );
              })}
            </Descriptions>
          </div>
        ),
      },
    ],
    [t, clusters, handleNameChange, formData]
  );

  const parseJsonField = useCallback((val: unknown) => {
    if (!val) return undefined;
    if (typeof val === 'string') {
      try {
        return JSON.parse(val);
      } catch {
        return undefined;
      }
    }
    return val;
  }, []);

  const handleNext = useCallback(() => {
    const step = stepsInfo[currentStep];
    if (!step) return;
    const fieldsToValidate = step.fields;
    if (fieldsToValidate.length > 0) {
      form
        .validateFields(fieldsToValidate)
        .then((values) => {
          setFormData((prev) => ({ ...prev, ...values }));
          setCurrentStep((prev) => prev + 1);
        })
        .catch(() => {});
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
      tenant_id: 'default',
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
        message.success(t('tenant.instances.create.success', 'Instance created successfully'));
        navigate('/instances');
      })
      .catch(() => {
        message.error(t('tenant.instances.create.error', 'Failed to create instance'));
      });
  }, [formData, createInstance, navigate, t, parseJsonField]);

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
      <h1 className="text-2xl font-bold">
        {t('tenant.instances.create.title', 'Create Instance')}
      </h1>

      <div className="bg-white dark:bg-slate-800 rounded-lg p-8 border border-slate-200 dark:border-slate-700">
        <Steps
          current={currentStep}
          items={stepsInfo.map((s) => ({ title: s.title }))}
          className="mb-8"
        />

        <Form form={form} layout="vertical">
          {stepsInfo.map((step, index) => (
            <div
              key={step.id || step.title}
              style={{ display: currentStep === index ? 'block' : 'none' }}
            >
              {step.content}
            </div>
          ))}
        </Form>

        <div className="flex justify-between mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
          <Button onClick={handleBack} disabled={currentStep === 0}>
            {t('tenant.instances.create.actions.back', 'Back')}
          </Button>
          <Space>
            <Button onClick={() => navigate('/instances')}>
              {t('tenant.instances.create.actions.cancel', 'Cancel')}
            </Button>
            {currentStep < stepsInfo.length - 1 ? (
              <Button type="primary" onClick={handleNext}>
                {t('tenant.instances.create.actions.next', 'Next')}
              </Button>
            ) : (
              <Button type="primary" onClick={handleSubmit}>
                {t('tenant.instances.create.actions.submit', 'Create')}
              </Button>
            )}
          </Space>
        </div>
      </div>
    </div>
  );
};
