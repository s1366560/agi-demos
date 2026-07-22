import { message } from 'antd';

import { useGeneMarketStore } from '@/stores/geneMarket';

/** Trim free text; map empty/whitespace to null (for nullable payload fields). */
export const normalizeNullableText = (value: string | undefined): string | null => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
};

/** Trim free text; map empty/whitespace to undefined (to omit payload fields). */
export const normalizeOptionalText = (value: string | undefined): string | undefined => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
};

/** Split a comma-separated input into a deduplicated list. */
export const splitCsv = (value: string | undefined): string[] =>
  Array.from(
    new Set(
      (value ?? '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );

/** antd form validation rejections carry errorFields; API errors do not. */
export const isFormValidationError = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && 'errorFields' in error;

/** Surface the gene-market store error when present, else the localized fallback. */
export const showGeneActionError = (fallbackMessage: string): void => {
  message.error(useGeneMarketStore.getState().error ?? fallbackMessage);
};
