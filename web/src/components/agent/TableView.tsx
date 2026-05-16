/**
 * TableView component (T124)
 *
 * Displays structured data in a table format with sorting,
 * filtering, and export capabilities.
 */

import React, { useState, useMemo } from 'react';

import { Typography } from 'antd';
import { Download, FileText, Search } from 'lucide-react';

import { LazyTable, LazyButton, LazyCard, LazyInput, LazySpace } from '@/components/ui/lazyAntd';

import type { ColumnsType, TableProps } from 'antd/es/table';

const { Text } = Typography;

type TableRow = Record<string, unknown> & { id?: React.Key | undefined };
type TableColumn = ColumnsType<TableRow>[number];
type DataIndexPath = string | number | readonly (string | number)[];

interface TableViewProps {
  /** Table data */
  data: TableRow[];
  /** Column definitions (optional, auto-detected if not provided) */
  columns?: ColumnsType<TableRow> | undefined;
  /** Table title */
  title?: string | undefined;
  /** Filename for export */
  filename?: string | undefined;
  /** Show search input */
  showSearch?: boolean | undefined;
  /** Show export button */
  showExport?: boolean | undefined;
  /** Table size */
  size?: 'small' | 'middle' | 'large' | undefined;
  /** Pagination config */
  pagination?: TableProps<TableRow>['pagination'] | undefined;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const formatCellValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'bigint') return value.toString();
  if (typeof value === 'symbol') return value.description ?? '';
  return '';
};

const getDataIndexPath = (column: TableColumn): DataIndexPath | undefined => {
  if (!('dataIndex' in column)) return undefined;
  const { dataIndex } = column;
  if (typeof dataIndex === 'string' || typeof dataIndex === 'number' || Array.isArray(dataIndex)) {
    return dataIndex;
  }
  return undefined;
};

const getNestedValue = (row: TableRow, path: DataIndexPath): unknown => {
  if (!Array.isArray(path)) {
    return row[String(path)];
  }

  return path.reduce<unknown>((current, key) => {
    if (!isRecord(current)) return undefined;
    return current[String(key)];
  }, row);
};

const getColumnHeader = (column: TableColumn, path: DataIndexPath): string => {
  if ('title' in column && (typeof column.title === 'string' || typeof column.title === 'number')) {
    return String(column.title);
  }
  return Array.isArray(path) ? path.map(String).join('.') : String(path);
};

const escapeCsvValue = (value: unknown): string => {
  const strValue = formatCellValue(value);
  if (strValue.includes(',') || strValue.includes('"') || strValue.includes('\n')) {
    return `"${strValue.replace(/"/g, '""')}"`;
  }
  return strValue;
};

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

  // Auto-detect columns if not provided
  const detectedColumns = useMemo<ColumnsType<TableRow>>(() => {
    if (propColumns) return propColumns;
    const firstRow = data[0];
    if (!firstRow) return [];

    const keys = Object.keys(firstRow);
    return keys.map((key) => ({
      title: key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
      dataIndex: key,
      key: key,
      sorter: (a, b) => {
        const aVal = a[key];
        const bVal = b[key];
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return aVal - bVal;
        }
        return formatCellValue(aVal).localeCompare(formatCellValue(bVal));
      },
      render: (value: unknown) => formatCellValue(value) || '-',
    }));
  }, [propColumns, data]);

  const filteredData = useMemo(() => {
    if (!searchText) return data;
    const lowerValue = searchText.toLowerCase();
    return data.filter((row) =>
      Object.values(row).some((cellValue) =>
        formatCellValue(cellValue).toLowerCase().includes(lowerValue)
      )
    );
  }, [data, searchText]);

  // Export to CSV
  const handleExportCSV = () => {
    if (data.length === 0) return;

    const exportColumns = detectedColumns
      .map((column) => ({ column, path: getDataIndexPath(column) }))
      .filter((item): item is { column: TableColumn; path: DataIndexPath } => item.path != null);

    const headers = exportColumns
      .map(({ column, path }) => escapeCsvValue(getColumnHeader(column, path)))
      .join(',');
    const rows = data.map((row) =>
      exportColumns.map(({ path }) => escapeCsvValue(getNestedValue(row, path))).join(',')
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
    <LazyCard
      title={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileText size={16} />
            <Text strong>{title}</Text>
            <Text type="secondary" style={{ fontWeight: 'normal', fontSize: 12 }}>
              ({filteredData.length} rows)
            </Text>
          </div>
          <LazySpace>
            {showSearch && (
              <LazyInput
                placeholder="Search..."
                prefix={<Search size={16} />}
                value={searchText}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setSearchText(e.target.value);
                }}
                allowClear
                style={{ width: 200 }}
              />
            )}
            {showExport && (
              <LazyButton
                icon={<Download size={16} />}
                onClick={handleExportCSV}
                disabled={data.length === 0}
              >
                Export CSV
              </LazyButton>
            )}
          </LazySpace>
        </div>
      }
      className="table-view"
    >
      <LazyTable
        columns={detectedColumns}
        dataSource={filteredData}
        rowKey={(record: TableRow, index?: number) => record.id ?? index ?? 0}
        size={size}
        pagination={pagination}
        scroll={{ x: 'max-content' }}
      />
    </LazyCard>
  );
};

export default TableView;
