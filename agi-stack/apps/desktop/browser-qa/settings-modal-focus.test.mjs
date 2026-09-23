import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createRequire } from 'node:module';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const bundle = await esbuild.build({
  stdin: {
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'tsx',
    contents: `
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {useModalDialog} from './src/features/settings/useModalDialog';
window.modalCloseCounts = {outer: 0, nested: 0};
function Inner({close}) {
  const ref = useModalDialog({nested:true,onClose:close});
  return <section ref={ref} role="dialog" aria-modal="true" aria-label="Nested" tabIndex={-1}>
    <button id="inner-first">Nested first</button><button disabled>Disabled</button>
    <button id="inner-last" onClick={close}>Close nested</button>
  </section>;
}
function Settings({active,close}) {
  const [nested,setNested] = useState(false);
  const ref = useModalDialog({active,returnFocusSelector:'.desktop-design-profile',onClose:close});
  if (!active) return null;
  const closeInner=()=>{window.modalCloseCounts.nested++;setNested(false)};
  return <section ref={ref} role="dialog" aria-modal="true" aria-label="Settings" tabIndex={-1}>
    <button id="settings-first" onClick={()=>setNested(true)}>Open nested</button>
    <input aria-label="Setting value"/><button id="settings-last" onClick={close}>Close settings</button>
    {nested && <Inner close={closeInner}/>}
  </section>;
}
function Fixture({retain}) {
  const [open,setOpen]=useState(false),[generation,setGeneration]=useState(0);
  const close=()=>{window.modalCloseCounts.outer++;setOpen(false);setGeneration(n=>n+1)};
  return <><button className="desktop-design-profile" key={generation} data-generation={generation}
    onClick={event=>{event.currentTarget.focus();setOpen(true)}}>Profile</button>
    <button id="outside-after">Outside after</button>
    {(retain || open) && <Settings active={open} close={close}/>}</>;
}
window.renderFixture=retain=>createRoot(document.getElementById('root')).render(<Fixture retain={retain}/>);
`,
  },
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
});
let browser;
before(async () => {
  browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
});
after(async () => {
  await browser?.close();
});

async function fixture(retain) {
  const page = await browser.newPage();
  await page.setContent('<div id="root"></div>');
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  await page.evaluate((retain) => window.renderFixture(retain), retain);
  await page.locator('.desktop-design-profile').click();
  await focused(page, 'settings-first');
  return page;
}
async function focused(page, id) {
  await page.waitForFunction((id) => document.activeElement?.id === id, id);
}
async function restored(page) {
  await page.waitForFunction(() =>
    document.activeElement?.matches('.desktop-design-profile[data-generation="1"]'),
  );
  assert.equal(await page.getByRole('dialog').count(), 0);
  await page.keyboard.press('Tab');
  await focused(page, 'outside-after');
  const closed = await page.evaluate(() => window.modalCloseCounts.outer);
  await page.keyboard.press('Escape');
  assert.equal(
    await page.evaluate(() => window.modalCloseCounts.outer),
    closed,
    'removed modal must not handle Escape',
  );
}
for (const retain of [false, true]) {
  test(`closing settings restores replaced opener after commit (${retain ? 'inactive mounted hook' : 'unmounted hook'})`, async () => {
    const page = await fixture(retain);
    const oldOpener = await page.locator('.desktop-design-profile').elementHandle();
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    await restored(page);
    assert.equal(
      await oldOpener.evaluate((node) => node.isConnected),
      false,
      'fixture must replace opener',
    );
    await page.close();
  });
}
test('nested Escape closes only nested dialog, returns focus, and both dialogs wrap keyboard focus', async () => {
  const page = await fixture(false);
  await page.keyboard.press('Shift+Tab');
  await focused(page, 'settings-last');
  await page.keyboard.press('Tab');
  await focused(page, 'settings-first');
  await page.getByRole('button', { name: 'Open nested' }).click();
  await focused(page, 'inner-first');
  await page.keyboard.press('Shift+Tab');
  await focused(page, 'inner-last');
  await page.keyboard.press('Tab');
  await focused(page, 'inner-first');
  await page.keyboard.press('Escape');
  await focused(page, 'settings-first');
  assert.equal(await page.getByRole('dialog', { name: 'Settings', exact: true }).count(), 1);
  assert.deepEqual(await page.evaluate(() => window.modalCloseCounts), { outer: 0, nested: 1 });
  await page.keyboard.press('Shift+Tab');
  await focused(page, 'settings-last');
  await page.keyboard.press('Escape');
  await restored(page);
  assert.deepEqual(await page.evaluate(() => window.modalCloseCounts), { outer: 1, nested: 1 });
  await page.close();
});
