import type React from 'react';
import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Input, Space, Table, Tag, Typography } from 'antd';
import { Search } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useProviderStore } from '@/stores/provider';

import { PROVIDERS } from '@/constants/providers';

import type { ModelCatalogEntry } from '@/types/memory';

const { Text } = Typography;

export interface ModelCatalogBrowserProps {
  onSelect?: (model: ModelCatalogEntry) => void;
  selectedModel?: string;
  filterProvider?: string;
}

export const ModelCatalogBrowser: React.FC<ModelCatalogBrowserProps> = ({
  onSelect,
  selectedModel,
  filterProvider,
}) => {
  const { t } = useTranslation();
  const { catalogLoading, modelSearchResults } = useProviderStore(
    useShallow((s) => ({
      catalogLoading: s.catalogLoading,
      modelSearchResults: s.modelSearchResults,
    }))
  );

  const { fetchModelCatalog, searchModels } = useProviderStore(
    useShallow((s) => ({
      fetchModelCatalog: s.fetchModelCatalog,
      searchModels: s.searchModels,
    }))
  );

  const [localSearch, setLocalSearch] = useState('');

  const [activeFilters, setActiveFilters] = useState<Record<string, boolean>>({
    vision: false,
    reasoning: false,
    tools: false,
    temp: false,
    seed: false,
    json: false,
    open: false,
  });

  const toggleFilter = (key: string, checked: boolean) => {
    setActiveFilters((prev) => ({ ...prev, [key]: checked }));
  };

  const filteredResults = modelSearchResults.filter((model) => {
    if (activeFilters.vision && !model.supports_attachment) return false;
    if (activeFilters.reasoning && !model.reasoning) return false;
    if (activeFilters.tools && !model.supports_tool_call) return false;
    if (activeFilters.temp && !model.supports_temperature) return false;
    if (activeFilters.seed && model.supports_seed !== true) return false;
    if (activeFilters.json && model.supports_response_format !== true) return false;
    if (activeFilters.open && !model.open_weights) return false;
    return true;
  });

  const filterTags = [
    { key: 'vision', labelKey: 'components.provider.modelCatalog.features.vision' },
    { key: 'reasoning', labelKey: 'components.provider.modelCatalog.features.reasoning' },
    { key: 'tools', labelKey: 'components.provider.modelCatalog.features.tools' },
    { key: 'temp', labelKey: 'components.provider.modelCatalog.features.temp' },
    { key: 'seed', labelKey: 'components.provider.modelCatalog.features.seed' },
    { key: 'json', labelKey: 'components.provider.modelCatalog.features.json' },
    { key: 'open', labelKey: 'components.provider.modelCatalog.features.open' },
  ];

  useEffect(() => {
    void fetchModelCatalog(filterProvider);
  }, [fetchModelCatalog, filterProvider]);

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setLocalSearch(value);
    searchModels(value);
  };

  const getProviderIcon = (providerValue: string) => {
    const meta = PROVIDERS.find((p) => p.value === providerValue);
    return meta ? meta.icon : '🤖';
  };

  const columns = [
    {
      title: t('components.provider.modelCatalog.columns.model', 'Model'),
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (text: string, record: ModelCatalogEntry) => (
        <Space orientation="vertical" size={0}>
          <Text strong>
            {record.provider && (
              <span
                className="mr-2"
                role="img"
                aria-label={t('components.provider.modelCatalog.providerIconAria', 'provider')}
              >
                {getProviderIcon(record.provider)}
              </span>
            )}
            {text}
          </Text>
          {record.provider && (
            <Text type="secondary" className="text-xs">
              {record.provider}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: t('components.provider.modelCatalog.columns.context', 'Context'),
      dataIndex: 'context_length',
      key: 'context_length',
      width: 100,
      sorter: (a: ModelCatalogEntry, b: ModelCatalogEntry) => a.context_length - b.context_length,
      render: (val: number) => (
        <Text>
          {val >= 1000000 ? `${(val / 1000000).toFixed(1)}M` : `${(val / 1000).toFixed(0)}k`}
        </Text>
      ),
    },
    {
      title: t('components.provider.modelCatalog.columns.maxOutput', 'Max Output'),
      dataIndex: 'max_output_tokens',
      key: 'max_output_tokens',
      width: 110,
      sorter: (a: ModelCatalogEntry, b: ModelCatalogEntry) =>
        a.max_output_tokens - b.max_output_tokens,
      render: (val: number) => (
        <Text>
          {val >= 1000000 ? `${(val / 1000000).toFixed(1)}M` : `${(val / 1000).toFixed(0)}k`}
        </Text>
      ),
    },
    {
      title: t('components.provider.modelCatalog.columns.cost', 'Cost ($/1M)'),
      key: 'cost',
      width: 120,
      render: (_: unknown, record: ModelCatalogEntry) => {
        const inCost = record.input_cost_per_1m;
        const outCost = record.output_cost_per_1m;
        if (inCost == null && outCost == null) return <Text type="secondary">-</Text>;
        return (
          <Space orientation="vertical" size={0}>
            <Text className="text-xs">
              {t('components.provider.modelCatalog.cost.in', 'In')}: ${inCost?.toFixed(2) ?? '-'}
            </Text>
            <Text className="text-xs">
              {t('components.provider.modelCatalog.cost.out', 'Out')}: ${outCost?.toFixed(2) ?? '-'}
            </Text>
          </Space>
        );
      },
    },
    {
      title: t('components.provider.modelCatalog.columns.features', 'Features'),
      key: 'features',
      width: 240,
      render: (_: unknown, record: ModelCatalogEntry) => (
        <Space orientation="vertical" size={4}>
          <Space size={[0, 4]} wrap>
            {record.reasoning && (
              <Tag color="gold">
                {t('components.provider.modelCatalog.features.reasoning', 'Reasoning')}
              </Tag>
            )}
            {record.supports_tool_call && (
              <Tag color="green">
                {t('components.provider.modelCatalog.features.tools', 'Tools')}
              </Tag>
            )}
            {record.supports_attachment && (
              <Tag color="purple">
                {t('components.provider.modelCatalog.features.vision', 'Vision')}
              </Tag>
            )}
            {record.supports_structured_output && (
              <Tag color="cyan">
                {t('components.provider.modelCatalog.features.structured', 'Structured')}
              </Tag>
            )}
            {record.open_weights && (
              <Tag color="orange">
                {t('components.provider.modelCatalog.features.open', 'Open')}
              </Tag>
            )}
          </Space>
          <Space size={[0, 4]} wrap>
            {record.supports_temperature && (
              <Tag>{t('components.provider.modelCatalog.features.temp', 'Temp')}</Tag>
            )}
            {record.supports_top_p === true && (
              <Tag>{t('components.provider.modelCatalog.features.topP', 'TopP')}</Tag>
            )}
            {record.supports_frequency_penalty === true && (
              <Tag>{t('components.provider.modelCatalog.features.freqP', 'FreqP')}</Tag>
            )}
            {record.supports_presence_penalty === true && (
              <Tag>{t('components.provider.modelCatalog.features.presP', 'PresP')}</Tag>
            )}
            {record.supports_seed === true && (
              <Tag color="volcano">
                {t('components.provider.modelCatalog.features.seed', 'Seed')}
              </Tag>
            )}
            {record.supports_stop === true && (
              <Tag>{t('components.provider.modelCatalog.features.stop', 'Stop')}</Tag>
            )}
            {record.supports_response_format === true && (
              <Tag color="geekblue">
                {t('components.provider.modelCatalog.features.json', 'JSON')}
              </Tag>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: t('components.provider.modelCatalog.columns.action', 'Action'),
      key: 'action',
      width: 90,
      render: (_: unknown, record: ModelCatalogEntry) => {
        const isSelected = selectedModel === record.name;
        return (
          <Button
            type={isSelected ? 'primary' : 'default'}
            size="small"
            onClick={() => onSelect?.(record)}
          >
            {isSelected
              ? t('components.provider.modelCatalog.actions.selected', 'Selected')
              : t('components.provider.modelCatalog.actions.select', 'Select')}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Input
        placeholder={t(
          'components.provider.modelCatalog.searchPlaceholder',
          'Search models by name, provider, or capability...'
        )}
        prefix={<Search size={16} className="text-gray-400" />}
        value={localSearch}
        onChange={handleSearch}
        allowClear
      />
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <Text type="secondary" className="text-sm">
          {t('components.provider.modelCatalog.filtersLabel', 'Filters:')}
        </Text>
        {filterTags.map((tag) => (
          <Tag.CheckableTag
            key={tag.key}
            checked={activeFilters[tag.key] ?? false}
            onChange={(checked) => {
              toggleFilter(tag.key, checked);
            }}
          >
            {t(tag.labelKey)}
          </Tag.CheckableTag>
        ))}
      </div>
      <Table
        dataSource={filteredResults}
        columns={columns}
        rowKey="name"
        loading={catalogLoading}
        pagination={{ pageSize: 8 }}
        size="small"
        scroll={{ x: 880 }}
      />
    </div>
  );
};
