/**
 * SEP-1865 Theming: Generate host styles from MemStack's Ant Design theme.
 *
 * Maps Ant Design token values to the standardized CSS variables defined in
 * the MCP Apps specification (McpUiStyleVariableKey).
 */

import { colors } from '@/theme/antdTheme';

const FONT_SANS =
  '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const FONT_MONO =
  '"JetBrains Mono", "Fira Code", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';

/**
 * Generate SEP-1865 host styles for a given theme.
 *
 * Returns `{ variables }` object matching the `McpUiHostStyles` type from
 * `@modelcontextprotocol/ext-apps`. The keys are `McpUiStyleVariableKey` CSS
 * custom property names, and values are CSS values derived from MemStack's
 * Ant Design tokens.
 */
export function buildHostStyles(theme: 'light' | 'dark'): { variables: Record<string, string> } {
  const isLight = theme === 'light';

  const variables: Record<string, string> = {
    // Background colors
    '--color-background-primary': isLight ? colors.surfaceLight : colors.surfaceDark,
    '--color-background-secondary': isLight ? colors.bgLight : colors.bgDark,
    '--color-background-tertiary': isLight ? '#f1f5f9' : colors.surfaceDarkAlt,
    '--color-background-inverse': isLight ? colors.bgDark : colors.surfaceLight,
    '--color-background-ghost': 'transparent',
    '--color-background-info': isLight ? colors.infoLight : 'rgba(59, 130, 246, 0.15)',
    '--color-background-danger': isLight ? colors.errorLight : 'rgba(239, 68, 68, 0.15)',
    '--color-background-success': isLight ? colors.successLight : 'rgba(16, 185, 129, 0.15)',
    '--color-background-warning': isLight ? colors.warningLight : 'rgba(245, 158, 11, 0.15)',
    '--color-background-disabled': isLight ? '#f1f5f9' : '#2a2a2e',

    // Text colors
    '--color-text-primary': isLight ? colors.textPrimary : '#e8eaed',
    '--color-text-secondary': isLight ? colors.textSecondary : '#b0b8c4',
    '--color-text-tertiary': isLight ? colors.textMutedLight : colors.textMuted,
    '--color-text-inverse': isLight ? '#e8eaed' : colors.textPrimary,
    '--color-text-ghost': isLight ? colors.textMutedLight : colors.textMuted,
    '--color-text-info': isLight ? colors.info : '#60a5fa',
    '--color-text-danger': isLight ? colors.error : '#f87171',
    '--color-text-success': isLight ? colors.success : '#34d399',
    '--color-text-warning': isLight ? colors.warning : '#fbbf24',
    '--color-text-disabled': isLight ? '#9ca3af' : '#4a4f5a',

    // Border colors
    '--color-border-primary': isLight ? colors.borderLight : colors.borderDark,
    '--color-border-secondary': isLight ? '#f1f5f9' : '#222226',
    '--color-border-tertiary': isLight ? '#e2e8f0' : '#3a3a3f',
    '--color-border-inverse': isLight ? colors.borderDark : colors.borderLight,
    '--color-border-ghost': 'transparent',
    '--color-border-info': isLight ? '#93c5fd' : 'rgba(59, 130, 246, 0.4)',
    '--color-border-danger': isLight ? '#fecaca' : 'rgba(239, 68, 68, 0.4)',
    '--color-border-success': isLight ? '#a7f3d0' : 'rgba(16, 185, 129, 0.4)',
    '--color-border-warning': isLight ? '#fde68a' : 'rgba(245, 158, 11, 0.4)',
    '--color-border-disabled': isLight ? '#e2e8f0' : '#2a2a2e',

    // Ring colors
    '--color-ring-primary': isLight ? colors.primary : colors.primaryLight,
    '--color-ring-secondary': isLight ? colors.borderLight : colors.borderDark,
    '--color-ring-inverse': isLight ? colors.borderDark : colors.borderLight,
    '--color-ring-info': isLight ? colors.info : '#60a5fa',
    '--color-ring-danger': isLight ? colors.error : '#f87171',
    '--color-ring-success': isLight ? colors.success : '#34d399',
    '--color-ring-warning': isLight ? colors.warning : '#fbbf24',

    // Typography - Family
    '--font-sans': FONT_SANS,
    '--font-mono': FONT_MONO,

    // Typography - Weight
    '--font-weight-normal': '400',
    '--font-weight-medium': '500',
    '--font-weight-semibold': '600',
    '--font-weight-bold': '700',

    // Typography - Text Size
    '--font-text-xs-size': '12px',
    '--font-text-sm-size': '13px',
    '--font-text-md-size': '14px',
    '--font-text-lg-size': '16px',

    // Typography - Heading Size (matches Ant Design fontSizeHeading*)
    '--font-heading-xs-size': '14px',
    '--font-heading-sm-size': '16px',
    '--font-heading-md-size': '20px',
    '--font-heading-lg-size': '24px',
    '--font-heading-xl-size': '30px',
    '--font-heading-2xl-size': '38px',
    '--font-heading-3xl-size': '46px',

    // Typography - Text Line Height
    '--font-text-xs-line-height': '1.6667',
    '--font-text-sm-line-height': '1.5385',
    '--font-text-md-line-height': '1.5714',
    '--font-text-lg-line-height': '1.5',

    // Typography - Heading Line Height
    '--font-heading-xs-line-height': '1.5714',
    '--font-heading-sm-line-height': '1.5',
    '--font-heading-md-line-height': '1.4',
    '--font-heading-lg-line-height': '1.3333',
    '--font-heading-xl-line-height': '1.2667',
    '--font-heading-2xl-line-height': '1.2105',
    '--font-heading-3xl-line-height': '1.1739',

    // Border radius (matches Ant Design borderRadius*)
    '--border-radius-xs': '2px',
    '--border-radius-sm': '4px',
    '--border-radius-md': '6px',
    '--border-radius-lg': '8px',
    '--border-radius-xl': '12px',
    '--border-radius-full': '9999px',

    // Border width
    '--border-width-regular': '1px',

    // Shadows
    '--shadow-hairline': isLight
      ? '0 0 0 1px rgba(0,0,0,0.05)'
      : '0 0 0 1px rgba(255,255,255,0.05)',
    '--shadow-sm': isLight
      ? '0 1px 2px rgba(0,0,0,0.05)'
      : '0 1px 2px rgba(0,0,0,0.3)',
    '--shadow-md': isLight
      ? '0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05)'
      : '0 4px 6px -1px rgba(0,0,0,0.4), 0 2px 4px -2px rgba(0,0,0,0.3)',
    '--shadow-lg': isLight
      ? '0 10px 15px -3px rgba(0,0,0,0.07), 0 4px 6px -4px rgba(0,0,0,0.05)'
      : '0 10px 15px -3px rgba(0,0,0,0.5), 0 4px 6px -4px rgba(0,0,0,0.4)',
  };

  return { variables };
}
