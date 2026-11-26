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

  it('stops mirroring the theme once the page is released', async () => {
    const { posted, disconnect } = connectedPort(signedPage(false));
    disconnect();
    document.documentElement.dataset.theme = 'dark';
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(appearances(posted)).toHaveLength(1);
  });
});
