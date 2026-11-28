import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const business = path.resolve(__dirname, '../../../../plugins/business');
const localeImport = /from\s+['"]([^'"]*locales\/(?:en-US|zh-CN)\.json)['"]/g;
const antdLocaleImport = /from\s+['"]([^'"]*locale\/(?:en_US|zh_CN))['"]/g;

describe('signed page locales', () => {
  it('load every signed entry from the locale bundle of its own package', () => {
    const checked: string[] = [];

    for (const pkg of fs.readdirSync(business)) {
      const signed = path.join(business, pkg, 'ui', 'signed');
      if (!fs.existsSync(signed)) continue;
      const own = path.join(business, pkg, 'ui', 'web', 'locales') + path.sep;
      for (const file of fs.readdirSync(signed)) {
        if (!file.endsWith('.tsx')) continue;
        const entry = fs.readFileSync(path.join(signed, file), 'utf8');
        for (const match of entry.matchAll(localeImport)) {
          // The host shell no longer carries business strings, so an entry that reads
          // another bundle shows raw keys once the page runs on its own.
          expect(path.resolve(signed, match[1]!).startsWith(own), `${pkg}/ui/signed/${file}`).toBe(
            true
          );
          checked.push(`${pkg}/ui/signed/${file}`);
        }
      }
    }

    expect(checked.length).toBeGreaterThan(10);
  });

  it('read the component-library locale from its ES module build', () => {
    const checked: string[] = [];

    for (const pkg of fs.readdirSync(business)) {
      const signed = path.join(business, pkg, 'ui', 'signed');
      if (!fs.existsSync(signed)) continue;
      for (const file of fs.readdirSync(signed)) {
        if (!file.endsWith('.tsx')) continue;
        const entry = fs.readFileSync(path.join(signed, file), 'utf8');
        for (const match of entry.matchAll(antdLocaleImport)) {
          // A standalone bundle hands out a wrapper for the CommonJS entry, so the
          // provider would receive that wrapper instead of the locale.
          expect(match[1], `${pkg}/ui/signed/${file}`).toMatch(/^antd\/es\/locale\//);
          checked.push(`${pkg}/${file}`);
        }
      }
    }

    expect(checked.length).toBeGreaterThan(4);
  });
});
