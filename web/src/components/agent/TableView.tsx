/**
 * TableView component (T124)
 *
 * Displays structured data in a table format with sorting,
 * filtering, and export capabilities.
 */

import React, { useState, useMemo } from 'react';
import { Table, Button, Card, Typography, Input, Space } from 'antd';
import {
  DownloadOutlined,
  SearchOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import type { ColumnsType, TableProps } from 'antd/es/table';

const { Text } = Typography;

interface TableViewProps {
  /** Table data */
  data: Record<string, any>[];
  /** Column definitions (optional, auto-detected if not provided) */
  columns?: ColumnsType<any>;
  /** Table title */
  title?: string;
  /** Filename for export */
  filename?: string;
  /** Show search input */
  showSearch?: boolean;
  /** Show export button */
  showExport?: boolean;
  /** Table size */
  size?: 'small' | 'middle' | 'large';
  /** Pagination config */
  pagination?: TableProps<any>['pagination'];
}

/**
 * Component for displaying data in a table with search and export
 */
export const TableView: React.FC<TableViewProps> = ({
  data,
  columns: propColumns,
  title = 'Data Table',
  filename = 'table',
  showSearch = true,
  showExport = true,
  size = 'middle',
  pagination = { pageSize: 10 },
}) => {
  const [searchText, setSearchText] = useState('');
  const [filteredData, setFilteredData] = useState(data);

  // Auto-detect columns if not provided
  const detectedColumns = useMemo(() => {
    if (propColumns) return propColumns;
    if (!data || data.length === 0) return [];

    const keys = Object.keys(data[0]);
    return keys.map((key) => ({
      title: key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
      dataIndex: key,
      key: key,
      sorter: (a: any, b: any) => {
        const aVal = a[key];
        const bVal = b[key];
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return aVal - bVal;
        }
        return String(aVal || '').localeCompare(String(bVal || ''));
      },
      render: (value: any) => {
        if (value === null || value === undefined) return '-';
        if (typeof value === 'object') return JSON.stringify(value);
        if (typeof value === 'boolean') return value ? 'Yes' : 'No';
        return String(value);
      },
    }));
  }, [propColumns, data]);

  // Filter data based on search text
  const handleSearch = (value: string) => {
    setSearchText(value);

    if (!value) {
      setFilteredData(data);
      return;
    }

    const lowerValue = value.toLowerCase();
    const filtered = data.filter((row) =>
      Object.values(row).some((cellValue) =>
        String(cellValue || '').toLowerCase().includes(lowerValue)
      )
    );
    setFilteredData(filtered);
  };

  // Export to CSV
  const handleExportCSV = () => {
    if (!data || data.length === 0) return;

    const headers = detectedColumns.map((col: any) => col.dataIndex).join(',');
    const rows = data.map((row) =>
      detectedColumns
        .map((col: any) => {
          const value = row[col.dataIndex];
          // Escape CSV values
          if (value === null || value === undefined) return '';
          const strValue = String(value);
          if (strValue.includes(',') || strValue.includes('"') || strValue.includes('\n')) {
            return `"${strValue.replace(/"/g, '""')}"`;
          }
          return strValue;
        })
        .join(',')
    );

    const csv = [headers, ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filename}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Card
      title={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileTextOutlined />
            <Text strong>{title}</Text>
            <Text type="secondary" style={{ fontWeight: 'normal', fontSize: 12 }}>
              ({filteredData.length} rows)
            </Text>
          </div>
          <Space>
            {showSearch && (
              <Input
                placeholder="Search..."
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={(e) => handleSearch(e.target.value)}
                allowClear
                style={{ width: 200 }}
              />
            )}
            {showExport && (
              <Button
                icon={<DownloadOutlined />}
                onClick={handleExportCSV}
                disabled={!data || data.length === 0}
              >
                Export CSV
              </Button>
            )}
          </Space>
        </div>
      }
      className="table-view"
    >
      <Table
        columns={detectedColumns}
        dataSource={filteredData}
        rowKey={(record, index) => record.id || index}
        size={size}
        pagination={pagination}
        scroll={{ x: 'max-content' }}
      />
    </Card>
  );
};

export default TableView;
