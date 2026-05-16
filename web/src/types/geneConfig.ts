import type { CyberGeneCategory } from './workspace';

/**
 * Field-level schema describing how a single property inside a CyberGene's
 * `config_json` should be presented in the structured editor.
 *
 * Schemas are deliberately small and human-curated per category. They are not
 * a general JSON-schema runtime: they only describe the fields the structured
 * form will surface. Unknown extra keys in `config_json` are preserved through
 * the editor lifecycle via the `extra` bucket on `GeneConfigDraft`.
 */
export type GeneConfigFieldType =
  | 'string'
  | 'text'
  | 'number'
  | 'boolean'
  | 'string_list'
  | 'kv_list'
  | 'select';

export interface GeneConfigFieldDef {
  key: string;
  labelKey: string;
  fallbackLabel: string;
  type: GeneConfigFieldType;
  required?: boolean;
  helpKey?: string;
  fallbackHelp?: string;
  defaultValue?: unknown;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
}

export interface GeneConfigSchema {
  category: CyberGeneCategory;
  fields: GeneConfigFieldDef[];
}

export const GENE_CONFIG_SCHEMAS: Record<CyberGeneCategory, GeneConfigSchema> = {
  skill: {
    category: 'skill',
    fields: [
      {
        key: 'system_prompt',
        labelKey: 'workspaceDetail.genes.config.skill.systemPrompt',
        fallbackLabel: 'System prompt',
        type: 'text',
        fallbackHelp: 'Instruction text injected when this skill is active.',
        defaultValue: '',
      },
      {
        key: 'trigger_keywords',
        labelKey: 'workspaceDetail.genes.config.skill.triggerKeywords',
        fallbackLabel: 'Trigger keywords',
        type: 'string_list',
        fallbackHelp: 'Keywords that route work into this skill.',
        defaultValue: [],
      },
      {
        key: 'model',
        labelKey: 'workspaceDetail.genes.config.skill.model',
        fallbackLabel: 'Preferred model',
        type: 'string',
        defaultValue: '',
      },
      {
        key: 'temperature',
        labelKey: 'workspaceDetail.genes.config.skill.temperature',
        fallbackLabel: 'Temperature',
        type: 'number',
        min: 0,
        max: 2,
        step: 0.1,
        defaultValue: 0.7,
      },
    ],
  },
  knowledge: {
    category: 'knowledge',
    fields: [
      {
        key: 'sources',
        labelKey: 'workspaceDetail.genes.config.knowledge.sources',
        fallbackLabel: 'Knowledge sources',
        type: 'string_list',
        fallbackHelp: 'URLs, document ids, or collection names.',
        defaultValue: [],
      },
      {
        key: 'top_k',
        labelKey: 'workspaceDetail.genes.config.knowledge.topK',
        fallbackLabel: 'Top K',
        type: 'number',
        min: 1,
        max: 100,
        step: 1,
        defaultValue: 5,
      },
      {
        key: 'embedding_strategy',
        labelKey: 'workspaceDetail.genes.config.knowledge.embeddingStrategy',
        fallbackLabel: 'Embedding strategy',
        type: 'select',
        options: [
          { value: 'semantic', label: 'Semantic' },
          { value: 'hybrid', label: 'Hybrid' },
          { value: 'keyword', label: 'Keyword' },
        ],
        defaultValue: 'semantic',
      },
    ],
  },
  tool: {
    category: 'tool',
    fields: [
      {
        key: 'tool_id',
        labelKey: 'workspaceDetail.genes.config.tool.toolId',
        fallbackLabel: 'Tool id',
        type: 'string',
        required: true,
        defaultValue: '',
      },
      {
        key: 'parameters',
        labelKey: 'workspaceDetail.genes.config.tool.parameters',
        fallbackLabel: 'Default parameters',
        type: 'kv_list',
        fallbackHelp: 'Static parameters passed to every invocation.',
        defaultValue: {},
      },
    ],
  },
  workflow: {
    category: 'workflow',
    fields: [
      {
        key: 'steps',
        labelKey: 'workspaceDetail.genes.config.workflow.steps',
        fallbackLabel: 'Steps',
        type: 'string_list',
        fallbackHelp: 'Ordered step names. Use the advanced JSON view for structured step bodies.',
        defaultValue: [],
      },
      {
        key: 'inputs',
        labelKey: 'workspaceDetail.genes.config.workflow.inputs',
        fallbackLabel: 'Inputs',
        type: 'kv_list',
        defaultValue: {},
      },
      {
        key: 'outputs',
        labelKey: 'workspaceDetail.genes.config.workflow.outputs',
        fallbackLabel: 'Outputs',
        type: 'kv_list',
        defaultValue: {},
      },
    ],
  },
};

export type GeneConfigFieldValue =
  | string
  | number
  | boolean
  | string[]
  | Record<string, string>
  | null;

export interface GeneConfigDraft {
  /** Field values keyed by the schema field `key`. */
  values: Record<string, GeneConfigFieldValue>;
  /**
   * Any keys present in the original `config_json` that are not declared by the
   * category schema. Round-tripped untouched so the structured editor never
   * silently drops data.
   */
  extra: Record<string, unknown>;
}

export interface GeneConfigValidationError {
  fieldKey: string;
  messageKey: string;
  fallbackMessage: string;
}

const cloneValue = (value: unknown): unknown => {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((item) => cloneValue(item));
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = cloneValue(v);
    }
    return out;
  }
  return value;
};

const stringifyFieldValue = (value: unknown): string => {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
};

const coerceFieldValue = (field: GeneConfigFieldDef, raw: unknown): GeneConfigFieldValue => {
  switch (field.type) {
    case 'string':
    case 'text':
    case 'select':
      return stringifyFieldValue(raw);
    case 'number': {
      const defaultNumber = typeof field.defaultValue === 'number' ? field.defaultValue : 0;
      if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
      if (typeof raw === 'string' && raw.trim() !== '') {
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : defaultNumber;
      }
      return defaultNumber;
    }
    case 'boolean':
      return Boolean(raw);
    case 'string_list':
      if (Array.isArray(raw)) return raw.map((item) => String(item));
      return [];
    case 'kv_list': {
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        const out: Record<string, string> = {};
        for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
          out[k] = typeof v === 'string' ? v : JSON.stringify(v);
        }
        return out;
      }
      return {};
    }
    default:
      return null;
  }
};

export const emptyGeneConfigDraft = (category: CyberGeneCategory): GeneConfigDraft => {
  const schema = GENE_CONFIG_SCHEMAS[category];
  const values: Record<string, GeneConfigFieldValue> = {};
  for (const field of schema.fields) {
    values[field.key] = coerceFieldValue(field, field.defaultValue);
  }
  return { values, extra: {} };
};

/**
 * Parse a stored `config_json` string into a structured draft for the given
 * category. Returns an empty draft if the JSON is missing or invalid.
 */
export const parseGeneConfig = (
  category: CyberGeneCategory,
  configJson: string | null | undefined
): GeneConfigDraft => {
  const schema = GENE_CONFIG_SCHEMAS[category];
  const draft = emptyGeneConfigDraft(category);
  if (!configJson || configJson.trim() === '') return draft;
  let parsed: unknown;
  try {
    parsed = JSON.parse(configJson);
  } catch {
    return draft;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return draft;
  const obj = parsed as Record<string, unknown>;
  const knownKeys = new Set(schema.fields.map((f) => f.key));
  for (const field of schema.fields) {
    if (field.key in obj) {
      draft.values[field.key] = coerceFieldValue(field, obj[field.key]);
    }
  }
  for (const [k, v] of Object.entries(obj)) {
    if (!knownKeys.has(k)) {
      draft.extra[k] = cloneValue(v);
    }
  }
  return draft;
};

/**
 * Serialize a structured draft back to a `config_json` string. Empty / default
 * fields are still emitted so the round-trip is symmetric and reviewers can
 * diff the stored config.
 */
export const serializeGeneConfig = (
  category: CyberGeneCategory,
  draft: GeneConfigDraft
): string => {
  const schema = GENE_CONFIG_SCHEMAS[category];
  const out: Record<string, unknown> = {};
  for (const field of schema.fields) {
    const value = draft.values[field.key];
    if (value === undefined) continue;
    out[field.key] = cloneValue(value);
  }
  for (const [k, v] of Object.entries(draft.extra)) {
    if (!(k in out)) out[k] = cloneValue(v);
  }
  return JSON.stringify(out, null, 2);
};

export const validateGeneConfig = (
  category: CyberGeneCategory,
  draft: GeneConfigDraft
): GeneConfigValidationError[] => {
  const schema = GENE_CONFIG_SCHEMAS[category];
  const errors: GeneConfigValidationError[] = [];
  for (const field of schema.fields) {
    const value = draft.values[field.key];
    if (field.required) {
      const empty =
        value === null ||
        value === undefined ||
        (typeof value === 'string' && value.trim() === '') ||
        (Array.isArray(value) && value.length === 0);
      if (empty) {
        errors.push({
          fieldKey: field.key,
          messageKey: 'workspaceDetail.genes.config.errors.required',
          fallbackMessage: `${field.fallbackLabel} is required`,
        });
        continue;
      }
    }
    if (field.type === 'number' && typeof value === 'number') {
      if (field.min !== undefined && value < field.min) {
        errors.push({
          fieldKey: field.key,
          messageKey: 'workspaceDetail.genes.config.errors.min',
          fallbackMessage: `${field.fallbackLabel} must be >= ${String(field.min)}`,
        });
      }
      if (field.max !== undefined && value > field.max) {
        errors.push({
          fieldKey: field.key,
          messageKey: 'workspaceDetail.genes.config.errors.max',
          fallbackMessage: `${field.fallbackLabel} must be <= ${String(field.max)}`,
        });
      }
    }
  }
  return errors;
};

/**
 * Validate that a string is a JSON object literal. Used by the advanced
 * JSON editor before allowing the user to switch back to the structured tab.
 */
export const parseRawConfigJson = (
  raw: string
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } => {
  const trimmed = raw.trim();
  if (trimmed === '') {
    return { ok: true, value: {} };
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'Config must be a JSON object' };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Invalid JSON' };
  }
};
