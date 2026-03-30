import { useEffect, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Tag,
  Space,
  Popconfirm,
  message,
  Descriptions,
  Select,
  Drawer,
  Card,
  Row,
  Col,
} from 'antd';

import {
  useClusters,
  useClusterHealth,
  useClusterLoading,
  useClusterSubmitting,
  useClusterError,
  useClusterTotal,
  useClusterActions,
} from '../../stores/cluster';

import type { ClusterResponse } from '../../services/clusterService';

const { TextArea } = Input;
const { Option } = Select;

interface FormValues {
  name: string;
  compute_provider?: string;
  proxy_endpoint?: string;
  provider_config?: string;
}

export const ClusterList: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm<FormValues>();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [isHealthDrawerVisible, setIsHealthDrawerVisible] = useState(false);
  const [editingCluster, setEditingCluster] = useState<ClusterResponse | null>(null);

  const clusters = useClusters();
  const clusterHealth = useClusterHealth();
  const loading = useClusterLoading();
  const submitting = useClusterSubmitting();
  const error = useClusterError();
  const total = useClusterTotal();
  const {
    listClusters,
    createCluster,
    updateCluster,
    deleteCluster,
    getClusterHealth,
    setCurrentCluster,
    clearError,
    reset,
  } = useClusterActions();

  useEffect(() => {
    void listClusters();
    return () => {
      clearError();
      reset();
    };
  }, [listClusters, clearError, reset]);

  useEffect(() => {
    if (error) {
      message.error(error);
      clearError();
    }
  }, [error, clearError]);

  const healthyCount = clusters.filter((c) => c.status === 'active').length;
  const unhealthyCount = clusters.filter(
    (c) => c.status === 'error' || c.status === 'inactive'
  ).length;

  const handleCreate = () => {
    setEditingCluster(null);
    form.resetFields();
    setIsModalVisible(true);
  };

  const handleEdit = (cluster: ClusterResponse) => {
    setEditingCluster(cluster);
    form.setFieldsValue({
      name: cluster.name,
      compute_provider: cluster.compute_provider,
      ...(cluster.proxy_endpoint != null ? { proxy_endpoint: cluster.proxy_endpoint } : {}),
      provider_config: JSON.stringify(cluster.provider_config, null, 2),
    });
    setIsModalVisible(true);
  };

  const handleDelete = async (id: string) => {
    await deleteCluster(id);
    message.success(t('tenant.clusters.deletedSuccess'));
  };

  const handleHealthCheck = async (id: string) => {
    setCurrentCluster(clusters.find((c) => c.id === id) || null);
    await getClusterHealth(id);
    setIsHealthDrawerVisible(true);
  };

  const handleModalOk = () => {
    void form.validateFields().then(async (values) => {
      try {
        const base: {
          name: string;
          compute_provider?: string;
          proxy_endpoint?: string;
          provider_config?: Record<string, unknown>;
        } = {
          name: values.name,
          ...(values.compute_provider != null ? { compute_provider: values.compute_provider } : {}),
          ...(values.proxy_endpoint != null ? { proxy_endpoint: values.proxy_endpoint } : {}),
        };
        if (values.provider_config) {
          base.provider_config = JSON.parse(values.provider_config) as Record<string, unknown>;
        }

        if (editingCluster) {
          await updateCluster(editingCluster.id, base);
          message.success(t('tenant.clusters.updatedSuccess'));
        } else {
          await createCluster(base);
          message.success(t('tenant.clusters.createdSuccess'));
        }
        setIsModalVisible(false);
      } catch {
        message.error(t('tenant.clusters.invalidJsonError'));
      }
    });
  };

  const handleModalCancel = () => {
    setIsModalVisible(false);
    form.resetFields();
  };

  const closeHealthDrawer = () => {
    setIsHealthDrawerVisible(false);
  };

  const getStatusTag = (status: string) => {
    let color = 'default';
    if (status === 'active') color = 'green';
    else if (status === 'maintenance') color = 'orange';
    else if (status === 'error') color = 'red';

    return <Tag color={color}>{t(`tenant.clusters.status.${status}`)}</Tag>;
  };

  const handleViewCluster = (id: string): void => {
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    navigate(`/clusters/${id}`);
  };

  const columns = [
    {
      title: t('tenant.clusters.columns.name'),
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: t('tenant.clusters.columns.provider'),
      dataIndex: 'compute_provider',
      key: 'compute_provider',
    },
    {
      title: t('tenant.clusters.columns.apiEndpoint'),
      dataIndex: 'proxy_endpoint',
      key: 'proxy_endpoint',
      render: (text: string | null) => (
        <span className="truncate max-w-50 inline-block" title={text || ''}>
          {text || '-'}
        </span>
      ),
    },
    {
      title: t('tenant.clusters.columns.status'),
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => getStatusTag(status),
    },
    {
      title: t('tenant.clusters.columns.actions'),
      key: 'actions',
      render: (_: unknown, record: ClusterResponse) => (
        <Space size="middle">
          <Button type="link" onClick={() => { handleViewCluster(record.id); }}>
            {t('common.actions.viewAll')}
          </Button>
          <Button type="link" onClick={() => void handleHealthCheck(record.id)}>
            {t('tenant.clusters.actions.healthCheck')}
          </Button>
          <Button
            type="link"
            onClick={() => {
              handleEdit(record);
            }}
          >
            {t('tenant.clusters.actions.edit')}
          </Button>
          <Popconfirm
            title={t('tenant.clusters.deleteConfirm')}
            onConfirm={() => void handleDelete(record.id)}
          >
            <Button type="link" danger>
              {t('tenant.clusters.actions.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-semibold">{t('tenant.clusters.title')}</h1>
          <p className="text-slate-500">{t('tenant.clusters.subtitle')}</p>
        </div>
        <Button type="primary" onClick={handleCreate}>
          {t('tenant.clusters.createButton')}
        </Button>
      </div>

      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <div className="text-slate-500">{t('tenant.clusters.stats.total')}</div>
            <div className="text-2xl font-bold">{total}</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <div className="text-slate-500">{t('tenant.clusters.stats.healthy')}</div>
            <div className="text-2xl font-bold text-green-600">{healthyCount}</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <div className="text-slate-500">{t('tenant.clusters.stats.unhealthy')}</div>
            <div className="text-2xl font-bold text-red-600">{unhealthyCount}</div>
          </Card>
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={clusters}
        rowKey="id"
        loading={loading}
        pagination={{ total: clusters.length, pageSize: 10 }}
      />

      <Modal
        title={editingCluster ? t('tenant.clusters.editTitle') : t('tenant.clusters.createTitle')}
        open={isModalVisible}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        confirmLoading={submitting}
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

      <Drawer
        title={t('tenant.clusters.healthDrawer.title')}
        placement="right"
        onClose={closeHealthDrawer}
        open={isHealthDrawerVisible}
        size="default"
      >
        {loading ? (
          <div>{t('tenant.clusters.healthDrawer.loading')}</div>
        ) : clusterHealth ? (
          <Descriptions column={1} bordered>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.status')}>
              {getStatusTag(clusterHealth.status)}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.nodeCount')}>
              {clusterHealth.node_count}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.cpuUsage')}>
              {clusterHealth.cpu_usage !== null ? `${clusterHealth.cpu_usage.toFixed(2)}%` : 'N/A'}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.memoryUsage')}>
              {clusterHealth.memory_usage !== null
                ? `${clusterHealth.memory_usage.toFixed(2)}%`
                : 'N/A'}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.checkedAt')}>
              {clusterHealth.checked_at
                ? new Date(clusterHealth.checked_at).toLocaleString()
                : 'N/A'}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <div>{t('tenant.clusters.healthDrawer.noData')}</div>
        )}
      </Drawer>
    </div>
  );
};
