import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  connectPage,
  type PageBridge,
} from '../../../../agi-stack/packages/plugin-slots/src/richPageBridge';
import type { RichPage } from '../../../../agi-stack/packages/plugin-slots/src/richPage';
import type { PageStorage } from '../../../../agi-stack/packages/plugin-slots/src/pageStorage';

function signedPage(workbench: boolean): RichPage {
  return {
    schema: 'memstack.rich-page/1',
    id: 'page',
    title: 'Page',
    routes: ['/tenant/:tenantId/page'],
    commands: [],
    device_tools: [],
    release_digest: `sha256:${'a'.repeat(64)}`,
    target: 'web',
    entry: { path: 'page.js', digest: `sha256:${'b'.repeat(64)}`, bytes_base64: '' },
    ...(workbench ? { workbench: true } : {}),
  };
}

function connectedPort(page: RichPage) {
  const posted: Record<string, unknown>[] = [];
  const port = {
    postMessage: (message: Record<string, unknown>) => {
      posted.push(message);
    },
    close: vi.fn(),
  } as unknown as MessagePort;
  const bridge: PageBridge = {
    scope: { tenantId: 't', projectId: 'p' },
    target: 'web',
    pathname: '/tenant/t/page',
    locale: 'zh-CN',
    status: vi.fn(),
    navigate: vi.fn(),
    invoke: vi.fn(),
  };
  return { posted, disconnect: connectPage(port, page, bridge) };
}

const appearances = (posted: Record<string, unknown>[]) =>
  posted.filter((message) => message.type === 'appearance');

describe('connectPage appearance', () => {
  afterEach(() => {
    document.documentElement.classList.remove('dark');
    delete document.documentElement.dataset.theme;
  });

  it('mirrors the workbench theme and language onto pages that are not workbench surfaces', () => {
    document.documentElement.classList.add('dark');
    const { posted, disconnect } = connectedPort(signedPage(false));

    expect(appearances(posted)).toEqual([
      expect.objectContaining({ type: 'appearance', dark: true, lang: 'zh-CN' }),
    ]);
    disconnect();
  });

  it('reports a light workbench as light', () => {
    const { posted, disconnect } = connectedPort(signedPage(false));

    expect(appearances(posted)).toEqual([
      expect.objectContaining({ type: 'appearance', dark: false, lang: 'zh-CN' }),
    ]);
    disconnect();
  });

  it('follows later theme changes on pages that are not workbench surfaces', async () => {
    const { posted, disconnect } = connectedPort(signedPage(false));
    document.documentElement.dataset.theme = 'dark';
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(appearances(posted).at(-1)).toEqual(expect.objectContaining({ dark: true }));
    disconnect();
  });

  it('stops mirroring the theme once the page is released', async () => {
    const { posted, disconnect } = connectedPort(signedPage(false));
    disconnect();
    document.documentElement.dataset.theme = 'dark';
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(appearances(posted)).toHaveLength(1);
  });
});

interface TestPort {
  postMessage(message: Record<string, unknown>): void;
  close(): void;
  onmessage: ((event: { data: unknown }) => void) | null;
}

// A page that asks for more than a theme: its requests are answered one at a time.
function asking(page: RichPage, extra: Partial<PageBridge> = {}) {
  const posted: Record<string, unknown>[] = [];
  const port: TestPort = {
    postMessage: (message) => {
      posted.push(message);
    },
    close: vi.fn(),
    onmessage: null,
  };
  let pathname = '/tenant/t/page';
  const bridge: PageBridge = {
    scope: { tenantId: 't', projectId: 'p' },
    target: 'web',
    get pathname() {
      return pathname;
    },
    locale: 'zh-CN',
    status: vi.fn(),
    navigate: vi.fn(),
    invoke: vi.fn(),
    ...extra,
  };
  const disconnect = connectPage(port as unknown as MessagePort, page, bridge);
  let sequence = 0;
  const ask = async (request: Record<string, unknown>) => {
    const id = String(++sequence);
    port.onmessage?.({ data: { id, ...request } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    return posted.filter((message) => message.id === id);
  };
  // What the workbench tells the page on its own, such as a new context.
  const notices = (type: string) => posted.filter((message) => message.type === type);
  return {
    posted,
    port,
    bridge,
    disconnect,
    ask,
    notices,
    move: (next: string) => (pathname = next),
  };
}

const navigable: RichPage = {
  ...signedPage(false),
  routes: ['/tenant/:tenantId/page', '/tenant/:tenantId/page/:id'],
  query_params: ['tab'],
};

describe('a page that keeps itself mounted', () => {
  it('passes its choice to the workbench, which alone talks to the router', async () => {
    const page = asking(navigable);
    await page.ask({ method: 'navigate', path: '/tenant/t/page/one', keepMounted: true });
    expect(page.bridge.navigate).toHaveBeenCalledWith('/tenant/t/page/one', {
      replace: false,
      keepMounted: true,
    });
    page.disconnect();
  });

  it('is told the context of the address it moved to', async () => {
    const storage: PageStorage = {
      snapshot: vi.fn(() => ({})),
      read: vi.fn(),
      write: vi.fn(),
      remove: vi.fn(),
      clear: vi.fn(),
    };
    const listeners = new Set<() => void>();
    const page = asking(navigable, {
      storage,
      contextChanged: (listener) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    });
    expect(listeners.size).toBe(1);
    page.move('/tenant/t/page/one?tab=2');
    for (const listener of listeners) listener();
    expect(page.notices('context')).toEqual([
      {
        type: 'context',
        value: expect.objectContaining({
          pathname: '/tenant/t/page/one',
          search: '?tab=2',
          tenantId: 't',
          projectId: 'p',
        }),
      },
    ]);
    page.disconnect();
    expect(listeners.size).toBe(0);
    // A page that is released no longer hears of the address.
    page.move('/tenant/t/page/two');
    page.port.onmessage?.({ data: { type: 'storage.set', key: 'k', value: 'v' } });
    expect(storage.write).not.toHaveBeenCalled();
    expect(page.notices('context')).toHaveLength(1);
  });

  it('reads its context again at the address it is at now', async () => {
    const page = asking(navigable);
    page.move('/tenant/t/page/one');
    expect(await page.ask({ method: 'scope' })).toEqual([
      {
        id: '1',
        type: 'result',
        value: expect.objectContaining({ pathname: '/tenant/t/page/one' }),
      },
    ]);
    page.disconnect();
  });
});

describe('a page that opens an address', () => {
  it.each([
    'javascript:alert(1)',
    'data:text/html,hi',
    'file:///etc/hosts',
    'vbscript:x',
    'https://user:pass@example.com/',
    'not a url',
    42,
  ])('is refused for %s', async (url) => {
    const openUrl = vi.fn();
    const page = asking(navigable, { openUrl });
    expect(await page.ask({ method: 'openUrl', url })).toEqual([
      { id: '1', type: 'error', error: 'page_navigation_denied' },
    ]);
    expect(openUrl).not.toHaveBeenCalled();
    page.disconnect();
  });

  it('is refused when the workbench has no way to open one', async () => {
    const page = asking(navigable);
    expect(await page.ask({ method: 'openUrl', url: 'https://example.com' })).toEqual([
      { id: '1', type: 'error', error: 'page_navigation_denied' },
    ]);
    page.disconnect();
  });

  it.each(['https://example.com/a?b=1#c', 'http://127.0.0.1:9000/files/a.png?X-Amz-Signature=1'])(
    'opens %s through the workbench',
    async (url) => {
      const openUrl = vi.fn();
      const page = asking(navigable, { openUrl });
      expect(await page.ask({ method: 'openUrl', url })).toEqual([
        { id: '1', type: 'result', value: undefined },
      ]);
      expect(openUrl).toHaveBeenCalledWith(url, expect.any(AbortSignal));
      page.disconnect();
    }
  );
});

describe('the storage of a page', () => {
  function stored() {
    const storage: PageStorage = {
      snapshot: vi.fn(() => ({ kept: 'value' })),
      read: vi.fn(),
      write: vi.fn(),
      remove: vi.fn(),
      clear: vi.fn(),
    };
    return { storage, ...asking(navigable, { storage }) };
  }

  it('is changed as the page runs, without an answer', async () => {
    const page = stored();
    page.port.onmessage?.({ data: { type: 'storage.set', key: 'layout', value: 'canvas' } });
    page.port.onmessage?.({ data: { type: 'storage.set', key: 'blank', value: 7 } });
    page.port.onmessage?.({ data: { type: 'storage.remove', key: 'layout' } });
    page.port.onmessage?.({ data: { type: 'storage.clear' } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(page.storage.write).toHaveBeenCalledWith('layout', 'canvas');
    expect(page.storage.write).toHaveBeenCalledWith('blank', '');
    expect(page.storage.remove).toHaveBeenCalledWith('layout');
    expect(page.storage.clear).toHaveBeenCalled();
    expect(page.notices('context')).toHaveLength(0);
    page.disconnect();
  });

  it.each([
    { type: 'storage.set', key: 'a\u0000b', value: 'v' },
    { type: 'storage.set', key: 7, value: 'v' },
    { type: 'storage.set', value: 'v' },
    { type: 'storage.remove', key: '' },
    { type: 'storage.remove', key: 'x'.repeat(257) },
  ])('keeps out a name that cannot be stored: %j', async (request) => {
    const page = stored();
    page.port.onmessage?.({ data: request });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(page.storage.write).not.toHaveBeenCalled();
    expect(page.storage.remove).not.toHaveBeenCalled();
    page.disconnect();
  });

  it('survives a write the workbench refuses', async () => {
    const page = stored();
    vi.mocked(page.storage.write).mockImplementation(() => {
      throw new Error('page_storage_quota');
    });
    page.port.onmessage?.({ data: { type: 'storage.set', key: 'big', value: 'v'.repeat(10) } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    // Nothing is answered: the page keeps its own copy until it loads again.
    expect(page.posted.every((message) => message.id === undefined)).toBe(true);
    page.disconnect();
  });

  it('is not changed without a storage to keep it', async () => {
    const page = asking(navigable);
    page.port.onmessage?.({ data: { type: 'storage.set', key: 'layout', value: 'canvas' } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(page.posted.every((message) => message.id === undefined)).toBe(true);
    page.disconnect();
  });
});
