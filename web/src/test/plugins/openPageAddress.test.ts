import { afterEach, describe, expect, it, vi } from 'vitest';

import { openPageAddress } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/openPageAddress';

const url = 'https://example.com/a file.png?X-Amz-Signature=1';

describe('opening an address for a page', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.querySelectorAll('dialog').forEach((dialog) => dialog.remove());
  });

  it('opens a new tab in the workbench window, cut off from it', async () => {
    const tab = { opener: window } as unknown as WindowProxy;
    const open = vi.spyOn(window, 'open').mockReturnValue(tab);
    await openPageAddress(url, new AbortController().signal, 'zh-CN', 'web');
    expect(open).toHaveBeenCalledWith(url, '_blank');
    expect(tab.opener).toBeNull();
    expect(document.querySelector('dialog')).toBeNull();
  });

  it('offers the address as a link when the browser refuses the tab', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
      this.dispatchEvent(new Event('close'));
    };
    const opened = openPageAddress(url, new AbortController().signal, 'zh-CN', 'web');
    const dialog = document.querySelector('dialog')!;
    expect(dialog).toHaveAttribute('aria-label', '打开链接');
    const link = dialog.querySelector('a')!;
    expect(link.getAttribute('href')).toBe(url);
    expect(link.target).toBe('_blank');
    expect(link.rel).toBe('noopener noreferrer');
    expect(link.textContent).toBe('在新标签页中打开');
    link.click();
    await opened;
    expect(document.querySelector('dialog')).toBeNull();
  });

  it('closes an offer nobody takes when the page stops asking', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    const controller = new AbortController();
    const opened = openPageAddress(url, controller.signal, 'en-US', 'web');
    expect(document.querySelector('dialog')).toHaveAttribute('aria-label', 'Open link');
    controller.abort();
    await expect(opened).rejects.toThrow();
    expect(document.querySelector('dialog')).toBeNull();
  });

  it('adds no link in a native window: the system browser has opened already', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    await openPageAddress(url, new AbortController().signal, 'en-US', 'desktop-renderer');
    expect(document.querySelector('dialog')).toBeNull();
  });
});
