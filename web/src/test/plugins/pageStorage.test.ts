import { describe, expect, it } from 'vitest';

import {
  createPageStorage,
  PAGE_STORAGE_TOTAL_UNITS,
  PAGE_STORAGE_VALUE_UNITS,
  windowPageStorage,
} from '../../../../agi-stack/packages/plugin-slots/src/pageStorage';
import {
  arrived,
  type RequestedAddress,
} from '../../../../agi-stack/packages/plugin-slots/src/pageArrival';
import {
  pageDocumentWithStorage,
  verifyPageDocument,
  type RichPage,
} from '../../../../agi-stack/packages/plugin-slots/src/richPage';

// The digest of an empty asset.
const digest = 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';

// The storage of a workbench document, as far as a page and its bounds can tell.
function documentStorage(): Storage {
  const rows = new Map<string, string>();
  return {
    get length() {
      return rows.size;
    },
    key: (index: number) => [...rows.keys()][index] ?? null,
    getItem: (key: string) => rows.get(String(key)) ?? null,
    setItem: (key: string, value: string) => void rows.set(String(key), String(value)),
    removeItem: (key: string) => void rows.delete(key),
    clear: () => rows.clear(),
  };
}

describe('the storage a page keeps in the workbench', () => {
  it('is the storage of the workbench document when the document has one', () => {
    const area = documentStorage();
    const declared = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', { configurable: true, get: () => area });
    try {
      expect(windowPageStorage()).toBe(area);
      // A document that the browser keeps from its storage reports none.
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        get: () => {
          throw new DOMException('Denied', 'SecurityError');
        },
      });
      expect(windowPageStorage()).toBeUndefined();
    } finally {
      if (declared) Object.defineProperty(window, 'localStorage', declared);
      else delete (window as { localStorage?: Storage }).localStorage;
    }
  });

  it('holds what a release stored in one tenant and project, and no other', () => {
    const area = documentStorage();
    area.setItem('memstack.page:t:p:notes:layout', 'canvas');
    area.setItem('memstack.page:t:other:notes:layout', 'task');
    area.setItem('memstack.page:t:p:other:layout', 'chat');
    area.setItem('auth-storage', '{"token":"secret"}');
    const page = createPageStorage(area, 't:p:notes')!;
    expect(page.snapshot()).toEqual({ layout: 'canvas' });
    expect(page.read('layout')).toBe('canvas');
    expect(page.read('missing')).toBeNull();
    page.write('tabs', '["a"]');
    expect(page.snapshot()).toEqual({ layout: 'canvas', tabs: '["a"]' });
    page.remove('layout');
    page.clear();
    expect(page.snapshot()).toEqual({});
    // The storage of other releases, projects and the workbench itself is untouched.
    expect(area.getItem('memstack.page:t:other:notes:layout')).toBe('task');
    expect(area.getItem('memstack.page:t:p:other:layout')).toBe('chat');
    expect(area.getItem('auth-storage')).toBe('{"token":"secret"}');
    expect(createPageStorage(undefined, 't:p:notes')).toBeUndefined();
  });

  it('refuses a name or a value it has no room for, and leaves the rest as it was', () => {
    const page = createPageStorage(documentStorage(), 't:p:notes')!;
    page.write('a', 'x'.repeat(PAGE_STORAGE_VALUE_UNITS));
    expect(() => page.write('b', 'y'.repeat(PAGE_STORAGE_VALUE_UNITS + 1))).toThrow(
      'page_request_invalid'
    );
    expect(() => page.write('a\u0000b', 'v')).toThrow('page_request_invalid');
    expect(() => page.write('', 'v')).toThrow('page_request_invalid');
    // Four values of the largest size fill the storage of a release.
    for (const name of ['b', 'c', 'd']) page.write(name, 'y'.repeat(PAGE_STORAGE_VALUE_UNITS));
    expect(() => page.write('e', 'z')).toThrow('page_storage_quota');
    // A value that replaces its own place is measured against what is left.
    expect(() => page.write('a', 'x'.repeat(PAGE_STORAGE_VALUE_UNITS))).not.toThrow();
    expect(page.snapshot().e).toBeUndefined();
    expect(() => page.write('a', 'short')).not.toThrow();
    page.remove('a\u0000b');
    expect(Object.keys(page.snapshot())).toEqual(['a', 'b', 'c', 'd']);
    expect(page.snapshot().a).toBe('short');
  });
});

describe('the document a page loads with', () => {
  it('carries what the page stored, where the guest reads it', async () => {
    const page: RichPage = {
      schema: 'memstack.rich-page/1',
      id: 'page',
      title: 'Page',
      routes: ['/tenant/:tenantId/page'],
      commands: [],
      device_tools: [],
      release_digest: digest,
      target: 'web',
      entry: { path: 'page.js', digest, bytes_base64: '' },
    };
    const html = await verifyPageDocument(page, 'web', digest, 'page');
    expect(html).toContain('<script id="memstack-storage" type="application/json"></script>');
    // The guest script reads the table, and only then the page runs.
    expect(html.indexOf('id="memstack-storage"')).toBeLessThan(html.indexOf('id="root"'));
    const loaded = pageDocumentWithStorage(html, { layout: 'canvas', code: '</script><b>x' });
    expect(loaded).toContain(
      '<script id="memstack-storage" type="application/json">' +
        '{"layout":"canvas","code":"\\u003c/script>\\u003cb>x"}</script>'
    );
    expect(
      JSON.parse(
        loaded.split('id="memstack-storage" type="application/json">')[1]!.split('</script>')[0]!
      )
    ).toEqual({
      layout: 'canvas',
      code: '</script><b>x',
    });
    // A document without the table is not touched.
    expect(pageDocumentWithStorage('<p>none</p>', { a: 'b' })).toBe('<p>none</p>');
  });
});

describe('an address a page asked for', () => {
  const asked: RequestedAddress = { address: '/tenant/t/page/one', at: 1000 };

  it('keeps the page mounted when the router has just arrived', () => {
    expect(arrived(asked, '/tenant/t/page/one', 1000)).toBe(true);
    expect(arrived(asked, '/tenant/t/page/one', 15999)).toBe(true);
  });

  it('loads the page again for an address nobody asked for, or one that came too late', () => {
    expect(arrived(asked, '/tenant/t/page/two', 1000)).toBe(false);
    expect(arrived(asked, '/tenant/t/page/one', 16000)).toBe(false);
    expect(arrived(null, '/tenant/t/page/one', 1000)).toBe(false);
  });
});
