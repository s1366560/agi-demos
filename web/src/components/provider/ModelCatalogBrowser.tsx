import React, { useEffect, useState } from 'react';

import { SearchOutlined } from '@ant-design/icons';
import { Table, Input, Tag, Space, Typography, Button } from 'antd';
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

  useEffect(() => {
    fetchModelCatalog(filterProvider);
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
      title: 'Model',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: ModelCatalogEntry) => (
        <Space direction="vertical" size={0}>
          <Text strong>
            {record.provider && (
              <span className="mr-2" role="img" aria-label="provider">
                {getProviderIcon(record.provider)}
              </span>
            )}
            {text}
          </Text>
          {record.provider && <Text type="secondary" className="text-xs">{record.provider}</Text>}
        </Space>
      ),
    },
    {
      title: 'Context Window',
      dataIndex: 'context_length',
      key: 'context_length',
      render: (val: number) => <Text>{(val / 1000).toFixed(0)}k tokens</Text>,
    },
    {
      title: 'Capabilities',
      dataIndex: 'capabilities',
      key: 'capabilities',
      render: (caps: string[]) => (
        <Space size={[0, 4]} wrap>
          {caps.map((cap) => (
            <Tag key={cap} color={cap === 'chat' ? 'blue' : cap === 'vision' ? 'purple' : 'default'}>
              {cap}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: 'Action',
      key: 'action',
      render: (_: unknown, record: ModelCatalogEntry) => {
        const isSelected = selectedModel === record.name;
        return (
          <Button
            type={isSelected ? 'primary' : 'default'}
            onClick={() => onSelect?.(record)}
          >
            {isSelected ? 'Selected' : 'Select'}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Input
        placeholder="Search models by name, provider, or capability..."
        prefix={<SearchOutlined className="text-gray-400" />}
        value={localSearch}
        onChange={handleSearch}
        allowClear
      />
      <Table
        dataSource={modelSearchResults}
        columns={columns}
        rowKey="name"
        loading={catalogLoading}
        pagination={{ pageSize: 5 }}
        size="small"
      />
    </div>
  );
};
