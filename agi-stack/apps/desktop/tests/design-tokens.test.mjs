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
  // phase-4: light-theme cleanup swap map (31 files)
  '03141a', '041410', '0d141e', '0d2029', '0e1d24', '0e2019', '0f2028', '10202a',
  '102622', '102d38', '112933', '112d37', '11313e', '12303b', '12313d', '13303c',
  '14232d', '14252d', '143340', '143642', '1496ad', '153642', '157a94', '17140e',
  '172632', '17303a', '17303c', '17313c', '173541', '176b84', '176e84', '18303a',
  '188ba7', '19140e', '1b150e', '1c1115', '1c170e', '1c6b83', '205264', '211217',
  '211b10', '211b38', '231516', '24576a', '245d45', '246b80', '247258', '251e11',
  '25536a', '26718a', '267e96', '2692ad', '271616', '275064', '27584a', '275c71',
  '27738c', '28171d', '285265', '285465', '285467', '285768', '28596a', '28667a',
  '286a80', '28738c', '29223f', '2a5a6a', '2a5c6d', '2b5360', '2b5362', '2b5d6d',
  '2c151b', '2c5361', '2c5566', '2c768a', '2d6878', '2dbf7f', '2e859c', '2e8ba5',
  '315062', '315263', '315767', '31596a', '315e9c', '31677a', '321b21', '32675f',
  '332518', '335a69', '34748a', '352719', '38bfe3', '3a342e', '42bb88', '43a7c0',
  '466079', '477086', '49c788', '4b2831', '4c3b25', '4dcbe8', '4fbfdc', '4fc29e',
  '4fcceb', '4fd1a7', '50cee9', '52cce8', '53c98f', '55d69a', '56b4cc', '56d7f5',
  '574629', '574989', '59d6ed', '5b4825', '5ccae8', '5d472c', '5f8391', '5fd6f2',
  '603635', '624a2d', '62d7eb', '62d8c7', '62d9ef', '6366f1', '63bcd1', '64b2c4',
  '65bad0', '65bdd9', '65d7d2', '663735', '66c5df', '683542', '68bbcf', '69b5c7',
  '69b5c8', '69d6f3', '6a4c27', '6abdd1', '6b343c', '6c5d8e', '6cb9ca', '6d313d',
  '6edff6', '6ee7b7', '6fb9ca', '6fd5e8', '70b9c9', '70dff2', '71639f', '72d4f4',
  '74bdcc', '77c8da', '7899b2', '78adba', '78b9c9', '78c2d2', '78e2b0', '796844',
  '79d6b0', '79e3b5', '79e4bd', '7b6e62', '7cc7ff', '7dd3cf', '7e9dab', '7f6bd1',
  '7fbfce', '7fe6bd', '806b4e', '80bdd0', '80cede', '85e1c3', '86e9c2', '87683f',
  '87cfe7', '89d8e8', '8a6970', '8b6533', '8b9cf6', '8c6634', '8cc8d6', '8dcda5',
  '8de4bd', '8e7b55', '8ed9e9', '8f7651', '8f9dc4', '91d9e8', '93c9d6', '96d5ab',
  '9acfe0', '9adbe8', '9bc9d5', '9bdfb0', '9be9f8', '9c8cff', '9ddceb', '9edcf1',
  '9fd3e8', 'a18cff', 'a2d6b1', 'a3ddef', 'a5b4fc', 'a78a5f', 'a98148', 'a9d5de',
  'a9d8b8', 'b63b52', 'b68a4a', 'b8efff', 'b9e5ed', 'bff8df', 'cc7e87', 'd2858d',
  'd2a1a1', 'd2f4fa', 'd5b84f', 'd6a65f', 'd6a86a', 'd8a14f', 'd8bd62', 'd98087',
  'd9a84c', 'd9b8ff', 'db6d7a', 'e1b674', 'e7c48d', 'e7c991', 'e8a1ad', 'e8bc78',
  'e8bd6e', 'e9a5b1', 'ef9494', 'ef9b9b', 'f0c37f', 'f1c77f', 'f29a9a', 'f2a7a7',
  'f3aab4', 'f3b2b8', 'f4a6a6', 'f6c983', 'f6d5a3', 'f8c273', 'fb7185', 'fcd34d',
  'ff7f8b', 'ff8793', 'ff8b96', 'ff8e86', 'ff8e8e', 'ff8e99', 'ff9c9c', 'ffaaa3',
  'ffaaaa', 'ffb0aa', 'ffb4bc', 'ffc0c0', 'ffc8c8', 'ffd7dc',
  // phase-5: final light-theme cleanup — residual singletons mapped to tokens
  '8eb7c2', '334155', '0f172a', '92400e', '116981', '304a58', 'e9f4f7', '173b4b',
  '365361', 'f1f8f6', '38574e', 'fff5f5', '24463c', 'f8fafc', 'd8e3ec', '42b99b',
  '55b7ce', '94a3b8', '0d131d', '0a111b', '657a8c', '273947', '71869a', 'b8cad7',
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
  // phase-4: light-theme cleanup swap map (31 files)
  [2, 6, 11], [2, 6, 12], [4, 13, 16], [5, 12, 19], [5, 13, 19], [6, 19, 22],
  [8, 13, 23], [8, 14, 22], [8, 17, 24], [8, 17, 26], [8, 20, 29], [8, 21, 29],
  [8, 26, 35], [8, 27, 25], [8, 28, 37], [9, 15, 24], [9, 16, 23], [9, 16, 26],
  [9, 23, 31], [10, 18, 29], [10, 20, 28], [10, 20, 31], [11, 16, 23], [11, 30, 42],
  [12, 18, 31], [12, 23, 31], [13, 30, 39], [14, 23, 32], [15, 25, 38], [15, 28, 38],
  [15, 29, 42], [15, 30, 39], [16, 98, 117], [16, 113, 84], [17, 25, 35], [17, 26, 37],
  [18, 48, 59], [19, 28, 40], [20, 31, 43], [20, 34, 44], [20, 40, 52], [20, 52, 68],
  [21, 25, 42], [21, 45, 57], [21, 58, 53], [22, 65, 78], [24, 47, 60], [25, 42, 53],
  [25, 54, 66], [25, 114, 136], [28, 74, 88], [28, 93, 112], [29, 164, 205], [30, 71, 84],
  [30, 108, 133], [31, 36, 57], [34, 16, 20], [44, 112, 133], [45, 176, 138], [47, 19, 24],
  [53, 22, 27], [66, 193, 225], [73, 143, 168], [76, 211, 234], [76, 214, 163], [77, 111, 129],
  [79, 209, 167], [82, 115, 129], [83, 240, 207], [84, 121, 139], [89, 188, 212], [90, 153, 177],
  [91, 91, 138], [92, 155, 181], [98, 217, 239], [99, 119, 134], [124, 34, 34], [130, 148, 157],
  [139, 156, 246], [143, 157, 196], [146, 64, 14], [151, 174, 190], [153, 27, 27], [185, 28, 28],
  [212, 92, 101], [232, 161, 173], [255, 107, 107], [255, 108, 124], [255, 182, 190],
  // phase-5: rgba channels folded into existing channel tokens (light overrides)
  [7, 126, 154], [238, 247, 250], [26, 132, 103], [173, 56, 67], [217, 119, 6],
  [8, 145, 178], [248, 250, 252],
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

test('hardcoded hex color budget ratchets down (phase-5 baseline: 0)', () => {
  // This budget may only go DOWN. Lower the number whenever a migration pass
  // removes more hardcoded hex colors; never raise it.
  const HEX_BUDGET = 0;
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
