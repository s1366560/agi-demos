import { useId } from 'react';

import { useI18n } from '../../i18n';
import {
  ComponentRegistry,
  useA2UIComponent,
  type A2UIRuntimeComponentProps,
} from '../../vendor/a2uiRendererInternals.mjs';

type JsonRecord = Record<string, unknown>;

let registered = false;

export function ensureDesktopA2UIRegistry(): void {
  if (registered) return;
  const registry = ComponentRegistry.getInstance();
  registry.register('Badge', { component: DesktopA2UIBadge });
  registry.register('Radio', { component: DesktopA2UIRadio });
  registry.register('Table', { component: DesktopA2UITable });
  registry.register('Progress', { component: DesktopA2UIProgress });
  registered = true;
}

function DesktopA2UIBadge({ node, surfaceId }: A2UIRuntimeComponentProps) {
  const helpers = useA2UIComponent(node, surfaceId);
  const text = helpers.resolveString(node.properties.text ?? node.properties.label);
  if (!text) return null;
  const tone = safeTone(node.properties.tone);
  return (
    <span className="desktop-a2ui-badge" data-tone={tone}>
      {text}
    </span>
  );
}

function DesktopA2UIRadio({ node, surfaceId }: A2UIRuntimeComponentProps) {
  const { t } = useI18n();
  const helpers = useA2UIComponent(node, surfaceId);
  const description = helpers.resolveString(node.properties.description);
  const options = radioOptions(node.properties.options, helpers.resolveString);
  const bindingPath = resolveBindingPath(node.properties);
  const selected =
    (bindingPath ? primitiveString(helpers.getValue(bindingPath)) : null) ??
    helpers.resolveString(
      node.properties.value ?? node.properties.selection ?? node.properties.selected,
    );
  const groupId = useId();
  if (options.length === 0) return null;
  return (
    <fieldset className="desktop-a2ui-radio">
      <legend id={`${groupId}-legend`}>
        {description ?? t('session.insights.selection')}
      </legend>
      <div role="radiogroup" aria-labelledby={`${groupId}-legend`}>
        {options.map((option) => (
          <label key={option.value}>
            <input
              type="radio"
              name={`${surfaceId}-${node.id}`}
              value={option.value}
              defaultChecked={selected === option.value}
              onChange={() => {
                if (bindingPath) helpers.setValue(bindingPath, option.value);
              }}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function DesktopA2UITable({ node, surfaceId }: A2UIRuntimeComponentProps) {
  const { t } = useI18n();
  const helpers = useA2UIComponent(node, surfaceId);
  const columns = tableColumns(node.properties.columns, helpers.resolveString);
  const rows = tableRows(node.properties.rows, helpers);
  const caption = helpers.resolveString(node.properties.caption);
  if (columns.length === 0) return null;
  return (
    <div className="desktop-a2ui-table-wrap">
      <table className="desktop-a2ui-table">
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col" style={{ textAlign: column.align }}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length > 0 ? (
            rows.map((row) => (
              <tr key={row.key}>
                {columns.map((column, index) => (
                  <td key={`${row.key}-${column.key}`} style={{ textAlign: column.align }}>
                    {row.cells[index] ?? ''}
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={columns.length}>{t('overview.none')}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DesktopA2UIProgress({ node, surfaceId }: A2UIRuntimeComponentProps) {
  const { t } = useI18n();
  const helpers = useA2UIComponent(node, surfaceId);
  const label = helpers.resolveString(node.properties.label) ?? t('myWork.progress');
  const maximum = positiveNumber(helpers.resolveNumber(node.properties.max)) ?? 100;
  const value = clamp(helpers.resolveNumber(node.properties.value) ?? 0, 0, maximum);
  const percent = Math.round((value / maximum) * 100);
  const labelId = useId();
  return (
    <div className="desktop-a2ui-progress" data-tone={safeTone(node.properties.tone)}>
      <span id={labelId}>{label}</span>
      {node.properties.showValue === false ? null : <strong>{percent}%</strong>}
      <div
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuemin={0}
        aria-valuemax={maximum}
        aria-valuenow={value}
      >
        <i style={{ width: `${String(percent)}%` }} />
      </div>
    </div>
  );
}

function radioOptions(
  value: unknown,
  resolveString: (value: unknown) => string | null,
): Array<{ label: string; value: string }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    if (typeof candidate === 'string' && candidate.trim()) {
      return [{ label: candidate.trim(), value: candidate.trim() }];
    }
    const option = asRecord(candidate);
    const optionValue = primitiveString(option?.value);
    const label = resolveString(option?.label ?? option?.text) ?? optionValue;
    return optionValue && label ? [{ label, value: optionValue }] : [];
  });
}

function tableColumns(
  value: unknown,
  resolveString: (value: unknown) => string | null,
): Array<{ key: string; header: string; align: 'left' | 'center' | 'right' }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate, index) => {
    if (typeof candidate === 'string' && candidate.trim()) {
      return [{ key: `column-${String(index)}`, header: candidate.trim(), align: 'left' as const }];
    }
    const column = asRecord(candidate);
    const header = resolveString(column?.header);
    if (!header) return [];
    const align =
      column?.align === 'center' || column?.align === 'right' ? column.align : 'left';
    return [{ key: `column-${String(index)}`, header, align }];
  });
}

function tableRows(
  value: unknown,
  helpers: ReturnType<typeof useA2UIComponent>,
): Array<{ key: string; cells: string[] }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate, index) => {
    const record = asRecord(candidate);
    const cells = Array.isArray(candidate)
      ? candidate
      : Array.isArray(record?.cells)
        ? record.cells
        : null;
    if (!cells) return [];
    return [
      {
        key: primitiveString(record?.key) ?? `row-${String(index)}`,
        cells: cells.map((cell) => resolveCell(cell, helpers)),
      },
    ];
  });
}

function resolveCell(
  value: unknown,
  helpers: ReturnType<typeof useA2UIComponent>,
): string {
  const primitive = primitiveString(value);
  if (primitive !== null) return primitive;
  return (
    helpers.resolveString(value) ??
    primitiveString(helpers.resolveNumber(value)) ??
    primitiveString(helpers.resolveBoolean(value)) ??
    ''
  );
}

function resolveBindingPath(properties: JsonRecord): string | null {
  const values = [
    properties.selections,
    properties.value,
    properties.selection,
    properties.selected,
  ];
  for (const value of values) {
    const path = asRecord(value)?.path;
    if (typeof path === 'string' && path.startsWith('/') && path.length <= 1_024) return path;
  }
  return typeof properties.path === 'string' &&
    properties.path.startsWith('/') &&
    properties.path.length <= 1_024
    ? properties.path
    : null;
}

function primitiveString(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return null;
}

function safeTone(value: unknown): 'neutral' | 'success' | 'warning' | 'error' {
  return value === 'success' || value === 'warning' || value === 'error' ? value : 'neutral';
}

function positiveNumber(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value > 0 ? value : null;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function asRecord(value: unknown): JsonRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}
