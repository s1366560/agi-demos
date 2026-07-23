import { useCallback, useEffect, useState } from 'react';

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
  InputNumber,
  Select,
  Switch,
  Table,
  Alert,
  theme,
} from 'antd';
import { Copy, Server, Network, HardDrive } from 'lucide-react';

import { clusterService } from '../../services/clusterService';
import {
  useCurrentCluster,
  useClusterHealth,
  useClusterLoading,
  useClusterSubmitting,
  useClusterActions,
} from '../../stores/cluster';

import { ClusterFormFields } from './utils/ClusterFormFields';
import { parseProviderConfig } from './utils/clusterFormUtils';
import { formatDate, getStatusColor } from './utils/instanceUtils';

import type { ACPRunnerPool, ACPRunnerTokenResponse } from '@/types/acp';

import type { ClusterUpdate } from '../../services/clusterService';

const { Title, Text } = Typography;

interface ClusterEditFormValues {
  name: string;
  compute_provider?: string | undefined;
  proxy_endpoint?: string | undefined;
  provider_config?: string | undefined;
}

interface RunnerPoolFormValues {
  poolKey: string;
  name: string;
  mode: 'kubernetes' | 'self_hosted';
  enabled: boolean;
  labelsText?: string | undefined;
  capacityPolicyText?: string | undefined;
  schedulingPolicyText?: string | undefined;
}

const parseJsonObject = (value: string | undefined): Record<string, unknown> => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return {};
  }
  const parsed: unknown = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Expected JSON object');
  }
  return parsed as Record<string, unknown>;
};

export const ClusterDetail: React.FC = () => {
  const { clusterId } = useParams<{ clusterId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [runnerModalVisible, setRunnerModalVisible] = useState(false);
  const [runnerPools, setRunnerPools] = useState<ACPRunnerPool[]>([]);
  const [runnerToken, setRunnerToken] = useState<ACPRunnerTokenResponse | null>(null);
  const [form] = Form.useForm<ClusterEditFormValues>();
  const [runnerForm] = Form.useForm<RunnerPoolFormValues>();

  const cluster = useCurrentCluster();
  const clusterHealth = useClusterHealth();
  const isLoading = useClusterLoading();
  const isSubmitting = useClusterSubmitting();
  const { getCluster, updateCluster, deleteCluster, getClusterHealth, clearError, reset } =
    useClusterActions();

  const loadRunnerPools = useCallback(
    async (id: string) => {
      try {
        const pools = await clusterService.listAcpRunnerPools(id);
        setRunnerPools(pools);
      } catch {
        message.error(
          t('tenant.clusters.acpRunners.loadFailed', {
            defaultValue: 'Failed to load runner pools',
          })
        );
      }
    },
    [t]
  );

  useEffect(() => {
    if (clusterId) {
      void getCluster(clusterId);
      void getClusterHealth(clusterId);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- load runner pools on mount, same pattern as getCluster/getClusterHealth
      void loadRunnerPools(clusterId);
    }
    return () => {
      clearError();
      reset();
    };
  }, [clusterId, getCluster, getClusterHealth, loadRunnerPools, clearError, reset]);

  const handleBack = () => {
    // Relative navigation: works under both /tenant/clusters/:id and /tenant/:tenantId/clusters/:id
    void navigate('..');
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
    let values: ClusterEditFormValues;
    try {
      values = await form.validateFields();
    } catch {
      // antd validation errors are shown inline on the form
      return;
    }

    let providerConfig: Record<string, unknown> | undefined;
    try {
      providerConfig = parseProviderConfig(values.provider_config);
    } catch {
      message.error(t('tenant.clusters.invalidJsonError'));
      return;
    }

    const updateData: ClusterUpdate = { name: values.name };
    if (values.compute_provider !== undefined) {
      updateData.compute_provider = values.compute_provider;
    }
    if (values.proxy_endpoint !== undefined) {
      updateData.proxy_endpoint = values.proxy_endpoint;
    }
    if (providerConfig) {
      updateData.provider_config = providerConfig;
    }
    if (!clusterId) {
      return;
    }
    try {
      await updateCluster(clusterId, updateData);
      message.success(t('tenant.clusters.updatedSuccess'));
      setEditModalVisible(false);
    } catch {
      message.error(
        t('tenant.clusters.saveFailedError', { defaultValue: 'Failed to save the cluster' })
      );
    }
  };

  const handleDelete = async () => {
    if (clusterId) {
      await deleteCluster(clusterId);
      message.success(t('tenant.clusters.deletedSuccess'));
      void navigate('..');
    }
  };

  const handleRefreshHealth = async () => {
    if (clusterId) {
      await getClusterHealth(clusterId);
      message.success(
        t('tenant.clusters.healthRefreshed', { defaultValue: 'Cluster health refreshed' })
      );
    }
  };

  const handleCreateRunnerPool = () => {
    setRunnerToken(null);
    runnerForm.setFieldsValue({
      mode: 'self_hosted',
      enabled: true,
      labelsText: '{}',
      capacityPolicyText: '{"max_sessions":1}',
      schedulingPolicyText: '{}',
    });
    setRunnerModalVisible(true);
  };

  const handleRunnerPoolSubmit = async () => {
    if (!clusterId) return;

    let values: RunnerPoolFormValues;
    try {
      values = await runnerForm.validateFields();
    } catch {
      // antd validation errors are shown inline on the form
      return;
    }

    let labels: Record<string, string>;
    let capacityPolicy: Record<string, unknown>;
    let schedulingPolicy: Record<string, unknown>;
    try {
      labels = parseJsonObject(values.labelsText) as Record<string, string>;
      capacityPolicy = parseJsonObject(values.capacityPolicyText);
      schedulingPolicy = parseJsonObject(values.schedulingPolicyText);
    } catch {
      message.error(t('tenant.clusters.invalidJsonError'));
      return;
    }

    try {
      const created = await clusterService.createAcpRunnerPool(clusterId, {
        poolKey: values.poolKey,
        name: values.name,
        mode: values.mode,
        enabled: values.enabled,
        labels,
        capacityPolicy,
        schedulingPolicy,
      });
      message.success(
        t('tenant.clusters.acpRunners.created', { defaultValue: 'Runner pool created' })
      );
      await loadRunnerPools(clusterId);
      const token = await clusterService.createAcpRunnerToken(clusterId, created.poolKey, {
        expiresInHours: 24,
      });
      setRunnerToken(token);
    } catch {
      message.error(
        t('tenant.clusters.acpRunners.createFailed', {
          defaultValue: 'Failed to create the runner pool',
        })
      );
    }
  };

  const handleGenerateRunnerToken = async (pool: ACPRunnerPool) => {
    if (!clusterId) return;
    runnerForm.setFieldsValue({
      poolKey: pool.poolKey,
      name: pool.name,
      mode: pool.mode,
      enabled: pool.enabled,
      labelsText: JSON.stringify(pool.labels ?? {}, null, 2),
      capacityPolicyText: JSON.stringify(pool.capacityPolicy ?? {}, null, 2),
      schedulingPolicyText: JSON.stringify(pool.schedulingPolicy ?? {}, null, 2),
    });
    try {
      const token = await clusterService.createAcpRunnerToken(clusterId, pool.poolKey, {
        expiresInHours: 24,
      });
      setRunnerToken(token);
      setRunnerModalVisible(true);
    } catch {
      message.error(
        t('tenant.clusters.acpRunners.tokenFailed', {
          defaultValue: 'Failed to generate the registration token',
        })
      );
    }
  };

  const usageColor = (usage: number) => {
    if (usage > 80) {
      return token.colorError;
    }
    if (usage > 60) {
      return token.colorWarning;
    }
    return token.colorSuccess;
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
              value={clusterHealth ? clusterHealth.node_count : '-'}
              prefix={<Network size={20} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('tenant.clusters.detail.cpuUsage')}
              value={clusterHealth?.cpu_usage ?? '-'}
              prefix={<HardDrive size={20} />}
              {...(clusterHealth?.cpu_usage != null
                ? {
                    suffix: '%',
                    styles: { content: { color: usageColor(clusterHealth.cpu_usage) } },
                  }
                : {})}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title={t('tenant.clusters.detail.memoryUsage')}
              value={clusterHealth?.memory_usage ?? '-'}
              prefix={<HardDrive size={20} />}
              {...(clusterHealth?.memory_usage != null
                ? {
                    suffix: '%',
                    styles: { content: { color: usageColor(clusterHealth.memory_usage) } },
                  }
                : {})}
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
            <Tag color={getStatusColor(cluster.status)}>
              {t(`tenant.clusters.status.${cluster.status}`, { defaultValue: cluster.status })}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.healthStatus')}>
            {cluster.health_status ? (
              <Tag color={getStatusColor(cluster.health_status)}>
                {t(`tenant.clusters.status.${cluster.health_status}`, {
                  defaultValue: cluster.health_status,
                })}
              </Tag>
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
              ? formatDate(cluster.last_health_check)
              : t('common.time.never')}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.createdAt')}>
            {formatDate(cluster.created_at)}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.detail.updatedAt')}>
            {cluster.updated_at ? formatDate(cluster.updated_at) : t('common.time.never')}
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

      <Card
        title={t('tenant.clusters.acpRunners.title', { defaultValue: 'ACP Runners' })}
        extra={
          <Button type="primary" onClick={handleCreateRunnerPool}>
            {t('tenant.clusters.acpRunners.addPool', { defaultValue: 'Add Pool' })}
          </Button>
        }
      >
        <Table
          rowKey="poolKey"
          dataSource={runnerPools}
          pagination={false}
          columns={[
            {
              title: t('tenant.clusters.acpRunners.pool', { defaultValue: 'Pool' }),
              dataIndex: 'name',
              render: (_value, pool) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{pool.name}</Text>
                  <Text type="secondary">{pool.poolKey}</Text>
                </Space>
              ),
            },
            {
              title: t('tenant.clusters.acpRunners.mode', { defaultValue: 'Mode' }),
              dataIndex: 'mode',
              render: (mode: string) => <Tag>{mode}</Tag>,
            },
            {
              title: t('tenant.clusters.acpRunners.runners', { defaultValue: 'Runners' }),
              dataIndex: 'readyRunnerCount',
              render: (_value, pool) => `${pool.readyRunnerCount}/${pool.runnerCount}`,
            },
            {
              title: t('tenant.clusters.acpRunners.sessions', { defaultValue: 'Sessions' }),
              dataIndex: 'activeSessionCount',
            },
            {
              title: t('common.actions.label'),
              key: 'actions',
              render: (_value, pool) => (
                <Button onClick={() => void handleGenerateRunnerToken(pool)}>
                  {t('tenant.clusters.acpRunners.token', { defaultValue: 'Registration Token' })}
                </Button>
              ),
            },
          ]}
        />
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
            {clusterHealth?.node_count ?? (
              <Text type="secondary">
                {t('tenant.clusters.detail.notAvailable', { defaultValue: 'N/A' })}
              </Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('tenant.clusters.healthDrawer.checkedAt')}>
            {clusterHealth?.checked_at
              ? formatDate(clusterHealth.checked_at)
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
          <ClusterFormFields />
        </Form>
      </Modal>

      <Modal
        title={t('tenant.clusters.acpRunners.createTitle', {
          defaultValue: 'ACP Runner Pool',
        })}
        open={runnerModalVisible}
        onOk={() => {
          if (runnerToken) {
            setRunnerModalVisible(false);
            setRunnerToken(null);
            return;
          }
          void handleRunnerPoolSubmit();
        }}
        onCancel={() => {
          setRunnerModalVisible(false);
          setRunnerToken(null);
        }}
        width={720}
      >
        <Form form={runnerForm} layout="vertical">
          <Form.Item
            name="poolKey"
            label={t('tenant.clusters.acpRunners.poolKey', { defaultValue: 'Pool Key' })}
            rules={[
              {
                required: !runnerToken,
                message: t('tenant.clusters.acpRunners.poolKeyRequired', {
                  defaultValue: 'Pool key is required',
                }),
              },
            ]}
          >
            <Input
              disabled={Boolean(runnerToken)}
              placeholder={t('tenant.clusters.acpRunners.poolKeyPlaceholder', {
                defaultValue: 'local-laptop',
              })}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('common.forms.name')}
            rules={[
              {
                required: !runnerToken,
                message: t('tenant.clusters.acpRunners.nameRequired', {
                  defaultValue: 'Name is required',
                }),
              },
            ]}
          >
            <Input disabled={Boolean(runnerToken)} />
          </Form.Item>
          <Form.Item
            name="mode"
            label={t('tenant.clusters.acpRunners.modeLabel', { defaultValue: 'Mode' })}
          >
            <Select
              disabled={Boolean(runnerToken)}
              options={[
                {
                  value: 'self_hosted',
                  label: t('tenant.clusters.acpRunners.modes.selfHosted', {
                    defaultValue: 'Self-hosted',
                  }),
                },
                {
                  value: 'kubernetes',
                  label: t('tenant.clusters.acpRunners.modes.kubernetes', {
                    defaultValue: 'Kubernetes',
                  }),
                },
              ]}
            />
          </Form.Item>
          <Form.Item name="enabled" label={t('common.forms.status')} valuePropName="checked">
            <Switch disabled={Boolean(runnerToken)} />
          </Form.Item>
          <Form.Item
            name="labelsText"
            label={t('tenant.clusters.acpRunners.labelsJson', { defaultValue: 'Labels JSON' })}
          >
            <Input.TextArea disabled={Boolean(runnerToken)} rows={3} spellCheck={false} />
          </Form.Item>
          <Form.Item
            name="capacityPolicyText"
            label={t('tenant.clusters.acpRunners.capacityPolicyJson', {
              defaultValue: 'Capacity policy JSON',
            })}
          >
            <Input.TextArea disabled={Boolean(runnerToken)} rows={3} spellCheck={false} />
          </Form.Item>
          <Form.Item
            name="schedulingPolicyText"
            label={t('tenant.clusters.acpRunners.schedulingPolicyJson', {
              defaultValue: 'Scheduling policy JSON',
            })}
          >
            <Input.TextArea disabled={Boolean(runnerToken)} rows={3} spellCheck={false} />
          </Form.Item>
          <Form.Item
            label={t('tenant.clusters.acpRunners.tokenExpiry', { defaultValue: 'Token expiry' })}
          >
            <InputNumber
              disabled
              value={24}
              addonAfter={t('tenant.clusters.acpRunners.hours', { defaultValue: 'hours' })}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Form>
        {runnerToken ? (
          <Alert
            className="mt-4"
            type="success"
            showIcon
            message={t('tenant.clusters.acpRunners.tokenReady', {
              defaultValue: 'Registration token created. Copy it now; it will not be shown again.',
            })}
            description={
              <Space direction="vertical" className="w-full">
                <Input.TextArea value={runnerToken.installCommand} autoSize readOnly />
                <Button
                  size="small"
                  icon={<Copy size={14} />}
                  onClick={() => {
                    void navigator.clipboard
                      .writeText(runnerToken.installCommand)
                      .then(() => message.success(t('common.copied')));
                  }}
                >
                  {t('common.copy')}
                </Button>
                <Text type="secondary">
                  {t('tenant.clusters.acpRunners.expiresAt', {
                    defaultValue: 'Expires at',
                  })}
                  : {runnerToken.expiresAt ? formatDate(runnerToken.expiresAt) : '-'}
                </Text>
              </Space>
            }
          />
        ) : null}
      </Modal>
    </div>
  );
};
