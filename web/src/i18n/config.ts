import { initReactI18next } from 'react-i18next';

import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import enUS from '../locales/en-US.json';
import zhCN from '../locales/zh-CN.json';

export const resources = {
  'en-US': {
    translation: enUS,
  },
  'zh-CN': {
    translation: zhCN,
  },
} as const;

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'en-US',
    supportedLngs: ['en-US', 'zh-CN'],
    interpolation: {
      escapeValue: false, // not needed for react as it escapes by default
    },
    detection: {
      // Honor previously chosen language first, then fall back to navigator.
      // navigator covers browser default per product requirement.
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'i18nextLng',
    },
  });

// Keep <html lang="..."> in sync with the active language so screen readers,
// browser spell-check, and search engines see the correct locale. Update on
// init and whenever the user switches via LanguageSwitcher.
const applyHtmlLang = (lang: string) => {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('lang', lang);
  }
};

applyHtmlLang(i18n.language || 'en-US');
i18n.on('languageChanged', applyHtmlLang);

export default i18n;
