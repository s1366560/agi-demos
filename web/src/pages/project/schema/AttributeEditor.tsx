/**
 * AttributeEditor - Shared attribute list editor for schema type modals.
 *
 * Used by the EntityTypeList and EdgeTypeList modals to edit attribute
 * definitions (name, data type, documentation, required flag, and optional
 * per-type validation rules).
 */

import React, { useCallback, useId, useState } from 'react';

import { ChevronDown, FileEdit, Gavel, Plus } from 'lucide-react';

// ============================================================================
// Types
// ============================================================================

export interface AttributeValidation {
  ge?: number | undefined;
  le?: number | undefined;
  min_len?: number | undefined;
  max_len?: number | undefined;
  regex?: string | undefined;
}

export interface EditableAttribute {
  name: string;
  type: string;
  description: string;
  required: boolean;
  validation?: AttributeValidation | undefined;
}

export type AttributeUpdateField =
  | 'name'
  | 'type'
  | 'description'
  | 'required'
  | `validation.${keyof AttributeValidation}`;

export type AttributeUpdateValue = string | boolean | number | undefined;

export const ATTRIBUTE_DATA_TYPES = [
  'String',
  'Integer',
  'Float',
  'Boolean',
  'DateTime',
  'List',
  'Dict',
] as const;

export const createEmptyAttribute = (): EditableAttribute => ({
  name: '',
  type: 'String',
  description: '',
  required: false,
  validation: {},
});

function isValidationField(value: string): value is keyof AttributeValidation {
  return (
    value === 'ge' ||
    value === 'le' ||
    value === 'min_len' ||
    value === 'max_len' ||
    value === 'regex'
  );
}

function normalizeValidationValue(
  field: keyof AttributeValidation,
  value: AttributeUpdateValue
): string | number | undefined {
  if (field === 'regex') {
    return typeof value === 'string' ? value : undefined;
  }

  return typeof value === 'number' ? value : undefined;
}

export function updateAttributeValue<T extends EditableAttribute>(
  attribute: T,
  field: AttributeUpdateField,
  value: AttributeUpdateValue
): T {
  if (field.startsWith('validation.')) {
    const validationField = field.slice('validation.'.length);
    if (!isValidationField(validationField)) return attribute;

    return {
      ...attribute,
      validation: {
        ...attribute.validation,
        [validationField]: normalizeValidationValue(validationField, value),
      },
    };
  }

  if (field === 'required') {
    return { ...attribute, required: value === true };
  }

  return { ...attribute, [field]: typeof value === 'string' ? value : '' };
}

// ============================================================================
// Labels
// ============================================================================

export interface AttributeEditorLabels {
  definedAttributes: string;
  addAttribute: string;
  attributeTitle: (index: number) => string;
  removeAttribute: string;
  nameLabel: string;
  namePlaceholder: string;
  dataTypeLabel: string;
  requiredLabel: string;
  docstringLabel: string;
  docstringPlaceholder: string;
  /** Only required when `showValidation` is enabled. */
  validationRulesTitle?: ((type: string) => string) | undefined;
  minValLabel?: string | undefined;
  maxValLabel?: string | undefined;
  minLenLabel?: string | undefined;
  maxLenLabel?: string | undefined;
  regexLabel?: string | undefined;
  regexPlaceholder?: string | undefined;
}

interface AttributeEditorProps {
  attributes: EditableAttribute[];
  onAdd: () => void;
  onUpdate: (index: number, field: AttributeUpdateField, value: AttributeUpdateValue) => void;
  onRemove: (index: number) => void;
  labels: AttributeEditorLabels;
  showRequired?: boolean | undefined;
  showValidation?: boolean | undefined;
}

// ============================================================================
// Component
// ============================================================================

export const AttributeEditor: React.FC<AttributeEditorProps> = React.memo(
  ({ attributes, onAdd, onUpdate, onRemove, labels, showRequired = false, showValidation }) => {
    // Stable row ids for keys and label association. Rows are only added or
    // removed through this component's controls, so an index-aligned id list
    // stays in sync with the attributes array.
    const rowIdPrefix = useId();
    const [rowIdentity, setRowIdentity] = useState(() => ({
      ids: attributes.map((_, index) => `${rowIdPrefix}-attr-row-${String(index)}`),
      nextId: attributes.length,
    }));
    const rowIds = rowIdentity.ids;

    const handleAdd = useCallback(() => {
      setRowIdentity((current) => {
        const ids = [...current.ids];
        let nextId = current.nextId;
        while (ids.length < attributes.length) {
          ids.push(`${rowIdPrefix}-attr-row-${String(nextId)}`);
          nextId += 1;
        }
        ids.push(`${rowIdPrefix}-attr-row-${String(nextId)}`);
        return { ids, nextId: nextId + 1 };
      });
      onAdd();
    }, [attributes.length, onAdd, rowIdPrefix]);

    const handleRemove = useCallback(
      (index: number) => {
        setRowIdentity((current) => ({
          ...current,
          ids: current.ids.filter((_, rowIndex) => rowIndex !== index),
        }));
        onRemove(index);
      },
      [onRemove]
    );

    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            {labels.definedAttributes}
          </h4>
          <button
            type="button"
            onClick={handleAdd}
            className="text-blue-600 dark:text-primary text-xs font-bold flex items-center gap-1 hover:text-blue-700 dark:hover:text-primary-light px-3 py-1.5 bg-blue-50 dark:bg-primary/10 rounded-lg border border-blue-200 dark:border-primary/20 transition-colors"
          >
            <Plus className="w-4 h-4" aria-hidden="true" /> {labels.addAttribute}
          </button>
        </div>
        <div className="flex flex-col gap-4">
          {attributes.map((attr, idx) => {
            const rowId = rowIds[idx] ?? `${rowIdPrefix}-external-attr-row-${String(idx)}`;
            const validation = attr.validation ?? {};
            return (
              <div
                key={rowId}
                className="overflow-hidden rounded-lg border border-blue-200 bg-white shadow-sm ring-1 ring-blue-100 dark:border-primary/50 dark:bg-surface-dark dark:ring-primary/30"
              >
                <div className="bg-slate-50 dark:bg-surface-dark-alt px-4 py-2 flex items-center justify-between border-b border-slate-200 dark:border-border-dark">
                  <div className="flex items-center gap-2">
                    <FileEdit className="w-4 h-4 text-blue-600 dark:text-primary" aria-hidden="true" />
                    <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wide">
                      {labels.attributeTitle(idx + 1)}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      handleRemove(idx);
                    }}
                    className="text-xs text-red-600 dark:text-red-400 hover:text-red-500 dark:hover:text-red-300 font-medium flex items-center gap-1"
                  >
                    {labels.removeAttribute}
                  </button>
                </div>
                <div className="p-5 flex flex-col gap-6">
                  <div className="grid grid-cols-12 gap-4">
                    <div className="col-span-5">
                      <label
                        htmlFor={`${rowId}-name`}
                        className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                      >
                        {labels.nameLabel}
                      </label>
                      <input
                        id={`${rowId}-name`}
                        className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 font-mono focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors"
                        type="text"
                        spellCheck={false}
                        value={attr.name}
                        onChange={(e) => {
                          onUpdate(idx, 'name', e.target.value);
                        }}
                        placeholder={labels.namePlaceholder}
                      />
                    </div>
                    <div className="col-span-4">
                      <label
                        htmlFor={`${rowId}-type`}
                        className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                      >
                        {labels.dataTypeLabel}
                      </label>
                      <div className="relative">
                        <select
                          id={`${rowId}-type`}
                          className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 outline-none appearance-none focus:border-blue-600 dark:focus:border-primary"
                          value={attr.type}
                          onChange={(e) => {
                            onUpdate(idx, 'type', e.target.value);
                          }}
                        >
                          {ATTRIBUTE_DATA_TYPES.map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </select>
                        <ChevronDown
                          className="absolute right-2 top-2.5 w-4 h-4 text-slate-400 dark:text-text-muted pointer-events-none"
                          aria-hidden="true"
                        />
                      </div>
                    </div>
                    {showRequired && (
                      <div className="col-span-3 flex items-end pb-2">
                        <label className="flex items-center gap-2 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={attr.required}
                            onChange={(e) => {
                              onUpdate(idx, 'required', e.target.checked);
                            }}
                            className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                          />
                          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                            {labels.requiredLabel}
                          </span>
                        </label>
                      </div>
                    )}
                  </div>
                  <div>
                    <label
                      htmlFor={`${rowId}-description`}
                      className="text-2xs uppercase text-slate-500 dark:text-text-muted font-bold mb-1.5 block"
                    >
                      {labels.docstringLabel}
                    </label>
                    <input
                      id={`${rowId}-description`}
                      className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-500 dark:text-text-muted px-3 py-2 focus:text-slate-900 dark:focus:text-white focus:border-blue-600 dark:focus:border-primary focus:ring-1 focus:ring-blue-600 dark:focus:ring-primary outline-none transition-colors"
                      type="text"
                      value={attr.description}
                      onChange={(e) => {
                        onUpdate(idx, 'description', e.target.value);
                      }}
                      placeholder={labels.docstringPlaceholder}
                    />
                  </div>

                  {showValidation && (
                    <div className="bg-slate-100 dark:bg-background-dark rounded-lg border border-slate-200 dark:border-border-dark p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <Gavel className="w-4 h-4 text-blue-500" aria-hidden="true" />
                        <span className="text-xs font-bold text-slate-700 dark:text-white uppercase tracking-wider">
                          {labels.validationRulesTitle?.(attr.type)}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        {(attr.type === 'Integer' || attr.type === 'Float') && (
                          <>
                            <div>
                              <label
                                htmlFor={`${rowId}-ge`}
                                className="text-2xs text-slate-500 dark:text-text-muted block mb-1 font-mono"
                              >
                                {labels.minValLabel}
                              </label>
                              <input
                                id={`${rowId}-ge`}
                                type="number"
                                className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                value={validation.ge ?? ''}
                                onChange={(e) => {
                                  onUpdate(
                                    idx,
                                    'validation.ge',
                                    e.target.value ? Number(e.target.value) : undefined
                                  );
                                }}
                              />
                            </div>
                            <div>
                              <label
                                htmlFor={`${rowId}-le`}
                                className="text-2xs text-slate-500 dark:text-text-muted block mb-1 font-mono"
                              >
                                {labels.maxValLabel}
                              </label>
                              <input
                                id={`${rowId}-le`}
                                type="number"
                                className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                value={validation.le ?? ''}
                                onChange={(e) => {
                                  onUpdate(
                                    idx,
                                    'validation.le',
                                    e.target.value ? Number(e.target.value) : undefined
                                  );
                                }}
                              />
                            </div>
                          </>
                        )}
                        {attr.type === 'String' && (
                          <>
                            <div>
                              <label
                                htmlFor={`${rowId}-min-len`}
                                className="text-2xs text-slate-500 dark:text-text-muted block mb-1 font-mono"
                              >
                                {labels.minLenLabel}
                              </label>
                              <input
                                id={`${rowId}-min-len`}
                                type="number"
                                className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                value={validation.min_len ?? ''}
                                onChange={(e) => {
                                  onUpdate(
                                    idx,
                                    'validation.min_len',
                                    e.target.value ? Number(e.target.value) : undefined
                                  );
                                }}
                              />
                            </div>
                            <div>
                              <label
                                htmlFor={`${rowId}-max-len`}
                                className="text-2xs text-slate-500 dark:text-text-muted block mb-1 font-mono"
                              >
                                {labels.maxLenLabel}
                              </label>
                              <input
                                id={`${rowId}-max-len`}
                                type="number"
                                className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                value={validation.max_len ?? ''}
                                onChange={(e) => {
                                  onUpdate(
                                    idx,
                                    'validation.max_len',
                                    e.target.value ? Number(e.target.value) : undefined
                                  );
                                }}
                              />
                            </div>
                            <div className="col-span-2">
                              <label
                                htmlFor={`${rowId}-regex`}
                                className="text-2xs text-slate-500 dark:text-text-muted block mb-1 font-mono"
                              >
                                {labels.regexLabel}
                              </label>
                              <input
                                id={`${rowId}-regex`}
                                type="text"
                                spellCheck={false}
                                className="w-full bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm px-2 py-1.5 focus:border-blue-600 focus:ring-0"
                                placeholder={labels.regexPlaceholder}
                                value={validation.regex ?? ''}
                                onChange={(e) => {
                                  onUpdate(idx, 'validation.regex', e.target.value);
                                }}
                              />
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
);

AttributeEditor.displayName = 'AttributeEditor';
