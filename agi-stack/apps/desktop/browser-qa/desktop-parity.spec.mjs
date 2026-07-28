import { existsSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

import { isExpectedBrowserQaSecurityDiagnostic } from './diagnostics.mjs';
import { buildBrowserQaMatrix, browserQaManifest } from './matrix.mjs';

const LOCALE_STORAGE_KEY = 'agistack.desktop.locale';
const THEME_STORAGE_KEY = 'agistack.desktop.theme';
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const STATIC_ASSET_ROOTS = [
  resolve(REPOSITORY_ROOT, 'artifacts'),
  resolve(REPOSITORY_ROOT, 'design-prototype'),
];
const BARE_I18N_KEY =
  /\b(?:artifact|automation|common|hitl|login|myWork|navigation|search|session|settings|workspace)\.[A-Za-z][\w.-]*\b/u;

test.describe.configure({ mode: 'parallel' });

for (const variant of buildBrowserQaMatrix()) {
  test(variant.id, async ({ page }) => {
    const runtimeErrors = [];
    page.on('pageerror', (error) => {
      if (
        !isExpectedBrowserQaSecurityDiagnostic(
          variant.scenario.id,
          'page',
          error.message,
        )
      ) {
        runtimeErrors.push(`page: ${error.message}`);
      }
    });
    page.on('console', (message) => {
      if (
        message.type() === 'error' &&
        !isExpectedBrowserQaSecurityDiagnostic(
          variant.scenario.id,
          'console',
          message.text(),
        )
      ) {
        runtimeErrors.push(`console: ${message.text()}`);
      }
    });
    await page.route(/\/(?:artifacts|design-prototype)\//u, async (route) => {
      const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
      const candidate = resolve(REPOSITORY_ROOT, `.${pathname}`);
      const allowed = STATIC_ASSET_ROOTS.some(
        (root) => candidate === root || candidate.startsWith(`${root}${sep}`),
      );
      if (!allowed || !existsSync(candidate)) {
        await route.abort('blockedbyclient');
        return;
      }
      await route.fulfill({ path: candidate });
    });

    await page.emulateMedia({ colorScheme: variant.theme });
    await page.addInitScript(
      ({
        localeStorageKey,
        localeStorageValue,
        documentLanguage,
        themeStorageKey,
        theme,
      }) => {
        const originalSetItem = Storage.prototype.setItem;
        originalSetItem.call(window.localStorage, localeStorageKey, localeStorageValue);
        originalSetItem.call(window.localStorage, themeStorageKey, theme);

        Storage.prototype.setItem = function setQaLockedPreference(key, value) {
          if (this === window.localStorage && key === localeStorageKey) {
            return originalSetItem.call(this, key, localeStorageValue);
          }
          if (this === window.localStorage && key === themeStorageKey) {
            return originalSetItem.call(this, key, theme);
          }
          return originalSetItem.call(this, key, value);
        };

        const applyQaPreferences = () => {
          if (document.documentElement.lang !== documentLanguage) {
            document.documentElement.lang = documentLanguage;
          }
          if (document.documentElement.dataset.theme !== theme) {
            document.documentElement.dataset.theme = theme;
          }
        };
        document.addEventListener('DOMContentLoaded', applyQaPreferences, { once: true });
      },
      {
        localeStorageKey: LOCALE_STORAGE_KEY,
        localeStorageValue: variant.locale.storageValue,
        documentLanguage: variant.locale.documentLanguage,
        themeStorageKey: THEME_STORAGE_KEY,
        theme: variant.theme,
      },
    );

    await page.setViewportSize({
      width: variant.viewport.width,
      height: variant.viewport.height,
    });
    const parameters = new URLSearchParams({
      qaLocale: variant.locale.id,
      qaTheme: variant.theme,
    });
    if (variant.scenario.id === 'mission-control-compare') {
      parameters.set('layout', 'vertical');
      parameters.set('width', String(variant.viewport.width));
    }
    const response = await page.goto(`${variant.scenario.path}?${parameters}`, {
      waitUntil: 'domcontentloaded',
    });
    expect(response?.status(), 'QA fixture must load without an HTTP error').toBeLessThan(400);
    await page.waitForFunction(() => {
      const root = document.querySelector('#root');
      const portalContent = document.querySelector(
        'body > :not(#root):not(script):not(style):not(link)',
      );
      return Boolean(root?.firstElementChild || portalContent);
    });
    await page.evaluate(
      ({ documentLanguage, theme }) => {
        document.documentElement.lang = documentLanguage;
        document.documentElement.dataset.theme = theme;
        document.documentElement.style.colorScheme = theme;
        for (const radixTheme of document.querySelectorAll('.radix-themes')) {
          radixTheme.classList.remove('light', 'dark');
          radixTheme.classList.add(theme);
          radixTheme.style.colorScheme = theme;
        }
      },
      {
        documentLanguage: variant.locale.documentLanguage,
        theme: variant.theme,
      },
    );

    await expect(page.locator('.app-fatal-error')).toHaveCount(0);
    await expect(page.locator('html')).toHaveAttribute(
      'lang',
      variant.locale.documentLanguage,
    );
    await expect(page.locator('html')).toHaveAttribute('data-theme', variant.theme);

    const structuralAudit = await page.evaluate((bareKeySource) => {
      const bareKeyPattern = new RegExp(bareKeySource, 'u');
      const root = document.documentElement;
      const body = document.body;
      const horizontalOverflow = Math.max(root.scrollWidth, body.scrollWidth) -
        Math.max(root.clientWidth, body.clientWidth);

      const bareKeys = [];
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const parent = node.parentElement;
        if (!parent || parent.closest('code, pre, script, style, textarea')) continue;
        const match = node.textContent?.match(bareKeyPattern);
        if (match) bareKeys.push(match[0]);
      }

      const positiveTabIndex = [...document.querySelectorAll('[tabindex]')]
        .filter((element) => Number(element.getAttribute('tabindex')) > 0)
        .map((element) => element.outerHTML.slice(0, 180));

      const unnamedButtons = [...document.querySelectorAll('button')]
        .filter((button) => {
          const labelledBy = button
            .getAttribute('aria-labelledby')
            ?.split(/\s+/u)
            .map((id) => document.getElementById(id)?.textContent ?? '')
            .join(' ');
          const name = [
            button.getAttribute('aria-label'),
            button.getAttribute('title'),
            labelledBy,
            button.textContent,
            button.closest('label')?.textContent,
          ].find((candidate) => candidate?.trim()) ?? '';
          return !name.trim();
        })
        .map((button) => button.outerHTML.slice(0, 180));

      const unlabeledInputs = [
        ...document.querySelectorAll(
          'input:not([type="hidden"]):not([hidden]):not([aria-hidden="true"]), select:not([hidden]):not([aria-hidden="true"]), textarea:not([hidden]):not([aria-hidden="true"])',
        ),
      ]
        .filter((control) => {
          const id = control.getAttribute('id');
          return !(
            control.getAttribute('aria-label') ||
            control.getAttribute('aria-labelledby') ||
            control.getAttribute('placeholder') ||
            (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) ||
            control.closest('label')
          );
        })
        .map((control) => control.outerHTML.slice(0, 180));

      return {
        horizontalOverflow,
        bareKeys: [...new Set(bareKeys)].slice(0, 10),
        positiveTabIndex: positiveTabIndex.slice(0, 10),
        unnamedButtons: unnamedButtons.slice(0, 10),
        unlabeledInputs: unlabeledInputs.slice(0, 10),
        focusableCount: document.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ).length,
      };
    }, BARE_I18N_KEY.source);

    expect(structuralAudit.horizontalOverflow, 'page must not overflow horizontally').toBeLessThanOrEqual(1);
    expect(structuralAudit.bareKeys, 'visible untranslated i18n keys').toEqual([]);
    expect(structuralAudit.positiveTabIndex, 'positive tabindex breaks document order').toEqual([]);
    expect(structuralAudit.unnamedButtons, 'buttons need accessible names').toEqual([]);
    expect(structuralAudit.unlabeledInputs, 'form controls need accessible names').toEqual([]);

    if (structuralAudit.focusableCount > 0) {
      await page.keyboard.press('Tab');
      const firstFocus = await page.evaluate(() => ({
        tag: document.activeElement?.tagName ?? '',
        inDocument: Boolean(document.activeElement && document.contains(document.activeElement)),
      }));
      expect(firstFocus.inDocument).toBe(true);
      expect(firstFocus.tag).not.toBe('BODY');
    }

    const visiblePopup = page
      .locator(
        '[role="menu"]:visible, [role="dialog"]:visible, [role="alertdialog"]:visible, [role="listbox"]:visible',
      )
      .first();
    const openPopupTrigger = page
      .locator(
        '[aria-expanded="true"][aria-haspopup="menu"]:visible, [aria-expanded="true"][aria-haspopup="dialog"]:visible, [aria-expanded="true"][aria-haspopup="listbox"]:visible',
      )
      .first();
    if ((await visiblePopup.count()) > 0 && (await openPopupTrigger.count()) > 0) {
      const openPopupTriggerElement = await openPopupTrigger.elementHandle();
      expect(openPopupTriggerElement, 'open popup must retain its trigger element').not.toBeNull();
      await page.keyboard.press('Escape');
      await expect(visiblePopup).toBeHidden();
      await expect
        .poll(() =>
          openPopupTriggerElement?.evaluate((element) => document.activeElement === element),
        )
        .toBe(true);
    } else if ((await visiblePopup.count()) === 0) {
      const closedPopupTrigger = page
        .locator(
          '[aria-expanded="false"][aria-haspopup="menu"]:visible, [aria-expanded="false"][aria-haspopup="dialog"]:visible, [aria-expanded="false"][aria-haspopup="listbox"]:visible',
        )
        .first();
      if ((await closedPopupTrigger.count()) > 0) {
        await closedPopupTrigger.click();
        const openedPopup = page
          .locator(
            '[role="menu"]:visible, [role="dialog"]:visible, [role="alertdialog"]:visible, [role="listbox"]:visible',
          )
          .first();
        if ((await openedPopup.count()) > 0) {
          await page.keyboard.press('Escape');
          await expect(openedPopup).toBeHidden();
          await expect(closedPopupTrigger).toBeFocused();
        }
      }
    }

    expect(runtimeErrors, 'page and console errors').toEqual([]);
  });
}

test('matrix contract covers every top-level QA fixture', () => {
  const variants = buildBrowserQaMatrix();
  const dimensionCount =
    browserQaManifest.locales.length *
    browserQaManifest.viewports.length *
    browserQaManifest.themes.length;
  const scenarioCount = new Set(variants.map((variant) => variant.scenario.id)).size;
  expect(scenarioCount).toBeGreaterThanOrEqual(36);
  expect(variants).toHaveLength(scenarioCount * dimensionCount);
  expect(variants.length).toBeGreaterThanOrEqual(288);
});
