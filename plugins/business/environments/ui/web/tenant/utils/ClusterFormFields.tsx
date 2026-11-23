import { useTranslation } from 'react-i18next';

import { Form, Input, Select } from 'antd';

import { CLUSTER_PROVIDER_OPTIONS } from './clusterFormUtils';

const { TextArea } = Input;
const { Option } = Select;

/** Form fields shared by the cluster create/edit modals (ClusterList, ClusterDetail). */
export const ClusterFormFields: React.FC = () => {
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name="name"
        label={t('tenant.clusters.form.name')}
        rules={[{ required: true, message: t('tenant.clusters.form.nameRequired') }]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="compute_provider" label={t('tenant.clusters.form.provider')}>
        <Select>
          {CLUSTER_PROVIDER_OPTIONS.map((option) => (
            <Option key={option.value} value={option.value}>
              {option.label}
            </Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item name="proxy_endpoint" label={t('tenant.clusters.form.apiEndpoint')}>
        <Input placeholder={t('tenant.clusters.form.apiEndpointPlaceholder')} />
      </Form.Item>
      <Form.Item name="provider_config" label={t('tenant.clusters.form.metadata')}>
        <TextArea
          rows={4}
          spellCheck={false}
          placeholder={t('tenant.clusters.form.metadataPlaceholder')}
        />
      </Form.Item>
    </>
  );
};
