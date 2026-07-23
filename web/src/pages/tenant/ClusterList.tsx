import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';

import {
  Table,
  Button,
  Modal,
  Form,
  Tag,
  Space,
  Popconfirm,
  message,
  Descriptions,
  Drawer,
  Card,
  Row,
  Col,
  Input,
  Select,
  Alert,
} from 'antd';
import { RefreshCw, Search as SearchIcon } from 'lucide-react';

import {
  useClusters,
  useClusterHealth,
  useClusterLoading,
  useClusterSubmitting,
  useClusterError,
  useClusterTotal,
  useClusterPage,
  useClusterPageSize,
  useClusterActions,
} from '../../stores/cluster';

import { ClusterFormFields } from './utils/ClusterFormFields';
import { parseProviderConfig } from './utils/clusterFormUtils';
import { formatDate, getStatusColor } from './utils/instanceUtils';

import type { ClusterResponse } from '../../services/clusterService';

interface FormValues {
  name: string;
  compute_provider?: string;
  proxy_endpoint?: string;
  provider_config?: string;
}

export const ClusterList: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [form] = Form.useForm<FormValues>();
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [isHealthDrawerVisible, setIsHealthDrawerVisible] = useState(false);
  const [editingCluster, setEditingCluster] = useState<ClusterResponse | null>(null);
  // The cluster list API has no search/status params, so filtering is client-side
  // over the loaded page and mirrored into the URL for shareability.
  const [search, setSearch] = useState(searchParams.get('search') ?? '');
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') ?? 'all');

  const clusters = useClusters();
  const clusterHealth = useClusterHealth();
  const loading = useClusterLoading();
  const submitting = useClusterSubmitting();
  const error = useClusterError();
  const total = useClusterTotal();
  const page = useClusterPage();
  const pageSize = useClusterPageSize();
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
    const pageParam = Number(searchParams.get('page'));
    const pageSizeParam = Number(searchParams.get('page_size'));
    void listClusters({
      ...(Number.isInteger(pageParam) && pageParam > 1 ? { page: pageParam } : {}),
      ...(Number.isInteger(pageSizeParam) && pageSizeParam > 0 ? { page_size: pageSizeParam } : {}),
    });
    return () => {
      clearError();
      reset();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listClusters, clearError, reset]);

  // Reflect page/pageSize/search/status in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (pageSize !== 20) {
      next.set('page_size', String(pageSize));
    } else {
      next.delete('page_size');
    }
    if (search) {
      next.set('search', search);
    } else {
      next.delete('search');
    }
    if (statusFilter !== 'all') {
      next.set('status', statusFilter);
    } else {
      next.delete('status');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [page, pageSize, search, statusFilter, searchParams, setSearchParams]);

  const filteredClusters = useMemo(() => {
    const term = search.trim().toLowerCase();
    return clusters.filter((cluster) => {
      if (statusFilter !== 'all' && cluster.status !== statusFilter) return false;
      if (!term) return true;
      return (
        cluster.name.toLowerCase().includes(term) ||
        cluster.compute_provider.toLowerCase().includes(term)
      );
    });
  }, [clusters, search, statusFilter]);

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
    try {
      await deleteCluster(id);
      message.success(t('tenant.clusters.deletedSuccess'));
    } catch {
      // The inline error alert surfaces API failures
    }
  };

  const handleHealthCheck = async (id: string) => {
    setCurrentCluster(clusters.find((c) => c.id === id) || null);
    try {
      await getClusterHealth(id);
      setIsHealthDrawerVisible(true);
    } catch {
      // The inline error alert surfaces the failure; keep stale health data hidden
    }
  };

  const handleModalOk = () => {
    void form
      .validateFields()
      .then(async (values) => {
        let providerConfig: Record<string, unknown> | undefined;
        try {
          providerConfig = parseProviderConfig(values.provider_config);
        } catch {
          form.setFields([
            { name: 'provider_config', errors: [t('tenant.clusters.invalidJsonError')] },
          ]);
          return;
        }

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
        if (providerConfig) {
          base.provider_config = providerConfig;
        }

        try {
          if (editingCluster) {
            await updateCluster(editingCluster.id, base);
            message.success(t('tenant.clusters.updatedSuccess'));
          } else {
            await createCluster(base);
            message.success(t('tenant.clusters.createdSuccess'));
          }
          setIsModalVisible(false);
        } catch {
          // The inline error alert surfaces API failures
        }
      })
      .catch(() => {
        // antd validation errors are shown inline on the form
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
    return (
      <Tag color={getStatusColor(status)}>
        {t(`tenant.clusters.status.${status}`, { defaultValue: status })}
      </Tag>
    );
  };

  const handleViewCluster = (id: string): void => {
    // Relative navigation: works under both /tenant/clusters and /tenant/:tenantId/clusters
    void navigate(`./${id}`);
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
          <Button
            type="link"
            onClick={() => {
              handleViewCluster(record.id);
            }}
          >
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
            okButtonProps={{ danger: true }}
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
    <div className="max-w-full mx-auto w-full flex flex-col gap-8 overflow-x-hidden">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('tenant.clusters.title')}</h1>
          <p className="text-slate-500">{t('tenant.clusters.subtitle')}</p>
        </div>
        <Button type="primary" onClick={handleCreate}>
          {t('tenant.clusters.createButton')}
        </Button>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <Card>
            <div className="text-slate-500">{t('tenant.clusters.stats.total')}</div>
            <div className="text-2xl font-bold">{total}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <div className="text-slate-500">
              {t('tenant.clusters.stats.healthy')}
              <span className="ml-1 text-xs">{t('tenant.clusters.stats.pageNote')}</span>
            </div>
            <div className="text-2xl font-bold text-green-600">{healthyCount}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <div className="text-slate-500">
              {t('tenant.clusters.stats.unhealthy')}
              <span className="ml-1 text-xs">{t('tenant.clusters.stats.pageNote')}</span>
            </div>
            <div className="text-2xl font-bold text-red-600">{unhealthyCount}</div>
          </Card>
        </Col>
      </Row>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          placeholder={t('tenant.clusters.searchPlaceholder', 'Search clusters')}
          aria-label={t('tenant.clusters.searchPlaceholder', 'Search clusters')}
          allowClear
          prefix={<SearchIcon size={14} aria-hidden="true" />}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          className="w-full sm:max-w-75"
        />
        <Select
          aria-label={t('tenant.clusters.columns.status')}
          value={statusFilter}
          onChange={setStatusFilter}
          className="w-full sm:w-40"
          options={[
            { value: 'all', label: t('tenant.clusters.status.all', { defaultValue: 'All' }) },
            ...['active', 'pending', 'provisioning', 'maintenance', 'error', 'inactive'].map(
              (status) => ({
                value: status,
                label: t(`tenant.clusters.status.${status}`, { defaultValue: status }),
              })
            ),
          ]}
        />
        <Button
          icon={<RefreshCw size={14} aria-hidden="true" />}
          onClick={() => void listClusters({})}
          loading={loading}
          aria-label={t('common.refresh')}
        >
          {t('common.refresh')}
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          showIcon
          closable={{ onClose: clearError }}
          title={error}
          action={
            <Button size="small" onClick={() => void listClusters({})}>
              {t('common.retry')}
            </Button>
          }
        />
      )}

      <Table
        columns={columns}
        dataSource={filteredClusters}
        rowKey="id"
        loading={loading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (nextPage, nextPageSize) => {
            void listClusters({ page: nextPage, page_size: nextPageSize });
          },
        }}
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
          <ClusterFormFields />
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
              {clusterHealth.cpu_usage !== null
                ? `${clusterHealth.cpu_usage.toFixed(2)}%`
                : t('tenant.clusters.detail.notAvailable')}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.memoryUsage')}>
              {clusterHealth.memory_usage !== null
                ? `${clusterHealth.memory_usage.toFixed(2)}%`
                : t('tenant.clusters.detail.notAvailable')}
            </Descriptions.Item>
            <Descriptions.Item label={t('tenant.clusters.healthDrawer.checkedAt')}>
              {clusterHealth.checked_at
                ? formatDate(clusterHealth.checked_at)
                : t('tenant.clusters.detail.notAvailable')}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <div>{t('tenant.clusters.healthDrawer.noData')}</div>
        )}
      </Drawer>
    </div>
  );
};
