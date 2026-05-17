/**
 * TableView component (T124)
 *
 * Displays structured data in a table format with sorting,
 * filtering, and export capabilities.
 */

import React, { useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Typography } from 'antd';
import { Download, FileText, Search } from 'lucide-react';

import { LazyTable, LazyButton, LazyCard, LazyInput, LazySpace } from '@/components/ui/lazyAntd';

import type { ColumnsType, TableProps } from 'antd/es/table';

const { Text } = Typography;

type TableRow = Record<string, unknown> & {
  id?: React.Key | undefined;
  key?: React.Key | undefined;
};
type TableColumn = ColumnsType<TableRow>[number];
type DataIndexPath = string | number | readonly (string | number)[];
interface CellValueLabels {
  yes: string;
  no: string;
}

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

const formatCellValue = (
  value: unknown,
  labels: CellValueLabels = { yes: 'Yes', no: 'No' }
): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? labels.yes : labels.no;
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

const getFallbackRowKey = (row: TableRow, index: number): React.Key => {
  const rowIndex = String(index);
  try {
    return `row-${rowIndex}-${JSON.stringify(row)}`;
  } catch {
    return `row-${rowIndex}`;
  }
};

/**
 * Component for displaying data in a table with search and export
 */
export const TableView: React.FC<TableViewProps> = ({
  data,
  columns: propColumns,
  title,
  filename = 'table',
  showSearch = true,
  showExport = true,
  size = 'middle',
  pagination = { pageSize: 10 },
}) => {
  const { t } = useTranslation();
  const [searchText, setSearchText] = useState('');
  const cellValueLabels = useMemo<CellValueLabels>(
    () => ({
      yes: t('common.yes', { defaultValue: 'Yes' }),
      no: t('common.no', { defaultValue: 'No' }),
    }),
    [t]
  );

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
        return formatCellValue(aVal, cellValueLabels).localeCompare(
          formatCellValue(bVal, cellValueLabels)
        );
      },
      render: (value: unknown) => formatCellValue(value, cellValueLabels) || '-',
    }));
  }, [propColumns, data, cellValueLabels]);

  const filteredData = useMemo(() => {
    if (!searchText) return data;
    const lowerValue = searchText.toLowerCase();
    return data.filter((row) =>
      Object.values(row).some((cellValue) =>
        formatCellValue(cellValue, cellValueLabels).toLowerCase().includes(lowerValue)
      )
    );
  }, [data, searchText, cellValueLabels]);
  const rowCountKey =
    filteredData.length === 1 ? 'agent.tableView.rowCount_one' : 'agent.tableView.rowCount_other';
  const rowKeys = useMemo(() => {
    const keys = new WeakMap<TableRow, React.Key>();
    data.forEach((row, index) => {
      keys.set(row, row.id ?? row.key ?? getFallbackRowKey(row, index));
    });
    return keys;
  }, [data]);

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
      exportColumns
        .map(({ path }) =>
          escapeCsvValue(formatCellValue(getNestedValue(row, path), cellValueLabels))
        )
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
    <LazyCard
      title={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileText size={16} />
            <Text strong>
              {title ?? t('agent.tableView.defaultTitle', { defaultValue: 'Data Table' })}
            </Text>
            <Text type="secondary" style={{ fontWeight: 'normal', fontSize: 12 }}>
              ({t(rowCountKey, {
                count: filteredData.length,
                defaultValue: filteredData.length === 1 ? '{{count}} row' : '{{count}} rows',
              })})
            </Text>
          </div>
          <LazySpace>
            {showSearch && (
              <LazyInput
                aria-label={t('agent.tableView.searchAria', {
                  defaultValue: 'Search table rows',
                })}
                placeholder={t('common.search', { defaultValue: 'Search' })}
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
                {t('agent.tableView.exportCsv', { defaultValue: 'Export CSV' })}
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
        rowKey={(record: TableRow) => rowKeys.get(record) ?? record.id ?? record.key ?? 0}
        size={size}
        pagination={pagination}
        scroll={{ x: 'max-content' }}
      />
    </LazyCard>
  );
};

export default TableView;
