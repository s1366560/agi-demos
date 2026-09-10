/**
 * Agent Workspace Typography Guard
 *
 * The workspace chrome used to carry several names for the same type step
 * (`text-[10px]` next to `text-2xs`, `text-[11px]` next to `text-xs-plus`) and
 * a dozen spellings of the uppercase micro-label. Both are now single-sourced:
 * sizes come from the `@theme` scale, and the label role comes from
 * `SECTION_LABEL_CLASSES` in `components/agent/styles.ts` with `tracking-label`.
 *
 * This guard keeps that state from drifting back one component at a time.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { SECTION_LABEL_CLASSES } from '@/components/agent/styles';

const SRC = resolve(__dirname, '../../');

/** Agent Workspace surface: the page, its agent components, and its chrome. */
const ROOTS = [
  'components/agent',
  'components/workspace/WorkspaceStatusBar.tsx',
  'components/layout/TenantChatSidebar.tsx',
  'components/layout/TenantHeader.tsx',
  'components/layout/NotificationDropdown.tsx',
  'pages/tenant/AgentWorkspace.tsx',
];

function collect(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return collect(path);
    return path.endsWith('.tsx') ? [path] : [];
  });
}

const files = ROOTS.flatMap((root) => {
  const path = join(SRC, root);
  return statSync(path).isDirectory() ? collect(path) : [path];
});

const sources = files.map((path) => ({
  path: path.slice(SRC.length),
  text: readFileSync(path, 'utf8'),
}));

describe('agent workspace typography', () => {
  it('scans the workspace surface', () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it('uses the @theme type scale instead of pixel-literal font sizes', () => {
    const offenders: string[] = [];
    for (const { path, text } of sources) {
      for (const [index, line] of text.split('\n').entries()) {
        if (/text-\[\d+(\.\d+)?(px|rem)\]/.test(line)) {
          offenders.push(`${path}:${String(index + 1)}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('keeps every uppercase label on the shared tracking step', () => {
    // The label role is defined once in SECTION_LABEL_CLASSES; assert both its
    // tokens and that no site spells the role differently.
    expect(SECTION_LABEL_CLASSES).toContain('tracking-label');
    expect(SECTION_LABEL_CLASSES).toContain('uppercase');

    const offenders: string[] = [];
    for (const { path, text } of sources) {
      for (const [index, line] of text.split('\n').entries()) {
        if (line.includes('uppercase') && !line.includes('tracking-label')) {
          offenders.push(`${path}:${String(index + 1)}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
