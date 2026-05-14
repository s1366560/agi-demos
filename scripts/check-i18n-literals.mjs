#!/usr/bin/env node
/**
 * check-i18n-literals.mjs
 *
 * Scans the frontend source tree for hardcoded CJK (Chinese / Japanese / Korean)
 * characters and fails the build if any are found outside the i18n whitelist.
 *
 * Usage:
 *   node scripts/check-i18n-literals.mjs            # scan web/src
 *   node scripts/check-i18n-literals.mjs path/...   # scan specific path
 *
 * Whitelist:
 *   - web/src/locales/**            (translation catalogs)
 *   - **\/*.test.*, **\/*.spec.*    (test fixtures may contain literals)
 *   - design-prototype/**           (static design mocks)
 *   - Files matching SCAN_IGNORE patterns
 *
 * Allowed inline patterns:
 *   - Single-line comments (//) and JSDoc/block comments (/* ... *\/)
 *     that contain CJK -- comments are allowed.
 *
 * Exit codes:
 *   0  no violations
 *   1  violations found
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const REPO_ROOT = join(__dirname, '..');

const DEFAULT_SCAN_ROOT = join(REPO_ROOT, 'web', 'src');
const SCAN_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx']);

const SCAN_IGNORE = [
  /[\\/]node_modules[\\/]/,
  /[\\/]dist[\\/]/,
  /[\\/]build[\\/]/,
  /[\\/]\.next[\\/]/,
  /[\\/]locales[\\/]/,
  /[\\/]design-prototype[\\/]/,
  /\.test\.[tj]sx?$/,
  /\.spec\.[tj]sx?$/,
  /[\\/]__tests__[\\/]/,
  /[\\/]__mocks__[\\/]/,
];

const CJK_RANGE = /[\u3400-\u9fff\uff00-\uffef\u3000-\u30ff]/;

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (SCAN_IGNORE.some((re) => re.test(full))) continue;
    const st = statSync(full);
    if (st.isDirectory()) {
      yield* walk(full);
    } else if (st.isFile()) {
      const ext = full.slice(full.lastIndexOf('.'));
      if (SCAN_EXTENSIONS.has(ext)) yield full;
    }
  }
}

/** Strip line and block comments so we only inspect actual code. Preserve newlines so line numbers stay aligned. */
function stripComments(source) {
  // Replace /* ... */ block comments while keeping newlines intact.
  let out = source.replace(/\/\*[\s\S]*?\*\//g, (m) =>
    m.replace(/[^\n]/g, ' '),
  );
  // Replace // line comments (single-line, so no newlines inside).
  out = out.replace(/\/\/[^\n]*/g, (m) => ' '.repeat(m.length));
  return out;
}

function scanFile(file) {
  const src = readFileSync(file, 'utf8');
  const stripped = stripComments(src);
  const lines = stripped.split('\n');
  const origLines = src.split('\n');
  const violations = [];
  for (let i = 0; i < lines.length; i++) {
    const m = CJK_RANGE.exec(lines[i]);
    if (m) {
      // Honor `// i18n-ignore` on the same or previous line.
      const same = origLines[i] || '';
      const prev = origLines[i - 1] || '';
      if (/i18n-ignore/.test(same) || /i18n-ignore-next/.test(prev)) continue;
      violations.push({
        line: i + 1,
        column: m.index + 1,
        excerpt: origLines[i].trim().slice(0, 160),
      });
    }
  }
  return violations;
}

const targets = process.argv.slice(2);
const root = targets.length > 0 ? targets : [DEFAULT_SCAN_ROOT];

let total = 0;
for (const r of root) {
  for (const file of walk(r)) {
    const v = scanFile(file);
    if (v.length > 0) {
      total += v.length;
      const rel = relative(REPO_ROOT, file).split(sep).join('/');
      for (const { line, column, excerpt } of v) {
        console.error(`${rel}:${line}:${column}  CJK literal in code: ${excerpt}`);
      }
    }
  }
}

if (total > 0) {
  console.error(`\n${total} hardcoded CJK literal(s) found. Move them to web/src/locales/*.json and use t().`);
  process.exit(1);
}
console.log('i18n literal scan: no CJK strings in code.');
