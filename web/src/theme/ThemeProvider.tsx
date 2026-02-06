/**
 * Theme Provider
 *
 * Provides Ant Design theming that syncs with the existing Zustand theme store.
 * This provider wraps the app to provide consistent theming across all components.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import { ConfigProvider, theme as antdTheme } from 'antd';
import enUS from 'antd/locale/en_US';
import zhCN from 'antd/locale/zh_CN';

import { useThemeStore } from '../stores/theme';

import { lightTheme, darkTheme } from './antdTheme';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { i18n } = useTranslation();
  const { computedTheme } = useThemeStore();

  const isDark = computedTheme === 'dark';

  // Get Ant Design locale based on i18n language
  const getAntdLocale = () => {
    if (i18n.language === 'zh-CN' || i18n.language === 'zh') return zhCN;
    return enUS;
  };

  // Get Ant Design theme config
  const antdThemeConfig = isDark
    ? { ...darkTheme, algorithm: antdTheme.darkAlgorithm }
    : lightTheme;

  return (
    <ConfigProvider locale={getAntdLocale()} theme={antdThemeConfig}>
      {children}
    </ConfigProvider>
  );
}

// Re-export useThemeStore as useTheme for convenience
export { useThemeStore as useTheme } from '../stores/theme';

export default ThemeProvider;
