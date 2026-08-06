/**
 * MemStack Design System — Single Source of Truth
 *
 * Palette direction: monochrome black/white/gray base. Surfaces, borders, text
 * and the primary accent are neutral grays; the only saturated hues left are
 * the semantic status colors (success / warning / error / info) and the accent
 * tile colors, which act as the deliberate colorful accents.
 *
 * - Dark is the primary theme: near-black neutral surfaces, near-white accent.
 * - Light is derived: white surfaces with a near-black accent (WCAG AA on white).
 *
 * NOTE: `web/src/index.css` `@theme` and `.dark {}` blocks contain LITERAL copies
 * of these values (CSS cannot import TS). `tokenSync.test.ts` asserts the two
 * stay in sync — update both together.
 */

export const tokens = {
  dark: {
    // Surfaces (neutral near-black ladder)
    bg: '#0a0a0a',
    panel: '#121212',
    panel2: '#181818',
    panel3: '#1f1f1f',
    border: '#333333',
    borderStrong: '#404040',

    // Text (neutral)
    text: '#ededed',
    textMuted: '#9c9c9c',
    // WCAG AA on panel (#121212): 5.4:1. Previously #6e6e6e (3.5:1, below AA).
    textMuted2: '#8a8a8a',

    // Accent — monochrome (near-white on dark); `cyan` key kept for compatibility.
    cyan: '#f2f2f2',
    cyanSoft: '#242424',
  },
  light: {
    bg: '#f7f7f7',
    panel: '#ffffff',
    panel2: '#f2f2f2',
    panel3: '#e9e9e9',
    border: '#e3e3e3',
    borderStrong: '#cccccc',

    text: '#141414',
    textMuted: '#4f4f4f',
    textMuted2: '#6b6b6b',

    // Near-black accent for AA contrast on white (approx 13:1).
    cyan: '#262626',
    cyanSoft: '#eeeeee',
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
 * variables so the utilities resolve to the monochrome palette.
 *
 * - `blueLight`  → near-black gray scale (AA on white); used in light mode.
 * - `blueDark`   → near-white gray scale centered on #f2f2f2; applied under .dark.
 * - `neutralDark`→ neutral near-black panel family; applied to slate-* / gray-* under .dark.
 */
export const blueLightScale = {
  50: '#f5f5f5',
  100: '#e8e8e8',
  200: '#d4d4d4',
  300: '#a3a3a3',
  400: '#737373',
  500: '#525252',
  600: '#262626',
  700: '#1f1f1f',
  800: '#171717',
  900: '#0f0f0f',
} as const;

export const blueDarkScale = {
  50: '#1c1c1c',
  100: '#242424',
  200: '#303030',
  300: '#4d4d4d',
  400: '#f2f2f2',
  500: '#f2f2f2',
  600: '#d9d9d9',
  700: '#bfbfbf',
  800: '#a6a6a6',
  900: '#8c8c8c',
} as const;

export const neutralDarkScale = {
  50: '#ededed',
  100: '#dbdbdb',
  200: '#bdbdbd',
  300: '#9c9c9c',
  400: '#8a8a8a',
  500: '#404040',
  600: '#262626',
  700: '#1f1f1f',
  800: '#181818',
  900: '#121212',
  950: '#0a0a0a',
} as const;
