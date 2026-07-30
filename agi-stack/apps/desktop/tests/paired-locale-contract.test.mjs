import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  compareObservedLocale,
  requireLocaleRenderingMatch,
} from '../contracts/desktop-web-parity/paired-locale-contract.mjs';
import { createPairedEvidenceMetadata } from '../browser-qa/paired-production-evidence.mjs';

const MATCHED_STATE = Object.freeze({
  locale: 'en',
  theme: 'light',
  viewport: Object.freeze({ width: 1440, height: 1024 }),
  device_scale_factor: 1,
  authentication_state: 'signed_out',
  account_state: 'none',
  permission_state: 'public_entry_only',
  data_state: 'empty',
  interaction_state: 'focused:email_entry',
});

function observedState(locale) {
  return {
    locale,
    theme: 'light',
    browser_color_scheme: 'light',
    viewport: { width: 1440, height: 1024 },
    device_scale_factor: 1,
    authentication_state: 'signed_out',
    account_state: 'none',
    permission_state: 'public_entry_only',
    data_state: 'empty',
    interaction_state: 'focused:email_entry',
    focus: {
      target_id: 'email_entry',
      tag_name: 'input',
      input_type: 'email',
    },
    locale_rendering: {
      date_sample: 'Thursday, January 2, 2020',
      number_sample: '1,234,567.89',
    },
  };
}

test('base-language declarations preserve raw BCP47 tags while comparing the primary language', () => {
  assert.deepEqual(compareObservedLocale('en-US', 'en'), {
    raw_locale: 'en-US',
    comparison_locale: 'en',
  });
  assert.deepEqual(compareObservedLocale('en', 'en'), {
    raw_locale: 'en',
    comparison_locale: 'en',
  });
});

test('region-specific declarations require an exact canonical BCP47 tag', () => {
  assert.deepEqual(compareObservedLocale('zh-cn', 'zh-CN'), {
    raw_locale: 'zh-cn',
    comparison_locale: 'zh-CN',
  });
  assert.throws(
    () => compareObservedLocale('en', 'en-US'),
    /does not satisfy declared locale en-US/u,
  );
  assert.throws(
    () => compareObservedLocale('zh-TW', 'zh-CN'),
    /does not satisfy declared locale zh-CN/u,
  );
  assert.throws(
    () => compareObservedLocale('zh', 'zh-CN'),
    /does not satisfy declared locale zh-CN/u,
  );
});

test('locale comparison rejects missing and invalid BCP47 tags', () => {
  assert.throws(
    () => compareObservedLocale('', 'en'),
    /observed locale must be a non-empty BCP47 tag/u,
  );
  assert.throws(
    () => compareObservedLocale('not_a_locale', 'en'),
    /observed locale is not a valid BCP47 tag/u,
  );
  assert.throws(
    () => compareObservedLocale('en', 'not_a_locale'),
    /declared locale is not a valid BCP47 tag/u,
  );
});

test('locale-sensitive rendering samples must match across paired runtimes', () => {
  const sample = {
    date_sample: 'Thursday, January 2, 2020',
    number_sample: '1,234,567.89',
  };
  assert.deepEqual(requireLocaleRenderingMatch(sample, sample), sample);
  assert.throws(
    () =>
      requireLocaleRenderingMatch(sample, {
        ...sample,
        number_sample: '1.234.567,89',
      }),
    /locale-sensitive rendering differs/u,
  );
});

test('paired metadata retains raw locales and their declared comparison locale', () => {
  const screenshot = Buffer.from('screenshot');
  const metadata = createPairedEvidenceMetadata({
    scenarioId: 'signed-out-entry',
    expectedObservableResult:
      'Both production entries render without runtime failure.',
    sourceRevision: '0'.repeat(40),
    worktreeState: 'clean',
    matchedState: MATCHED_STATE,
    finalObservedState: {
      web: observedState('en-US'),
      desktop: observedState('en'),
    },
    rendererBuildReceipt: Buffer.from('receipt'),
    webScreenshot: screenshot,
    desktopScreenshot: screenshot,
    diffScreenshot: screenshot,
    webText: 'Welcome Back Email',
    desktopText: 'Sign in to MemStack Work email',
    pixelObservation: {
      differing_pixels: 0,
      total_pixels: 1,
      max_channel_delta: 0,
    },
  });

  assert.equal(metadata.final_observed_state.web.locale, 'en-US');
  assert.equal(metadata.final_observed_state.desktop.locale, 'en');
  assert.equal(metadata.final_observed_state.web.comparison_locale, 'en');
  assert.equal(metadata.final_observed_state.desktop.comparison_locale, 'en');
  assert.deepEqual(
    metadata.final_observed_state.web.locale_rendering,
    metadata.final_observed_state.desktop.locale_rendering,
  );
});
