/**
 * MemStack Design System — Single Source of Truth
 *
 * Canonical values sourced from PRODUCT.md (mission-control aesthetic) and the
 * design prototype `design-prototype/memstack-desktop-agent-mission-control/src/styles.css`.
 *
 * - Dark is the primary theme: blue-black surfaces, luminous cyan accent.
 * - Light is derived: white surfaces with a deeper cyan that meets WCAG AA on white.
 *
 * NOTE: `web/src/index.css` `@theme` and `.dark {}` blocks contain LITERAL copies
 * of these values (CSS cannot import TS). `tokenSync.test.ts` asserts the two
 * stay in sync — update both together.
 */

export const tokens = {
  dark: {
    // Surfaces (prototype: --bg / --panel / --panel-2 / --panel-3)
    bg: '#080c12',
    panel: '#0d121a',
    panel2: '#111720',
    panel3: '#151c27',
    border: '#242d3a',
    borderStrong: '#334154',

    // Text (prototype: --text / --muted / --muted-2)
    text: '#e7edf6',
    textMuted: '#8996a9',
    textMuted2: '#5d6979',

    // Accent (prototype: --cyan / --cyan-soft)
    cyan: '#38d6ff',
    cyanSoft: '#112b36',
  },
  light: {
    bg: '#f6f8fa',
    panel: '#ffffff',
    panel2: '#f1f5f9',
    panel3: '#e8edf2',
    border: '#e2e8f0',
    borderStrong: '#cbd5e1',

    text: '#0f172a',
    textMuted: '#475569',
    textMuted2: '#64748b',

    // Deeper cyan for AA contrast on white (approx 5.4:1).
    cyan: '#0e7490',
    cyanSoft: '#ecfeff',
  },

  // Status — spec-faithful, tuned for both themes.
  status: {
    success: '#35d399',
    warning: '#f0b35a',
    error: '#ff6978',
    info: '#38d6ff',
  },

  // Geometry
  radius: { sm: 2, md: 6, lg: 8, xl: 8 },
  controlHeight: { sm: 28, md: 32, lg: 36 },

  // Typography
  fontFamilySans:
    '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  fontFamilyMono:
    '"JetBrains Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
} as const;

/**
 * Tailwind palette shims.
 *
 * The app historically uses `blue-*` for brand and `slate-*` / `gray-*` for
 * neutrals. Rather than rewriting ~2000 call sites, we redefine those CSS
 * variables so the utilities resolve to the mission-control palette.
 *
 * - `blueLight`  → deeper cyan scale (AA on white); used in light mode.
 * - `blueDark`   → luminous cyan scale centered on #38d6ff; applied under .dark.
 * - `neutralDark`→ blue-black panel family; applied to slate-* / gray-* under .dark.
 */
export const blueLightScale = {
  50: '#ecfeff',
  100: '#cffafe',
  200: '#a5f3fc',
  300: '#67e8f9',
  400: '#22d3ee',
  500: '#0891b2',
  600: '#0e7490',
  700: '#155e75',
  800: '#164e63',
  900: '#083344',
} as const;

export const blueDarkScale = {
  50: '#0a1f28',
  100: '#112b36',
  200: '#1a3f52',
  300: '#2a6680',
  400: '#38d6ff',
  500: '#38d6ff',
  600: '#2bb8e0',
  700: '#2398bd',
  800: '#1b7a98',
  900: '#145f7a',
} as const;

export const neutralDarkScale = {
  50: '#e7edf6',
  100: '#d6dde6',
  200: '#b8c3d2',
  300: '#8996a9',
  400: '#5d6979',
  500: '#334154',
  600: '#1f2937',
  700: '#151c27',
  800: '#111720',
  900: '#0d121a',
  950: '#080c12',
} as const;
