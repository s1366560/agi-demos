const FORBIDDEN_DATA_KEYS = new Set(["__proto__", "prototype", "constructor"]);

interface ParsedValueMapEntry {
  key: string;
  value: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSafeDataKey(key: string): boolean {
  return !FORBIDDEN_DATA_KEYS.has(key);
}

function getPathSegments(path: string): string[] {
  if (!path || path === "/") return [];
  const normalized = path.startsWith("/") ? path.slice(1) : path;
  if (!normalized) return [];
  return normalized
    .split("/")
    .filter(Boolean)
    .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function setNestedDataValue(
  target: Record<string, unknown>,
  path: string,
  value: unknown,
): void {
  const segments = getPathSegments(path);
  if (segments.length === 0) {
    if (isRecord(value)) {
      for (const [key, nestedValue] of Object.entries(value)) {
        if (!isSafeDataKey(key)) continue;
        target[key] = nestedValue;
      }
    }
    return;
  }

  let cursor: Record<string, unknown> = target;
  for (const segment of segments.slice(0, -1)) {
    if (!isSafeDataKey(segment)) return;
    const existing = cursor[segment];
    if (!isRecord(existing)) {
      cursor[segment] = Object.create(null) as Record<string, unknown>;
    }
    cursor = cursor[segment] as Record<string, unknown>;
  }

  const leaf = segments[segments.length - 1];
  if (!leaf || !isSafeDataKey(leaf)) return;
  cursor[leaf] = value;
}

function parseValueMapEntry(rawEntry: unknown): ParsedValueMapEntry | null {
  if (!isRecord(rawEntry) || typeof rawEntry.key !== "string" || !rawEntry.key)
    return null;

  if (Array.isArray(rawEntry.valueMap)) {
    const nested = valueMapEntriesToData(rawEntry.valueMap);
    return { key: rawEntry.key, value: nested ?? [] };
  }
  if (typeof rawEntry.valueString === "string") {
    return { key: rawEntry.key, value: rawEntry.valueString };
  }
  if (typeof rawEntry.valueNumber === "number") {
    return { key: rawEntry.key, value: rawEntry.valueNumber };
  }
  if (typeof rawEntry.valueBoolean === "boolean") {
    return { key: rawEntry.key, value: rawEntry.valueBoolean };
  }
  return { key: rawEntry.key, value: null };
}

function valueMapEntriesToData(
  entries: unknown[],
): Record<string, unknown> | unknown[] | null {
  const parsedEntries = entries
    .map((entry) => parseValueMapEntry(entry))
    .filter((entry): entry is ParsedValueMapEntry => entry !== null);
  if (parsedEntries.length === 0) return null;

  const allNumericKeys = parsedEntries.every((entry) =>
    /^\d+$/.test(entry.key),
  );
  if (allNumericKeys) {
    const orderedEntries = [...parsedEntries].sort(
      (left, right) => Number(left.key) - Number(right.key),
    );
    const maxIndex = Number(
      orderedEntries[orderedEntries.length - 1]?.key ?? -1,
    );
    const values = Array.from(
      { length: maxIndex + 1 },
      () => null,
    ) as Array<unknown>;
    for (const entry of orderedEntries) {
      values[Number(entry.key)] = entry.value;
    }
    return values;
  }

  const result = Object.create(null) as Record<string, unknown>;
  for (const entry of parsedEntries) {
    if (entry.key === ".") {
      if (isRecord(entry.value)) {
        for (const [key, value] of Object.entries(entry.value)) {
          if (!isSafeDataKey(key)) continue;
          result[key] = value;
        }
      } else {
        result["."] = entry.value;
      }
      continue;
    }
    setNestedDataValue(result, entry.key, entry.value);
  }
  return result;
}

export function applyA2UIDataModelUpdate(
  target: Record<string, unknown>,
  path: string,
  contents: unknown[],
): void {
  const normalizedValueMap = valueMapEntriesToData(contents);
  if (normalizedValueMap) {
    if (path === "/" || path === "") {
      if (Array.isArray(normalizedValueMap)) {
        return;
      }
      for (const [key, value] of Object.entries(normalizedValueMap)) {
        if (!isSafeDataKey(key) || key === ".") continue;
        target[key] = value;
      }
      return;
    }
    if (!Array.isArray(normalizedValueMap)) {
      const directValue = normalizedValueMap["."];
      if (directValue !== undefined) {
        setNestedDataValue(target, path, directValue);
        return;
      }
    }
    setNestedDataValue(target, path, normalizedValueMap);
    return;
  }

  if (path === "/" || path === "") {
    for (const item of contents) {
      if (isRecord(item)) {
        for (const [key, value] of Object.entries(item)) {
          if (!isSafeDataKey(key)) continue;
          target[key] = value;
        }
      }
    }
    return;
  }

  setNestedDataValue(target, path, contents);
}
