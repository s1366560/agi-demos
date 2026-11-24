import i18n, { type ResourceLanguage } from 'i18next';
import shellEn from '../projectPackages/locales/en-US.json';
import shellZh from '../projectPackages/locales/zh-CN.json';
import legacyEn from '../locales/en-US.json';
import legacyZh from '../locales/zh-CN.json';

// Locale namespaces such as 'tenant' span business packages in the full compatibility UI.
function mergeResources(...sources: ResourceLanguage[]): ResourceLanguage {
  const result: ResourceLanguage = {};
  for (const source of sources) {
    for (const [key, value] of Object.entries(source)) {
      const existing = result[key];
      result[key] =
        typeof value === 'object' && typeof existing === 'object'
          ? mergeResources(existing, value)
          : value;
    }
  }
  return result;
}
export const enUS = mergeResources(shellEn, legacyEn);
export const zhCN = mergeResources(shellZh, legacyZh);

/** Original workbench modules contribute their own strings when loaded in this renderer. */
export function addWorkbenchTranslations(english: ResourceLanguage, chinese: ResourceLanguage) {
  for (const [language, current, contribution] of [
    ['en-US', enUS, english],
    ['zh-CN', zhCN, chinese],
  ] as const) {
    Object.assign(current, mergeResources(contribution, current));
    if (i18n.isInitialized) i18n.addResourceBundle(language, 'translation', current, true, true);
  }
}
