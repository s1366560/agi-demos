import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const stylesheet = readFileSync(new URL('../src/features/settings/ComputerUseSettingsPage.css', import.meta.url), 'utf8');
const themes = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8');

function declarations(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const result = new Map();
  for (const match of stylesheet.matchAll(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`, 'g'))) {
    for (const property of match[1].matchAll(/([\w-]+)\s*:\s*([^;]+);/g)) {
      result.set(property[1], property[2].trim());
    }
  }
  return result;
}
function palette(theme) {
  const selector = theme === 'light' ? /:root\[data-theme='light'\]\s*\{([^}]+)\}/ : /:root\s*\{([^}]+)\}/;
  return new Map([...themes.match(selector)[1].matchAll(/(--desktop-[\w-]+)\s*:\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]));
}
function color(value, tokens) {
  const variable = value?.match(/^var\((--desktop-[\w-]+)\)$/)?.[1];
  assert.ok(variable && tokens.has(variable), `CUA surfaces must resolve a desktop theme color: ${value}`);
  const hex = tokens.get(variable);
  assert.match(hex, /^#[0-9a-f]{6}$/i);
  const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  return channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
    .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
}
function contrast(foreground, background, tokens) {
  const values = [color(foreground, tokens), color(background, tokens)].sort((a, b) => a - b);
  return (values[1] + 0.05) / (values[0] + 0.05);
}

for (const theme of ['dark', 'light']) {
  test(`computer use activity and controls retain readable ${theme} theme contrast`, () => {
    const tokens = palette(theme);
    const card = declarations('.computer-use-activity');
    const button = declarations('.computer-use-activity button');
    assert.ok(contrast(card.get('color'), card.get('background'), tokens) >= 4.5);
    assert.ok(contrast(button.get('color'), button.get('background'), tokens) >= 4.5);
    assert.ok(contrast('var(--desktop-muted)', card.get('background'), tokens) >= 4.5);
    assert.ok(contrast('var(--desktop-red)', card.get('background'), tokens) >= 4.5);
    assert.match(declarations('.computer-use-activity button:focus-visible').get('outline'), /var\(--desktop-muted\)/);
    assert.ok(contrast('var(--desktop-muted)', card.get('background'), tokens) >= 3);
  });
}

test('computer use preview colors share the desktop theme outside a Radix appearance root', () => {
  assert.doesNotMatch(stylesheet, /var\(--(?:color-panel-solid|gray-\d+|red-\d+|amber-\d+)/);
  assert.equal(declarations('.computer-use-phase').get('color'), 'var(--desktop-text)');
  assert.equal(declarations('.computer-use-window-preview > p').get('color'), 'var(--desktop-muted)');
});
