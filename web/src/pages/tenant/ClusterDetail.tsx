import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Button,
  Space,
  Popconfirm,
  message,
  Breadcrumb,
  Typography,
  Descriptions,
  Progress,
  Timeline,
  Empty,
  Spin,
  Modal,
  Form,
  Input,
  Select,
} from 'antd';
import {
  Server,
  Network,
  HardDrive,
  CheckCircle2,
  AlertCircle,
  XCircle,
  Clock,
} from 'lucide-react';

import {
  useCurrentCluster,
  useClusterHealth,
  useClusterLoading,
  useClusterSubmitting,
  useClusterActions,
} from '../../stores/cluster';

import type { ColumnsType } from 'antd/es/table';

const { TextArea } = Input;
const { Option } = Select;
const { Title, Text } = Typography;

interface NodeInfo {
  id: string;
  name: string;
  status: string;
  cpu_usage: number;
  memory_usage: number;
  roles: string[];
  kubelet_version: string;
}

interface ClusterEvent {
  id: string;
  type: string;
  message: string;
  reason: string;
  count: number;
  timestamp: string;
  source: string;
}

// Mock data for nodes and events (would come from API in real implementation)
const mockNodes: NodeInfo[] = [];
const mockEvents: ClusterEvent[] = [];

export const ClusterDetail: React.FC = () => {
  const { clusterId } = useParams<{ clusterId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [form] = Form.useForm();

  const cluster = useCurrentCluster();
  const clusterHealth = useClusterHealth();
  const isLoading = useClusterLoading();
  const isSubmitting = useClusterSubmitting();
  const { getCluster, updateCluster, deleteCluster, getClusterHealth, clearError, reset } =
    useClusterActions();

  useEffect(() => {
    if (clusterId) {
      getCluster(clusterId);
      getClusterHealth(clusterId);
    }
    return () => {
      clearError();
      reset();
    };
  }, [clusterId, getCluster, getClusterHealth, clearError, reset]);

  const handleBack = () => {
    navigate('/clusters');
  };

  const handleEdit = () => {
    if (cluster) {
      form.setFieldsValue({
        name: cluster.name,
        compute_provider: cluster.compute_provider,
        proxy_endpoint: cluster.proxy_endpoint,
        provider_config: cluster.provider_config
          ? JSON.stringify(cluster.provider_config, null, 2)
          : '',
      });
      setEditModalVisible(true);
    }
  };

  const handleEditSubmit = async () => {
    try {
      const values = await form.validateFields();
      const updateData: Record<string, unknown> = {
        name: values.name,
        compute_provider: values.compute_provider,
        proxy_endpoint: values.proxy_endpoint,
      };
      if (values.provider_config) {
        updateData.provider_config = JSON.parse(values.provider_config);
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
      navigate('/clusters');
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

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'active':
      case 'connected':
      case 'healthy':
        return <CheckCircle2 className="text-[#52c41a]" size={16} />;
      case 'pending':
      case 'provisioning':
        return <Clock className="text-[#1890ff]" size={16} />;
      case 'warning':
      case 'maintenance':
        return <AlertCircle className="text-[#faad14]" size={16} />;
      case 'error':
      case 'disconnected':
      case 'unhealthy':
        return <XCircle className="text-[#ff4d4f]" size={16} />;
      default:
        return <Clock size={16} />;
    }
  };

  const nodeColumns: ColumnsType<NodeInfo> = [
    {
      title: t('tenant.clusters.detail.nodes.name'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record) => (
        <Space>
          {getStatusIcon(record.status)}
          {name}
        </Space>
      ),
    },
    {
      title: t('tenant.clusters.detail.nodes.status'),
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag color={getStatusColor(status)}>{status}</Tag>,
    },
    {
      title: t('tenant.clusters.detail.nodes.cpu'),
      dataIndex: 'cpu_usage',
      key: 'cpu_usage',
      render: (usage: number) => (
        <Progress percent={usage} size="small" status={usage > 80 ? 'exception' : 'active'} />
      ),
    },
    {
      title: t('tenant.clusters.detail.nodes.memory'),
      dataIndex: 'memory_usage',
      key: 'memory_usage',
      render: (usage: number) => (
        <Progress percent={usage} size="small" status={usage > 80 ? 'exception' : 'active'} />
      ),
    },
    {
      title: t('tenant.clusters.detail.nodes.roles'),
      dataIndex: 'roles',
      key: 'roles',
      render: (roles: string[]) => roles.map((role) => <Tag key={role}>{role}</Tag>),
    },
    {
      title: t('tenant.clusters.detail.nodes.version'),
      dataIndex: 'kubelet_version',
      key: 'kubelet_version',
    },
  ];

  const renderEventTimeline = () => {
    if (mockEvents.length === 0) {
      return (
        <Empty
          description={t('tenant.clusters.detail.noEvents')}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      );
    }

    return (
      <Timeline
        items={mockEvents.map((event) => ({
          color: event.type === 'Warning' ? 'red' : 'blue',
          children: (
            <div>
              <Text strong>{event.reason}</Text>
              <br />
              <Text type="secondary">{event.message}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {new Date(event.timestamp).toLocaleString()} - {event.source}
                {event.count > 1 && ` (x${event.count})`}
              </Text>
            </div>
          ),
        }))}
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
          <Button onClick={handleRefreshHealth} loading={isLoading}>
            {t('common.actions.checkHealth')}
          </Button>
          <Button onClick={handleEdit}>{t('common.edit')}</Button>
          <Popconfirm
            title={t('tenant.clusters.deleteConfirm')}
            onConfirm={handleDelete}
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
              valueStyle={{
                color:
                  (clusterHealth?.cpu_usage ?? 0) > 80
                    ? '#ff4d4f'
                    : (clusterHealth?.cpu_usage ?? 0) > 60
                      ? '#faad14'
                      : '#3f8600',
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
              valueStyle={{
                color:
                  (clusterHealth?.memory_usage ?? 0) > 80
                    ? '#ff4d4f'
                    : (clusterHealth?.memory_usage ?? 0) > 60
                      ? '#faad14'
                      : '#3f8600',
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
              <Text type="secondary">N/A</Text>
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
            {cluster.created_by || <Text type="secondary">N/A</Text>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Provider Config */}
      {Object.keys(cluster.provider_config || {}).length > 0 && (
        <Card title={t('tenant.clusters.detail.providerConfig')}>
          <pre className="bg-slate-100 dark:bg-slate-900 p-4 rounded-lg overflow-x-auto text-sm">
            {JSON.stringify(cluster.provider_config, null, 2)}
          </pre>
        </Card>
      )}

      {/* Node List */}
      <Card title={t('tenant.clusters.detail.nodes.title')}>
        {mockNodes.length === 0 ? (
          <Empty
            description={t('tenant.clusters.detail.nodes.empty')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <Table
            columns={nodeColumns}
            dataSource={mockNodes}
            rowKey="id"
            pagination={false}
            size="small"
          />
        )}
      </Card>

      {/* Recent Events */}
      <Card title={t('tenant.clusters.detail.events.title')}>{renderEventTimeline()}</Card>

      {/* Edit Modal */}
      <Modal
        title={t('tenant.clusters.editTitle')}
        open={editModalVisible}
        onOk={handleEditSubmit}
        onCancel={() => {
          setEditModalVisible(false);
        }}
        confirmLoading={isSubmitting}
        destroyOnClose
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
              <Option value="docker">Docker</Option>
              <Option value="kubernetes">Kubernetes</Option>
              <Option value="aws">AWS</Option>
              <Option value="gcp">GCP</Option>
              <Option value="azure">Azure</Option>
              <Option value="on-prem">On-Premise</Option>
            </Select>
          </Form.Item>
          <Form.Item name="proxy_endpoint" label={t('tenant.clusters.form.apiEndpoint')}>
            <Input placeholder="https://cluster.example.com" />
          </Form.Item>
          <Form.Item name="provider_config" label={t('tenant.clusters.form.metadata')}>
            <TextArea rows={4} placeholder="{}" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
