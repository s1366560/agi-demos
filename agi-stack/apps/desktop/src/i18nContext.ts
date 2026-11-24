import { createContext, useContext } from 'react';

export type DesktopLocale = 'en' | 'zh-CN';

export type TranslationValues = Record<string, string | number>;

export type I18nContextValue = {
  locale: DesktopLocale;
  setLocale: (locale: DesktopLocale) => void;
  t: (key: string, values?: TranslationValues) => string;
};

export const I18nContext = createContext<I18nContextValue | null>(null);

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used inside I18nProvider');
  return context;
}
