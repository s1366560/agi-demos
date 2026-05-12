import { useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Form, Input, InputNumber, Select, Switch, Tag, Typography } from 'antd';
import { Plus, X } from 'lucide-react';

import {
  GENE_CONFIG_SCHEMAS,
  type GeneConfigDraft,
  type GeneConfigFieldDef,
  type GeneConfigFieldValue,
  type GeneConfigValidationError,
} from '@/types/geneConfig';

import type { CyberGeneCategory } from '@/types/workspace';

export interface GeneConfigFormProps {
  category: CyberGeneCategory;
  draft: GeneConfigDraft;
  errors?: GeneConfigValidationError[];
  onChange: (next: GeneConfigDraft) => void;
}

const setField = (
  draft: GeneConfigDraft,
  key: string,
  value: GeneConfigFieldValue
): GeneConfigDraft => ({
  values: { ...draft.values, [key]: value },
  extra: draft.extra,
});

const StringListEditor: React.FC<{
  value: string[];
  onChange: (next: string[]) => void;
}> = ({ value, onChange }) => {
  const handleAdd = useCallback(() => {
    onChange([...value, '']);
  }, [onChange, value]);
  return (
    <div className="space-y-2">
      {value.map((item, idx) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: order-dependent editable list
        <div key={`item-${idx}`} className="flex items-center gap-2">
          <Input
            value={item}
            onChange={(e) => {
              const next = [...value];
              next[idx] = e.target.value;
              onChange(next);
            }}
          />
          <button
            type="button"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            onClick={() => {
              onChange(value.filter((_, i) => i !== idx));
            }}
            aria-label="Remove item"
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={handleAdd}
        className="inline-flex items-center gap-1 rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50"
      >
        <Plus size={12} /> Add
      </button>
    </div>
  );
};

const KVListEditor: React.FC<{
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}> = ({ value, onChange }) => {
  const entries = Object.entries(value);
  const updateKey = (oldKey: string, newKey: string) => {
    if (newKey === oldKey) return;
    const next: Record<string, string> = {};
    for (const [k, v] of entries) next[k === oldKey ? newKey : k] = v;
    onChange(next);
  };
  const updateValue = (key: string, newValue: string) => {
    onChange({ ...value, [key]: newValue });
  };
  const removeKey = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };
  const addEntry = () => {
    let suffix = entries.length + 1;
    let key = `key${suffix}`;
    while (key in value) {
      suffix += 1;
      key = `key${suffix}`;
    }
    onChange({ ...value, [key]: '' });
  };
  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <Input
            value={k}
            placeholder="key"
            className="max-w-[40%]"
            onChange={(e) => {
              updateKey(k, e.target.value);
            }}
          />
          <Input
            value={v}
            placeholder="value"
            onChange={(e) => {
              updateValue(k, e.target.value);
            }}
          />
          <button
            type="button"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            onClick={() => {
              removeKey(k);
            }}
            aria-label="Remove entry"
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={addEntry}
        className="inline-flex items-center gap-1 rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50"
      >
        <Plus size={12} /> Add entry
      </button>
    </div>
  );
};

export const GeneConfigForm: React.FC<GeneConfigFormProps> = ({
  category,
  draft,
  errors,
  onChange,
}) => {
  const { t } = useTranslation();
  const schema = GENE_CONFIG_SCHEMAS[category];
  const errorByKey = new Map((errors ?? []).map((e) => [e.fieldKey, e]));

  const renderField = (field: GeneConfigFieldDef) => {
    const value = draft.values[field.key];
    switch (field.type) {
      case 'string':
        return (
          <Input
            value={typeof value === 'string' ? value : ''}
            onChange={(e) => {
              onChange(setField(draft, field.key, e.target.value));
            }}
          />
        );
      case 'text':
        return (
          <Input.TextArea
            value={typeof value === 'string' ? value : ''}
            autoSize={{ minRows: 3, maxRows: 8 }}
            onChange={(e) => {
              onChange(setField(draft, field.key, e.target.value));
            }}
          />
        );
      case 'number':
        return (
          <InputNumber
            value={typeof value === 'number' ? value : 0}
            {...(field.min !== undefined ? { min: field.min } : {})}
            {...(field.max !== undefined ? { max: field.max } : {})}
            {...(field.step !== undefined ? { step: field.step } : {})}
            onChange={(next) => {
              onChange(setField(draft, field.key, typeof next === 'number' ? next : 0));
            }}
          />
        );
      case 'boolean':
        return (
          <Switch
            checked={Boolean(value)}
            onChange={(next) => {
              onChange(setField(draft, field.key, next));
            }}
          />
        );
      case 'select':
        return (
          <Select
            value={typeof value === 'string' ? value : ''}
            options={field.options ?? []}
            onChange={(next: string) => {
              onChange(setField(draft, field.key, next));
            }}
            className="w-full"
          />
        );
      case 'string_list':
        return (
          <StringListEditor
            value={Array.isArray(value) ? (value as string[]) : []}
            onChange={(next) => {
              onChange(setField(draft, field.key, next));
            }}
          />
        );
      case 'kv_list':
        return (
          <KVListEditor
            value={
              value && typeof value === 'object' && !Array.isArray(value)
                ? (value as Record<string, string>)
                : {}
            }
            onChange={(next) => {
              onChange(setField(draft, field.key, next));
            }}
          />
        );
      default:
        return null;
    }
  };

  const extraKeys = Object.keys(draft.extra);

  return (
    <Form layout="vertical" className="space-y-3">
      {schema.fields.map((field) => {
        const err = errorByKey.get(field.key);
        const label = t(field.labelKey, field.fallbackLabel);
        const help = field.helpKey ? t(field.helpKey, field.fallbackHelp ?? '') : field.fallbackHelp;
        return (
          <Form.Item
            key={field.key}
            label={
              <span>
                {label}
                {field.required && <span className="ml-1 text-red-500">*</span>}
              </span>
            }
            extra={help}
            {...(err ? { validateStatus: 'error' as const, help: t(err.messageKey, err.fallbackMessage) } : {})}
          >
            {renderField(field)}
          </Form.Item>
        );
      })}
      {extraKeys.length > 0 && (
        <div className="rounded border border-dashed border-slate-300 bg-slate-50 p-3">
          <Typography.Text type="secondary" className="text-xs">
            {t(
              'workspaceDetail.genes.config.preservedKeys',
              'Extra keys preserved from JSON (edit them in the JSON tab):'
            )}
          </Typography.Text>
          <div className="mt-2 flex flex-wrap gap-1">
            {extraKeys.map((k) => (
              <Tag key={k} color="default">
                {k}
              </Tag>
            ))}
          </div>
        </div>
      )}
    </Form>
  );
};
