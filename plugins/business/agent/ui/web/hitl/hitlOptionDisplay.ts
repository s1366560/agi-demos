import { decodeHtmlEntities } from "./hitlEnvVarDisplay";

function normalizeOptionText(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const decodedValue = decodeHtmlEntities(value) ?? value;
  const trimmedValue = decodedValue.trim();
  return trimmedValue.length > 0 ? trimmedValue : undefined;
}

export function getOptionLabelText(value: unknown): string | undefined {
  return normalizeOptionText(value);
}

export function getOptionDescriptionText(value: unknown): string | undefined {
  return normalizeOptionText(value);
}

export function getOptionRiskList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((risk) => {
    const normalizedRisk = normalizeOptionText(risk);
    return normalizedRisk ? [normalizedRisk] : [];
  });
}
