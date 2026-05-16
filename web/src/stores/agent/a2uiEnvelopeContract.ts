type CanonicalA2UIEnvelopeKey =
  | 'beginRendering'
  | 'surfaceUpdate'
  | 'dataModelUpdate'
  | 'deleteSurface';

export type NormalizedA2UIEnvelopeRecord = Partial<
  Record<CanonicalA2UIEnvelopeKey, Record<string, unknown>>
>;

type NormalizedStringValue = { literalString?: string; path?: string };
type NormalizedBooleanValue = { literalBoolean?: boolean; path?: string };
type NormalizedNumberValue = { literalNumber?: number; path?: string };

const DIRECT_ENVELOPE_KEY_ALIASES: Record<string, CanonicalA2UIEnvelopeKey> = {
  beginRendering: 'beginRendering',
  begin_rendering: 'beginRendering',
  surfaceUpdate: 'surfaceUpdate',
  surface_update: 'surfaceUpdate',
  dataModelUpdate: 'dataModelUpdate',
  data_model_update: 'dataModelUpdate',
  deleteSurface: 'deleteSurface',
  delete_surface: 'deleteSurface',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function normalizeDataPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length === 0) {
    return undefined;
  }
  return value.startsWith('/') ? value : `/${value}`;
}

function normalizeStringValue(value: unknown): NormalizedStringValue | null {
  if (typeof value === 'string') {
    return { literalString: value };
  }
  if (!isRecord(value)) {
    return null;
  }

  const normalized: NormalizedStringValue = {};
  if (typeof value.literalString === 'string') {
    normalized.literalString = value.literalString;
  } else if (typeof value.literal === 'string') {
    normalized.literalString = value.literal;
  }

  const path = normalizeDataPath(value.path);
  if (path) {
    normalized.path = path;
  }

  return Object.keys(normalized).length > 0 ? normalized : null;
}

function normalizeBooleanValue(value: unknown): NormalizedBooleanValue | null {
  if (typeof value === 'boolean') {
    return { literalBoolean: value };
  }
  if (!isRecord(value)) {
    return null;
  }

  const normalized: NormalizedBooleanValue = {};
  if (typeof value.literalBoolean === 'boolean') {
    normalized.literalBoolean = value.literalBoolean;
  } else if (typeof value.literal === 'boolean') {
    normalized.literalBoolean = value.literal;
  }

  const path = normalizeDataPath(value.path);
  if (path) {
    normalized.path = path;
  }

  return Object.keys(normalized).length > 0 ? normalized : null;
}

function normalizeNumberValue(value: unknown): NormalizedNumberValue | null {
  if (typeof value === 'number') {
    return { literalNumber: value };
  }
  if (!isRecord(value)) {
    return null;
  }

  const normalized: NormalizedNumberValue = {};
  if (typeof value.literalNumber === 'number') {
    normalized.literalNumber = value.literalNumber;
  } else if (typeof value.literal === 'number') {
    normalized.literalNumber = value.literal;
  }

  const path = normalizeDataPath(value.path);
  if (path) {
    normalized.path = path;
  }

  return Object.keys(normalized).length > 0 ? normalized : null;
}

function normalizeChildrenRef(value: unknown): { explicitList: string[] } | null {
  if (Array.isArray(value)) {
    return {
      explicitList: value.filter((item): item is string => typeof item === 'string'),
    };
  }
  if (!isRecord(value) || !Array.isArray(value.explicitList)) {
    return null;
  }
  return {
    explicitList: value.explicitList.filter((item): item is string => typeof item === 'string'),
  };
}

function normalizeChoiceOptions(value: unknown): Record<string, unknown>[] | null {
  if (!Array.isArray(value)) {
    return null;
  }

  return value.flatMap((option) => {
    if (!isRecord(option)) {
      return [];
    }

    const normalizedOption: Record<string, unknown> = { ...option };
    const label = normalizeStringValue(option.label ?? option.text);
    if (label) {
      normalizedOption.label = label;
    }
    return [normalizedOption];
  });
}

function canonicalizeComponentName(componentName: string): string {
  if (componentName === 'Checkbox') {
    return 'CheckBox';
  }
  if (componentName === 'Select') {
    return 'MultipleChoice';
  }
  return componentName;
}

function normalizeComponentPayload(
  componentName: string,
  payload: Record<string, unknown>
): Record<string, unknown> {
  const normalizedPayload: Record<string, unknown> = { ...payload };

  if (componentName === 'Text') {
    const text = normalizeStringValue(
      normalizedPayload.text ?? normalizedPayload.literal ?? normalizedPayload.literalString
    );
    if (text) {
      normalizedPayload.text = text;
    }
    delete normalizedPayload.literal;
    delete normalizedPayload.literalString;
  }

  if (componentName === 'TextField') {
    const label = normalizeStringValue(normalizedPayload.label);
    if (label) {
      normalizedPayload.label = label;
    }
    const text = normalizeStringValue(normalizedPayload.text ?? normalizedPayload.value);
    if (text) {
      normalizedPayload.text = text;
    }
    delete normalizedPayload.value;
  }

  if (componentName === 'Image') {
    const url = normalizeStringValue(normalizedPayload.url ?? normalizedPayload.src);
    if (url) {
      normalizedPayload.url = url;
    }
    delete normalizedPayload.src;
  }

  if (componentName === 'CheckBox') {
    const label = normalizeStringValue(normalizedPayload.label ?? normalizedPayload.text);
    if (label) {
      normalizedPayload.label = label;
    }

    const value = normalizeBooleanValue(
      normalizedPayload.value ?? normalizedPayload.checked ?? normalizedPayload.selected
    );
    const path = normalizeDataPath(normalizedPayload.path ?? normalizedPayload.onChange);
    if (value || path) {
      normalizedPayload.value = {
        ...(isRecord(value) ? value : {}),
        ...(path ? { path } : {}),
      };
    }

    delete normalizedPayload.text;
    delete normalizedPayload.checked;
    delete normalizedPayload.selected;
    delete normalizedPayload.path;
    delete normalizedPayload.onChange;
  }

  if (componentName === 'MultipleChoice') {
    const description = normalizeStringValue(
      normalizedPayload.description ?? normalizedPayload.label
    );
    if (description) {
      normalizedPayload.description = description;
    }

    const options = normalizeChoiceOptions(normalizedPayload.options);
    if (options) {
      normalizedPayload.options = options;
    }

    const selections = normalizeDataPath(
      (isRecord(normalizedPayload.selections) ? normalizedPayload.selections.path : undefined) ??
        normalizedPayload.selection ??
        normalizedPayload.selected ??
        normalizedPayload.value ??
        normalizedPayload.path
    );
    if (selections) {
      normalizedPayload.selections = { path: selections };
    }

    delete normalizedPayload.label;
    delete normalizedPayload.selection;
    delete normalizedPayload.selected;
    delete normalizedPayload.value;
    delete normalizedPayload.path;
  }

  if (componentName === 'Radio') {
    const description = normalizeStringValue(
      normalizedPayload.description ?? normalizedPayload.label
    );
    if (description) {
      normalizedPayload.description = description;
    }

    const options = normalizeChoiceOptions(normalizedPayload.options);
    if (options) {
      normalizedPayload.options = options;
    }

    const value = normalizeStringValue(
      normalizedPayload.value ?? normalizedPayload.selection ?? normalizedPayload.selected
    );
    if (value) {
      normalizedPayload.value = value;
    }

    const selections = normalizeDataPath(
      (isRecord(normalizedPayload.selections) ? normalizedPayload.selections.path : undefined) ??
        normalizedPayload.path
    );
    if (selections) {
      normalizedPayload.selections = { path: selections };
    }

    delete normalizedPayload.label;
    delete normalizedPayload.selection;
    delete normalizedPayload.selected;
    delete normalizedPayload.path;
  }

  if (componentName === 'Badge') {
    const text = normalizeStringValue(
      normalizedPayload.text ??
        normalizedPayload.label ??
        normalizedPayload.literal ??
        normalizedPayload.literalString
    );
    if (text) {
      normalizedPayload.text = text;
    }

    delete normalizedPayload.label;
    delete normalizedPayload.literal;
    delete normalizedPayload.literalString;
  }

  if (componentName === 'Tabs' && Array.isArray(normalizedPayload.tabItems)) {
    normalizedPayload.tabItems = normalizedPayload.tabItems.flatMap((item) => {
      if (!isRecord(item)) {
        return [];
      }
      const normalizedItem: Record<string, unknown> = { ...item };
      const title = normalizeStringValue(item.title);
      if (title) {
        normalizedItem.title = title;
      }
      return [normalizedItem];
    });
  }

  if (componentName === 'Table') {
    const columns = normalizedPayload.columns;
    if (Array.isArray(columns)) {
      normalizedPayload.columns = columns.flatMap((column) => {
        if (!isRecord(column)) {
          return [];
        }
        const normalizedColumn: Record<string, unknown> = { ...column };
        const header = normalizeStringValue(column.header);
        if (header) {
          normalizedColumn.header = header;
        }
        return [normalizedColumn];
      });
    }

    const rows = normalizedPayload.rows;
    if (Array.isArray(rows)) {
      normalizedPayload.rows = rows.flatMap((row) => {
        if (!isRecord(row)) {
          return [];
        }
        const normalizedRow: Record<string, unknown> = { ...row };
        const cells = row.cells;
        if (Array.isArray(cells)) {
          normalizedRow.cells = cells.map((cell: unknown): unknown => {
            const stringCell = normalizeStringValue(cell);
            if (stringCell) {
              return stringCell;
            }
            const numberCell = normalizeNumberValue(cell);
            if (numberCell) {
              return numberCell;
            }
            const booleanCell = normalizeBooleanValue(cell);
            if (booleanCell) {
              return booleanCell;
            }
            return cell;
          });
        }
        return [normalizedRow];
      });
    }
  }

  if (componentName === 'Progress') {
    const label = normalizeStringValue(normalizedPayload.label);
    if (label) {
      normalizedPayload.label = label;
    }
    const value = normalizeNumberValue(normalizedPayload.value);
    if (value) {
      normalizedPayload.value = value;
    }
    const max = normalizeNumberValue(normalizedPayload.max);
    if (max) {
      normalizedPayload.max = max;
    }
  }

  if (componentName === 'Card' || componentName === 'Column' || componentName === 'Row') {
    const children = normalizeChildrenRef(normalizedPayload.children);
    if (children) {
      normalizedPayload.children = children;
    }
  }

  return normalizedPayload;
}

export function normalizeA2UIComponentEntry(value: unknown): Record<string, unknown> | null {
  if (!isRecord(value) || typeof value.id !== 'string' || !value.id) {
    return null;
  }

  const componentRecord = isRecord(value.component) ? value.component : null;
  if (!componentRecord) {
    return null;
  }

  const supportedEntries = Object.entries(componentRecord).filter(([, payload]) =>
    isRecord(payload)
  );
  if (supportedEntries.length !== 1) {
    return null;
  }

  const [rawComponentName, rawPayload] = supportedEntries[0] ?? [];
  if (!rawComponentName || !isRecord(rawPayload)) {
    return null;
  }

  const componentName = canonicalizeComponentName(rawComponentName);
  return {
    id: value.id,
    component: {
      [componentName]: normalizeComponentPayload(componentName, rawPayload),
    },
  };
}

export function normalizeA2UIComponents(
  components: unknown
): Record<string, unknown>[] | Record<string, Record<string, unknown>> | null {
  if (Array.isArray(components)) {
    return components.flatMap((component) => {
      const normalized = normalizeA2UIComponentEntry(component);
      return normalized ? [normalized] : [];
    });
  }

  if (!isRecord(components)) {
    return null;
  }

  const normalizedEntries = Object.entries(components).flatMap(([key, component]) => {
    const normalized = normalizeA2UIComponentEntry(component);
    return normalized ? [[key, normalized] as const] : [];
  });

  return Object.fromEntries(normalizedEntries);
}

function normalizeA2UIEnvelopePayload(payload: unknown): Record<string, unknown> | null {
  if (!isRecord(payload)) return null;

  const normalizedPayload = { ...payload };
  if (
    typeof normalizedPayload.surface_id === 'string' &&
    (typeof normalizedPayload.surfaceId !== 'string' || !normalizedPayload.surfaceId)
  ) {
    normalizedPayload.surfaceId = normalizedPayload.surface_id;
  }
  delete normalizedPayload.surface_id;

  return normalizedPayload;
}

function getDirectEnvelopeEntries(
  record: Record<string, unknown>
): Array<[CanonicalA2UIEnvelopeKey, Record<string, unknown>]> {
  return Object.entries(record).flatMap(([key, value]) => {
    const canonicalKey = DIRECT_ENVELOPE_KEY_ALIASES[key];
    const normalizedPayload = canonicalKey ? normalizeA2UIEnvelopePayload(value) : null;
    return canonicalKey && normalizedPayload ? [[canonicalKey, normalizedPayload]] : [];
  });
}

function hoistNestedDataModelUpdate(
  entry: [CanonicalA2UIEnvelopeKey, Record<string, unknown>]
): NormalizedA2UIEnvelopeRecord[] {
  const [canonicalKey, normalizedPayload] = entry;
  if (canonicalKey !== 'surfaceUpdate') {
    return [{ [canonicalKey]: normalizedPayload }];
  }

  const hoistedPayload = normalizeA2UIEnvelopePayload(normalizedPayload.dataModelUpdate);
  if (!hoistedPayload) {
    return [{ surfaceUpdate: normalizedPayload }];
  }

  const surfaceUpdatePayload = { ...normalizedPayload };
  delete surfaceUpdatePayload.dataModelUpdate;
  return [{ surfaceUpdate: surfaceUpdatePayload }, { dataModelUpdate: hoistedPayload }];
}

function isIdentifierBoundary(char: string | undefined): boolean {
  return char === undefined || !/[A-Za-z0-9_$]/.test(char);
}

export function normalizeA2UIJsonLikeString(input: string): string {
  const replacements: Record<string, string> = {
    True: 'true',
    False: 'false',
    None: 'null',
  };
  let normalized = '';
  let inString = false;
  let escaped = false;

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    if (!char) continue;

    if (inString) {
      normalized += char;
      if (escaped) {
        escaped = false;
      } else if (char === '\\') {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      inString = true;
      normalized += char;
      continue;
    }

    const replacementEntry = Object.entries(replacements).find(([token]) => {
      if (!input.startsWith(token, index)) {
        return false;
      }
      return (
        isIdentifierBoundary(input[index - 1]) && isIdentifierBoundary(input[index + token.length])
      );
    });

    if (replacementEntry) {
      const [token, replacement] = replacementEntry;
      normalized += replacement;
      index += token.length - 1;
      continue;
    }

    normalized += char;
  }

  return normalized;
}

export function normalizeA2UIEnvelopeRecords(rawEnvelope: unknown): NormalizedA2UIEnvelopeRecord[] {
  if (!isRecord(rawEnvelope)) return [];

  const directEntries = getDirectEnvelopeEntries(rawEnvelope);
  const rawType = rawEnvelope.type;
  const hasTypedShape =
    rawType !== undefined || Object.prototype.hasOwnProperty.call(rawEnvelope, 'payload');

  if (hasTypedShape) {
    if (directEntries.length > 0 || typeof rawType !== 'string') {
      return [];
    }

    const canonicalKey = DIRECT_ENVELOPE_KEY_ALIASES[rawType];
    const normalizedPayload = canonicalKey
      ? normalizeA2UIEnvelopePayload(rawEnvelope.payload)
      : null;
    return canonicalKey && normalizedPayload ? [{ [canonicalKey]: normalizedPayload }] : [];
  }

  return directEntries.flatMap(hoistNestedDataModelUpdate);
}

export function normalizeA2UIEnvelopeRecord(
  rawEnvelope: unknown
): NormalizedA2UIEnvelopeRecord | null {
  const records = normalizeA2UIEnvelopeRecords(rawEnvelope);
  return records.length === 1 ? (records[0] ?? null) : null;
}
