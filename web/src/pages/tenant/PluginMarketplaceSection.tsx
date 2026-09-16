import React, { useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Badge, Button, Popconfirm, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { Eye } from 'lucide-react';

import { marketplaceInstallAvailability } from '@/utils/pluginMarketplaceInstall';

import type { MarketplacePackageCatalogEntry } from '@/types/pluginMarketplace';

import type { PaginationProps, TableColumnsType } from 'antd';

const { Text, Title } = Typography;

interface PluginMarketplaceSectionProps {
  readonly packages: MarketplacePackageCatalogEntry[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly actionKey: string | null;
  readonly canInstall: boolean;
  readonly onRetry: () => void;
  readonly onOpen: (pluginId: string) => void;
  readonly onInstall: (entry: MarketplacePackageCatalogEntry) => void;
  readonly onUninstall: (entry: MarketplacePackageCatalogEntry) => Promise<void>;
}

const manifestTargets = (entry: MarketplacePackageCatalogEntry): string[] => {
  const targets = entry.manifest.targets;
  return Array.isArray(targets)
    ? targets.filter((target): target is string => typeof target === 'string')
    : [];
};

export const PluginMarketplaceSection: React.FC<PluginMarketplaceSectionProps> = ({
  packages,
  loading,
  error,
  actionKey,
  canInstall,
  onRetry,
  onOpen,
  onInstall,
  onUninstall,
}) => {
  const { t } = useTranslation();

  const renderPaginationItem = useCallback<NonNullable<PaginationProps['itemRender']>>(
    (_page, type, originalElement) => {
      const label =
        type === 'prev'
          ? t('tenant.pluginHub.pagination.previousPage')
          : type === 'next'
            ? t('tenant.pluginHub.pagination.nextPage')
            : undefined;
      if (!label || !React.isValidElement(originalElement)) return originalElement;
      return React.cloneElement(originalElement, {
        'aria-label': label,
        title: label,
      } as React.AriaAttributes & { title: string });
    },
    [t]
  );

  const pagination = useMemo(
    () =>
      packages.length > 8
        ? { pageSize: 8, showSizeChanger: false, itemRender: renderPaginationItem }
        : false,
    [packages.length, renderPaginationItem]
  );

  const columns = useMemo<TableColumnsType<MarketplacePackageCatalogEntry>>(
    () => [
      {
        title: t('tenant.pluginHub.pluginsList.plugin'),
        dataIndex: 'plugin_id',
        key: 'plugin_id',
        render: (pluginId: string, entry) => (
          <Space orientation="vertical" size={0}>
            <Button
              type="link"
              className="h-auto p-0 text-left font-medium"
              onClick={() => {
                onOpen(entry.plugin_id);
              }}
            >
              {pluginId}
            </Button>
            <Text type="secondary" className="text-xs">
              {entry.publisher}
            </Text>
          </Space>
        ),
      },
      {
        title: t('tenant.pluginHub.pluginDetail.version'),
        dataIndex: 'version',
        key: 'version',
      },
      {
        title: t('tenant.pluginHub.pluginDetail.targets'),
        key: 'targets',
        render: (_value, entry) => {
          const targets = manifestTargets(entry);
          return targets.length > 0 ? (
            <Space wrap>
              {targets.map((target) => (
                <Tag key={target}>{target}</Tag>
              ))}
            </Space>
          ) : (
            <Text type="secondary">{t('tenant.pluginHub.pluginDetail.notDeclared')}</Text>
          );
        },
      },
      {
        title: t('tenant.pluginHub.pluginDetail.desiredState'),
        key: 'install_status',
        render: (_value, entry) => (
          <Space>
            <Badge
              status={entry.install_status === 'approved' ? 'success' : 'default'}
              text={entry.install_status}
            />
            {entry.revoked ? (
              <Tag color="error">{t('tenant.pluginHub.pluginDetail.revoked')}</Tag>
            ) : null}
          </Space>
        ),
      },
      {
        title: t('tenant.pluginHub.pluginDetail.securityScan'),
        dataIndex: 'security_scan_status',
        key: 'security_scan_status',
        render: (scanStatus: string) => (
          <Tag color={scanStatus === 'passed' ? 'success' : 'warning'}>{scanStatus}</Tag>
        ),
      },
      {
        title: t('tenant.pluginHub.channelsList.actions'),
        key: 'actions',
        render: (_value, entry) => {
          const installAvailability = marketplaceInstallAvailability(entry);
          const installActionKey = `install:${entry.plugin_id}:${entry.version}`;
          const installable = canInstall && installAvailability === 'ready';
          const installReason = canInstall
            ? t(`tenant.pluginHub.pluginsList.installUnavailable.${installAvailability}`)
            : t('tenant.pluginHub.pluginsList.installAdminRequired');
          return (
          <Space>
            <Button
              size="small"
              icon={<Eye size={16} />}
              aria-label={t('tenant.pluginHub.pluginsList.viewPlugin', {
                name: entry.plugin_id,
              })}
              title={t('tenant.pluginHub.pluginsList.viewPlugin', { name: entry.plugin_id })}
              onClick={() => {
                onOpen(entry.plugin_id);
              }}
            />
            {entry.install_status !== 'installed' && !entry.revoked ? (
              installable ? (
                <Button
                  size="small"
                  type="primary"
                  loading={actionKey === installActionKey}
                  onClick={() => {
                    onInstall(entry);
                  }}
                >
                  {t('tenant.pluginHub.pluginsList.install')}
                </Button>
              ) : (
                <Tooltip title={installReason}>
                  <Button size="small" disabled>
                    {t('tenant.pluginHub.pluginsList.install')}
                  </Button>
                </Tooltip>
              )
            ) : null}
            <Popconfirm
              title={t('tenant.pluginHub.pluginsList.confirmUninstallNamed', {
                name: entry.plugin_id,
              })}
              description={t('tenant.pluginHub.pluginsList.uninstallDescriptionV2')}
              onConfirm={() => onUninstall(entry)}
              okText={t('tenant.pluginHub.pluginsList.uninstall')}
              okButtonProps={{ danger: true }}
              disabled={entry.revoked || entry.install_status === 'uninstalled'}
            >
              <Button
                size="small"
                danger
                disabled={entry.revoked || entry.install_status === 'uninstalled'}
                loading={actionKey === `${entry.plugin_id}:${entry.version}`}
              >
                {t('tenant.pluginHub.pluginsList.uninstall')}
              </Button>
            </Popconfirm>
          </Space>
          );
        },
      },
    ],
    [actionKey, canInstall, onInstall, onOpen, onUninstall, t]
  );

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-surface-dark">
      <div className="px-5 pb-2 pt-5">
        <Title level={5} className="!m-0">
          {t('tenant.pluginHub.pluginsList.installedPlugins')}
        </Title>
      </div>
      <div className="px-5 pb-5">
        {error ? (
          <Alert
            type="error"
            showIcon
            className="mb-4"
            title={t('tenant.pluginHub.messages.loadPluginsFailed')}
            description={error}
            action={<Button onClick={onRetry}>{t('common.retry')}</Button>}
          />
        ) : null}
        <Table
          dataSource={packages}
          columns={columns}
          rowKey={(entry) => `${entry.plugin_id}:${entry.version}`}
          loading={loading}
          locale={{ emptyText: t('tenant.pluginHub.pluginsList.noPluginsAvailable') }}
          scroll={{ x: 'max-content' }}
          pagination={pagination}
        />
      </div>
    </section>
  );
};
