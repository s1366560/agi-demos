import { createContext, useContext, useMemo } from 'react';

export type DesktopLocale = 'en' | 'zh-CN';

export type TranslationValues = Record<string, string | number>;

export type I18nContextValue = {
  locale: DesktopLocale;
  setLocale: (locale: DesktopLocale) => void;
  t: (key: string, values?: TranslationValues) => string;
};

export const I18nContext = createContext<I18nContextValue | null>(null);

type Messages = Readonly<Record<string, string>>;

export function interpolate(message: string, values?: TranslationValues): string {
  if (!values) return message;
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)),
    message,
  );
}

export function useI18n(english?: Messages, chinese?: Messages): I18nContextValue {
  const context = useContext(I18nContext);
  return useMemo(() => {
    if (!context) throw new Error('useI18n must be used inside I18nProvider');
    if (!english) return context;
    const messages = context.locale === 'zh-CN' ? chinese : english;
    return {
      ...context,
      t(key: string, values?: TranslationValues) {
        const message = messages?.[key] ?? english[key];
        return message === undefined ? context.t(key, values) : interpolate(message, values);
      },
    };
  }, [context, english, chinese]);
}
