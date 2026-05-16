import { memo, useMemo } from 'react';
import type { CSSProperties } from 'react';

import { useTranslation } from 'react-i18next';

import {
  normalizeNumberValue,
  normalizeStringValue,
  normalizeStyle,
  resolveBoundNumberValue,
  resolveBoundStringValue,
  type StringValue,
} from './a2uiCustomUtils';
import { useA2UIActions, useA2UIState } from './a2uiInternals';

interface TableColumn {
  header?: StringValue | string | undefined;
  align?: unknown;
  width?: unknown;
}

interface TableRow {
  key?: unknown;
  cells?: unknown;
}

interface TableProperties {
  caption?: StringValue | string;
  emptyText?: StringValue | string;
  columns?: unknown[];
  rows?: unknown[];
  style?: Record<string, unknown>;
}

type TableNode = Record<string, unknown> & {
  id: string;
  dataContextPath?: string;
  weight?: number;
  properties?: TableProperties;
};

interface ResolvedColumn {
  key: string;
  header: string;
  align: 'left' | 'center' | 'right';
  width?: string;
}

interface ResolvedRow {
  key: string;
  cells: string[];
}

function normalizeColumnAlign(input: unknown): ResolvedColumn['align'] {
  return input === 'center' || input === 'right' ? input : 'left';
}

function resolveCellValue(
  input: unknown,
  node: TableNode,
  surfaceId: string,
  actions: ReturnType<typeof useA2UIActions>
): string {
  if (typeof input === 'string') {
    return input;
  }
  if (typeof input === 'number' && Number.isFinite(input)) {
    return String(input);
  }
  if (typeof input === 'boolean') {
    return input ? 'true' : 'false';
  }

  const resolvedString = resolveBoundStringValue(input, node, surfaceId, actions);
  if (typeof resolvedString === 'string') {
    return resolvedString;
  }

  const resolvedNumber = resolveBoundNumberValue(input, node, surfaceId, actions);
  if (typeof resolvedNumber === 'number') {
    return String(resolvedNumber);
  }

  if (normalizeNumberValue(input) || normalizeStringValue(input)) {
    return '';
  }

  if (input && typeof input === 'object' && !Array.isArray(input)) {
    const record = input as Record<string, unknown>;
    if (typeof record.literalBoolean === 'boolean') {
      return record.literalBoolean ? 'true' : 'false';
    }
    if (typeof record.literal === 'boolean') {
      return record.literal ? 'true' : 'false';
    }
  }

  return '';
}

function normalizeColumns(
  input: TableProperties['columns'],
  node: TableNode,
  surfaceId: string,
  actions: ReturnType<typeof useA2UIActions>
): ResolvedColumn[] {
  if (!Array.isArray(input)) {
    return [];
  }

  const normalizedColumns: ResolvedColumn[] = [];
  input.forEach((column, index) => {
    if (typeof column === 'string') {
      normalizedColumns.push({ key: `column-${String(index)}`, header: column, align: 'left' });
      return;
    }
    if (!column || typeof column !== 'object' || Array.isArray(column)) {
      return;
    }

    const columnRecord = column as TableColumn;
    const header = resolveBoundStringValue(columnRecord.header, node, surfaceId, actions);
    if (!header) {
      return;
    }
    normalizedColumns.push({
      key: `column-${String(index)}`,
      header,
      align: normalizeColumnAlign(columnRecord.align),
      ...(typeof columnRecord.width === 'string' ? { width: columnRecord.width } : {}),
    });
  });
  return normalizedColumns;
}

function normalizeRows(
  input: TableProperties['rows'],
  node: TableNode,
  surfaceId: string,
  actions: ReturnType<typeof useA2UIActions>
): ResolvedRow[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.flatMap((row, rowIndex) => {
    const rowRecord =
      row && typeof row === 'object' && !Array.isArray(row) ? (row as TableRow) : null;
    const rawCells = Array.isArray(row) ? row : rowRecord ? rowRecord.cells : undefined;
    if (!Array.isArray(rawCells)) {
      return [];
    }

    return [
      {
        key:
          rowRecord && typeof rowRecord.key === 'string'
            ? rowRecord.key
            : `row-${String(rowIndex)}`,
        cells: rawCells.map((cell) => resolveCellValue(cell, node, surfaceId, actions)),
      },
    ];
  });
}

export const A2UITable = memo(function A2UITable({
  node,
  surfaceId,
}: {
  node: TableNode;
  surfaceId: string;
}) {
  const { t } = useTranslation();
  const actions = useA2UIActions();
  const { version } = useA2UIState();

  const props = node.properties ?? {};
  const caption = useMemo(() => {
    void version;
    return resolveBoundStringValue(props.caption, node, surfaceId, actions);
  }, [actions, node, props.caption, surfaceId, version]);
  const emptyText = useMemo(() => {
    void version;
    return (
      resolveBoundStringValue(props.emptyText, node, surfaceId, actions) ??
      t('components.a2uiTable.noData')
    );
  }, [actions, node, props.emptyText, surfaceId, version, t]);
  const columns = useMemo(() => {
    void version;
    return normalizeColumns(props.columns, node, surfaceId, actions);
  }, [actions, node, props.columns, surfaceId, version]);
  const rows = useMemo(() => {
    void version;
    return normalizeRows(props.rows, node, surfaceId, actions);
  }, [actions, node, props.rows, surfaceId, version]);

  const rootStyle =
    node.weight !== undefined ? ({ '--weight': node.weight } as CSSProperties) : undefined;
  const sectionStyle = useMemo(
    () =>
      ({
        overflowX: 'auto',
        minWidth: 0,
        ...normalizeStyle(props.style),
      }) satisfies CSSProperties,
    [props.style]
  );

  if (columns.length === 0) {
    return null;
  }

  return (
    <div className="a2ui-table" style={rootStyle}>
      <section className="a2ui-table__section" style={sectionStyle}>
        <table className="a2ui-table__table">
          {caption ? (
            <caption className="a2ui-table__caption" dir="auto">
              {caption}
            </caption>
          ) : null}
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  className="a2ui-table__header"
                  style={{ textAlign: column.align, width: column.width }}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? (
              rows.map((row) => (
                <tr key={row.key}>
                  {columns.map((column, columnIndex) => (
                    <td
                      key={`${row.key}-${column.key}`}
                      className="a2ui-table__cell"
                      style={{ textAlign: column.align }}
                    >
                      {row.cells[columnIndex] ?? ''}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length} className="a2ui-table__empty">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
});
