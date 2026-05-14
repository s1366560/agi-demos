/**
 * Locale-aware Intl formatter hooks.
 *
 * Use these instead of hardcoding a locale like 'en-US' in
 * `Intl.DateTimeFormat` or `Intl.NumberFormat`. They follow the
 * currently active i18next language so dates, times and numbers
 * render correctly in the user's preferred locale.
 */

import { useMemo } from 'react';

import { useTranslation } from 'react-i18next';

/** Map an i18next language tag (e.g. "zh-CN") to a BCP-47 Intl locale tag. */
function normalizeLocale(language: string | undefined): string {
  if (!language) {
    return 'en-US';
  }
  // i18next sometimes returns lower-case ("zh-cn"); Intl is case-insensitive
  // but BCP-47 prefers region in upper-case.
  const [lang, region] = language.split(/[-_]/);
  if (!lang) {
    return 'en-US';
  }
  if (!region) {
    return lang;
  }
  return `${lang.toLowerCase()}-${region.toUpperCase()}`;
}

export function useCurrentLocale(): string {
  const { i18n } = useTranslation();
  return useMemo(() => normalizeLocale(i18n.language), [i18n.language]);
}

export function useLocaleDateFormat(
  options?: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const locale = useCurrentLocale();
  return useMemo(() => new Intl.DateTimeFormat(locale, options), [locale, options]);
}

export function useLocaleNumberFormat(
  options?: Intl.NumberFormatOptions,
): Intl.NumberFormat {
  const locale = useCurrentLocale();
  return useMemo(() => new Intl.NumberFormat(locale, options), [locale, options]);
}
