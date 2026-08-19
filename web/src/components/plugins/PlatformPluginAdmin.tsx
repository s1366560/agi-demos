/**
 * Platform plugin admin surface (I4).
 *
 * Three-level view of the plugin control plane — cutover gate panel
 * (shadow parity + rollback drill + operator approval), the composed
 * profile (id/version/digest), and the per-row view with layer provenance
 * from the canonical snapshot.
 */

import { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Empty, Space, Spin, Table, Tag, Typography } from 'antd';
import { CheckCircle2, OctagonX, RefreshCw, ShieldCheck } from 'lucide-react';

import {
  platformPluginAdminService,
  type CutoverReadiness,
} from '@/services/admin/platformPluginAdminService';

import type { PlatformPluginSnapshotResponse } from '@/types/pluginSlots';

const { Text, Title } = Typography;

interface SnapshotRowView {
  key: string;
  id: string;
  layerId: string;
  capabilityKinds: string;
  configKeys: string;
}

function toRowViews(payload: PlatformPluginSnapshotResponse['payload']): SnapshotRowView[] {
  return payload.plugins.map((row) => {
    const layerId = (row as { layer_id?: string }).layer_id ?? '';
    return {
      key: row.id,
      id: row.id,
      layerId,
      capabilityKinds: row.provides.map((capability) => capability.kind).join(', ') || '—',
      configKeys: Object.keys(row.config ?? {}).join(', ') || '—',
    };
  });
}

export function PlatformPluginAdmin() {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<PlatformPluginSnapshotResponse | null>(null);
  const [readiness, setReadiness] = useState<CutoverReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const [snapshotResult, readinessResult] = await Promise.all([
        platformPluginAdminService.snapshot(),
        platformPluginAdminService.cutoverReadiness(),
      ]);
      setSnapshot(snapshotResult);
      setReadiness(readinessResult);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const runAction = useCallback(
    async (action: () => Promise<unknown>) => {
      setActionBusy(true);
      setActionError(null);
      try {
        await action();
        await reload();
      } catch (error) {
        setActionError(error instanceof Error ? error.message : String(error));
      } finally {
        setActionBusy(false);
      }
    },
    [reload]
  );

  const readinessReasons = readiness?.reasons ?? [];
  const snapshotPayload = snapshot?.payload ?? null;

  const rowColumns = [
    { title: t('tenant.platformPluginAdmin.rowId', 'Plugin row'), dataIndex: 'id', key: 'id' },
    {
      title: t('tenant.platformPluginAdmin.layer', 'Layer'),
      dataIndex: 'layerId',
      key: 'layerId',
      render: (value: string) => (value ? <Text code>{value}</Text> : '—'),
    },
    {
      title: t('tenant.platformPluginAdmin.capabilities', 'Capabilities'),
      dataIndex: 'capabilityKinds',
      key: 'capabilityKinds',
    },
    {
      title: t('tenant.platformPluginAdmin.configKeys', 'Config keys'),
      dataIndex: 'configKeys',
      key: 'configKeys',
    },
  ];

  return (
    <section
      className="bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm p-5"
      data-testid="platform-plugin-admin"
    >
      <div className="flex items-center justify-between mb-4">
        <Title level={5} className="!m-0">
          {t('tenant.platformPluginAdmin.title', 'Platform plugin control plane')}
        </Title>
        <Button
          icon={<RefreshCw size={14} />}
          onClick={() => void reload()}
          loading={loading}
          size="small"
        >
          {t('common.refresh', 'Refresh')}
        </Button>
      </div>

      {actionError ? (
        <Text type="danger" data-testid="platform-plugin-admin-error">
          {actionError}
        </Text>
      ) : null}

      {loading && !readiness ? (
        <Spin />
      ) : (
        <Space orientation="vertical" size="large" className="w-full">
          {/* Cutover gate panel */}
          <div data-testid="cutover-gate-panel">
            <Space wrap align="center">
              <ShieldCheck size={16} />
              <Text strong>{t('tenant.platformPluginAdmin.cutoverGate', 'Cutover gate')}</Text>
              {readiness?.ready ? (
                <Tag icon={<CheckCircle2 size={12} />} color="success">
                  {t('tenant.platformPluginAdmin.ready', 'ready')}
                </Tag>
              ) : (
                <Tag icon={<OctagonX size={12} />} color="error">
                  {t('tenant.platformPluginAdmin.notReady', 'not ready')}
                </Tag>
              )}
              {readiness?.operator_approved ? (
                <Tag color="processing">
                  {t('tenant.platformPluginAdmin.operatorApproved', 'operator approved')}
                </Tag>
              ) : null}
            </Space>
            {readinessReasons.length > 0 ? (
              <ul className="mt-2 text-xs text-slate-500">
                {readinessReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <Space wrap className="mt-3">
              <Button
                size="small"
                type="primary"
                disabled={!readiness?.ready || readiness.operator_approved || actionBusy}
                onClick={() =>
                  void runAction(() => platformPluginAdminService.approveCutover())
                }
              >
                {t('tenant.platformPluginAdmin.approve', 'Approve cutover')}
              </Button>
              <Button
                size="small"
                danger
                disabled={!readiness?.operator_approved || actionBusy}
                onClick={() => void runAction(() => platformPluginAdminService.revokeCutover())}
              >
                {t('tenant.platformPluginAdmin.revoke', 'Revoke approval')}
              </Button>
            </Space>
          </div>

          {/* Profile view */}
          {snapshotPayload ? (
            <div data-testid="platform-profile-view">
              <Text strong>{t('tenant.platformPluginAdmin.profile', 'Profile')}</Text>
              <div className="mt-1 flex flex-wrap gap-2">
                <Tag>{snapshotPayload.profile_id}</Tag>
                <Tag>{`v${String(snapshot?.version ?? 0)}`}</Tag>
                <Text code className="text-xs">
                  {snapshotPayload.digest}
                </Text>
              </div>
            </div>
          ) : null}

          {/* Row view */}
          <div data-testid="platform-row-view">
            <Text strong>{t('tenant.platformPluginAdmin.rows', 'Composed rows')}</Text>
            {snapshotPayload && snapshotPayload.plugins.length > 0 ? (
              <Table
                className="mt-2"
                size="small"
                dataSource={toRowViews(snapshotPayload)}
                columns={rowColumns}
                pagination={false}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t('tenant.platformPluginAdmin.noRows', 'No composed rows')}
              />
            )}
          </div>
        </Space>
      )}
    </section>
  );
}

export default PlatformPluginAdmin;
