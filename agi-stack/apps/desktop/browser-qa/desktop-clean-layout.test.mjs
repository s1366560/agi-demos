import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';

import qaConfig from './playwright.config.mjs';

// Isolated geometry fixtures reproduce the production shell DOM and load its real CSS.
// They exercise layout only; native Electron and real component behavior have separate tests.
const styles = [
  'styles/tokens.css',
  'styles/chrome.css',
  'styles/base.css',
  'features/navigation/DesktopSidebar.css',
  'features/chrome/DesktopTitlebar.css',
  'features/chrome/WorkbenchTabBar.css',
  'features/chat/ChatTimeline.css',
  'features/chat/ChatPanel.css',
  'features/session/SessionWorkspace.css',
  'features/task/NewThreadComposer.css',
  'features/settings/SettingsWindow.css',
  'features/settings/SettingsCorePages.css',
]
  .map((path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'))
  .join('\n');
const evidenceDirectory = mkdtempSync(join(tmpdir(), 'codex-desktop-clean-layout-'));
const measurements = [];
let browser;

before(async () => {
  browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
});
after(async () => {
  await browser?.close();
  writeFileSync(
    join(evidenceDirectory, 'measurements.json'),
    JSON.stringify(measurements, null, 2),
  );
  console.log(`Layout evidence: ${evidenceDirectory}`);
});

function documentMarkup(theme, content) {
  return `<!doctype html><html data-theme="${theme}"><head><style>${styles}</style></head>
    <body><div id="root">${content}</div></body></html>`;
}

function shellFixture(withTabs) {
  return `<div class="app-shell desktop-window">
    <header class="desktop-titlebar"><span class="desktop-titlebar-title">Release review</span></header>
    <section class="desktop-body">
      <aside class="desktop-design-sidebar"><strong>MemStack</strong><button>New task</button>
        <nav>Search</nav><header>Desktop Client</header><section>Release review</section>
        <footer>Functions · Account</footer></aside>
      <main class="workbench">
        ${withTabs ? '<div class="workbench-tab-bar"><button>Release review</button><button>Planning</button></div>' : ''}
        <div class="workbench-content">
          <section class="session-workspace-shell">
            <header class="session-workspace-header"><div class="session-workspace-actions">
              <details class="session-workspace-more"><summary>More session actions</summary></details>
            </div></header>
            <div class="session-workspace-body"><section class="session-workspace-thread">
              <section class="pane-stage single-stage">
                <section class="pane-shell chat-shell session-chat-narrative">
                  <div class="message-scroll"><div class="message-stack">
                    ${Array.from({ length: 50 }, (_, i) => `<p>Message ${i}: Review the release and report progress.</p>`).join('')}
                  </div></div>
                  <form class="composer chat-composer"><textarea class="chat-composer-input" aria-label="Message"></textarea>
                    <div class="chat-composer-footer"><button>Attach</button><button>Model</button><button>Send</button></div></form>
                </section></section>
            </section></div>
          </section>
        </div>
      </main>
    </section>
  </div>`;
}

const newThreadFixture = `<section class="workbench-layout"><section class="pane-stage single-stage">
  <main class="new-thread-view"><div class="new-thread-content">
    <header class="new-thread-heading"><h1>What would you like to work on?</h1></header>
    <section class="new-thread-composer"><textarea aria-label="New message"></textarea>
      <div class="new-thread-composer-toolbar"><button>+</button><div class="composer-pickers">
        <button class="picker-chip">Work</button><button class="picker-chip">Desktop Client</button>
        <button class="picker-chip">Model</button><button class="picker-chip">Full access</button>
      </div><button class="send-button">↑</button></div></section>
  </div></main></section></section>`;

for (const viewport of [
  { width: 1100, height: 800 },
  { width: 1440, height: 1024 },
]) {
  for (const theme of ['light', 'dark']) {
    for (const withTabs of [false, true]) {
      const name = `${viewport.width}x${viewport.height}-${theme}-${withTabs ? 'tabs' : 'no-tabs'}`;
      test(`shell keeps content and composer full-height without horizontal overflow: ${name}`, async () => {
        const page = await browser.newPage({
          viewport,
          colorScheme: theme,
          reducedMotion: 'reduce',
        });
        try {
          await page.setContent(documentMarkup(theme, shellFixture(withTabs)));
          const geometry = await page.evaluate(() => {
            const rect = (selector) => {
              const { x, y, width, height, bottom, right } = document
                .querySelector(selector)
                .getBoundingClientRect();
              return { x, y, width, height, bottom, right };
            };
            return {
              shell: rect('.app-shell'),
              workbench: rect('.workbench'),
              content: rect('.workbench-content'),
              session: rect('.session-workspace-shell'),
              timeline: rect('.message-scroll'),
              composer: rect('.chat-composer'),
              input: rect('textarea'),
              overflow: document.documentElement.scrollWidth - innerWidth,
              timelineScrolls:
                document.querySelector('.message-scroll').scrollHeight >
                document.querySelector('.message-scroll').clientHeight,
            };
          });
          measurements.push({ name, geometry });
          assert.equal(geometry.overflow, 0);
          assert.ok(
            Math.abs(geometry.content.y - (withTabs ? 68 : 36)) <= 1,
            'content is in row 2',
          );
          assert.ok(
            Math.abs(geometry.content.bottom - viewport.height) <= 1,
            'content fills workbench',
          );
          assert.ok(
            geometry.content.height >= viewport.height - 70,
            'hidden tabs cannot collapse content',
          );
          assert.ok(Math.abs(geometry.session.height - geometry.content.height) <= 1);
          assert.ok(geometry.timeline.height > 300, 'transcript retains useful height');
          assert.ok(geometry.timelineScrolls, 'long history scrolls independently');
          assert.ok(geometry.composer.height >= 80 && geometry.input.height >= 50);
          assert.ok(
            Math.abs(geometry.composer.bottom - viewport.height) <= 2,
            'composer stays at bottom',
          );
          assert.ok(geometry.composer.right <= viewport.width + 1);
          await page.screenshot({ path: join(evidenceDirectory, `${name}-session.png`) });
          await page.locator('.workbench-content').evaluate((element, markup) => {
            element.innerHTML = markup;
          }, newThreadFixture);
          const fresh = await page.locator('.new-thread-composer').boundingBox();
          assert.ok(fresh && fresh.width > 500 && fresh.width <= 800);
          assert.ok(
            fresh.y > 100 && fresh.y + fresh.height < viewport.height,
            'new task composer remains visible',
          );
          await page.screenshot({ path: join(evidenceDirectory, `${name}-new-task.png`) });
        } finally {
          await page.close();
        }
      });
    }
    test(`settings theme copy uses full grid width and sidebar text has contrast: ${viewport.width}-${theme}`, async () => {
      const page = await browser.newPage({ viewport, colorScheme: theme });
      try {
        await page.setContent(
          documentMarkup(
            theme,
            `<div class="settings-window-backdrop">
          <section class="settings-window-dialog"><header class="settings-window-titlebar">Settings</header>
            <div class="settings-window-body"><aside class="settings-window-rail">
              <div class="settings-rail-group"><span>Preferences</span>
                <button><i></i>General</button><button class="active"><i></i>Appearance</button></div>
            </aside><main class="settings-window-content"><section class="settings-panel">
              <div class="settings-language-options settings-theme-options">
                ${['System', 'Light', 'Dark'].map((label) => `<button><div><strong>${label}</strong><small>Choose how the desktop application appears.</small></div><svg width="18" height="18"></svg></button>`).join('')}
              </div></section></main></div></section></div>`,
          ),
        );
        const result = await page.evaluate(() => {
          const cards = [...document.querySelectorAll('.settings-theme-options button')].map(
            (card) => ({
              card: card.getBoundingClientRect().width,
              copy: card.querySelector('div').getBoundingClientRect().width,
              overflow: card.scrollWidth > card.clientWidth,
            }),
          );
          const buttons = [...document.querySelectorAll('.settings-rail-group button')].map(
            (button) => {
              const style = getComputedStyle(button);
              let background = style.backgroundColor;
              if (background === 'rgba(0, 0, 0, 0)')
                background = getComputedStyle(
                  document.querySelector('.settings-window-rail'),
                ).backgroundColor;
              return { foreground: style.color, background };
            },
          );
          return { cards, buttons, overflow: document.documentElement.scrollWidth - innerWidth };
        });
        for (const card of result.cards) {
          assert.ok(
            card.copy > 120 && card.copy / card.card > 0.65,
            'theme copy is not trapped in icon column',
          );
          assert.equal(card.overflow, false);
        }
        for (const button of result.buttons)
          assert.ok(contrast(button.foreground, button.background) >= 4.5, JSON.stringify(button));
        assert.equal(result.overflow, 0);
        measurements.push({ name: `settings-${viewport.width}-${theme}`, ...result });
        await page.screenshot({
          path: join(evidenceDirectory, `settings-${viewport.width}-${theme}.png`),
        });
      } finally {
        await page.close();
      }
    });
  }
}

function contrast(foreground, background) {
  const luminance = (color) => {
    const channels = color
      .match(/[\d.]+/g)
      .slice(0, 3)
      .map(Number)
      .map((channel) => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const a = luminance(foreground),
    b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
