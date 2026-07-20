/**
 * Token Sync Guard
 *
 * Asserts that the LITERAL CSS values in `web/src/index.css` (`@theme` + `.dark`
 * palette-shim blocks) match the single source of truth in
 * `web/src/theme/tokens.ts`.
 *
 * CSS cannot import TS, so the two are kept in sync manually. This test fails
 * fast whenever someone drifts the palette — update BOTH together.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { tokens } from '@/theme/tokens';

const css = readFileSync(resolve(__dirname, '../../index.css'), 'utf8');

/** Read `--name: value;` from a CSS substring. `name` is the full suffix. */
function varValue(scope: string, name: string): string | null {
  const m = scope.match(new RegExp(`--${name}:\\s*([^;]+);`));
  return m ? m[1].trim() : null;
}

/** First top-level block whose selector matches `selectorRe`. */
function blockContents(selectorRe: RegExp): string {
  const m = css.match(new RegExp(`(${selectorRe.source})\\s*\\{([\\s\\S]*?)\\n\\}`, 'm'));
  if (!m) throw new Error(`CSS block matching ${selectorRe} not found`);
  return m[2];
}

const themeBlock = blockContents(/^@theme/);
// The LAST `.dark {` block is the palette shim (earlier .dark blocks redefine
// form-vars only). Each closes with a column-0 brace.
const darkBlocks = css.match(/\.dark\s*\{[\s\S]*?\n\}/g) ?? [];
const darkPalette = darkBlocks[darkBlocks.length - 1] ?? '';

describe('token sync: index.css ↔ tokens.ts', () => {
  it('@theme and .dark palette blocks are both present', () => {
    expect(themeBlock.length).toBeGreaterThan(0);
    expect(darkPalette.length).toBeGreaterThan(0);
  });

  /* ---------- Status (theme-agnostic, in @theme) ---------- */
  it.each([
    ['color-success', tokens.status.success],
    ['color-warning', tokens.status.warning],
    ['color-error', tokens.status.error],
    ['color-info', tokens.status.info],
  ])('@theme --%s === %s', (name, expected) => {
    expect(varValue(themeBlock, name)).toBe(expected);
  });

  /* ---------- Light surfaces / borders / text (in @theme) ---------- */
  it.each([
    ['color-surface-light', tokens.light.panel],
    ['color-surface-dark', tokens.dark.panel],
    ['color-surface-dark-alt', tokens.dark.panel2],
    ['color-surface-elevated', tokens.dark.panel3],
    ['color-border-light', tokens.light.border],
    ['color-border-dark', tokens.dark.border],
    ['color-text-primary', tokens.light.text],
    ['color-text-secondary', tokens.light.textMuted],
    ['color-text-muted', tokens.light.textMuted2],
    ['color-text-inverse', tokens.dark.text],
  ])('@theme --%s === %s', (name, expected) => {
    expect(varValue(themeBlock, name)).toBe(expected);
  });

  it('@theme --color-primary === tokens.light.cyan (AA cyan)', () => {
    expect(varValue(themeBlock, 'color-primary')).toBe(tokens.light.cyan);
  });

  /* ---------- Dark palette shim (.dark block) ---------- */
  it.each([
    ['color-primary', tokens.dark.cyan],
    ['color-blue-400', tokens.dark.cyan],
    ['color-blue-500', tokens.dark.cyan],
    ['color-blue-100', tokens.dark.cyanSoft],
    ['color-primary-100', tokens.dark.cyanSoft],
  ])('.dark --%s === %s', (name, expected) => {
    expect(varValue(darkPalette, name)).toBe(expected);
  });

  it.each([
    ['color-slate-950', tokens.dark.bg],
    ['color-slate-900', tokens.dark.panel],
    ['color-slate-800', tokens.dark.panel2],
    ['color-slate-700', tokens.dark.panel3],
    ['color-slate-500', tokens.dark.borderStrong],
    ['color-slate-300', tokens.dark.textMuted],
    ['color-slate-400', tokens.dark.textMuted2],
    ['color-slate-50', tokens.dark.text],
    ['color-gray-950', tokens.dark.bg],
    ['color-gray-900', tokens.dark.panel],
    ['color-gray-400', tokens.dark.textMuted2],
  ])('.dark --%s === %s', (name, expected) => {
    expect(varValue(darkPalette, name)).toBe(expected);
  });

  /* ---------- Geometry: radius (rem → px, 1rem === 16px) ---------- */
  it.each([
    ['radius-md', tokens.radius.md],
    ['radius-lg', tokens.radius.lg],
    ['radius-xl', tokens.radius.xl],
  ])('@theme --%s === %spx', (name, px) => {
    const raw = varValue(themeBlock, name);
    expect(raw, `--${name} missing`).toMatch(/rem$/);
    expect(Math.round(parseFloat(raw!.replace('rem', '')) * 16)).toBe(px);
  });

  /* ---------- No retired brand literals anywhere in index.css ---------- */
  it('index.css contains no retired brand palette literals', () => {
    const retired = [
      '#1e3fae',
      '#152d7e',
      '#3b5fc9',
      '#4b6fd9',
      '30, 63, 174',
      '59, 95, 201',
      '#1c1c1f',
      '#242428',
      '#2c2c31',
      '#3a3a40',
      '#737373',
      '#181818',
      '#f87171',
      '#fbbf24',
      '#60a5fa',
      '#3b82f6',
    ];
    const lower = css.toLowerCase();
    expect(retired.filter((lit) => lower.includes(lit.toLowerCase()))).toEqual([]);
  });
});
