import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import {
  Card,
  Row,
  Col,
  Statistic,
  Tag,
  Button,
  Space,
  Popconfirm,
  message,
  Breadcrumb,
  Typography,
  Descriptions,
  Progress,
  Empty,
  Spin,
  Modal,
  Form,
  Input,
  Select,
} from 'antd';
import { Server, Network, HardDrive } from 'lucide-react';

import {
  useCurrentCluster,
  useClusterHealth,
  useClusterLoading,
  useClusterSubmitting,
  useClusterActions,
} from '../../stores/cluster';

import type { ClusterUpdate } from '../../services/clusterService';

const { TextArea } = Input;
const { Option } = Select;
const { Title, Text } = Typography;

const CLUSTER_PROVIDER_OPTIONS = [
  { value: 'docker', label: 'Docker' },
  { value: 'vke', label: 'Volcengine VKE' },
  { value: 'ack', label: 'Alibaba ACK' },
  { value: 'tke', label: 'Tencent TKE' },
  { value: 'custom', label: 'Custom Kubernetes' },
] as const;

interface ClusterEditFormValues {
  name: string;
  compute_provider?: string | undefined;
  proxy_endpoint?: string | undefined;
  provider_config?: string | undefined;
}

const parseProviderConfig = (value: string | undefined): Record<string, unknown> | undefined => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed: unknown = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Provider config must be a JSON object');
  }

  return parsed as Record<string, unknown>;
};

const usageColor = (usage: number) => {
  if (usage > 80) {
    return '#ff4d4f';
  }
  if (usage > 60) {
    return '#faad14';
  }
  return '#3f8600';
};

export const ClusterDetail: React.FC = () => {
  const { clusterId } = useParams<{ clusterId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [form] = Form.useForm<ClusterEditFormValues>();

  const cluster = useCurrentCluster();
  const clusterHealth = useClusterHealth();
  const isLoading = useClusterLoading();
  const isSubmitting = useClusterSubmitting();
  const { getCluster, updateCluster, deleteCluster, getClusterHealth, clearError, reset } =
    useClusterActions();

  useEffect(() => {
    if (clusterId) {
      void getCluster(clusterId);
      void getClusterHealth(clusterId);
    }
    return () => {
      clearError();
      reset();
    };
  }, [clusterId, getCluster, getClusterHealth, clearError, reset]);

  const handleBack = () => {
    void navigate('/clusters');
  };

  const handleEdit = () => {
    if (cluster) {
      form.setFieldsValue({
        name: cluster.name,
        compute_provider: cluster.compute_provider,
        proxy_endpoint: cluster.proxy_endpoint ?? undefined,
        provider_config:
          Object.keys(cluster.provider_config).length > 0
            ? JSON.stringify(cluster.provider_config, null, 2)
            : '',
      });
      setEditModalVisible(true);
    }
  };

  const handleEditSubmit = async () => {
    try {
      const values = await form.validateFields();
      const updateData: ClusterUpdate = { name: values.name };
      if (values.compute_provider !== undefined) {
        updateData.compute_provider = values.compute_provider;
      }
      if (values.proxy_endpoint !== undefined) {
        updateData.proxy_endpoint = values.proxy_endpoint;
      }
      const providerConfig = parseProviderConfig(values.provider_config);
      if (providerConfig) {
        updateData.provider_config = providerConfig;
      }
      if (clusterId) {
        await updateCluster(clusterId, updateData);
        message.success(t('tenant.clusters.updatedSuccess'));
        setEditModalVisible(false);
      }
    } catch {
      message.error(t('tenant.clusters.invalidJsonError'));
    }
  };

  const handleDelete = async () => {
    if (clusterId) {
      await deleteCluster(clusterId);
      message.success(t('tenant.clusters.deletedSuccess'));
      void navigate('/clusters');
    }
  };

  const handleRefreshHealth = async () => {
    if (clusterId) {
      await getClusterHealth(clusterId);
      message.success(t('tenant.clusters.healthDrawer.title') + ' refreshed');
    }
  };

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
      case 'connected':
      case 'healthy':
        return 'green';
      case 'pending':
      case 'provisioning':
        return 'blue';
      case 'warning':
      case 'maintenance':
        return 'orange';
      case 'error':
      case 'disconnected':
      case 'unhealthy':
        return 'red';
      default:
        return 'default';
    }
  };

  const renderUsage = (usage: number | null | undefined) => {
    if (usage == null) {
      return (
        <Text type="secondary">
          {t('tenant.clusters.detail.notAvailable', { defaultValue: 'N/A' })}
        </Text>
      );
    }
    return (
      <Progress
        percent={Number(usage.toFixed(2))}
        size="small"
        status={usage > 80 ? 'exception' : 'active'}
      />
    );
  };

  if (isLoading && !cluster) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <Spin size="large" />
      </div>
    );
  }

  if (!cluster) {
    return (
      <div className="p-8 text-center">
        <Empty description={t('common.notFound')} />
        <Button type="primary" onClick={handleBack} className="mt-4">
          {t('tenant.clusters.detail.backToList')}
        </Button>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          {
            title: (
              <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={handleBack}>
                {t('tenant.clusters.title')}
              </Button>
            ),
          },
          {
            title: cluster.name,
          },
        ]}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Server className="text-3xl text-primary" size={32} />
          <div>
            <Title level={3} className="m-0 flex items-center gap-3">
              {cluster.name}
              <Tag color={getStatusColor(cluster.status)}>
                {t(`tenant.clusters.status.${cluster.status}`, { defaultValue: cluster.status })}
              </Tag>
            </Title>
            <Text type="secondary" className="text-sm">
              ID: {cluster.id}
            </Text>
          </div>
        </div>
        <Space>
          <Button
            onClick={() => {
              void handleRefreshHealth();
            }}
            loading={isLoading}
          >
            {t('common.actions.checkHealth')}
          </Button>
          <Button onClick={handleEdit}>{t('common.edit')}</Button>
          <Popconfirm
            title={t('tenant.clusters.deleteConfirm')}
            onConfirm={() => {
              void handleDelete();
            }}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true }}
          >
            <Button danger>{t('common.delete')}</Button>
          </Popconfirm>
        </Space>
      </div>

      {/* Stats Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('tenant.clusters.detail.provider')}
              value={cluster.compute_provider}
              prefix={<Server size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('common.stats.nodes')}
              value={clusterHealth?.node_count ?? 0}
              prefix={<Network size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('tenant.clusters.detail.cpuUsage')}
              value={clusterHealth?.cpu_usage ?? 0}
              suffix="%"
              prefix={<HardDrive size={20} />}
              styles={{
                content: {
                  color: usageColor(clusterHealth?.cpu_usage ?? 0),
                },
              }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('tenant.clusters.detail.memoryUsage')}
              value={clusterHealth?.memory_usage ?? 0}
              suffix="%"
              prefix={<HardDrive size={20} />}
              styles={{
                content: {
                  color: usageColor(clusterHealth?.memory_usage ?? 0),
                },
              }}
            />
          </Card>
        </Col>
      </Row>

      {/* Cluster Info */}
      <Card title={t('tenant.clusters.detail.info')}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} bordered size="small">
          <Descriptions.Item label={t('tenant.clusters.detail.name')}>
            {cluster.name}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.status')}>
            <Tag color={getStatusColor(cluster.status)}>{cluster.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.healthStatus')}>
            {cluster.health_status ? (
              <Tag color={getStatusColor(cluster.health_status)}>{cluster.health_status}</Tag>
            ) : (
              <Text type="secondary">
                {t('tenant.clusters.detail.notAvailable', { defaultValue: 'N/A' })}
              </Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.provider')}>
            {cluster.compute_provider}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.endpoint')}>
            {cluster.proxy_endpoint || (
              <Text type="secondary">{t('tenant.clusters.detail.notConfigured')}</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.lastHealthCheck')}>
            {cluster.last_health_check
              ? new Date(cluster.last_health_check).toLocaleString()
              : t('common.time.never')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.createdAt')}>
            {new Date(cluster.created_at).toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.updatedAt')}>
            {cluster.updated_at
              ? new Date(cluster.updated_at).toLocaleString()
              : t('common.time.never')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.createdBy')}>
            {cluster.created_by || (
              <Text type="secondary">
                {t('tenant.clusters.detail.notAvailable', { defaultValue: 'N/A' })}
              </Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Provider Config */}
      {Object.keys(cluster.provider_config).length > 0 && (
        <Card title={t('tenant.clusters.detail.providerConfig')}>
          <pre className="bg-slate-100 dark:bg-slate-900 p-4 rounded-lg overflow-x-auto text-sm">
            {JSON.stringify(cluster.provider_config, null, 2)}
          </pre>
        </Card>
      )}

      {/* Node List */}
      <Card title={t('tenant.clusters.detail.nodes.title')}>
        <Descriptions column={{ xs: 1, md: 2 }} bordered size="small">
          <Descriptions.Item label={t('tenant.clusters.healthDrawer.nodeCount')}>
            {clusterHealth?.node_count ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.healthDrawer.checkedAt')}>
            {clusterHealth?.checked_at
              ? new Date(clusterHealth.checked_at).toLocaleString()
              : t('common.time.never')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.healthDrawer.cpuUsage')}>
            {renderUsage(clusterHealth?.cpu_usage)}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.healthDrawer.memoryUsage')}>
            {renderUsage(clusterHealth?.memory_usage)}
          </Descriptions.Item>
        </Descriptions>
        {!clusterHealth || clusterHealth.node_count === 0 ? (
          <Empty
            description={t('tenant.clusters.detail.nodes.empty')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            className="mt-4"
          />
        ) : null}
      </Card>

      {/* Recent Events */}
      <Card title={t('tenant.clusters.detail.events.title')}>
        <Empty
          description={t('tenant.clusters.detail.noEvents')}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </Card>

      {/* Edit Modal */}
      <Modal
        title={t('tenant.clusters.editTitle')}
        open={editModalVisible}
        onOk={() => {
          void handleEditSubmit();
        }}
        onCancel={() => {
          setEditModalVisible(false);
        }}
        confirmLoading={isSubmitting}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
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
            <TextArea rows={4} placeholder={t('tenant.clusters.form.metadataPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
