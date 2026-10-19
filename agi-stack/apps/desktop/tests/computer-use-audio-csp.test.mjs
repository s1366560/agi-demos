import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { chromium } from '@playwright/test';

const shell = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const policy = shell.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/u)?.[1];
assert.ok(policy, 'the real desktop shell must declare its CSP');
const origin = 'http://cua-audio-fixture.test/';
const remoteAudio = 'https://unapproved-media.test/recording.wav';

function wave() {
  const rate = 48000;
  const channels = 2;
  const bytes = Buffer.alloc(44 + rate * channels * 2);
  bytes.write('RIFF', 0);
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(channels, 22);
  bytes.writeUInt32LE(rate, 24);
  bytes.writeUInt32LE(rate * channels * 2, 28);
  bytes.writeUInt16LE(channels * 2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36);
  bytes.writeUInt32LE(bytes.length - 44, 40);
  for (let frame = 0; frame < rate; frame += 1) {
    const sample = Math.round(8192 * Math.sin((2 * Math.PI * 440 * frame) / rate));
    for (let channel = 0; channel < channels; channel += 1)
      bytes.writeInt16LE(sample, 44 + (frame * channels + channel) * 2);
  }
  return bytes;
}

async function withPage(run) {
  const browser = await chromium.launch({ headless: true });
  let remoteRequests = 0;
  try {
    const page = await browser.newPage();
    await page.route('**/*', async (route) => {
      if (route.request().url() === origin) {
        await route.fulfill({
          contentType: 'text/html',
          body: `<html><head><meta http-equiv="Content-Security-Policy" content="${policy}"></head><body></body></html>`,
        });
      } else if (route.request().url() === remoteAudio) {
        remoteRequests += 1;
        await route.fulfill({ contentType: 'audio/wav', body: wave() });
      } else {
        await route.fulfill({ status: 404, body: '' });
      }
    });
    await page.goto(origin);
    await page.evaluate(() => {
      window.audioState = { started: false, error: null, violations: [] };
      document.addEventListener('securitypolicyviolation', (event) => {
        window.audioState.violations.push({
          directive: event.effectiveDirective,
          blockedURI: event.blockedURI,
        });
      });
    });
    await run(page, () => remoteRequests);
  } finally {
    await browser.close();
  }
}

test('the actual desktop CSP permits a user-started WAV Blob to decode and advance playback', async () => {
  await withPage(async (page) => {
    await page.evaluate(
      (bytes) => {
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'metadata';
        audio.muted = true;
        audio.src = URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: 'audio/wav' }));
        audio.addEventListener('error', () => {
          window.audioState.error = audio.error?.code ?? 'unknown';
        });
        const button = document.createElement('button');
        button.textContent = 'Play recording';
        button.addEventListener('click', async () => {
          try {
            await audio.play();
            window.audioState.started = true;
          } catch (error) {
            window.audioState.error = error.name;
          }
        });
        document.body.append(audio, button);
      },
      [...wave()],
    );
    await page.getByRole('button', { name: 'Play recording' }).click();
    await page.waitForFunction(() => window.audioState.started || window.audioState.error !== null);
    const state = await page.evaluate(() => window.audioState);
    assert.equal(state.error, null, JSON.stringify(state));
    assert.equal(state.started, true);
    await page.waitForFunction(() => document.querySelector('audio').currentTime > 0.05);
    const media = await page.locator('audio').evaluate((audio) => ({
      duration: audio.duration,
      currentTime: audio.currentTime,
      error: audio.error?.code ?? null,
    }));
    assert.ok(Math.abs(media.duration - 1) < 0.01);
    assert.ok(media.currentTime > 0.05);
    assert.equal(media.error, null);
    assert.deepEqual(state.violations, []);
    await page.locator('audio').evaluate((audio) => {
      audio.pause();
      URL.revokeObjectURL(audio.src);
    });
  });
});

test('the actual desktop CSP blocks an unapproved remote audio URL before network access', async () => {
  await withPage(async (page, remoteRequests) => {
    await page.evaluate((url) => {
      const audio = document.createElement('audio');
      audio.preload = 'auto';
      audio.addEventListener('error', () => {
        window.audioState.error = audio.error?.code ?? 'unknown';
      });
      audio.src = url;
      document.body.append(audio);
      audio.load();
    }, remoteAudio);
    await page.waitForFunction(
      () =>
        window.audioState.error !== null &&
        window.audioState.violations.some((event) => event.directive === 'media-src'),
    );
    const state = await page.evaluate(() => window.audioState);
    assert.equal(state.error, 4);
    assert.ok(
      state.violations.some(
        (event) => event.directive === 'media-src' && event.blockedURI === remoteAudio,
      ),
    );
    assert.equal(remoteRequests(), 0);
  });
});
