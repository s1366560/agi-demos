/**
 * Theme Provider
 *
 * Provides Ant Design theming that syncs with the existing Zustand theme store.
 * This provider wraps the app to provide consistent theming across all components.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import { App as AntApp, ConfigProvider, theme as antdTheme } from 'antd';
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
      {/*
        antd <App> exposes context-aware message/notification/modal instances
        via App.useApp(). Without it, useApp() falls back to empty placeholder
        objects and calls throw at runtime. `contents` keeps the wrapper div
        out of layout (display: contents), and keeps the default `component`
        so the cssVar dev warning does not fire.
      */}
      <AntApp className="contents">{children}</AntApp>
    </ConfigProvider>
  );
}

// Re-export useThemeStore as useTheme for convenience
// eslint-disable-next-line react-refresh/only-export-components
export { useThemeStore as useTheme } from '../stores/theme';

export default ThemeProvider;
