import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ArrowLeft, Package, RefreshCw } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { pluginMarketplaceService } from '@/services/pluginMarketplaceService';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';

import type {
  MarketplacePackageCatalogEntry,
  MarketplacePackageDetail,
} from '@/types/pluginMarketplace';

const { Title, Text } = Typography;

const jsonView = (value: Record<string, unknown>) => JSON.stringify(value, null, 2);

export const PluginDetail: React.FC = () => {
  const { tenantId: urlTenantId, pluginName } = useParams<{
    tenantId?: string | undefined;
    pluginName?: string | undefined;
  }>();
  const { t } = useTranslation();
  const { message } = App.useApp();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = urlTenantId || currentTenant?.id || null;
  const [detail, setDetail] = useState<MarketplacePackageDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const loadPackage = useCallback(async () => {
    const requestedPluginName = pluginName;
    const requestId = ++requestIdRef.current;
    if (!requestedPluginName) {
      setDetail(null);
      return;
    }

    setLoading(true);
    try {
      const nextDetail = await pluginMarketplaceService.getPackage(requestedPluginName, {
        includeRevoked: true,
      });
      if (requestIdRef.current !== requestId) return;
      setDetail(nextDetail);
      setError(null);
    } catch (loadError) {
      if (requestIdRef.current !== requestId) return;
      setDetail(null);
      setError(
        loadError instanceof Error
          ? loadError.message
          : t('tenant.pluginHub.messages.loadPluginsFailed')
      );
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [pluginName, t]);

  useEffect(() => {
    void loadPackage();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadPackage]);

  const handleUninstall = useCallback(
    async (entry: MarketplacePackageCatalogEntry) => {
      if (!tenantId) return;
      const nextActionKey = `${entry.plugin_id}:${entry.version}`;
      setActionKey(nextActionKey);
      try {
        await pluginMarketplaceService.uninstallPackage(entry.plugin_id, {
          tenant_id: tenantId,
          version: entry.version,
        });
        message.success(
          t('tenant.pluginHub.messages.pluginUninstalled', {
            name: entry.plugin_id,
            version: entry.version,
          })
        );
        await loadPackage();
      } catch (uninstallError) {
        message.error(
          uninstallError instanceof Error
            ? uninstallError.message
            : t('tenant.pluginHub.messages.pluginUninstallFailed')
        );
      } finally {
        setActionKey((current) => (current === nextActionKey ? null : current));
      }
    },
    [loadPackage, message, tenantId, t]
  );

  const columns = useMemo(
    () => [
      {
        title: t('tenant.pluginHub.pluginDetail.version'),
        dataIndex: 'version',
        key: 'version',
      },
      {
        title: t('tenant.pluginHub.pluginDetail.publisher'),
        dataIndex: 'publisher',
        key: 'publisher',
      },
      {
        title: t('tenant.pluginHub.pluginDetail.desiredState'),
        dataIndex: 'install_status',
        key: 'install_status',
        render: (status: string) => (
          <Tag color={status === 'approved' ? 'success' : 'default'}>{status}</Tag>
        ),
      },
      {
        title: t('tenant.pluginHub.pluginDetail.securityScan'),
        dataIndex: 'security_scan_status',
        key: 'security_scan_status',
        render: (status: string) => (
          <Tag color={status === 'passed' ? 'success' : 'warning'}>{status}</Tag>
        ),
      },
      {
        title: t('tenant.pluginHub.channelsList.actions'),
        key: 'actions',
        render: (_: unknown, entry: MarketplacePackageCatalogEntry) => (
          <Popconfirm
            title={t('tenant.pluginHub.pluginsList.confirmUninstallNamed', {
              name: entry.plugin_id,
            })}
            description={t('tenant.pluginHub.pluginsList.uninstallDescriptionV2')}
            onConfirm={() => {
              void handleUninstall(entry);
            }}
            okText={t('tenant.pluginHub.pluginsList.uninstall')}
            okButtonProps={{ danger: true }}
            disabled={entry.revoked || entry.install_status === 'uninstalled'}
          >
            <Button
              danger
              size="small"
              disabled={entry.revoked || entry.install_status === 'uninstalled'}
              loading={actionKey === `${entry.plugin_id}:${entry.version}`}
            >
              {t('tenant.pluginHub.pluginsList.uninstall')}
            </Button>
          </Popconfirm>
        ),
      },
    ],
    [actionKey, handleUninstall, t]
  );

  const versions = detail?.versions ?? [];
  const primaryVersion = versions[0];
  const backPath = tenantId ? `/tenant/${tenantId}/plugins` : '/';

  if (!tenantId) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Empty description={t('tenant.pluginHub.missingTenantContext')} />
      </div>
    );
  }

  return (
    <div className="mx-auto h-full w-full max-w-full space-y-4 p-4 md:p-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
              <Package size={20} className="text-primary" />
            </div>
            <div className="min-w-0">
              <Link
                to={backPath}
                className="mb-1 inline-flex items-center gap-1 text-sm text-slate-500 transition-colors hover:text-primary"
              >
                <ArrowLeft size={16} />
                {t('tenant.pluginHub.pluginDetail.back')}
              </Link>
              <Title level={3} className="!m-0 break-all">
                {pluginName}
              </Title>
              <Text type="secondary">{t('tenant.pluginHub.pluginDetail.subtitle')}</Text>
            </div>
          </div>
          <Button
            icon={<RefreshCw size={16} />}
            loading={loading}
            onClick={() => {
              void loadPackage();
            }}
          >
            {t('tenant.pluginHub.pluginsList.reload')}
          </Button>
        </div>
      </section>

      {error ? (
        <Alert
          type="error"
          showIcon
          title={t('tenant.pluginHub.messages.loadPluginsFailed')}
          description={error}
          action={
            <Button
              onClick={() => {
                void loadPackage();
              }}
            >
              {t('common.retry')}
            </Button>
          }
        />
      ) : null}

      {loading && !primaryVersion ? <SkeletonLoader type="table" /> : null}

      {!loading && !error && !primaryVersion ? (
        <section className="rounded-xl border border-slate-200 bg-white p-8 dark:border-slate-800 dark:bg-surface-dark">
          <Empty description={t('tenant.pluginHub.pluginDetail.notFound')} />
        </section>
      ) : null}

      {primaryVersion ? (
        <>
          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
            <Title level={5} className="!mt-0">
              {t('tenant.pluginHub.pluginDetail.overview')}
            </Title>
            <Descriptions bordered column={{ xs: 1, md: 2 }} size="small">
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.version')}>
                {primaryVersion.version}
              </Descriptions.Item>
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.publisher')}>
                {primaryVersion.publisher}
              </Descriptions.Item>
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.artifactSource')}>
                {`${primaryVersion.artifact_registry}/${primaryVersion.artifact_repository}`}
              </Descriptions.Item>
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.artifactDigest')}>
                <Text code copyable>
                  {primaryVersion.artifact_digest}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.securityScan')}>
                <Tag
                  color={primaryVersion.security_scan_status === 'passed' ? 'success' : 'warning'}
                >
                  {primaryVersion.security_scan_status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('tenant.pluginHub.pluginDetail.desiredState')}>
                <Space>
                  <Tag color={primaryVersion.install_status === 'approved' ? 'success' : 'default'}>
                    {primaryVersion.install_status}
                  </Tag>
                  {primaryVersion.revoked ? (
                    <Tag color="error">{t('tenant.pluginHub.pluginDetail.revoked')}</Tag>
                  ) : null}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
            <Title level={5} className="!mt-0">
              {t('tenant.pluginHub.pluginDetail.versions')}
            </Title>
            <Table
              dataSource={versions}
              columns={columns}
              rowKey={(entry) => `${entry.plugin_id}:${entry.version}`}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-3">
            {[
              ['bundleManifest', primaryVersion.manifest],
              ['provenance', primaryVersion.provenance],
              ['signature', primaryVersion.signature],
            ].map(([label, value]) => (
              <div
                key={label as string}
                className="min-w-0 rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark"
              >
                <Title level={5} className="!mt-0">
                  {t(`tenant.pluginHub.pluginDetail.${label as string}`)}
                </Title>
                <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 text-xs text-slate-100">
                  {jsonView(value as Record<string, unknown>)}
                </pre>
              </div>
            ))}
          </section>
        </>
      ) : null}
    </div>
  );
};

export default PluginDetail;
