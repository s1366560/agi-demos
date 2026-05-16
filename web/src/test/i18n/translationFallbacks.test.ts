import { describe, expect, it } from 'vitest';

import enUS from '@/locales/en-US.json';

const sourceModules = import.meta.glob('../../**/*.{ts,tsx}', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>;

const TRANSLATION_CALL_PATTERN =
  /\bt\(\s*['"]([^'"`]+)['"]\s*(?:,\s*(['"`])([\s\S]*?)\2|,\s*\{([\s\S]*?)\})?/g;

function readLocaleValue(locale: Record<string, unknown>, key: string): unknown {
  return key.split('.').reduce<unknown>((current, segment) => {
    if (current && typeof current === 'object' && segment in current) {
      return (current as Record<string, unknown>)[segment];
    }
    return undefined;
  }, locale);
}

function hasStaticFallback(match: RegExpExecArray): boolean {
  const directFallback = match[3];
  if (typeof directFallback === 'string' && directFallback.length > 0) {
    return true;
  }

  const options = match[4];
  return typeof options === 'string' && /defaultValue\s*:\s*(['"`])[\s\S]*?\1/.test(options);
}

function isSourceFile(path: string): boolean {
  return !path.includes('/test/') && !path.includes('/vendor/') && !path.endsWith('.d.ts');
}

function isStaticTranslationKey(key: string): boolean {
  return key.includes('.') && !key.includes('${') && !key.includes('{');
}

describe('translation fallback coverage', () => {
  it('keeps static translation calls covered by locale entries or explicit defaults', () => {
    const missingFallbacks: string[] = [];

    for (const [path, source] of Object.entries(sourceModules)) {
      if (!isSourceFile(path)) {
        continue;
      }

      TRANSLATION_CALL_PATTERN.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = TRANSLATION_CALL_PATTERN.exec(source))) {
        const key = match[1];
        if (!key || !isStaticTranslationKey(key)) {
          continue;
        }

        const localeValue = readLocaleValue(enUS, key);
        if (typeof localeValue === 'string' && localeValue.trim().length > 0) {
          continue;
        }

        if (!hasStaticFallback(match)) {
          missingFallbacks.push(`${path}: ${key}`);
        }
      }
    }

    expect(missingFallbacks).toEqual([]);
  });
});
