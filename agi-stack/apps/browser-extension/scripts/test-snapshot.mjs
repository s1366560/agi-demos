// Playwright harness for assets/snapshot.js. Exits non-zero on any failure.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const snapshotSource = readFileSync(join(root, 'assets', 'snapshot.js'), 'utf8');
const fixtureHtml = readFileSync(join(root, 'scripts', 'fixtures', 'snapshot-fixture.html'), 'utf8');

let failures = 0;

function check(name, condition, detail) {
  if (condition) {
    console.log(`ok   - ${name}`);
  } else {
    failures += 1;
    console.error(`FAIL - ${name}${detail ? `\n       ${detail}` : ''}`);
  }
}

function extractRefs(output) {
  return [...output.matchAll(/\[ref=e(\d+)\]/g)].map((m) => Number(m[1]));
}

const browser = await chromium.launch();

try {
  // ---------------------------------------------------------- fixture page
  const page = await browser.newPage();
  await page.setContent(fixtureHtml, { waitUntil: 'load' });
  const output = await page.evaluate(snapshotSource);

  console.log('--- fixture snapshot (first 40 lines) ---');
  console.log(output.split('\n').slice(0, 40).join('\n'));
  console.log('--- end fixture snapshot ---');

  const refs = extractRefs(output);
  check('refs are present', refs.length > 0, `found ${refs.length}`);
  check(
    'refs are sequential e1..eN',
    refs.every((n, i) => n === i + 1),
    `got [${refs.join(', ')}]`,
  );

  const expectations = [
    ['link "Home"', 'interactive link listed'],
    ['link "About"', 'second link listed'],
    ['heading "Fixture Page"', 'heading listed'],
    ['textbox "Search"', 'labelled textbox listed'],
    ['value="abc"', 'textbox value emitted'],
    ['checkbox "Agree to terms"', 'checkbox listed'],
    ['checked', 'checked state emitted'],
    ['button "Save"', 'submit input listed as button'],
    ['button "Disabled Action"', 'disabled button listed'],
    ['disabled', 'disabled state emitted'],
    ['combobox "Choice"', 'select listed with aria-label'],
    ['textbox "Notes"', 'textarea listed via placeholder'],
    ['img "Logo image"', 'img alt emitted'],
    ['- text "Some static paragraph text."', 'static text emitted'],
    ['#shadow-root', 'shadow root recursion present'],
    ['button "Shadow Action"', 'shadow-DOM button listed'],
    ['iframe "Inner frame"', 'iframe section present'],
    ['heading "Frame Heading"', 'iframe child snapshot present'],
    ['button "Frame Button"', 'iframe button listed'],
  ];
  for (const [needle, name] of expectations) {
    check(name, output.includes(needle), `missing: ${needle}`);
  }

  const exclusions = [
    ['Hidden Display', 'display:none excluded'],
    ['Hidden Visibility', 'visibility:hidden excluded'],
    ['Hidden Aria', 'aria-hidden subtree excluded'],
    ['Hidden Zero Box', 'zero bounding box excluded'],
  ];
  for (const [needle, name] of exclusions) {
    check(name, !output.includes(needle), `unexpected: ${needle}`);
  }

  const refStore = await page.evaluate(() => {
    const store = window.__memstackSnapshotRefs;
    if (!(store instanceof Map)) return { ok: false, size: -1, resolves: false };
    const first = store.get('e1');
    const el = first && typeof first.deref === 'function' ? first.deref() : first;
    return { ok: true, size: store.size, resolves: el instanceof Element };
  });
  check('window.__memstackSnapshotRefs is a Map', refStore.ok);
  check('ref store size matches emitted refs', refStore.size === refs.length,
    `store=${refStore.size} emitted=${refs.length}`);
  check('ref e1 resolves to a live element', refStore.resolves);

  // ------------------------------------------------------------ huge page
  const hugePage = await browser.newPage();
  const hugeHtml =
    '<!doctype html><html><body>' +
    Array.from(
      { length: 3000 },
      (_, i) => `<button>Button number ${i} with a reasonably long label</button>`,
    ).join('') +
    '</body></html>';
  await hugePage.setContent(hugeHtml, { waitUntil: 'load' });
  const hugeOutput = await hugePage.evaluate(snapshotSource);
  check(
    'huge page is truncated',
    hugeOutput.endsWith('… [truncated]'),
    `tail: ${JSON.stringify(hugeOutput.slice(-40))}`,
  );
  check(
    'truncated output stays within budget',
    hugeOutput.length <= 20000 + '\n… [truncated]'.length,
    `length: ${hugeOutput.length}`,
  );
  const hugeRefs = extractRefs(hugeOutput);
  check(
    'refs stay sequential under truncation',
    hugeRefs.length > 0 && hugeRefs.every((n, i) => n === i + 1),
    `got ${hugeRefs.length} refs`,
  );
} finally {
  await browser.close();
}

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall snapshot checks passed');
