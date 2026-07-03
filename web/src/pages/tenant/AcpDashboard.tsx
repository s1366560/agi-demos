import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { Pencil, PlayCircle, Plus, RefreshCw, Trash2, X } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { acpService } from '@/services/acpService';

import {
  ACP_SECRET_UNCHANGED_SENTINEL,
  type ACPConfigValue,
  type ACPConfigValueType,
  type ACPExternalSession,
  type ACPRunnerPool,
  type ACPTransport,
  type ACPOperationEvent,
  type TenantACPStatus,
  type TenantACPTestResponse,
  type TenantExternalACPAgent,
  type UpsertTenantACPAgentRequest,
} from '@/types/acp';

import type { ColumnsType } from 'antd/es/table';

const { Text, Title } = Typography;
const STATUS_REFRESH_INTERVAL = 10_000;

interface ConfigEntryFormValue {
  name?: string | undefined;
  type?: ACPConfigValueType | undefined;
  value?: string | undefined;
}

interface AgentFormValues {
  agentKey?: string | undefined;
  name: string;
  transport: ACPTransport;
  command?: string | undefined;
  argsText?: string | undefined;
  url?: string | undefined;
  runnerPoolKey?: string | undefined;
  requiredLabelsText?: string | undefined;
  cwdPolicyText?: string | undefined;
  enabled: boolean;
  envEntries: ConfigEntryFormValue[];
  headerEntries: ConfigEntryFormValue[];
}

interface TestFormValues {
  cwd: string;
  projectId?: string | undefined;
  prompt: string;
  timeoutSeconds: number;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function recordToEntries(record: Record<string, ACPConfigValue>): ConfigEntryFormValue[] {
  return Object.entries(record).map(([name, value]) => ({
    name,
    type: value.type,
    value: value.type === 'env_ref' ? (value.value ?? '') : '',
  }));
}

function entriesToRecord(
  entries: ConfigEntryFormValue[] | undefined,
  existing: Record<string, ACPConfigValue> | undefined
): Record<string, ACPConfigValue> {
  const result: Record<string, ACPConfigValue> = {};
  for (const entry of entries ?? []) {
    const name = entry.name?.trim();
    if (!name || !entry.type) continue;
    const value = entry.value?.trim();
    const existingEntry = existing?.[name];
    result[name] = {
      type: entry.type,
      value:
        entry.type === 'secret' &&
        !value &&
        existingEntry?.type === 'secret' &&
        existingEntry.has_value
          ? ACP_SECRET_UNCHANGED_SENTINEL
          : value,
    };
  }
  return result;
}

function parseArgs(text: string | undefined): string[] {
  return (text ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseJsonObject(text: string | undefined, fallback: Record<string, unknown>) {
  const trimmed = text?.trim();
  if (!trimmed) return fallback;
  const parsed: unknown = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Expected a JSON object');
  }
  return parsed as Record<string, unknown>;
}

function agentToFormValues(agent: TenantExternalACPAgent): AgentFormValues {
  return {
    agentKey: agent.agentKey,
    name: agent.name,
    transport: agent.transport,
    command: agent.command ?? undefined,
    argsText: agent.args.join('\n'),
    url: agent.url ?? undefined,
    runnerPoolKey: agent.runnerPoolKey ?? undefined,
    requiredLabelsText:
      Object.keys(agent.requiredLabels ?? {}).length > 0
        ? JSON.stringify(agent.requiredLabels, null, 2)
        : '',
    cwdPolicyText:
      Object.keys(agent.cwdPolicy ?? {}).length > 0 ? JSON.stringify(agent.cwdPolicy, null, 2) : '',
    enabled: agent.enabled,
    envEntries: recordToEntries(agent.env),
    headerEntries: recordToEntries(agent.headers),
  };
}

export const AcpDashboard: React.FC = () => {
  const { tenantId: urlTenantId } = useParams<{ tenantId?: string | undefined }>();
  const { t } = useTranslation();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = urlTenantId || currentTenant?.id || null;
  const [statusData, setStatusData] = useState<TenantACPStatus | null>(null);
  const [runnerPools, setRunnerPools] = useState<ACPRunnerPool[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [testDrawerOpen, setTestDrawerOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<TenantExternalACPAgent | null>(null);
  const [testingAgent, setTestingAgent] = useState<TenantExternalACPAgent | null>(null);
  const [testResult, setTestResult] = useState<TenantACPTestResponse | null>(null);
  const [form] = Form.useForm<AgentFormValues>();
  const [testForm] = Form.useForm<TestFormValues>();

  const agents = statusData?.agents ?? [];
  const sessions = statusData?.sessions ?? [];
  const recentEvents = statusData?.recentEvents ?? [];

  const loadStatus = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const response = await acpService.getStatus(tenantId);
      const pools = await acpService.listRunnerPools(tenantId);
      setStatusData(response);
      setRunnerPools(pools);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t('tenant.acp.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [tenantId, t]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    if (!tenantId) return;
    const timer = window.setInterval(() => {
      void loadStatus();
    }, STATUS_REFRESH_INTERVAL);
    return () => {
      window.clearInterval(timer);
    };
  }, [loadStatus, tenantId]);

  const openCreateDrawer = useCallback(() => {
    setEditingAgent(null);
    form.setFieldsValue({
      transport: 'stdio',
      enabled: true,
      envEntries: [],
      headerEntries: [],
    });
    setDrawerOpen(true);
  }, [form]);

  const openEditDrawer = useCallback(
    (agent: TenantExternalACPAgent) => {
      setEditingAgent(agent);
      form.setFieldsValue(agentToFormValues(agent));
      setDrawerOpen(true);
    },
    [form]
  );

  const openTestDrawer = useCallback(
    (agent: TenantExternalACPAgent) => {
      setTestingAgent(agent);
      setTestResult(null);
      testForm.setFieldsValue({
        cwd: '/tmp',
        prompt: t('tenant.acp.test.defaultPrompt', { defaultValue: 'Reply with PONG only.' }),
        timeoutSeconds: 30,
      });
      setTestDrawerOpen(true);
    },
    [t, testForm]
  );

  const submitAgent = useCallback(async () => {
    if (!tenantId) return;
    const values = await form.validateFields();
    let payload: UpsertTenantACPAgentRequest;
    try {
      payload = {
        name: values.name,
        transport: values.transport,
        command: values.command || null,
        args: parseArgs(values.argsText),
        url: values.url || null,
        enabled: values.enabled,
        env: entriesToRecord(values.envEntries, editingAgent?.env),
        headers: entriesToRecord(values.headerEntries, editingAgent?.headers),
        runnerPoolKey: values.runnerPoolKey || null,
        requiredLabels: parseJsonObject(values.requiredLabelsText, {}) as Record<string, string>,
        cwdPolicy: parseJsonObject(values.cwdPolicyText, {}),
      };
    } catch {
      message.error(t('tenant.acp.errors.invalidJson', { defaultValue: 'Invalid JSON object' }));
      return;
    }
    setSaving(true);
    try {
      if (editingAgent) {
        await acpService.updateAgent(tenantId, editingAgent.agentKey, payload);
        message.success(t('tenant.acp.messages.updated'));
      } else {
        const agentKey = values.agentKey?.trim();
        if (!agentKey) {
          message.error(t('tenant.acp.errors.agentKeyRequired'));
          return;
        }
        await acpService.createAgent(tenantId, { ...payload, agentKey });
        message.success(t('tenant.acp.messages.created'));
      }
      setDrawerOpen(false);
      await loadStatus();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t('tenant.acp.errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  }, [editingAgent, form, loadStatus, tenantId, t]);

  const deleteAgent = useCallback(
    async (agent: TenantExternalACPAgent) => {
      if (!tenantId) return;
      try {
        await acpService.deleteAgent(tenantId, agent.agentKey);
        message.success(t('tenant.acp.messages.deleted'));
        await loadStatus();
      } catch (error) {
        message.error(error instanceof Error ? error.message : t('tenant.acp.errors.deleteFailed'));
      }
    },
    [loadStatus, tenantId, t]
  );

  const submitTest = useCallback(async () => {
    if (!tenantId || !testingAgent) return;
    const values = await testForm.validateFields();
    setTesting(true);
    setTestResult(null);
    try {
      const result = await acpService.testAgent(tenantId, testingAgent.agentKey, {
        cwd: values.cwd,
        projectId: values.projectId || null,
        prompt: values.prompt,
        timeoutSeconds: values.timeoutSeconds,
        mcpServers: [],
      });
      setTestResult(result);
      await loadStatus();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t('tenant.acp.errors.testFailed'));
    } finally {
      setTesting(false);
    }
  }, [loadStatus, tenantId, testForm, testingAgent, t]);

  const agentColumns: ColumnsType<TenantExternalACPAgent> = useMemo(
    () => [
      {
        title: t('tenant.acp.columns.agent'),
        dataIndex: 'name',
        key: 'name',
        render: (_, agent) => (
          <Space orientation="vertical" size={0}>
            <Text strong>{agent.name}</Text>
            <Text type="secondary">{agent.agentKey}</Text>
          </Space>
        ),
      },
      {
        title: t('tenant.acp.columns.transport'),
        dataIndex: 'transport',
        key: 'transport',
        width: 120,
        render: (transport: ACPTransport) => <Tag>{transport}</Tag>,
      },
      {
        title: t('tenant.acp.columns.runnerPool', { defaultValue: 'Runner Pool' }),
        dataIndex: 'runnerPoolKey',
        key: 'runnerPoolKey',
        width: 150,
        render: (value?: string | null) => value || <Tag>direct</Tag>,
      },
      {
        title: t('tenant.acp.columns.status'),
        key: 'status',
        width: 180,
        render: (_, agent) => (
          <Space>
            <Tag color={agent.enabled ? 'green' : 'default'}>
              {agent.enabled ? t('common.status.enabled') : t('common.status.disabled')}
            </Tag>
            <Tag color={agent.available ? 'green' : 'red'}>
              {agent.available ? t('common.ready') : t('common.status.unavailable')}
            </Tag>
          </Space>
        ),
      },
      {
        title: t('tenant.acp.columns.sessions'),
        dataIndex: 'activeSessions',
        key: 'activeSessions',
        width: 120,
      },
      {
        title: t('tenant.acp.columns.lastLatency'),
        dataIndex: 'lastLatencyMs',
        key: 'lastLatencyMs',
        width: 130,
        render: (value?: number | null) => (value == null ? '-' : `${String(value)} ms`),
      },
      {
        title: t('tenant.acp.columns.lastError'),
        dataIndex: 'lastError',
        key: 'lastError',
        ellipsis: true,
        render: (value?: string | null) => value || '-',
      },
      {
        title: t('common.actions.label'),
        key: 'actions',
        width: 190,
        render: (_, agent) => (
          <Space>
            <Button
              icon={<PlayCircle size={16} />}
              onClick={() => {
                openTestDrawer(agent);
              }}
              aria-label={t('tenant.acp.actions.test')}
            />
            <Button
              icon={<Pencil size={16} />}
              onClick={() => {
                openEditDrawer(agent);
              }}
              aria-label={t('common.edit')}
            />
            <Popconfirm
              title={t('tenant.acp.deleteConfirm')}
              onConfirm={() => void deleteAgent(agent)}
            >
              <Button danger icon={<Trash2 size={16} />} aria-label={t('common.delete')} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [deleteAgent, openEditDrawer, openTestDrawer, t]
  );

  const sessionColumns: ColumnsType<ACPExternalSession> = useMemo(
    () => [
      { title: t('tenant.acp.columns.session'), dataIndex: 'session_id', key: 'session_id' },
      { title: t('tenant.acp.columns.agent'), dataIndex: 'agent_id', key: 'agent_id' },
      {
        title: t('tenant.acp.columns.createdAt'),
        dataIndex: 'created_at',
        key: 'created_at',
        render: formatTime,
      },
      {
        title: t('tenant.acp.columns.lastActivity'),
        dataIndex: 'last_activity',
        key: 'last_activity',
        render: formatTime,
      },
    ],
    [t]
  );

  const eventColumns: ColumnsType<ACPOperationEvent> = useMemo(
    () => [
      { title: t('tenant.acp.columns.agent'), dataIndex: 'agent_id', key: 'agent_id' },
      { title: t('tenant.acp.columns.action'), dataIndex: 'action', key: 'action' },
      {
        title: t('tenant.acp.columns.status'),
        dataIndex: 'status',
        key: 'status',
        render: (value: string) => <Tag color={value === 'success' ? 'green' : 'red'}>{value}</Tag>,
      },
      {
        title: t('tenant.acp.columns.duration'),
        dataIndex: 'duration_ms',
        key: 'duration_ms',
        render: (value?: number | null) => (value == null ? '-' : `${String(value)} ms`),
      },
      {
        title: t('tenant.acp.columns.timestamp'),
        dataIndex: 'timestamp',
        key: 'timestamp',
        render: formatTime,
      },
      {
        title: t('tenant.acp.columns.error'),
        dataIndex: 'error',
        key: 'error',
        ellipsis: true,
        render: (value?: string | null) => value || '-',
      },
    ],
    [t]
  );

  const renderConfigEntryList = (
    fieldName: 'envEntries' | 'headerEntries',
    title: string,
    addLabel: string
  ) => (
    <Form.List name={fieldName}>
      {(fields, { add, remove }) => (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Text strong>{title}</Text>
          {fields.map((field) => (
            <Space key={field.key} align="start" style={{ width: '100%' }}>
              <Form.Item
                name={[field.name, 'name']}
                rules={[{ required: true, message: t('tenant.acp.errors.nameRequired') }]}
              >
                <Input placeholder={t('tenant.acp.form.namePlaceholder')} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item name={[field.name, 'type']} initialValue="env_ref">
                <Select
                  style={{ width: 120 }}
                  options={[
                    { value: 'env_ref', label: t('tenant.acp.form.envRef') },
                    { value: 'secret', label: t('tenant.acp.form.secret') },
                  ]}
                />
              </Form.Item>
              <Form.Item noStyle shouldUpdate>
                {({ getFieldValue }) => {
                  const type = getFieldValue([fieldName, field.name, 'type']) as
                    | ACPConfigValueType
                    | undefined;
                  return (
                    <Form.Item name={[field.name, 'value']}>
                      {type === 'secret' ? (
                        <Input.Password
                          placeholder={t('tenant.acp.form.secretPlaceholder')}
                          style={{ width: 260 }}
                        />
                      ) : (
                        <Input
                          placeholder={t('tenant.acp.form.envRefPlaceholder')}
                          style={{ width: 260 }}
                        />
                      )}
                    </Form.Item>
                  );
                }}
              </Form.Item>
              <Button
                icon={<X size={16} />}
                onClick={() => {
                  remove(field.name);
                }}
              />
            </Space>
          ))}
          <Button
            type="dashed"
            icon={<Plus size={16} />}
            onClick={() => {
              add({ type: 'env_ref' });
            }}
          >
            {addLabel}
          </Button>
        </Space>
      )}
    </Form.List>
  );

  if (!tenantId) {
    return (
      <div className="p-6">
        <Empty description={t('tenant.acp.noTenant')} />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <Title level={2} className="m-0">
            {t('tenant.acp.title')}
          </Title>
          <Text type="secondary">{t('tenant.acp.subtitle')}</Text>
        </div>
        <Space>
          <Button
            icon={<RefreshCw size={16} />}
            loading={loading}
            onClick={() => void loadStatus()}
          >
            {t('common.retry')}
          </Button>
          <Button type="primary" icon={<Plus size={16} />} onClick={openCreateDrawer}>
            {t('tenant.acp.actions.addAgent')}
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title={t('tenant.acp.stats.agents')} value={statusData?.agentCount ?? 0} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic
              title={t('tenant.acp.stats.available')}
              value={statusData?.availableCount ?? 0}
            />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic
              title={t('tenant.acp.stats.activeSessions')}
              value={statusData?.activeSessionCount ?? 0}
            />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic
              title={t('tenant.acp.stats.missingEnv')}
              value={statusData?.missingEnvCount ?? 0}
            />
          </Card>
        </Col>
      </Row>

      {statusData && !statusData.enabled ? (
        <Alert type="warning" showIcon title={t('tenant.acp.disabledWarning')} />
      ) : null}

      <Tabs
        items={[
          {
            key: 'agents',
            label: t('tenant.acp.tabs.agents'),
            children: (
              <Card>
                <Table
                  rowKey="agentKey"
                  loading={loading}
                  columns={agentColumns}
                  dataSource={agents}
                  pagination={{ pageSize: 10 }}
                />
              </Card>
            ),
          },
          {
            key: 'sessions',
            label: t('tenant.acp.tabs.sessions'),
            children: (
              <Card>
                <Table
                  rowKey="session_id"
                  columns={sessionColumns}
                  dataSource={sessions}
                  pagination={{ pageSize: 8 }}
                />
              </Card>
            ),
          },
          {
            key: 'events',
            label: t('tenant.acp.tabs.events'),
            children: (
              <Card>
                <Table
                  rowKey={(event) => `${event.agent_id}-${event.action}-${event.timestamp}`}
                  columns={eventColumns}
                  dataSource={recentEvents}
                  pagination={{ pageSize: 8 }}
                />
              </Card>
            ),
          },
        ]}
      />

      <Drawer
        title={editingAgent ? t('tenant.acp.form.editTitle') : t('tenant.acp.form.createTitle')}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
        }}
        size={720}
        extra={
          <Button type="primary" loading={saving} onClick={() => void submitAgent()}>
            {t('common.save')}
          </Button>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="agentKey"
            label={t('tenant.acp.form.agentKey')}
            rules={[{ required: !editingAgent, message: t('tenant.acp.errors.agentKeyRequired') }]}
          >
            <Input disabled={Boolean(editingAgent)} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('common.forms.name')}
            rules={[{ required: true, message: t('tenant.acp.errors.nameRequired') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="enabled" label={t('common.forms.status')} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="transport" label={t('tenant.acp.form.transport')}>
            <Select
              options={[
                { value: 'stdio', label: 'stdio' },
                { value: 'websocket', label: 'websocket' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="runnerPoolKey"
            label={t('tenant.acp.form.runnerPool', { defaultValue: 'Runner Pool' })}
            extra={t('tenant.acp.form.runnerPoolHelp', {
              defaultValue: 'Leave empty to run this ACP agent directly in the API process.',
            })}
          >
            <Select
              allowClear
              placeholder={t('tenant.acp.form.directRunner', { defaultValue: 'Direct transport' })}
              options={runnerPools.map((pool) => ({
                value: pool.poolKey,
                label: `${pool.name} (${pool.mode})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="requiredLabelsText"
            label={t('tenant.acp.form.requiredLabels', { defaultValue: 'Required labels JSON' })}
          >
            <Input.TextArea rows={3} placeholder={'{"region":"local"}'} />
          </Form.Item>
          <Form.Item
            name="cwdPolicyText"
            label={t('tenant.acp.form.cwdPolicy', { defaultValue: 'CWD policy JSON' })}
          >
            <Input.TextArea rows={3} placeholder={'{"allowed_roots":["/workspace"]}'} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) => {
              const transport = getFieldValue('transport') as ACPTransport | undefined;
              return transport === 'websocket' ? (
                <Form.Item
                  name="url"
                  label={t('tenant.acp.form.url')}
                  rules={[{ required: true, message: t('tenant.acp.errors.urlRequired') }]}
                >
                  <Input placeholder="wss://example.com/acp" />
                </Form.Item>
              ) : (
                <>
                  <Form.Item
                    name="command"
                    label={t('tenant.acp.form.command')}
                    rules={[{ required: true, message: t('tenant.acp.errors.commandRequired') }]}
                  >
                    <Input placeholder="uv" />
                  </Form.Item>
                  <Form.Item name="argsText" label={t('tenant.acp.form.args')}>
                    <Input.TextArea rows={4} placeholder={'run\npython\n-m\nagent'} />
                  </Form.Item>
                </>
              );
            }}
          </Form.Item>
          {renderConfigEntryList(
            'envEntries',
            t('tenant.acp.form.env'),
            t('tenant.acp.form.addEnv')
          )}
          {renderConfigEntryList(
            'headerEntries',
            t('tenant.acp.form.headers'),
            t('tenant.acp.form.addHeader')
          )}
        </Form>
      </Drawer>

      <Drawer
        title={t('tenant.acp.test.title', { name: testingAgent?.name ?? '' })}
        open={testDrawerOpen}
        onClose={() => {
          setTestDrawerOpen(false);
        }}
        size={620}
        extra={
          <Button type="primary" loading={testing} onClick={() => void submitTest()}>
            {t('tenant.acp.actions.runTest')}
          </Button>
        }
      >
        <Form form={testForm} layout="vertical">
          <Form.Item
            name="cwd"
            label={t('tenant.acp.test.cwd')}
            rules={[{ required: true, message: t('tenant.acp.errors.cwdRequired') }]}
          >
            <Input placeholder="/tmp/project" />
          </Form.Item>
          <Form.Item name="projectId" label={t('tenant.acp.test.projectId')}>
            <Input />
          </Form.Item>
          <Form.Item name="prompt" label={t('tenant.acp.test.prompt')}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="timeoutSeconds" label={t('tenant.acp.test.timeout')}>
            <InputNumber min={1} max={300} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
        {testResult ? (
          <Alert
            className="mt-4"
            type={testResult.success ? 'success' : 'error'}
            showIcon
            title={testResult.success ? t('tenant.acp.test.success') : t('tenant.acp.test.failure')}
            description={
              <Space orientation="vertical" size={4}>
                <Text>{t('tenant.acp.test.duration', { duration: testResult.durationMs })}</Text>
                <Text>{t('tenant.acp.test.updates', { count: testResult.updatesCount })}</Text>
                {testResult.assistantText ? <Text>{testResult.assistantText}</Text> : null}
                {testResult.error ? <Text type="danger">{testResult.error}</Text> : null}
              </Space>
            }
          />
        ) : null}
      </Drawer>
    </div>
  );
};
