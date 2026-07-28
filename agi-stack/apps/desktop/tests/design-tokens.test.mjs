import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const srcRoot = new URL('../src/', import.meta.url);

const collectCssFiles = (dirUrl, prefix = '') => {
  const files = [];
  for (const entry of readdirSync(dirUrl)) {
    const child = new URL(`${entry}${statSync(new URL(entry, dirUrl)).isDirectory() ? '/' : ''}`, dirUrl);
    const rel = prefix ? `${prefix}/${entry}` : entry;
    if (statSync(child).isDirectory()) files.push(...collectCssFiles(child, rel));
    else if (entry.endsWith('.css')) files.push(rel);
  }
  return files;
};

const cssFiles = collectCssFiles(srcRoot);
// Phase 3 tokenized ChatPanel.css; every src CSS file is now covered by all guards.
const migratedCssFiles = cssFiles;
const readSrc = (file) => readFileSync(new URL(file, srcRoot), 'utf8');
const blankComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, (match) => ' '.repeat(match.length));

// Declaration matcher: property name + colon + value up to ; { or }. Custom
// property definitions (--desktop-*) are skipped — token definitions are the
// one place where raw literals are allowed.
const DECL_RE = /([a-zA-Z-][\w-]*)\s*:\s*([^;{}]+)/g;

const declarationValues = (css) => {
  const blanked = blankComments(css);
  const values = [];
  let match;
  DECL_RE.lastIndex = 0;
  while ((match = DECL_RE.exec(blanked))) {
    if (match[1].startsWith('--')) continue;
    values.push(match[2]);
  }
  return values;
};

const stylesCss = readSrc('styles.css');
const rootBlock = stylesCss.match(/:root\s*\{([\s\S]*?)\}/);
assert.ok(rootBlock, 'styles.css must define a :root block');
const definedTokens = new Set();
const duplicateTokens = new Set();
for (const match of rootBlock[1].matchAll(/(--desktop-[\w-]+)\s*:/g)) {
  if (definedTokens.has(match[1])) duplicateTokens.add(match[1]);
  definedTokens.add(match[1]);
}

test('every --desktop-* token in the styles.css :root block is defined exactly once', () => {
  assert.deepEqual([...duplicateTokens], []);
  assert.ok(definedTokens.size > 0);
});

// Full phase-1 migration list: hex literals replaced by tokens. Budget test (b)
// pins that none of them reappear in declaration value position.
const migratedHexLiterals = [
  // exact matches of pre-existing tokens
  '38d6ff', '080c12', '0f141d', '151a24', '242b36', '1b222e',
  'e7edf6', '9aa5b5', '687386', '35d399', 'f0b35a', 'ff6978',
  // surface ladder
  '060a11', '080d14', '090e15', '090e16', '0a0f15', '0a1017', '0b1017',
  '0b1018', '0b1118', '0b1119', '0c131c', '0d131b', '0d141c', '101720', '111923',
  // tinted surfaces
  '241419', '10232c',
  // border ladder
  '202a35', '202a36', '202c3a', '242d3a', '293442', '334052',
  // gray ladder
  '536174', '59687a', '607083', '617083', '637285', '647386', '657487',
  '667588', '637786', '718797', '7f91a3', '8290a2', '8ca0af',
  // light text + white
  'cbd7e3', 'dbe5ef', 'edf6fb', 'fff',
  // accent variants
  'e58b95', 'ff9aa4', 'ffadb6', '5a4f83', '145f73', '287d94',
  '55d8f7', '4cd6a3', 'e8ad5b',
  // phase-2: all hex literals with >=3 occurrences at phase-1 end
  // surface ladder extension
  '070c13', '080d13', '080e16', '0a1018', '0a1119', '0d141d', '101923',
  '111820', '111821', '111a25', '121923', '141b25', '141c27', '151d27',
  '162330', '171e27',
  // tinted surfaces
  '211c37', '10222b', '102630', '13271f', '10231b', '10251d', '2a2014', '231d15',
  // border ladder extension
  '1b2531', '252f3b', '253140', '263140', '273340', '273444', '293541',
  '293542', '2a3643', '2b3643', '2c3948', '2d3947', '334151', '334154', '345066',
  // tinted borders
  '375a4d', '265943', '5d3239', '5a4930', '6d5334', '6b5427',
  '2a6376', '23404c', '286a7d', '2b8ea7', '2b7084',
  // gray ladder extension
  '465466', '526174', '536274', '566577', '586779', '5e6e82', '627185',
  '667487', '68778a', '718094', '718195', '758396', '75869a', '8996a7',
  '8ca0b4', '9fb0c1', 'aab5c3', 'aeb9c6', 'b7c8d9', 'b8c3ce', 'b9c4cf', 'b9c5d2',
  // light text rungs
  'dce5ee', 'dce9f5', 'effbff',
  // accent variants
  'a58cff', 'd8cfff', '65d6a4', '63d78f', '52d68a', '54d68b', '53f0cf',
  'e98598', 'ffb6be', 'fecaca', 'c68c94', 'e5a54b', 'fbbf24',
  '146f87', '177c96', '8bd2ff', '8ee9ff',
  // phase-3: ChatPanel.css values meeting the >=3-in-file (or >=2 cross-file) bar
  'c9edf5', '718091', '6caec0', '53d0ef', '9faab6', 'fca5a5', '263342',
];

// Full phase-1 channel list: rgb triples replaced by --desktop-*-rgb tokens.
const migratedChannels = [
  [56, 214, 255], [148, 163, 184], [240, 179, 90], [53, 211, 153],
  [255, 105, 120], [248, 113, 113], [0, 0, 0], [255, 255, 255],
  [71, 113, 135], [118, 145, 170], [124, 150, 177],
  [3, 7, 12], [8, 15, 23], [10, 16, 25], [9, 17, 27], [13, 19, 29], [13, 24, 34],
  [34, 211, 238], [83, 208, 239], [245, 158, 11], [245, 183, 71],
  // phase-2: comma-form rgba families with >=2 occurrences at phase-1 end
  [127, 29, 29], [15, 23, 42], [111, 25, 37], [255, 102, 119], [74, 222, 128],
  [156, 163, 175], [7, 11, 18], [13, 20, 30], [11, 17, 26], [73, 177, 207],
  [251, 191, 36], [4, 10, 17], [9, 14, 22], [4, 9, 15], [8, 13, 20],
  [36, 178, 222], [65, 158, 216], [87, 181, 239], [214, 180, 110],
  [229, 139, 149], [19, 176, 219], [4, 8, 14], [79, 209, 231],
  [76, 221, 168], [10, 14, 21],
  // phase-3: ChatPanel.css comma-rgba families meeting the occurrence bar
  [103, 232, 249], [56, 189, 248], [129, 140, 248], [72, 104, 122],
  [45, 212, 191], [15, 25, 35], [27, 113, 138], [98, 144, 139],
  [250, 204, 21], [30, 41, 59], [31, 116, 145], [90, 99, 129],
  [56, 81, 96], [120, 53, 15],
];

test('migrated hex and rgba literals stay out of value position in every src CSS file', () => {
  const offenders = [];
  const hexRes = migratedHexLiterals.map((hex) => [hex, new RegExp(`#${hex}\\b`, 'i')]);
  // Matches both comma form rgba(r, g, b, a) and slash form rgb(r g b / a) —
  // phase-2 converted slash forms onto channel tokens too.
  const channelRes = migratedChannels.map(
    ([r, g, b]) => [
      `${r},${g},${b}`,
      new RegExp(`\\brgba?\\(\\s*${r}(?:\\s*,\\s*|\\s+)${g}(?:\\s*,\\s*|\\s+)${b}\\s*[,/)]`, 'i'),
    ],
  );
  for (const file of migratedCssFiles) {
    for (const value of declarationValues(readSrc(file))) {
      for (const [hex, re] of hexRes) {
        if (re.test(value)) offenders.push(`${file}: #${hex}`);
      }
      for (const [channel, re] of channelRes) {
        if (re.test(value)) offenders.push(`${file}: rgba(${channel}, ...)`);
      }
    }
  }
  assert.deepEqual(offenders, []);
});

test('hardcoded hex color budget ratchets down (phase-3 baseline: 985, includes ChatPanel.css)', () => {
  // This budget may only go DOWN. Lower the number whenever a migration pass
  // removes more hardcoded hex colors; never raise it.
  const HEX_BUDGET = 985;
  let count = 0;
  for (const file of migratedCssFiles) {
    for (const value of declarationValues(readSrc(file))) {
      count += (value.match(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g) ?? []).length;
    }
  }
  assert.ok(count <= HEX_BUDGET, `hardcoded hex count ${count} exceeds budget ${HEX_BUDGET}`);
});

test('every rgba(var(--desktop-*-rgb), ...) reference targets a defined channel token', () => {
  const missing = [];
  for (const file of cssFiles) {
    const css = blankComments(readSrc(file));
    for (const match of css.matchAll(/\brgba?\(\s*var\((--desktop-[\w-]+-rgb)\)/g)) {
      if (!definedTokens.has(match[1])) missing.push(`${file}: ${match[1]}`);
    }
  }
  assert.deepEqual(missing, []);
});

test('every var(--desktop-*) reference targets a token defined in :root', () => {
  // Guards against dropped declarations: a var() reference to a token that was
  // never defined is invalid at computed-value time and silently discarded.
  const missing = [];
  for (const file of cssFiles) {
    const css = blankComments(readSrc(file));
    for (const match of css.matchAll(/\bvar\((--desktop-[\w-]+)/g)) {
      if (!definedTokens.has(match[1])) missing.push(`${file}: ${match[1]}`);
    }
  }
  assert.deepEqual(missing, []);
});
