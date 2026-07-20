/**
 * Ant Design Theme Configuration
 *
 * Single source of truth: `web/src/theme/tokens.ts` (PRODUCT.md mission-control).
 * - Dark (primary): #080c12 surfaces, cyan #38d6ff accent.
 * - Light (derived): white surfaces, deeper cyan #0e7490 for WCAG AA on white.
 *
 * NOTE: `index.css` `@theme` / `.dark` hold LITERAL copies of these values for
 * Tailwind utility resolution; `tokenSync.test.ts` asserts they stay in sync.
 */

import { tokens } from './tokens';

import type { ThemeConfig } from 'antd';

// Design System Colors (values from tokens.ts; kept flat for hostStyles consumers)
export const colors = {
  // Primary — light-appropriate cyan (AA on white); dark uses #38d6ff below
  primary: tokens.light.cyan,
  primaryDark: '#155e75',
  primaryLight: '#0891b2',
  primaryGlow: '#22d3ee',
  primaryCyanDark: tokens.dark.cyan, // luminous accent for dark theme

  // Background
  bgLight: tokens.light.bg,
  bgDark: tokens.dark.bg,

  // Surface
  surfaceLight: tokens.light.panel,
  surfaceDark: tokens.dark.panel,
  surfaceDarkAlt: tokens.dark.panel2,
  surfaceElevated: tokens.dark.panel3,

  // Border
  borderLight: tokens.light.border,
  borderStrongLight: tokens.light.borderStrong,
  borderDark: tokens.dark.border,
  borderStrongDark: tokens.dark.borderStrong,

  // Text
  textPrimary: tokens.light.text,
  textSecondary: tokens.light.textMuted,
  textMuted: tokens.light.textMuted2,
  textMutedLight: tokens.light.textMuted2,

  // Dark-theme text (mission-control neutrals)
  textPrimaryDark: tokens.dark.text,
  textSecondaryDark: tokens.dark.textMuted,
  textMutedDark2: tokens.dark.textMuted2,

  // Status
  success: tokens.status.success,
  successLight: '#d1fae5',
  warning: tokens.status.warning,
  warningLight: '#fef3c7',
  error: tokens.status.error,
  errorLight: '#fee2e2',
  info: tokens.status.info,
  infoLight: '#cffafe',

  // Accent tile colors — cohesive cyan/teal family (was random rainbow)
  tileBlue: '#38d6ff',
  tilePurple: '#a78bfa',
  tileEmerald: '#35d399',
  tileAmber: '#f0b35a',
  tileIndigo: '#22d3ee',
  tileRose: '#ff6978',
};

// Light Theme Configuration
export const lightTheme: ThemeConfig = {
  token: {
    // Primary Colors
    colorPrimary: colors.primary,
    colorPrimaryHover: colors.primaryLight,
    colorPrimaryActive: colors.primaryDark,
    colorPrimaryBg: '#ecfeff',
    colorPrimaryBgHover: '#cffafe',
    colorPrimaryBorder: '#a5f3fc',
    colorPrimaryBorderHover: '#67e8f9',
    colorPrimaryText: colors.primary,
    colorPrimaryTextHover: colors.primaryLight,
    colorPrimaryTextActive: colors.primaryDark,

    // Background Colors
    colorBgBase: colors.bgLight,
    colorBgContainer: colors.surfaceLight,
    colorBgElevated: colors.surfaceLight,
    colorBgLayout: colors.bgLight,
    colorBgSpotlight: 'rgba(8, 145, 178, 0.1)',
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
    colorInfoBorder: '#a5f3fc',

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
    borderRadiusSM: 2,
    borderRadiusXS: 2,

    // Shadows - Subtle and sophisticated
    boxShadow:
      '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
    boxShadowSecondary:
      '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12), 0 9px 28px 8px rgba(0, 0, 0, 0.05)',

    // Control
    controlHeight: 32,
    controlHeightLG: 36,
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
      itemSelectedBg: 'rgba(8, 145, 178, 0.1)',
      itemSelectedColor: colors.primary,
      itemActiveBg: 'rgba(8, 145, 178, 0.15)',
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      defaultBg: '#ffffff',
      defaultColor: '#171717',
      defaultBorderColor: '#eaeaea',
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
      colorBgContainer: '#ffffff',
      colorBorder: '#eaeaea',
      addonBg: '#fafafa',
      hoverBg: '#fafafa',
      activeBg: '#ffffff',
      activeBorderColor: '#171717',
      hoverBorderColor: '#d4d4d4',
      activeShadow: '0 0 0 1px rgba(0, 0, 0, 0.32), 0 0 0 4px rgba(0, 0, 0, 0.12)',
    },
    Select: {
      colorBgContainer: '#ffffff',
      colorBorder: '#eaeaea',
      selectorBg: '#ffffff',
      optionSelectedBg: '#fafafa',
      optionSelectedColor: '#171717',
      multipleItemBg: '#fafafa',
      multipleItemBorderColor: '#eaeaea',
      activeBorderColor: '#171717',
      hoverBorderColor: '#d4d4d4',
      activeOutlineColor: 'rgba(0, 0, 0, 0.12)',
    },
    DatePicker: {
      colorBgContainer: '#ffffff',
      colorBorder: '#eaeaea',
      activeBg: '#ffffff',
      hoverBg: '#fafafa',
      activeBorderColor: '#171717',
      hoverBorderColor: '#d4d4d4',
      activeShadow: '0 0 0 1px rgba(0, 0, 0, 0.32), 0 0 0 4px rgba(0, 0, 0, 0.12)',
    },
    InputNumber: {
      colorBgContainer: '#ffffff',
      colorBorder: '#eaeaea',
      activeBg: '#ffffff',
      hoverBg: '#fafafa',
      activeBorderColor: '#171717',
      hoverBorderColor: '#d4d4d4',
      activeShadow: '0 0 0 1px rgba(0, 0, 0, 0.32), 0 0 0 4px rgba(0, 0, 0, 0.12)',
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
    colorPrimary: colors.primaryCyanDark,
    colorPrimaryHover: colors.primaryGlow,
    colorPrimaryActive: colors.primaryCyanDark,
    colorPrimaryBg: 'rgba(56, 214, 255, 0.15)',
    colorPrimaryBgHover: 'rgba(56, 214, 255, 0.25)',
    colorPrimaryBorder: 'rgba(56, 214, 255, 0.4)',
    colorPrimaryBorderHover: 'rgba(56, 214, 255, 0.6)',
    colorPrimaryText: colors.primaryCyanDark,
    colorPrimaryTextHover: colors.primaryGlow,
    colorPrimaryTextActive: colors.primaryCyanDark,

    // Background Colors
    colorBgBase: colors.bgDark,
    colorBgContainer: colors.surfaceDark,
    colorBgElevated: colors.surfaceDarkAlt,
    colorBgLayout: colors.bgDark,
    colorBgSpotlight: 'rgba(56, 214, 255, 0.15)',
    colorBgMask: 'rgba(0, 0, 0, 0.65)',

    // Border Colors
    colorBorder: colors.borderDark,
    colorBorderSecondary: '#1a2230',

    // Text Colors
    colorText: colors.textPrimaryDark,
    colorTextSecondary: colors.textSecondaryDark,
    colorTextTertiary: colors.textMuted,
    colorTextQuaternary: colors.textMutedDark2,
    colorTextDescription: colors.textMuted,
    colorTextDisabled: '#3a4452',
    colorTextPlaceholder: colors.textMutedDark2,

    // Status Colors
    colorSuccess: colors.success,
    colorSuccessBg: 'rgba(53, 211, 153, 0.15)',
    colorSuccessBorder: 'rgba(53, 211, 153, 0.4)',
    colorWarning: colors.warning,
    colorWarningBg: 'rgba(240, 179, 90, 0.15)',
    colorWarningBorder: 'rgba(240, 179, 90, 0.4)',
    colorError: colors.error,
    colorErrorBg: 'rgba(255, 105, 120, 0.15)',
    colorErrorBorder: 'rgba(255, 105, 120, 0.4)',
    colorInfo: colors.info,
    colorInfoBg: 'rgba(56, 214, 255, 0.15)',
    colorInfoBorder: 'rgba(56, 214, 255, 0.4)',

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
    borderRadiusSM: 2,
    borderRadiusXS: 2,

    // Shadows
    boxShadow:
      '0 1px 2px 0 rgba(0, 0, 0, 0.2), 0 1px 6px -1px rgba(0, 0, 0, 0.15), 0 2px 4px 0 rgba(0, 0, 0, 0.1)',
    boxShadowSecondary:
      '0 6px 16px 0 rgba(0, 0, 0, 0.32), 0 3px 6px -4px rgba(0, 0, 0, 0.48), 0 9px 28px 8px rgba(0, 0, 0, 0.2)',

    // Control
    controlHeight: 32,
    controlHeightLG: 36,
    controlHeightSM: 28,

    // Motion
    motion: true,
  },
  components: {
    Layout: {
      headerBg: colors.surfaceDark,
      headerColor: colors.textPrimaryDark,
      siderBg: colors.surfaceDark,
      bodyBg: colors.bgDark,
      triggerBg: colors.surfaceDarkAlt,
    },
    Menu: {
      itemBg: 'transparent',
      itemColor: colors.textMuted,
      itemHoverBg: colors.borderDark,
      itemHoverColor: colors.textPrimaryDark,
      itemSelectedBg: 'rgba(56, 214, 255, 0.15)',
      itemSelectedColor: colors.primaryCyanDark,
      itemActiveBg: 'rgba(56, 214, 255, 0.2)',
      darkItemBg: 'transparent',
      darkItemColor: colors.textMuted,
      darkItemHoverBg: colors.borderDark,
      darkItemHoverColor: colors.textPrimaryDark,
      darkItemSelectedBg: 'rgba(56, 214, 255, 0.15)',
      darkItemSelectedColor: colors.primaryCyanDark,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      defaultBg: colors.surfaceDarkAlt,
      defaultColor: '#fafafa',
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
      addonBg: colors.surfaceDark,
      hoverBg: colors.surfaceElevated,
      activeBg: colors.surfaceDarkAlt,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeShadow: '0 0 0 1px rgba(56, 214, 255, 0.45), 0 0 0 4px rgba(56, 214, 255, 0.16)',
    },
    Select: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      selectorBg: colors.surfaceDarkAlt,
      optionSelectedBg: colors.surfaceElevated,
      optionSelectedColor: '#fafafa',
      multipleItemBg: colors.surfaceElevated,
      multipleItemBorderColor: colors.borderDark,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeOutlineColor: 'rgba(56, 214, 255, 0.16)',
    },
    DatePicker: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      activeBg: colors.surfaceDarkAlt,
      hoverBg: colors.surfaceElevated,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeShadow: '0 0 0 1px rgba(56, 214, 255, 0.45), 0 0 0 4px rgba(56, 214, 255, 0.16)',
    },
    InputNumber: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      activeBg: colors.surfaceDarkAlt,
      hoverBg: colors.surfaceElevated,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeShadow: '0 0 0 1px rgba(56, 214, 255, 0.45), 0 0 0 4px rgba(56, 214, 255, 0.16)',
    },
    Modal: {
      headerBg: colors.surfaceDark,
      contentBg: colors.surfaceDark,
    },
    Tabs: {
      inkBarColor: colors.primaryCyanDark,
      itemActiveColor: colors.primaryCyanDark,
      itemSelectedColor: colors.primaryCyanDark,
      itemHoverColor: colors.primaryGlow,
      itemColor: colors.textMuted,
    },
    Tag: {
      defaultBg: colors.borderDark,
      defaultColor: colors.textMuted,
    },
    Badge: {
      colorBgContainer: colors.error,
    },
    Breadcrumb: {
      itemColor: colors.textMuted,
      lastItemColor: colors.textPrimaryDark,
      linkColor: colors.textMuted,
      linkHoverColor: colors.primaryLight,
      separatorColor: colors.borderDark,
    },
    Statistic: {
      titleFontSize: 12,
      contentFontSize: 28,
    },
    Progress: {
      defaultColor: colors.primaryCyanDark,
    },
    Spin: {
      colorPrimary: colors.primaryCyanDark,
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
