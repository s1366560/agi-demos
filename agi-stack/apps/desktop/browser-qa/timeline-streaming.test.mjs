import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import config from './playwright.config.mjs';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const sourceRoot =
  process.env.TIMELINE_QA_SOURCE_ROOT || fileURLToPath(new URL('..', import.meta.url));
const fixture = readFileSync(new URL('timeline-streaming.fixture.tsx', import.meta.url), 'utf8');
const bundle = await esbuild.build({
  stdin: { resolveDir: join(sourceRoot, 'src'), loader: 'tsx', contents: fixture },
  jsx: 'automatic',
  alias: {
    '@desktop': join(sourceRoot, 'src'),
    ...Object.fromEntries(
      ['react', 'react-dom', '@radix-ui/themes', '@radix-ui/react-icons'].map((name) => [
        name,
        join(sourceRoot, 'node_modules', name),
      ]),
    ),
  },
  bundle: true,
  write: false,
  outfile: 'timeline-fixture.js',
  platform: 'browser',
  format: 'iife',
  loader: { '.svg': 'text', '.woff': 'dataurl', '.woff2': 'dataurl', '.ttf': 'dataurl' },
  define: {
    'process.env.NODE_ENV': '"development"',
    'import.meta.env.DEV': 'false',
    'import.meta.env.PROD': 'true',
  },
});
const viewport = '.message-scroll [data-radix-scroll-area-viewport]';
const anchor = (id) => `[data-timeline-anchor-id="${id}"]`;
let browser;
before(async () => {
  browser = await chromium.launch(config.use.launchOptions);
});
after(async () => {
  await browser?.close();
});

async function frames(page, count = 3) {
  await page.evaluate(async (n) => {
    for (let i = 0; i < n; i++) await new Promise(requestAnimationFrame);
  }, count);
}
async function open(t) {
  const page = await browser.newPage({
    viewport: { width: 1050, height: 770 },
    reducedMotion: 'reduce',
  });
  const errors = [];
  page.on('pageerror', (err) => {
    errors.push(err.message);
    console.error(err.message);
  });
  t.after(async () => {
    await page.close();
    assert.deepEqual(errors, []);
  });
  await page.route('http://timeline.test/', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><html><head></head><body><div id="root"></div></body></html>',
    }),
  );
  await page.goto('http://timeline.test/');
  await page.addStyleTag({
    content: bundle.outputFiles.find((file) => file.path.endsWith('.css')).text,
  });
  await page.addScriptTag({
    content: bundle.outputFiles.find((file) => file.path.endsWith('.js')).text,
  });
  await page.locator(anchor('item-47')).waitFor({ timeout: 4000 });
  await frames(page);
  return page;
}
async function bottomGap(page) {
  return page.locator(viewport).evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop);
}
async function measureAnchor(page) {
  return page.locator(viewport).evaluate((el) => {
    const box = el.getBoundingClientRect();
    const paragraph = [...el.querySelectorAll('.markdown-content p')].find((node) => {
      const rect = node.getBoundingClientRect();
      return rect.height > 0 && rect.top >= box.top && rect.top < box.bottom;
    });
    if (!paragraph) throw new Error('No readable paragraph in viewport');
    const origin = paragraph.getBoundingClientRect().top - box.top;
    const samples = [];
    // A timer may run after the next React commit but before that commit's layout
    // and scroll correction. Sample the post-layout stage on each rendering frame.
    const probe = document.createElement('div');
    probe.style.cssText =
      'position:fixed;top:-10px;left:-10px;width:1px;height:1px;visibility:hidden;contain:strict';
    document.body.append(probe);
    const observer = new ResizeObserver(() => {
      samples.push(
        paragraph.isConnected
          ? paragraph.getBoundingClientRect().top - el.getBoundingClientRect().top - origin
          : Infinity,
      );
    });
    observer.observe(probe);
    let frame;
    const tick = () => {
      probe.style.width = probe.style.width === '1px' ? '2px' : '1px';
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    window.finishReadingSamples = () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      probe.remove();
      return {
        samples,
        mounted: paragraph.isConnected,
        offset: paragraph.getBoundingClientRect().top - el.getBoundingClientRect().top,
      };
    };
    return origin;
  });
}
async function assertStable(page, offset) {
  const {
    samples,
    mounted,
    offset: final,
  } = await page.evaluate(() => window.finishReadingSamples());
  assert.ok(mounted, 'Visible paragraph was remounted');
  assert.ok(samples.length > 0, 'Observed at least one rendered layout');
  const delta = Math.max(Math.abs(final - offset), ...samples.map(Math.abs));
  assert.ok(delta <= 2, `reading paragraph moved ${delta}px (final drift ${final - offset}px; samples ${samples})`);
}

test('stream replay keeps the tail pinned and preserves the final Markdown', async (t) => {
  const page = await open(t);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const layoutMs = async () =>
    (await cdp.send('Performance.getMetrics')).metrics.find(({ name }) => name === 'LayoutDuration')
      .value * 1000;
  const initialLayout = await layoutMs();
  const metrics = await page.evaluate(async (selector) => {
    const el = document.querySelector(selector);
    const stats = { ...window.transcript.stats };
    const gaps = [],
      intervals = [];
    const nextFrame = () => new Promise(requestAnimationFrame);
    let previous = await nextFrame();
    function recordFrame(now) {
      intervals.push(now - previous);
      previous = now;
    }
    async function measure() {
      recordFrame(await nextFrame());
      recordFrame(await nextFrame());
      gaps.push(el.scrollHeight - el.clientHeight - el.scrollTop);
    }
    const qa = window.transcript;
    qa.event('thought_start', {});
    qa.event('thought_delta', { delta: 'Inspect current state' });
    await measure();
    qa.event('thought', { thought: 'Inspect current state and verify the output.' });
    qa.event('act_delta', {
      tool_name: 'read',
      accumulated_arguments: '{"path":',
      tool_call_id: 'call',
    });
    await measure();
    qa.event('act', { tool_name: 'read', tool_input: { path: 'test.ts' }, tool_call_id: 'call' });
    qa.event('observe', { tool_name: 'read', observation: { ok: true }, tool_call_id: 'call' });
    await measure();
    qa.event('text_start', {});
    qa.event('text_delta', { delta: 'Response' });
    let text = 'Response';
    for (let i = 0; i < 12; i++) {
      const chunk = '\n\nParagraph ' + i + ' ' + 'Abc '.repeat(35) + 'end.';
      text += chunk;
      qa.event('text_delta', { delta: chunk });
      await measure();
    }
    const code = 'const result = 2;';
    const fence = '\n\n```js\n' + code;
    qa.event('text_delta', { delta: fence });
    await measure();
    const draft = el.querySelector('[data-timeline-anchor-id="streaming-assistant-replay"]');
    if (!draft) throw new Error('Expected a rendered streaming draft');
    qa.event('text_end', { full_text: text + fence + '\n```' });
    qa.event('assistant_message', { content: text + fence + '\n```' });
    await measure();
    if (!draft.isConnected) throw new Error('Finalization remounted the draft message');
    return {
      maxGap: Math.max(...gaps.map(Math.abs)),
      longFrames: intervals.filter((ms) => ms > 50).length,
      commits: qa.stats.commits - stats.commits,
      renderMs: qa.stats.renderMs - stats.renderMs,
      text,
      code,
    };
  }, viewport);
  const { text, code, ...stats } = metrics;
  console.log(
    'Chromium replay',
    JSON.stringify({ ...stats, layoutMs: (await layoutMs()) - initialLayout }),
  );
  assert.ok(stats.maxGap <= 2, `follow gap ${stats.maxGap}px`);
  const final = page.locator(anchor('streaming-assistant-replay'));
  assert.deepEqual(
    await final.locator('.markdown-content p').allTextContents(),
    text.split('\n\n'),
  );
  assert.equal((await final.locator('pre code').textContent()).trimEnd(), code);
});

test('reading survives pagination overlapping a tail update, then returns to latest', async (t) => {
  const page = await open(t);
  await page.evaluate(() => window.transcript.reset(48, true));
  const scroll = page.locator(viewport);
  await scroll.hover();
  await page.mouse.wheel(0, -20000);
  await page.waitForFunction(() => window.transcript.loadingEarlier);
  await page.mouse.wheel(0, 350);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate(() => {
    window.transcript.finishPage();
    window.transcript.append('assistant_message', {
      role: 'assistant',
      content: 'Concurrent append',
    });
  });
  await frames(page);
  await assertStable(page, offset);
  await page.locator('.session-jump-latest').click();
  await frames(page);
  assert.ok(Math.abs(await bottomGap(page)) <= 2);
});

test('wheel inside expanded reasoning stays local while the transcript follows', async (t) => {
  const page = await open(t);
  const text = Array.from({ length: 80 }, (_, i) => '  Reasoning line ' + i).join('\n') + '\n';
  await page.evaluate(
    (content) => window.transcript.append('thought', { content, metadata: { streaming: true } }),
    text,
  );
  const thought = page.locator('.thought-timeline-toggle').last();
  if ((await thought.getAttribute('aria-expanded')) !== 'true') await thought.click();
  const region = page.locator('.thought-timeline-content').last();
  await frames(page);
  assert.equal(await region.textContent(), text, 'the expanded trace retains its exact whitespace');
  await region.hover();
  await page.mouse.wheel(0, -90);
  await frames(page);
  const innerTop = await region.evaluate((el) => el.scrollTop);
  assert.ok(await region.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop > 20));
  await page.evaluate(
    (content) => window.transcript.edit('item-48', { content: content + '\nNext line' }),
    text,
  );
  await frames(page);
  assert.equal(await region.evaluate((el) => el.scrollTop), innerTop);
  assert.equal(await page.locator('.session-jump-latest').count(), 0);
  const innerHeight = await region.evaluate((el) => el.clientHeight);
  await page.evaluate(() => window.transcript.edit('item-48', { metadata: { streaming: false } }));
  await frames(page);
  assert.equal(await region.evaluate((el) => el.clientHeight), innerHeight);
  assert.equal(await region.evaluate((el) => el.scrollTop), innerTop);
});

test('search navigation remains detached during updates and session replacement follows the new tail', async (t) => {
  const page = await open(t);
  await page.keyboard.press('Control+f');
  await page.getByRole('searchbox').fill('Reference paragraph 7.');
  await page.locator('.chat-search-highlight').waitFor();
  await frames(page);
  await page.locator(viewport).hover();
  await page.mouse.wheel(0, -140);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate(() =>
    window.transcript.append('assistant_message', {
      role: 'assistant',
      content: 'Searching during a response',
    }),
  );
  await frames(page);
  await assertStable(page, offset);
  await page.evaluate(() => window.transcript.reset(56, false, 'next-thread'));
  await frames(page, 5);
  assert.ok(Math.abs(await bottomGap(page)) <= 2);
  assert.equal(await page.getByRole('searchbox').count(), 0);
});

test('render window threshold preserves the mounted paragraph under the reader', async (t) => {
  const page = await open(t);
  await page.evaluate(() => window.transcript.reset(150, false, 'long'));
  await frames(page);
  await page.locator(viewport).hover();
  await page.mouse.wheel(0, -100000);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate(() =>
    window.transcript.append('user_message', { role: 'user', content: 'A new turn' }),
  );
  await frames(page);
  await assertStable(page, offset);
});

test('late content above the viewport preserves the reading paragraph inside a long response', async (t) => {
  const page = await open(t);
  const paragraphs = Array.from({ length: 90 }, (_, i) => 'Unchanged paragraph ' + i + '.');
  await page.evaluate(
    (parts) => window.transcript.edit('item-47', { content: parts.join('\n\n') }),
    paragraphs,
  );
  await frames(page);
  await page.locator(viewport).hover();
  await page.mouse.wheel(0, -450);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate((parts) => {
    parts[0] += ' Additional words'.repeat(340);
    window.transcript.edit('item-47', { content: parts.join('\n\n') });
  }, paragraphs);
  await frames(page);
  await assertStable(page, offset);
  // Late media may acquire its height without a new React commit.
  const beforeResize = await measureAnchor(page);
  await page
    .locator(anchor('item-47'))
    .locator('.markdown-content p')
    .first()
    .evaluate(
      (el) =>
        new Promise((resolve) =>
          requestAnimationFrame(() => {
            el.style.paddingTop = '180px';
            resolve();
          }),
        ),
    );
  await frames(page);
  await assertStable(page, beforeResize);
});

test('tool completion above the reader leaves their paragraph and its DOM identity stable', async (t) => {
  const page = await open(t);
  await page.evaluate(() => {
    window.transcript.append('act', {
      toolName: 'read',
      toolInput: { path: 'file.ts' },
      payload: { tool_call_id: 'late-call' },
    });
    for (let n = 0; n < 18; n++) {
      window.transcript.append(n % 2 ? 'assistant_message' : 'user_message', {
        role: n % 2 ? 'assistant' : 'user',
        content: 'Messages while a tool is pending, number ' + n,
      });
    }
  });
  await frames(page);
  await page.locator(viewport).hover();
  await page.mouse.wheel(0, -300);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate(() =>
    window.transcript.append('observe', {
      toolName: 'read',
      toolOutput: { text: 'Late result' },
      payload: { tool_call_id: 'late-call' },
    }),
  );
  await frames(page);
  await assertStable(page, offset);
});

test('persisted history promotes the draft without replacing its mounted paragraph', async (t) => {
  const page = await open(t);
  await page.evaluate(() => window.transcript.event('text_delta', { delta: 'Draft paragraph' }));
  const draft = page.locator(anchor('streaming-assistant-replay')).locator('.markdown-content p');
  await draft.waitFor();
  const retained = await draft.elementHandle();
  await page.evaluate(() => window.transcript.promoteDraft());
  const canonical = page.locator(anchor('persisted-response')).locator('.markdown-content p');
  await canonical.waitFor();
  assert.equal(await canonical.evaluate((node, previous) => node === previous, retained), true);
  assert.equal(await canonical.textContent(), 'Final paragraph');
});

test('PageUp detaches the reader and End resumes following incoming content', async (t) => {
  const page = await open(t);
  const scroll = page.locator(viewport);
  await scroll.focus();
  await page.keyboard.press('PageUp');
  await page.waitForFunction((selector) => {
    const el = document.querySelector(selector);
    return el.scrollHeight - el.clientHeight - el.scrollTop >= el.clientHeight / 2;
  }, viewport);
  // Wait for the browser's native keyboard scroll animation to settle.
  await scroll.evaluate(
    (el) =>
      new Promise((resolve) => {
        let previous = el.scrollTop,
          stable = 0;
        function sample() {
          stable = previous === el.scrollTop ? stable + 1 : 0;
          previous = el.scrollTop;
          if (stable >= 3) resolve();
          else requestAnimationFrame(sample);
        }
        requestAnimationFrame(sample);
      }),
  );
  const offset = await measureAnchor(page);
  await page.evaluate(() =>
    window.transcript.event('text_delta', { delta: 'Content during keyboard navigation' }),
  );
  await frames(page);
  await assertStable(page, offset);
  await page.keyboard.press('End');
  await page.waitForFunction((selector) => {
    const el = document.querySelector(selector);
    return el.scrollHeight - el.clientHeight - el.scrollTop <= 2;
  }, viewport);
  await page.evaluate(() =>
    window.transcript.event('text_delta', { delta: '\n\nFollowing again. '.repeat(20) }),
  );
  await frames(page);
  assert.ok(Math.abs(await bottomGap(page)) <= 2);
});

test('an incidental scroll during execution cannot resume follow while reading', async (t) => {
  const page = await open(t);
  const scroll = page.locator(viewport);
  await scroll.hover();
  await page.mouse.wheel(0, -450);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  // Chromium may reveal a focused descendant while cards finish rendering.
  // Only the reader's navigation or the explicit jump button resumes following.
  await scroll.evaluate((el) => {
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  });
  await frames(page, 30);
  await assertStable(page, offset);
  assert.equal(await page.locator('.session-jump-latest').count(), 1);
});

test('refreshing conversation metadata preserves a detached viewport in the same session', async (t) => {
  const page = await open(t);
  await page.locator(viewport).hover();
  await page.mouse.wheel(0, -450);
  await frames(page, 5);
  const offset = await measureAnchor(page);
  await page.evaluate(() => window.transcript.refreshConversationCatalog());
  await frames(page, 5);
  await assertStable(page, offset);
  assert.equal(await page.locator('.session-jump-latest').count(), 1);
});

test('keyboard focus can reveal an offscreen message action while reading', async (t) => {
  const page = await open(t);
  const scroll = page.locator(viewport);
  await scroll.hover();
  await page.mouse.wheel(0, -450);
  await frames(page, 5);
  const actions = page.locator(anchor('item-1')).locator('.session-message-actions button');
  await actions.first().evaluate((button) => button.focus({ preventScroll: true }));
  await page.keyboard.press('Tab');
  await frames(page, 5);
  const focusedIsVisible = await scroll.evaluate((el) => {
    const focused = document.activeElement;
    if (!focused?.closest('.session-message-actions')) return false;
    const target = focused.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    return target.top >= box.top && target.bottom <= box.bottom;
  });
  assert.ok(focusedIsVisible, 'Tab reveals the newly focused control');
});
