import type { EnvVarRequestedEventData } from "@/types/agent";
import type { EnvVarRequestData } from "@/types/hitl.unified";

const NAMED_HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  quot: '"',
};

function decodeNumericEntity(codePoint: number, fallback: string): string {
  if (!Number.isInteger(codePoint) || codePoint < 0 || codePoint > 0x10ffff) {
    return fallback;
  }

  try {
    return String.fromCodePoint(codePoint);
  } catch {
    return fallback;
  }
}

export function decodeHtmlEntities(
  value: string | null | undefined,
): string | undefined {
  if (value == null || !value.includes("&")) {
    return value ?? undefined;
  }

  return value.replace(
    /&(#(?:x[0-9a-fA-F]+|\d+)|[a-zA-Z]+);/g,
    (match, entity: string) => {
      if (entity.startsWith("#x") || entity.startsWith("#X")) {
        const codePoint = Number.parseInt(entity.slice(2), 16);
        return decodeNumericEntity(codePoint, match);
      }

      if (entity.startsWith("#")) {
        const codePoint = Number.parseInt(entity.slice(1), 10);
        return decodeNumericEntity(codePoint, match);
      }

      return NAMED_HTML_ENTITIES[entity] ?? match;
    },
  );
}

function decodeEnvVarValue(value: unknown): unknown {
  if (typeof value === "string") {
    return decodeHtmlEntities(value) ?? value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => decodeEnvVarValue(item));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [
        decodeHtmlEntities(key) ?? key,
        decodeEnvVarValue(nestedValue),
      ]),
    );
  }

  return value;
}

export function decodeEnvVarContext(
  context: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!context) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(context).map(([key, value]) => [
      decodeHtmlEntities(key) ?? key,
      decodeEnvVarValue(value),
    ]),
  );
}

export function decodeEnvVarRequestedEventData(
  data: EnvVarRequestedEventData,
): EnvVarRequestedEventData {
  return {
    ...data,
    tool_name: decodeHtmlEntities(data.tool_name) ?? data.tool_name,
    message: decodeHtmlEntities(data.message) ?? data.message,
    fields: data.fields.map((field) => ({
      ...field,
      label: decodeHtmlEntities(field.label) ?? field.label,
      description: decodeHtmlEntities(field.description) ?? field.description,
      default_value:
        decodeHtmlEntities(field.default_value) ?? field.default_value,
      placeholder: decodeHtmlEntities(field.placeholder) ?? field.placeholder,
      pattern: decodeHtmlEntities(field.pattern) ?? field.pattern,
    })),
    context: decodeEnvVarContext(data.context),
  };
}

export function decodeUnifiedEnvVarRequestData(
  data: EnvVarRequestData | undefined,
): EnvVarRequestData | undefined {
  if (!data) {
    return undefined;
  }

  return {
    ...data,
    toolName: decodeHtmlEntities(data.toolName) ?? data.toolName,
    message: decodeHtmlEntities(data.message) ?? data.message,
    fields: data.fields.map((field) => ({
      ...field,
      label: decodeHtmlEntities(field.label) ?? field.label,
      description: decodeHtmlEntities(field.description) ?? field.description,
      defaultValue:
        decodeHtmlEntities(field.defaultValue) ?? field.defaultValue,
      placeholder: decodeHtmlEntities(field.placeholder) ?? field.placeholder,
      pattern: decodeHtmlEntities(field.pattern) ?? field.pattern,
    })),
    context: decodeEnvVarContext(data.context),
  };
}
