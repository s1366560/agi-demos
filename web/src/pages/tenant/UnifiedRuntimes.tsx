/**
 * Unified Runtimes panel.
 *
 * Read-only diagnostic view combining the two runtime surfaces MemStack
 * currently exposes independently:
 *
 *   - Agent Pool actors   (`poolService`, /admin/pool/*)
 *   - Project sandboxes   (`projectSandboxService`)
 *
 * Borrowed from multica's Unified Runtimes concept: operators want one
 * place to answer "is the agent slow because its actor is unhealthy or
 * because its sandbox died?" without tabbing through separate screens.
 *
 * This is intentionally **read-only** and non-mutating — control actions
 * already live on each dedicated page; this is a situational-awareness
 * aggregator.
 */
import { useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { useQuery } from '@tanstack/react-query';
import { Alert, Badge, Button, Card, Empty, Space, Table, Tag, Typography } from 'antd';
import { RefreshCw } from 'lucide-react';

import { poolService, type PoolInstance, type PoolStatus } from '@/services/poolService';
import {
  projectSandboxService,
  type ProjectSandbox,
  type SandboxStats,
} from '@/services/projectSandboxService';

import { formatDateTime } from '@/utils/date';

import { getStatusColor } from './utils/instanceUtils';

const { Title, Text } = Typography;

interface RuntimeRow {
  key: string;
  kind: 'pool_actor' | 'sandbox';
  identifier: string;
  tenantId: string;
  projectId: string;
  status: string;
  health: string;
  tier?: string;
  lastActivity?: string | null | undefined;
  loadLabel?: string | undefined;
  memoryMb?: number | undefined;
}

interface SandboxRuntimeRecord {
  sandbox: ProjectSandbox;
  stats?: SandboxStats | undefined;
}

function healthStatus(health: string): 'success' | 'warning' | 'error' | 'default' {
  if (health === 'healthy') return 'success';
  if (health === 'degraded') return 'warning';
  if (health === 'unhealthy') return 'error';
  return 'default';
}

function sandboxHealth(sandbox: ProjectSandbox): string {
  if (sandbox.is_healthy) return 'healthy';
  if (sandbox.status === 'stopped' || sandbox.status === 'terminated') return 'unknown';
  return 'unhealthy';
}

function bytesToMb(value?: number): number | undefined {
  if (typeof value !== 'number') return undefined;
  return value / (1024 * 1024);
}

function renderLoad(row: RuntimeRow): string {
  const load = row.loadLabel ?? '—';
  const memory = typeof row.memoryMb === 'number' ? `${String(Math.round(row.memoryMb))} MB` : '—';
  return `${load} · ${memory}`;
}

async function fetchSandboxRuntimeRecords(): Promise<SandboxRuntimeRecord[]> {
  const response = await projectSandboxService.listProjectSandboxes({ limit: 100 });
  const records = await Promise.all(
    response.sandboxes.map(async (sandbox) => {
      try {
        const stats = await projectSandboxService.getStats(sandbox.project_id);
        return { sandbox, stats };
      } catch {
        return { sandbox };
      }
    })
  );
  return records;
}

export function UnifiedRuntimes() {
  const { t } = useTranslation();
  const { tenantId } = useParams<{ tenantId?: string }>();
  const poolStatusQuery = useQuery<PoolStatus>({
    queryKey: ['runtimes', 'pool', 'status'],
    queryFn: () => poolService.getStatus(),
    refetchInterval: 15_000,
  });

  const poolInstancesQuery = useQuery({
    queryKey: ['runtimes', 'pool', 'instances'],
    queryFn: () => poolService.listInstances({ page: 1, page_size: 100 }),
    refetchInterval: 15_000,
  });

  const sandboxesQuery = useQuery<SandboxRuntimeRecord[]>({
    queryKey: ['runtimes', 'sandboxes', tenantId ?? 'current'],
    queryFn: fetchSandboxRuntimeRecords,
    refetchInterval: 15_000,
  });

  const rows: RuntimeRow[] = useMemo(() => {
    const instances: PoolInstance[] = poolInstancesQuery.data?.instances ?? [];
    const poolRows = instances.map((inst) => ({
      key: `pool:${inst.instance_key}`,
      kind: 'pool_actor' as const,
      identifier: inst.instance_key,
      tenantId: inst.tenant_id,
      projectId: inst.project_id,
      status: inst.status,
      health: inst.health_status,
      tier: inst.tier,
      lastActivity: inst.last_request_at,
      loadLabel: `${String(inst.active_requests)} req`,
      memoryMb: inst.memory_used_mb,
    }));
    const sandboxRows =
      sandboxesQuery.data?.map(({ sandbox, stats }) => ({
        key: `sandbox:${sandbox.sandbox_id}`,
        kind: 'sandbox' as const,
        identifier: sandbox.sandbox_id,
        tenantId: sandbox.tenant_id,
        projectId: sandbox.project_id,
        status: stats?.status ?? sandbox.status,
        health: sandboxHealth(sandbox),
        tier: 'project',
        lastActivity: sandbox.last_accessed_at ?? sandbox.created_at ?? null,
        loadLabel: stats ? `${String(stats.pids)} pids` : undefined,
        memoryMb: bytesToMb(stats?.memory_usage),
      })) ?? [];
    return [...poolRows, ...sandboxRows];
  }, [poolInstancesQuery.data, sandboxesQuery.data]);

  const sandboxSummary = useMemo(() => {
    const records = sandboxesQuery.data ?? [];
    const memoryMb = records.reduce(
      (total, record) => total + (bytesToMb(record.stats?.memory_usage) ?? 0),
      0
    );
    return {
      total: records.length,
      healthy: records.filter((record) => sandboxHealth(record.sandbox) === 'healthy').length,
      attention: records.filter((record) => sandboxHealth(record.sandbox) === 'unhealthy').length,
      memoryMb,
      missingStats: records.filter((record) => record.sandbox.status === 'running' && !record.stats)
        .length,
    };
  }, [sandboxesQuery.data]);

  const columns = [
    {
      title: t('tenant.runtimes.columns.kind'),
      dataIndex: 'kind',
      key: 'kind',
      width: 130,
      render: (kind: RuntimeRow['kind']) => (
        <Tag color={kind === 'pool_actor' ? 'geekblue' : 'purple'}>
          {kind === 'pool_actor'
            ? t('tenant.runtimes.kind.poolActor')
            : t('tenant.runtimes.kind.sandbox')}
        </Tag>
      ),
    },
    {
      title: t('tenant.runtimes.columns.identifier'),
      dataIndex: 'identifier',
      key: 'identifier',
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: t('tenant.runtimes.columns.scope'),
      key: 'scope',
      render: (_: unknown, row: RuntimeRow) => (
        <Space orientation="vertical" size={0}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.tenantId}
          </Text>
          <Text style={{ fontSize: 13 }}>{row.projectId}</Text>
        </Space>
      ),
    },
    {
      title: t('tenant.runtimes.columns.status'),
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={getStatusColor(s)}>{s}</Tag>,
    },
    {
      title: t('tenant.runtimes.columns.health'),
      dataIndex: 'health',
      key: 'health',
      render: (h: string) => <Badge status={healthStatus(h)} text={h} />,
    },
    {
      title: t('tenant.runtimes.columns.tier'),
      dataIndex: 'tier',
      key: 'tier',
      render: (tier?: string) => (tier ? <Tag>{tier}</Tag> : '—'),
    },
    {
      title: t('tenant.runtimes.columns.loadMemory'),
      key: 'load',
      render: (_: unknown, row: RuntimeRow) => (
        <Text style={{ fontSize: 12 }} className="tabular-nums">
          {renderLoad(row)}
        </Text>
      ),
    },
    {
      title: t('tenant.runtimes.columns.lastActivity'),
      dataIndex: 'lastActivity',
      key: 'lastActivity',
      render: (value?: string | null) => (value ? formatDateTime(value) : '—'),
    },
  ];

  const poolStatus = poolStatusQuery.data;

  return (
    <div style={{ padding: 24 }}>
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Title level={1} style={{ marginBottom: 4 }}>
            {t('tenant.runtimes.title')}
          </Title>
          <Text type="secondary">{t('tenant.runtimes.description')}</Text>
        </div>

        {poolStatusQuery.isError && (
          <Alert
            type="warning"
            showIcon
            title={t('tenant.runtimes.errors.poolStatus')}
            description={poolStatusQuery.error.message}
          />
        )}

        {poolInstancesQuery.isError && (
          <Alert
            type="warning"
            showIcon
            title={t('tenant.runtimes.errors.poolInstances')}
            description={poolInstancesQuery.error.message}
          />
        )}

        {sandboxesQuery.isError && (
          <Alert
            type="warning"
            showIcon
            title={t('tenant.runtimes.errors.projectSandboxes')}
            description={sandboxesQuery.error.message}
          />
        )}

        {sandboxSummary.missingStats > 0 && (
          <Alert
            type="info"
            showIcon
            title={t('tenant.runtimes.errors.sandboxMetrics')}
            description={t('tenant.runtimes.errors.sandboxMetricsDescription', {
              count: sandboxSummary.missingStats,
            })}
          />
        )}

        {(poolStatus || sandboxesQuery.data) && (
          <Space size="large" wrap>
            {poolStatus && (
              <>
                <Card size="small" title={t('tenant.runtimes.cards.poolTotal')}>
                  <Title level={4} style={{ margin: 0 }} className="tabular-nums">
                    {poolStatus.total_instances}
                  </Title>
                </Card>
                <Card size="small" title={t('tenant.runtimes.cards.hotWarmCold')}>
                  <Text className="tabular-nums">
                    {poolStatus.hot_instances} / {poolStatus.warm_instances} /{' '}
                    {poolStatus.cold_instances}
                  </Text>
                </Card>
                <Card size="small" title={t('tenant.runtimes.cards.readyExecuting')}>
                  <Text className="tabular-nums">
                    {poolStatus.ready_instances} / {poolStatus.executing_instances}
                  </Text>
                </Card>
                <Card size="small" title={t('tenant.runtimes.cards.unhealthy')}>
                  {poolStatus.unhealthy_instances > 0 ? (
                    <Text type="danger" className="tabular-nums">
                      {poolStatus.unhealthy_instances}
                    </Text>
                  ) : (
                    <Text className="tabular-nums">{poolStatus.unhealthy_instances}</Text>
                  )}
                </Card>
                <Card size="small" title={t('tenant.runtimes.cards.memory')}>
                  <Text className="tabular-nums">
                    {Math.round(poolStatus.resource_usage.used_memory_mb)} /{' '}
                    {Math.round(poolStatus.resource_usage.total_memory_mb)} MB
                  </Text>
                </Card>
              </>
            )}
            <Card size="small" title={t('tenant.runtimes.cards.sandboxes')}>
              <Title level={4} style={{ margin: 0 }} className="tabular-nums">
                {sandboxSummary.total}
              </Title>
            </Card>
            <Card size="small" title={t('tenant.runtimes.cards.sandboxHealth')}>
              <Text className="tabular-nums">
                {t('tenant.runtimes.sandboxHealthValue', {
                  healthy: sandboxSummary.healthy,
                  attention: sandboxSummary.attention,
                })}
              </Text>
            </Card>
            <Card size="small" title={t('tenant.runtimes.cards.sandboxMemory')}>
              <Text className="tabular-nums">{Math.round(sandboxSummary.memoryMb)} MB</Text>
            </Card>
          </Space>
        )}

        <Card
          title={t('tenant.runtimes.instances')}
          extra={
            <Space size="middle">
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('tenant.runtimes.autoRefresh')}
              </Text>
              <Button
                size="small"
                icon={<RefreshCw size={14} aria-hidden="true" />}
                aria-label={t('common.refresh')}
                loading={
                  poolStatusQuery.isFetching ||
                  poolInstancesQuery.isFetching ||
                  sandboxesQuery.isFetching
                }
                onClick={() => {
                  void poolStatusQuery.refetch();
                  void poolInstancesQuery.refetch();
                  void sandboxesQuery.refetch();
                }}
              >
                {t('common.refresh')}
              </Button>
            </Space>
          }
        >
          {rows.length === 0 && !poolInstancesQuery.isLoading && !sandboxesQuery.isLoading ? (
            <Empty description={t('tenant.runtimes.empty')} />
          ) : (
            <Table<RuntimeRow>
              columns={columns}
              dataSource={rows}
              loading={poolInstancesQuery.isLoading || sandboxesQuery.isLoading}
              pagination={{ pageSize: 25 }}
              size="small"
              scroll={{ x: 900 }}
              rowKey="key"
            />
          )}
        </Card>
      </Space>
    </div>
  );
}

export default UnifiedRuntimes;
