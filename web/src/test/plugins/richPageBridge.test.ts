import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  connectPage,
  type PageBridge,
} from '../../../../agi-stack/packages/plugin-slots/src/richPageBridge';
import type { RichPage } from '../../../../agi-stack/packages/plugin-slots/src/richPage';

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

  it('authorizes the tenant chat address against the project route when a project is named', () => {
    const posted: Record<string, unknown>[] = [];
    const navigate = vi.fn();
    const port = {
      postMessage: (message: Record<string, unknown>) => {
        posted.push(message);
      },
      close: vi.fn(),
      onmessage: null as ((event: MessageEvent) => void) | null,
    };
    const page: RichPage = {
      ...signedPage(true),
      routes: ['/tenant/:tenantId/project/:projectId/agent-workspace/:conversationId'],
      navigation_routes: [
        '/tenant/:tenantId/project/:projectId/agent-workspace/:conversationId',
      ],
    };
    const disconnect = connectPage(port as unknown as MessagePort, page, {
      scope: { tenantId: 't', projectId: 'p' },
      target: 'web',
      pathname: '/tenant/t/agent-workspace',
      locale: 'en',
      status: vi.fn(),
      navigate,
      invoke: vi.fn(),
    });
    port.onmessage?.({
      data: {
        id: 'nav-1',
        method: 'navigate',
        path: '/tenant/t/agent-workspace/conversation',
      },
    } as MessageEvent);
    expect(navigate).toHaveBeenCalledWith('/tenant/t/agent-workspace/conversation', {
      replace: false,
    });
    disconnect();
    expect(posted.some((message) => message.error === 'page_navigation_denied')).toBe(false);
  });

  it('lets a tenant page open a named project session on its declared route', () => {
    const navigate = vi.fn();
    const port = {
      postMessage: vi.fn(),
      close: vi.fn(),
      onmessage: null as ((event: MessageEvent) => void) | null,
    };
    const page: RichPage = {
      ...signedPage(false),
      routes: ['/tenant/:tenantId/agent-workspace/:conversationId'],
      navigation_routes: [
        '/tenant/:tenantId/project/:projectId/agent-workspace/:conversationId',
      ],
    };
    const disconnect = connectPage(port as unknown as MessagePort, page, {
      scope: { tenantId: 't', projectId: null },
      target: 'web',
      pathname: '/tenant/t/agent-workspace',
      locale: 'en',
      status: vi.fn(),
      navigate,
      invoke: vi.fn(),
    });
    const destination = '/tenant/t/project/p/agent-workspace/conversation';
    port.onmessage?.({
      data: { id: 'nav-2', method: 'navigate', path: destination },
    } as MessageEvent);
    expect(navigate).toHaveBeenCalledWith(destination, { replace: false });
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
