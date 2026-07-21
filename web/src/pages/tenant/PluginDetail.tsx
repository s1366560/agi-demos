import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { Alert, Button, Collapse, Empty, Spin, Space, Tag, Typography } from 'antd';
import { ArrowLeft, Package, RefreshCw } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { channelService } from '@/services/channelService';

import type { PluginConfigSchema, PluginDiagnostic, RuntimePlugin } from '@/types/channel';

const { Title, Text } = Typography;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasEntries = (value: unknown): boolean =>
  Array.isArray(value) ? value.length > 0 : isRecord(value) && Object.keys(value).length > 0;

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2);

const getStringField = (value: Record<string, unknown>, field: string): string | null => {
  const rawValue = value[field];
  return typeof rawValue === 'string' && rawValue.trim() ? rawValue : null;
};

const humanizeKey = (value: string): string =>
  value
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

interface DetailItemProps {
  label: string;
  children: React.ReactNode;
}

const DetailItem: React.FC<DetailItemProps> = ({ label, children }) => (
  <div className="min-w-0 border-b border-slate-100 py-3 last:border-b-0 dark:border-slate-800">
    <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
    <div className="mt-1 min-w-0 text-sm text-slate-900 dark:text-slate-100">{children}</div>
  </div>
);

interface JsonBlockProps {
  value: unknown;
  maxHeightClassName?: string;
}

const JsonBlock: React.FC<JsonBlockProps> = ({ value, maxHeightClassName = 'max-h-[320px]' }) => (
  <pre
    className={`${maxHeightClassName} overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-800 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100`}
  >
    {formatJson(value)}
  </pre>
);

interface SkillDefinitionListProps {
  items: Array<Record<string, unknown>> | undefined;
  emptyLabel: string;
}

const SkillDefinitionList: React.FC<SkillDefinitionListProps> = ({ items, emptyLabel }) => {
  if (!items || items.length === 0) {
    return <Text type="secondary">{emptyLabel}</Text>;
  }

  return (
    <div className="space-y-4">
      {items.map((item, index) => {
        const name = getStringField(item, 'name') ?? `skill-${index + 1}`;
        const path = getStringField(item, 'path');
        const content = getStringField(item, 'content');

        return (
          <div key={`${name}:${path ?? index}`} className="space-y-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Tag color="blue">{name}</Tag>
              {path ? (
                <Text code className="break-all">
                  {path}
                </Text>
              ) : null}
            </div>
            {content ? (
              <pre className="max-h-[520px] overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-800 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100">
                {content}
              </pre>
            ) : (
              <JsonBlock value={item} />
            )}
          </div>
        );
      })}
    </div>
  );
};

interface DetailSectionProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

const DetailSection: React.FC<DetailSectionProps> = ({ title, children, className }) => (
  <section
    className={`min-w-0 rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-surface-dark ${className ?? ''}`}
  >
    <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-800">
      <Title level={5} style={{ margin: 0 }} className="text-sm">
        {title}
      </Title>
    </div>
    <div className="p-4">{children}</div>
  </section>
);

interface SummaryItemProps {
  label: string;
  children: React.ReactNode;
}

const SummaryItem: React.FC<SummaryItemProps> = ({ label, children }) => (
  <div className="min-w-0 bg-white px-4 py-3 dark:bg-surface-dark">
    <div className="text-xs font-medium uppercase text-slate-500">{label}</div>
    <div className="mt-1 min-w-0 text-sm font-medium text-slate-900 dark:text-slate-100">
      {children}
    </div>
  </div>
);

interface SectionPairProps {
  title: string;
  children: React.ReactNode;
}

const SectionPair: React.FC<SectionPairProps> = ({ title, children }) => (
  <div className="min-w-0">
    <Text strong className="text-xs uppercase text-slate-500">
      {title}
    </Text>
    <div className="mt-2 min-w-0">{children}</div>
  </div>
);

const renderTags = (items: string[] | undefined, emptyLabel: string): React.ReactNode => {
  if (!items || items.length === 0) {
    return <Text type="secondary">{emptyLabel}</Text>;
  }

  return (
    <Space wrap size={[4, 4]}>
      {items.map((item) => (
        <Tag key={item}>{item}</Tag>
      ))}
    </Space>
  );
};

export const PluginDetail: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: urlTenantId, pluginName: encodedPluginName } = useParams<{
    tenantId?: string | undefined;
    pluginName?: string | undefined;
  }>();
  const [searchParams] = useSearchParams();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = urlTenantId || currentTenant?.id || null;
  const pluginName = encodedPluginName ? decodeURIComponent(encodedPluginName) : null;
  const projectId = searchParams.get('projectId');

  const [plugin, setPlugin] = useState<RuntimePlugin | null>(null);
  const [diagnostics, setDiagnostics] = useState<PluginDiagnostic[]>([]);
  const [schema, setSchema] = useState<PluginConfigSchema | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const backPath = useMemo(() => {
    const query = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';
    return tenantId ? `/tenant/${tenantId}/plugins${query}` : '/tenant/plugins';
  }, [projectId, tenantId]);

  const loadPlugin = useCallback(async () => {
    if (!tenantId || !pluginName) return;

    setLoading(true);
    setLoadError(null);
    setSchemaError(null);
    try {
      const pluginList = await channelService.listTenantPlugins(tenantId);
      const nextPlugin =
        pluginList.items.find((item) => item.name === pluginName) ??
        pluginList.items.find((item) => item.manifest_id === pluginName) ??
        null;

      setPlugin(nextPlugin);
      setDiagnostics(
        pluginList.diagnostics.filter((item) => !nextPlugin || item.plugin_name === nextPlugin.name)
      );

      if (nextPlugin?.schema_supported) {
        try {
          const nextSchema = await channelService.getTenantPluginConfigSchema(
            tenantId,
            nextPlugin.name
          );
          setSchema(nextSchema);
        } catch (error) {
          setSchema(null);
          setSchemaError(
            error instanceof Error
              ? error.message
              : t('tenant.pluginHub.pluginDetail.schemaLoadFailed')
          );
        }
      } else {
        setSchema(null);
      }
    } catch (error) {
      setLoadError(
        error instanceof Error ? error.message : t('tenant.pluginHub.messages.loadPluginsFailed')
      );
      setPlugin(null);
      setDiagnostics([]);
      setSchema(null);
    } finally {
      setLoading(false);
    }
  }, [pluginName, tenantId, t]);

  useEffect(() => {
    void loadPlugin();
  }, [loadPlugin]);

  const declaredCapabilities = useMemo(
    () => [
      {
        key: 'channel_types',
        label: t('tenant.pluginHub.channelsList.channels'),
        value: plugin?.channel_types,
      },
      {
        key: 'providers',
        label: t('tenant.pluginHub.pluginDetail.providers'),
        value: plugin?.providers,
      },
      {
        key: 'skills',
        label: t('tenant.pluginHub.pluginsList.capabilitySkills'),
        value: plugin?.skills,
      },
      {
        key: 'manifest_channels',
        label: t('tenant.pluginHub.pluginDetail.manifestChannels'),
        value: plugin?.channels,
      },
    ],
    [plugin, t]
  );

  const skillDefinitionCount = plugin?.skill_definitions?.length ?? 0;
  const toolDefinitionCount = plugin?.tool_definitions?.length ?? 0;

  if (!tenantId || !pluginName) {
    return <Empty description={t('tenant.pluginHub.missingTenantContext')} />;
  }

  return (
    <div className="mx-auto h-full w-full max-w-full space-y-4 p-4 md:p-6">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-surface-dark">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-slate-100 dark:bg-slate-900">
              <Package size={20} className="text-slate-700 dark:text-slate-200" />
            </div>
            <div className="min-w-0">
              <Link
                to={backPath}
                className="mb-1 inline-flex items-center gap-1 text-sm text-slate-500 transition-colors hover:text-primary focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              >
                <ArrowLeft size={16} aria-hidden="true" />
                {t('tenant.pluginHub.pluginDetail.back')}
              </Link>
              <Title level={1} style={{ margin: 0 }} className="break-all">
                {pluginName}
              </Title>
              <Text type="secondary">{t('tenant.pluginHub.pluginDetail.subtitle')}</Text>
            </div>
          </div>
          <Button
            icon={<RefreshCw size={16} />}
            loading={loading}
            onClick={() => {
              void loadPlugin();
            }}
          >
            {t('tenant.pluginHub.pluginsList.reload')}
          </Button>
        </div>
      </section>

      <Spin spinning={loading}>
        {!plugin ? (
          <section className="rounded-lg border border-slate-200 bg-white p-8 dark:border-slate-800 dark:bg-surface-dark">
            {loadError && !loading ? (
              <Alert
                type="error"
                showIcon
                title={t('tenant.pluginHub.messages.loadPluginsFailed')}
                description={loadError}
                action={
                  <Button
                    onClick={() => {
                      void loadPlugin();
                    }}
                  >
                    {t('common.retry')}
                  </Button>
                }
              />
            ) : (
              !loading && <Empty description={t('tenant.pluginHub.pluginDetail.notFound')} />
            )}
          </section>
        ) : (
          <div className="space-y-4">
            <section className="grid overflow-hidden rounded-md border border-slate-200 bg-slate-200 shadow-sm dark:border-slate-800 dark:bg-slate-800 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              <SummaryItem label={t('tenant.pluginHub.pluginsList.source')}>
                <Tag>{plugin.source}</Tag>
              </SummaryItem>
              <SummaryItem label={t('tenant.pluginHub.channelsList.status')}>
                {plugin.enabled ? (
                  <Tag color="success">{t('tenant.pluginHub.pluginsList.enable')}</Tag>
                ) : (
                  <Tag>{t('tenant.pluginHub.pluginsList.disabled')}</Tag>
                )}
              </SummaryItem>
              <SummaryItem label={t('tenant.pluginHub.pluginDetail.version')}>
                {plugin.version || t('tenant.pluginHub.pluginDetail.notDeclared')}
              </SummaryItem>
              <SummaryItem label={t('tenant.pluginHub.pluginDetail.kind')}>
                {plugin.kind || t('tenant.pluginHub.pluginDetail.notDeclared')}
              </SummaryItem>
              <SummaryItem label={t('tenant.pluginHub.pluginsList.capabilitySkills')}>
                {skillDefinitionCount}
              </SummaryItem>
              <SummaryItem label={t('tenant.pluginHub.pluginsList.capabilityTools')}>
                {toolDefinitionCount}
              </SummaryItem>
            </section>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
              <main className="min-w-0 space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <DetailSection title={t('tenant.pluginHub.pluginDetail.overview')}>
                    <div className="grid gap-x-6 md:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
                      <DetailItem label={t('tenant.pluginHub.pluginDetail.package')}>
                        {plugin.package || t('tenant.pluginHub.pluginsList.local')}
                      </DetailItem>
                      <DetailItem label={t('tenant.pluginHub.pluginDetail.manifestId')}>
                        {plugin.manifest_id || t('tenant.pluginHub.pluginDetail.notDeclared')}
                      </DetailItem>
                      <DetailItem label={t('tenant.pluginHub.pluginDetail.manifestPath')}>
                        <Text code className="break-all">
                          {plugin.manifest_path || t('tenant.pluginHub.pluginDetail.notDeclared')}
                        </Text>
                      </DetailItem>
                      <DetailItem label={t('tenant.pluginHub.schemaSupported')}>
                        {plugin.schema_supported ? (
                          <Tag color="success">{t('tenant.pluginHub.schemaSupported')}</Tag>
                        ) : (
                          <Tag>{t('tenant.pluginHub.pluginDetail.notSupported')}</Tag>
                        )}
                      </DetailItem>
                    </div>
                  </DetailSection>

                  <DetailSection title={t('tenant.pluginHub.pluginDetail.declaredCapabilities')}>
                    <div className="grid gap-x-6 md:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
                      {declaredCapabilities.map((item) => (
                        <DetailItem key={item.key} label={item.label}>
                          {renderTags(item.value, t('tenant.pluginHub.pluginDetail.none'))}
                        </DetailItem>
                      ))}
                    </div>
                  </DetailSection>
                </div>

                <DetailSection title={t('tenant.pluginHub.pluginDetail.contracts')}>
                  {hasEntries(plugin.contracts) ? (
                    <div className="grid gap-x-6 md:grid-cols-2">
                      {Object.entries(plugin.contracts ?? {}).map(([key, values]) => (
                        <DetailItem key={key} label={humanizeKey(key)}>
                          {renderTags(values, t('tenant.pluginHub.pluginDetail.none'))}
                        </DetailItem>
                      ))}
                    </div>
                  ) : (
                    <Text type="secondary">{t('tenant.pluginHub.pluginsList.noCapabilities')}</Text>
                  )}
                </DetailSection>

                <DetailSection
                  title={t('tenant.pluginHub.pluginDetail.builtinSkills')}
                  className="overflow-hidden"
                >
                  <SkillDefinitionList
                    items={plugin.skill_definitions}
                    emptyLabel={t('tenant.pluginHub.pluginDetail.none')}
                  />
                </DetailSection>

                <DetailSection title={t('tenant.pluginHub.pluginDetail.toolDefinitions')}>
                  {hasEntries(plugin.tool_definitions) ? (
                    <JsonBlock value={plugin.tool_definitions} maxHeightClassName="max-h-[460px]" />
                  ) : (
                    <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                  )}
                </DetailSection>

                <DetailSection title={t('tenant.pluginHub.pluginDetail.commandsAndHooks')}>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.commandAliases')}>
                      {hasEntries(plugin.command_aliases) ? (
                        <JsonBlock value={plugin.command_aliases} />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.hookMetadata')}>
                      {hasEntries(plugin.hook_metadata) ? (
                        <JsonBlock value={plugin.hook_metadata} />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                  </div>
                </DetailSection>

                <Collapse
                  className="rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-surface-dark"
                  bordered={false}
                  items={[
                    {
                      key: 'raw',
                      label: (
                        <Text strong>{t('tenant.pluginHub.pluginDetail.rawRuntimeRecord')}</Text>
                      ),
                      children: <JsonBlock value={plugin} maxHeightClassName="max-h-[560px]" />,
                    },
                  ]}
                />
              </main>

              <aside className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
                <DetailSection title={t('tenant.pluginHub.pluginDetail.configuration')}>
                  {schemaError ? (
                    <Alert type="warning" showIcon title={schemaError} className="mb-3" />
                  ) : null}
                  <div className="space-y-4">
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.secretPaths')}>
                      {renderTags(schema?.secret_paths, t('tenant.pluginHub.pluginDetail.none'))}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.defaults')}>
                      {hasEntries(schema?.defaults) ? (
                        <JsonBlock value={schema?.defaults} maxHeightClassName="max-h-[220px]" />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.configSchema')}>
                      {hasEntries(schema?.config_schema ?? plugin.config_schema) ? (
                        <JsonBlock
                          value={schema?.config_schema ?? plugin.config_schema}
                          maxHeightClassName="max-h-[260px]"
                        />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.configUiHints')}>
                      {hasEntries(schema?.config_ui_hints ?? plugin.config_ui_hints) ? (
                        <JsonBlock
                          value={schema?.config_ui_hints ?? plugin.config_ui_hints}
                          maxHeightClassName="max-h-[220px]"
                        />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                  </div>
                </DetailSection>

                <DetailSection title={t('tenant.pluginHub.pluginDetail.metadata')}>
                  <div className="space-y-4">
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.activation')}>
                      {hasEntries(plugin.activation) ? (
                        <JsonBlock value={plugin.activation} maxHeightClassName="max-h-[220px]" />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.toolMetadata')}>
                      {hasEntries(plugin.tool_metadata) ? (
                        <JsonBlock
                          value={plugin.tool_metadata}
                          maxHeightClassName="max-h-[220px]"
                        />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                    <SectionPair title={t('tenant.pluginHub.pluginDetail.envVars')}>
                      {hasEntries(plugin.env_vars) ? (
                        <JsonBlock value={plugin.env_vars} maxHeightClassName="max-h-[260px]" />
                      ) : (
                        <Text type="secondary">{t('tenant.pluginHub.pluginDetail.none')}</Text>
                      )}
                    </SectionPair>
                  </div>
                </DetailSection>

                {diagnostics.length > 0 ? (
                  <DetailSection title={t('tenant.pluginHub.pluginDetail.diagnostics')}>
                    <div className="space-y-2">
                      {diagnostics.map((diagnostic) => (
                        <Alert
                          key={`${diagnostic.plugin_name}:${diagnostic.code}`}
                          type={diagnostic.level === 'error' ? 'error' : 'warning'}
                          showIcon
                          title={`${diagnostic.code}: ${diagnostic.message}`}
                        />
                      ))}
                    </div>
                  </DetailSection>
                ) : null}
              </aside>
            </div>
          </div>
        )}
      </Spin>
    </div>
  );
};
