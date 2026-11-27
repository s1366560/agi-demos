import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { openPageAddress } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/openPageAddress';
import {
  savePageExport,
  savePageFile,
} from '../../../../agi-stack/packages/plugin-marketplace-ui/src/savePageExport';

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

describe('offering a file of a page', () => {
  beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
      this.dispatchEvent(new Event('close'));
    };
  });

  it('lets the user click a download named as the page named it', async () => {
    const created: string[] = [];
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      created.push((blob as Blob).type);
      return 'blob:offered';
    });
    const offered = savePageFile(
      'conversation-1.md',
      '# Title',
      'text/markdown;charset=utf-8',
      new AbortController().signal,
      'zh-CN'
    );
    const dialog = document.querySelector('dialog')!;
    const link = dialog.querySelector('a')!;
    expect(dialog).toHaveAttribute('aria-label', '保存文件');
    expect(link.getAttribute('href')).toBe('blob:offered');
    expect(link.getAttribute('download')).toBe('conversation-1.md');
    expect(link.textContent).toBe('下载 conversation-1.md');
    link.click();
    await offered;
    expect(created).toEqual(['text/markdown;charset=utf-8']);
    expect(document.querySelector('dialog')).toBeNull();
  });

  it('hands bytes to a native window under their name and type', async () => {
    const saveNative = vi.fn().mockResolvedValue(undefined);
    const blob = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    await savePageFile(
      'report.pdf',
      blob,
      'application/pdf',
      new AbortController().signal,
      'en-US',
      saveNative
    );
    expect(saveNative).toHaveBeenCalledWith(blob, 'report.pdf', 'application/pdf');
    expect(document.querySelector('dialog')).toBeNull();
  });

  it('refuses a file too large to offer', async () => {
    await expect(
      savePageFile(
        'big.bin',
        'x'.repeat(12 * 1024 * 1024 + 1),
        'text/plain',
        new AbortController().signal,
        'en-US'
      )
    ).rejects.toThrow('page_export_too_large');
  });

  it('keeps the CSV export of a page as it was', async () => {
    const saveNative = vi.fn().mockResolvedValue(undefined);
    await savePageExport('a,b\n1,2\n', new AbortController().signal, 'en-US', saveNative);
    expect(saveNative).toHaveBeenCalledWith(expect.any(Blob), 'export.csv', 'text/csv');
    expect(vi.mocked(saveNative).mock.calls[0]![0].type).toBe('text/csv');
  });
});
