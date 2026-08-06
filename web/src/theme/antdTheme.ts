/**
 * Ant Design Theme Configuration
 *
 * Single source of truth: `web/src/theme/tokens.ts` (monochrome palette).
 * - Dark (primary): #0a0a0a neutral surfaces, near-white #f2f2f2 accent.
 * - Light (derived): white surfaces, near-black #262626 accent (WCAG AA on white).
 * Saturated hues remain only in semantic status colors and accent tiles.
 *
 * NOTE: `index.css` `@theme` / `.dark` hold LITERAL copies of these values for
 * Tailwind utility resolution; `tokenSync.test.ts` asserts they stay in sync.
 */

import { tokens } from './tokens';

import type { ThemeConfig } from 'antd';

// Design System Colors (values from tokens.ts; kept flat for hostStyles consumers)
export const colors = {
  // Primary — near-black on light (AA on white); dark uses near-white below
  primary: tokens.light.cyan,
  primaryDark: '#171717',
  primaryLight: '#525252',
  primaryGlow: '#a3a3a3',
  primaryCyanDark: tokens.dark.cyan, // near-white accent for dark theme

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

  // Accent tile colors — the deliberate colorful accents on the gray base
  tileBlue: '#38d6ff',
  tilePurple: '#a78bfa',
  tileEmerald: '#35d399',
  tileAmber: '#f0b35a',
  tileIndigo: '#22d3ee',
  tileRose: '#ff6978',
};

// Motion tokens shared by both themes (values from tokens.ts).
const motionTokens = {
  motion: true,
  motionDurationFast: tokens.motion.durationFast,
  motionDurationMid: tokens.motion.durationMid,
  motionDurationSlow: tokens.motion.durationSlow,
  motionEaseInOut: tokens.motion.easeInOut,
  motionEaseOut: tokens.motion.easeOut,
} as const;

// Light Theme Configuration
export const lightTheme: ThemeConfig = {
  token: {
    // Primary Colors
    colorPrimary: colors.primary,
    colorPrimaryHover: colors.primaryLight,
    colorPrimaryActive: colors.primaryDark,
    colorPrimaryBg: '#eeeeee',
    colorPrimaryBgHover: '#e0e0e0',
    colorPrimaryBorder: '#d4d4d4',
    colorPrimaryBorderHover: '#a3a3a3',
    colorPrimaryText: colors.primary,
    colorPrimaryTextHover: colors.primaryLight,
    colorPrimaryTextActive: colors.primaryDark,

    // Background Colors
    colorBgBase: colors.bgLight,
    colorBgContainer: colors.surfaceLight,
    colorBgElevated: colors.surfaceLight,
    colorBgLayout: colors.bgLight,
    colorBgSpotlight: 'rgba(0, 0, 0, 0.85)',
    colorBgMask: 'rgba(0, 0, 0, 0.45)',

    // Border Colors
    colorBorder: colors.borderLight,
    colorBorderSecondary: '#f2f2f2',

    // Text Colors
    colorText: colors.textPrimary,
    colorTextSecondary: colors.textSecondary,
    colorTextTertiary: colors.textMutedLight,
    colorTextQuaternary: '#9c9c9c',
    colorTextDescription: colors.textMutedLight,
    colorTextDisabled: '#9c9c9c',
    colorTextPlaceholder: '#9c9c9c',

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
    ...motionTokens,
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
      itemHoverBg: '#f2f2f2',
      itemHoverColor: colors.textPrimary,
      itemSelectedBg: 'rgba(0, 0, 0, 0.06)',
      itemSelectedColor: colors.primary,
      itemActiveBg: 'rgba(0, 0, 0, 0.1)',
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      primaryColor: '#ffffff',
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
      headerBg: '#f7f7f7',
      headerColor: colors.textSecondary,
      rowHoverBg: '#f7f7f7',
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
      defaultBg: '#f2f2f2',
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
      separatorColor: '#cccccc',
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
      colorBgSpotlight: '#262626',
      colorTextLightSolid: '#fafafa',
    },
  },
};

// Dark Theme Configuration
export const darkTheme: ThemeConfig = {
  token: {
    // Primary Colors
    colorPrimary: colors.primaryCyanDark,
    colorPrimaryHover: '#ffffff',
    colorPrimaryActive: '#d9d9d9',
    colorPrimaryBg: 'rgba(255, 255, 255, 0.12)',
    colorPrimaryBgHover: 'rgba(255, 255, 255, 0.2)',
    colorPrimaryBorder: 'rgba(255, 255, 255, 0.35)',
    colorPrimaryBorderHover: 'rgba(255, 255, 255, 0.55)',
    colorPrimaryText: colors.primaryCyanDark,
    colorPrimaryTextHover: '#ffffff',
    colorPrimaryTextActive: '#d9d9d9',

    // Background Colors
    colorBgBase: colors.bgDark,
    colorBgContainer: colors.surfaceDark,
    colorBgElevated: colors.surfaceDarkAlt,
    colorBgLayout: colors.bgDark,
    colorBgSpotlight: '#1f1f1f',
    colorBgMask: 'rgba(0, 0, 0, 0.65)',

    // Border Colors
    colorBorder: colors.borderDark,
    colorBorderSecondary: '#222222',

    // Text Colors
    colorText: colors.textPrimaryDark,
    colorTextSecondary: colors.textSecondaryDark,
    colorTextTertiary: colors.textMuted,
    colorTextQuaternary: colors.textMutedDark2,
    colorTextDescription: colors.textMuted,
    colorTextDisabled: '#4a4a4a',
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
    ...motionTokens,
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
      itemSelectedBg: 'rgba(255, 255, 255, 0.1)',
      itemSelectedColor: colors.primaryCyanDark,
      itemActiveBg: 'rgba(255, 255, 255, 0.16)',
      darkItemBg: 'transparent',
      darkItemColor: colors.textMuted,
      darkItemHoverBg: colors.borderDark,
      darkItemHoverColor: colors.textPrimaryDark,
      darkItemSelectedBg: 'rgba(255, 255, 255, 0.1)',
      darkItemSelectedColor: colors.primaryCyanDark,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      primaryColor: '#121212',
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
      activeShadow: '0 0 0 1px rgba(255, 255, 255, 0.4), 0 0 0 4px rgba(255, 255, 255, 0.14)',
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
      activeOutlineColor: 'rgba(255, 255, 255, 0.14)',
    },
    DatePicker: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      activeBg: colors.surfaceDarkAlt,
      hoverBg: colors.surfaceElevated,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeShadow: '0 0 0 1px rgba(255, 255, 255, 0.4), 0 0 0 4px rgba(255, 255, 255, 0.14)',
    },
    InputNumber: {
      colorBgContainer: colors.surfaceDarkAlt,
      colorBorder: colors.borderDark,
      activeBg: colors.surfaceDarkAlt,
      hoverBg: colors.surfaceElevated,
      activeBorderColor: colors.borderStrongDark,
      hoverBorderColor: colors.borderDark,
      activeShadow: '0 0 0 1px rgba(255, 255, 255, 0.4), 0 0 0 4px rgba(255, 255, 255, 0.14)',
    },
    Modal: {
      headerBg: colors.surfaceDark,
      contentBg: colors.surfaceDark,
    },
    Tabs: {
      inkBarColor: colors.primaryCyanDark,
      itemActiveColor: colors.primaryCyanDark,
      itemSelectedColor: colors.primaryCyanDark,
      itemHoverColor: '#ffffff',
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
      colorTextLightSolid: '#fafafa',
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
