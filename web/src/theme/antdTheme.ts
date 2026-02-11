/**
 * Ant Design Theme Configuration
 *
 * Matches design prototype from design-prototype/
 * Color scheme: Primary Blue #1e3fae with sophisticated neutrals
 *
 * Design Reference:
 * - Primary: #1e3fae (Deep Blue)
 * - Background Light: #f8f9fb
 * - Background Dark: #141416
 * - Surface Light: #ffffff
 * - Surface Dark: #1c1c1f
 * - Border Dark: #2c2c31
 * - Text Muted: #7d8599
 */

import type { ThemeConfig } from 'antd';

// Design System Colors
export const colors = {
  // Primary
  primary: '#1e3fae',
  primaryDark: '#152d7e',
  primaryLight: '#3b5fc9',
  primaryGlow: '#4b6fd9',

  // Background
  bgLight: '#f8f9fb',
  bgDark: '#141416',

  // Surface
  surfaceLight: '#ffffff',
  surfaceDark: '#1c1c1f',
  surfaceDarkAlt: '#242428',

  // Border
  borderLight: '#e2e8f0',
  borderDark: '#2c2c31',

  // Text
  textPrimary: '#1a2332',
  textSecondary: '#5a6577',
  textMuted: '#7d8599',
  textMutedLight: '#6b7280',

  // Status
  success: '#10b981',
  successLight: '#d1fae5',
  warning: '#f59e0b',
  warningLight: '#fef3c7',
  error: '#ef4444',
  errorLight: '#fee2e2',
  info: '#3b82f6',
  infoLight: '#dbeafe',

  // Accent colors for tiles/cards
  tileBlue: '#3b82f6',
  tilePurple: '#8b5cf6',
  tileEmerald: '#10b981',
  tileAmber: '#f59e0b',
  tileIndigo: '#6366f1',
  tileRose: '#f43f5e',
};

// Light Theme Configuration
export const lightTheme: ThemeConfig = {
  token: {
    // Primary Colors
    colorPrimary: colors.primary,
    colorPrimaryHover: colors.primaryLight,
    colorPrimaryActive: colors.primaryDark,
    colorPrimaryBg: '#eef2ff',
    colorPrimaryBgHover: '#e0e7ff',
    colorPrimaryBorder: '#c7d2fe',
    colorPrimaryBorderHover: '#a5b4fc',
    colorPrimaryText: colors.primary,
    colorPrimaryTextHover: colors.primaryLight,
    colorPrimaryTextActive: colors.primaryDark,

    // Background Colors
    colorBgBase: colors.bgLight,
    colorBgContainer: colors.surfaceLight,
    colorBgElevated: colors.surfaceLight,
    colorBgLayout: colors.bgLight,
    colorBgSpotlight: 'rgba(30, 63, 174, 0.1)',
    colorBgMask: 'rgba(0, 0, 0, 0.45)',

    // Border Colors
    colorBorder: colors.borderLight,
    colorBorderSecondary: '#f1f5f9',

    // Text Colors
    colorText: colors.textPrimary,
    colorTextSecondary: colors.textSecondary,
    colorTextTertiary: colors.textMutedLight,
    colorTextQuaternary: '#9ca3af',
    colorTextDescription: colors.textMutedLight,
    colorTextDisabled: '#9ca3af',
    colorTextPlaceholder: '#9ca3af',

    // Status Colors
    colorSuccess: colors.success,
    colorSuccessBg: colors.successLight,
    colorSuccessBorder: '#a7f3d0',
    colorWarning: colors.warning,
    colorWarningBg: colors.warningLight,
    colorWarningBorder: '#fde68a',
    colorError: colors.error,
    colorErrorBg: colors.errorLight,
    colorErrorBorder: '#fecaca',
    colorInfo: colors.info,
    colorInfoBg: colors.infoLight,
    colorInfoBorder: '#93c5fd',

    // Typography
    fontFamily:
      '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 14,
    fontSizeHeading1: 30,
    fontSizeHeading2: 24,
    fontSizeHeading3: 20,
    fontSizeHeading4: 16,
    fontSizeHeading5: 14,
    lineHeight: 1.5714285714285714,
    lineHeightHeading1: 1.2666666666666666,
    lineHeightHeading2: 1.3333333333333333,
    lineHeightHeading3: 1.4,
    lineHeightHeading4: 1.5,
    lineHeightHeading5: 1.5714285714285714,

    // Border Radius
    borderRadius: 6,
    borderRadiusLG: 8,
    borderRadiusSM: 4,
    borderRadiusXS: 2,

    // Shadows - Subtle and sophisticated
    boxShadow:
      '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
    boxShadowSecondary:
      '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 9px 28px 8px rgba(0, 0, 0, 0.05)',

    // Control
    controlHeight: 36,
    controlHeightLG: 44,
    controlHeightSM: 28,

    // Motion
    motion: true,
    motionDurationFast: '0.1s',
    motionDurationMid: '0.2s',
    motionDurationSlow: '0.3s',
    motionEaseInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
    motionEaseOut: 'cubic-bezier(0, 0, 0.2, 1)',
  },
  components: {
    Layout: {
      headerBg: colors.surfaceLight,
      headerColor: colors.textPrimary,
      siderBg: colors.surfaceLight,
      bodyBg: colors.bgLight,
      triggerBg: colors.bgLight,
    },
    Menu: {
      itemBg: 'transparent',
      itemColor: colors.textSecondary,
      itemHoverBg: '#f1f5f9',
      itemHoverColor: colors.textPrimary,
      itemSelectedBg: 'rgba(30, 63, 174, 0.1)',
      itemSelectedColor: colors.primary,
      itemActiveBg: 'rgba(30, 63, 174, 0.15)',
    },
    Button: {
      primaryShadow: '0 2px 4px rgba(30, 63, 174, 0.2)',
      defaultShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
      fontWeight: 500,
    },
    Card: {
      headerBg: 'transparent',
      colorBorderSecondary: colors.borderLight,
      paddingLG: 24,
    },
    Table: {
      headerBg: '#f8fafc',
      headerColor: colors.textSecondary,
      rowHoverBg: '#f8fafc',
      borderColor: colors.borderLight,
    },
    Input: {
      activeBorderColor: colors.primary,
      hoverBorderColor: colors.primaryLight,
    },
    Select: {
      optionSelectedBg: 'rgba(30, 63, 174, 0.1)',
      optionSelectedColor: colors.primary,
    },
    Modal: {
      headerBg: colors.surfaceLight,
      contentBg: colors.surfaceLight,
    },
    Tabs: {
      inkBarColor: colors.primary,
      itemActiveColor: colors.primary,
      itemSelectedColor: colors.primary,
      itemHoverColor: colors.primaryLight,
    },
    Tag: {
      defaultBg: '#f1f5f9',
      defaultColor: colors.textSecondary,
    },
    Badge: {
      colorBgContainer: colors.error,
    },
    Breadcrumb: {
      itemColor: colors.textMutedLight,
      lastItemColor: colors.textPrimary,
      linkColor: colors.textMutedLight,
      linkHoverColor: colors.primary,
      separatorColor: '#cbd5e1',
    },
    Statistic: {
      titleFontSize: 12,
      contentFontSize: 28,
    },
    Progress: {
      defaultColor: colors.primary,
    },
    Spin: {
      colorPrimary: colors.primary,
    },
    Tooltip: {
      colorBgSpotlight: '#1e293b',
      colorTextLightSolid: '#f8fafc',
    },
  },
};

// Dark Theme Configuration
export const darkTheme: ThemeConfig = {
  token: {
    // Primary Colors
    colorPrimary: colors.primaryLight,
    colorPrimaryHover: colors.primaryGlow,
    colorPrimaryActive: colors.primary,
    colorPrimaryBg: 'rgba(59, 95, 201, 0.15)',
    colorPrimaryBgHover: 'rgba(59, 95, 201, 0.25)',
    colorPrimaryBorder: 'rgba(59, 95, 201, 0.4)',
    colorPrimaryBorderHover: 'rgba(59, 95, 201, 0.6)',
    colorPrimaryText: colors.primaryLight,
    colorPrimaryTextHover: colors.primaryGlow,
    colorPrimaryTextActive: colors.primary,

    // Background Colors
    colorBgBase: colors.bgDark,
    colorBgContainer: colors.surfaceDark,
    colorBgElevated: colors.surfaceDarkAlt,
    colorBgLayout: colors.bgDark,
    colorBgSpotlight: 'rgba(59, 95, 201, 0.15)',
    colorBgMask: 'rgba(0, 0, 0, 0.65)',

    // Border Colors
    colorBorder: colors.borderDark,
    colorBorderSecondary: '#222226',

    // Text Colors
    colorText: '#e8eaed',
    colorTextSecondary: '#b0b8c4',
    colorTextTertiary: colors.textMuted,
    colorTextQuaternary: '#5a6270',
    colorTextDescription: colors.textMuted,
    colorTextDisabled: '#4a4f5a',
    colorTextPlaceholder: '#5a6270',

    // Status Colors
    colorSuccess: '#34d399',
    colorSuccessBg: 'rgba(16, 185, 129, 0.15)',
    colorSuccessBorder: 'rgba(16, 185, 129, 0.4)',
    colorWarning: '#fbbf24',
    colorWarningBg: 'rgba(245, 158, 11, 0.15)',
    colorWarningBorder: 'rgba(245, 158, 11, 0.4)',
    colorError: '#f87171',
    colorErrorBg: 'rgba(239, 68, 68, 0.15)',
    colorErrorBorder: 'rgba(239, 68, 68, 0.4)',
    colorInfo: '#60a5fa',
    colorInfoBg: 'rgba(59, 130, 246, 0.15)',
    colorInfoBorder: 'rgba(59, 130, 246, 0.4)',

    // Typography
    fontFamily:
      '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    fontSize: 14,
    fontSizeHeading1: 30,
    fontSizeHeading2: 24,
    fontSizeHeading3: 20,
    fontSizeHeading4: 16,
    fontSizeHeading5: 14,

    // Border Radius
    borderRadius: 6,
    borderRadiusLG: 8,
    borderRadiusSM: 4,
    borderRadiusXS: 2,

    // Shadows
    boxShadow:
      '0 1px 2px 0 rgba(0, 0, 0, 0.2), 0 1px 6px -1px rgba(0, 0, 0, 0.15), 0 2px 4px 0 rgba(0, 0, 0, 0.1)',
    boxShadowSecondary:
      '0 6px 16px 0 rgba(0, 0, 0, 0.32), 0 3px 6px -4px rgba(0, 0, 0, 0.48), 0 9px 28px 8px rgba(0, 0, 0, 0.2)',

    // Control
    controlHeight: 36,
    controlHeightLG: 44,
    controlHeightSM: 28,

    // Motion
    motion: true,
  },
  components: {
    Layout: {
      headerBg: colors.surfaceDark,
      headerColor: '#e8eaed',
      siderBg: colors.surfaceDark,
      bodyBg: colors.bgDark,
      triggerBg: colors.surfaceDarkAlt,
    },
    Menu: {
      itemBg: 'transparent',
      itemColor: colors.textMuted,
      itemHoverBg: colors.borderDark,
      itemHoverColor: '#e8eaed',
      itemSelectedBg: 'rgba(59, 95, 201, 0.15)',
      itemSelectedColor: colors.primaryLight,
      itemActiveBg: 'rgba(59, 95, 201, 0.2)',
      darkItemBg: 'transparent',
      darkItemColor: colors.textMuted,
      darkItemHoverBg: colors.borderDark,
      darkItemHoverColor: '#e8eaed',
      darkItemSelectedBg: 'rgba(59, 95, 201, 0.15)',
      darkItemSelectedColor: colors.primaryLight,
    },
    Button: {
      primaryShadow: '0 2px 8px rgba(59, 95, 201, 0.3)',
      defaultBg: colors.surfaceDarkAlt,
      defaultColor: '#e8eaed',
      defaultBorderColor: colors.borderDark,
      fontWeight: 500,
    },
    Card: {
      colorBgContainer: colors.surfaceDark,
      headerBg: 'transparent',
      colorBorderSecondary: colors.borderDark,
    },
    Table: {
      headerBg: colors.surfaceDarkAlt,
      headerColor: colors.textMuted,
      rowHoverBg: 'rgba(255, 255, 255, 0.04)',
      borderColor: colors.borderDark,
      colorBgContainer: colors.surfaceDark,
    },
    Input: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      activeBorderColor: colors.primaryLight,
      hoverBorderColor: colors.primaryLight,
    },
    Select: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      optionSelectedBg: 'rgba(59, 95, 201, 0.2)',
      optionSelectedColor: colors.primaryLight,
    },
    Modal: {
      headerBg: colors.surfaceDark,
      contentBg: colors.surfaceDark,
    },
    Tabs: {
      inkBarColor: colors.primaryLight,
      itemActiveColor: colors.primaryLight,
      itemSelectedColor: colors.primaryLight,
      itemHoverColor: colors.primaryGlow,
      itemColor: colors.textMuted,
    },
    Tag: {
      defaultBg: colors.borderDark,
      defaultColor: colors.textMuted,
    },
    Badge: {
      colorBgContainer: '#f87171',
    },
    Breadcrumb: {
      itemColor: colors.textMuted,
      lastItemColor: '#e8eaed',
      linkColor: colors.textMuted,
      linkHoverColor: colors.primaryLight,
      separatorColor: '#3a3a40',
    },
    Statistic: {
      titleFontSize: 12,
      contentFontSize: 28,
    },
    Progress: {
      defaultColor: colors.primaryLight,
    },
    Spin: {
      colorPrimary: colors.primaryLight,
    },
    Tooltip: {
      colorBgSpotlight: colors.surfaceDarkAlt,
      colorTextLightSolid: '#f8fafc',
    },
    Dropdown: {
      colorBgElevated: colors.surfaceDark,
    },
    Popover: {
      colorBgElevated: colors.surfaceDark,
    },
  },
};

// Export default theme (light)
export default lightTheme;
