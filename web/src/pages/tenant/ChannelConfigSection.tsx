import React, { useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Badge, Button, Empty, Popconfirm, Space, Table, Tag, Typography } from 'antd';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';

import type { ChannelConfig, ChannelPluginCatalogItem } from '@/types/channel';
import type { PaginationProps, TableColumnsType } from 'antd';

const { Text, Title } = Typography;

export interface ChannelTypeOption {
  readonly value: string;
  readonly label: string;
  readonly color: string;
}

interface ChannelConfigSectionProps {
  readonly selectedProjectId: string | null;
  readonly configs: ChannelConfig[];
  readonly catalog: ChannelPluginCatalogItem[];
  readonly channelTypeOptions: ChannelTypeOption[];
  readonly loading: boolean;
  readonly actionKey: string | null;
  readonly onAdd: () => void;
  readonly onEdit: (config: ChannelConfig) => void;
  readonly onTest: (configId: string) => Promise<void>;
  readonly onDelete: (configId: string) => Promise<void>;
}

const humanizeChannelType = (channelType: string): string =>
  channelType
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

export const ChannelConfigSection: React.FC<ChannelConfigSectionProps> = ({
  selectedProjectId,
  configs,
  catalog,
  channelTypeOptions,
  loading,
  actionKey,
  onAdd,
  onEdit,
  onTest,
  onDelete,
}) => {
  const { t } = useTranslation();
  const channelTypeOptionMap = useMemo(
    () => Object.fromEntries(channelTypeOptions.map((item) => [item.value, item])),
    [channelTypeOptions]
  );

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
      configs.length > 8
        ? { pageSize: 8, showSizeChanger: false, itemRender: renderPaginationItem }
        : false,
    [configs.length, renderPaginationItem]
  );

  const columns = useMemo<TableColumnsType<ChannelConfig>>(
    () => [
      {
        title: t('tenant.pluginHub.channelsList.name'),
        dataIndex: 'name',
        key: 'name',
        render: (name: string, record) => (
          <Space>
            <Text strong>{name}</Text>
            {record.enabled ? (
              <Tag color="success">{t('common.status.enabled')}</Tag>
            ) : (
              <Tag>{t('tenant.pluginHub.pluginsList.disabled')}</Tag>
            )}
          </Space>
        ),
      },
      {
        title: t('tenant.pluginHub.channelsList.channelType'),
        dataIndex: 'channel_type',
        key: 'channel_type',
        render: (channelType: string) => {
          const option = channelTypeOptionMap[channelType];
          return (
            <Tag color={option?.color || 'default'}>
              {option?.label || humanizeChannelType(channelType)}
            </Tag>
          );
        },
      },
      {
        title: t('tenant.pluginHub.channelsList.status'),
        dataIndex: 'status',
        key: 'status',
        render: (status: ChannelConfig['status']) => {
          if (status === 'connected') {
            return <Badge status="success" text={t('tenant.pluginHub.status.connected')} />;
          }
          if (status === 'error') {
            return <Badge status="error" text={t('tenant.pluginHub.status.error')} />;
          }
          if (status === 'circuit_open') {
            return <Badge color="orange" text={t('tenant.pluginHub.status.circuitOpen')} />;
          }
          return <Badge status="default" text={t('tenant.pluginHub.status.disconnected')} />;
        },
      },
      {
        title: t('tenant.pluginHub.channelsList.actions'),
        key: 'actions',
        render: (_value, record) => (
          <Space>
            <Button
              size="small"
              icon={<RefreshCw size={16} />}
              aria-label={t('tenant.pluginHub.channelsList.testChannel', { name: record.name })}
              title={t('tenant.pluginHub.channelsList.testChannel', { name: record.name })}
              loading={actionKey === `test:${record.id}`}
              onClick={() => {
                void onTest(record.id);
              }}
            />
            <Button
              size="small"
              icon={<Pencil size={16} />}
              aria-label={t('tenant.pluginHub.channelsList.editChannel', { name: record.name })}
              title={t('tenant.pluginHub.channelsList.editChannel', { name: record.name })}
              onClick={() => {
                onEdit(record);
              }}
            />
            <Popconfirm
              title={t('tenant.pluginHub.channelsList.deleteConfirm')}
              onConfirm={() => onDelete(record.id)}
              okText={t('tenant.pluginHub.channelsList.delete')}
              okButtonProps={{ danger: true }}
            >
              <Button
                size="small"
                danger
                icon={<Trash2 size={16} />}
                aria-label={t('tenant.pluginHub.channelsList.deleteChannel', {
                  name: record.name,
                })}
                title={t('tenant.pluginHub.channelsList.deleteChannel', { name: record.name })}
                loading={actionKey === `delete:${record.id}`}
              />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [actionKey, channelTypeOptionMap, onDelete, onEdit, onTest, t]
  );

  return (
    <>
      <section className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-surface-dark">
        <div className="flex items-center justify-between px-5 pb-2 pt-5">
          <Title level={5} className="!m-0">
            {t('tenant.pluginHub.channelsList.configuredChannels')}
          </Title>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={onAdd}
            disabled={!selectedProjectId || channelTypeOptions.length === 0}
          >
            {t('tenant.pluginHub.channelsList.addChannel')}
          </Button>
        </div>
        <div className="px-5 pb-5">
          {selectedProjectId ? (
            <Table
              dataSource={configs}
              columns={columns}
              rowKey="id"
              loading={loading}
              scroll={{ x: 'max-content' }}
              pagination={pagination}
            />
          ) : (
            <Empty description={t('tenant.pluginHub.channelsList.selectProjectToConfigure')} />
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
        <Title level={5} className="!mt-0">
          {t('tenant.pluginHub.channelCatalogDiagnostics')}
        </Title>
        {catalog.length > 0 ? (
          <Space wrap>
            {catalog.map((entry) => (
              <Tag key={`${entry.plugin_name}:${entry.channel_type}`} color="processing">
                {humanizeChannelType(entry.channel_type)} · {entry.plugin_name}
                {entry.schema_supported ? ` · ${t('tenant.pluginHub.schemaSupported')}` : ''}
              </Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">{t('tenant.pluginHub.noChannelAdapters')}</Text>
        )}
      </section>
    </>
  );
};
