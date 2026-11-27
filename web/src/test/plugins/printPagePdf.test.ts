import { afterEach, describe, expect, it, vi } from 'vitest';

import { printPagePdf } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/printPagePdf';
import { printDocument } from '../../projectPackages/printDocument';

// The printer of the original workbench, as far as these tests are concerned.
const printed = vi.hoisted(() => {
  const outputPdf = vi.fn();
  const from = vi.fn(() => ({ outputPdf }));
  const set = vi.fn(() => ({ from }));
  return { outputPdf, from, set };
});
vi.mock('html2pdf.js', () => ({ default: () => ({ set: printed.set }) }));

describe('printing a document of a page', () => {
  afterEach(() => {
    vi.clearAllMocks();
    document.querySelectorAll('iframe, dialog').forEach((node) => node.remove());
  });

  it('lays the document out where it runs no script and reaches no address, then prints it', async () => {
    const file = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    // The printer takes its time, as a real one does, so the frame can be looked at.
    let release!: (file: Blob) => void;
    const print = vi.fn(
      () =>
        new Promise<Blob>((resolve) => {
          release = resolve;
        })
    );
    const saveNative = vi.fn().mockResolvedValue(undefined);

    const printing = printPagePdf(
      'conversation.pdf',
      '<h1>Title</h1><p>Body</p>',
      new AbortController().signal,
      'zh-CN',
      saveNative,
      print
    );
    await vi.waitFor(() => expect(print).toHaveBeenCalled(), { timeout: 5000 });
    const frame = document.querySelector('iframe')!;
    // No script is allowed in the frame, and its document has nowhere to reach.
    expect(frame.getAttribute('sandbox')).toBe('allow-same-origin');
    expect(frame.getAttribute('aria-hidden')).toBe('true');
    expect(frame.srcdoc).toContain("default-src 'none'");
    expect(frame.contentDocument?.body.innerHTML).toContain('<h1>Title</h1><p>Body</p>');
    // What is printed is the document of the page, and nothing else of the workbench.
    expect(print.mock.calls[0]![0]).toBe(frame.contentDocument!.body);
    release(file);
    await printing;
    expect(saveNative).toHaveBeenCalledWith(file, 'conversation.pdf', 'application/pdf');
    // The frame of the document does not outlive the printing.
    expect(frame.isConnected).toBe(false);
  });

  it('offers the printed file to the user of the workbench window', async () => {
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
      this.dispatchEvent(new Event('close'));
    };
    const printing = printPagePdf(
      '报告.pdf',
      '<p>x</p>',
      new AbortController().signal,
      'zh-CN',
      undefined,
      async () => new Blob(['%PDF-1.4'], { type: 'application/pdf' })
    );
    await vi.waitFor(() => expect(document.querySelector('dialog')).not.toBeNull(), {
      timeout: 5000,
    });
    const dialog = document.querySelector('dialog')!;
    expect(dialog).toHaveAttribute('aria-label', '保存文件');
    expect(dialog.querySelector('a')?.getAttribute('download')).toBe('报告.pdf');
    dialog.querySelector('a')!.click();
    await printing;
  });

  it('leaves nothing behind when the page stops asking', async () => {
    const controller = new AbortController();
    const printing = printPagePdf(
      'a.pdf',
      '<p>a</p>',
      controller.signal,
      'en-US',
      undefined,
      () => new Promise<Blob>(() => {})
    );
    await vi.waitFor(() => expect(document.querySelector('iframe')).not.toBeNull(), {
      timeout: 5000,
    });
    controller.abort();
    await expect(printing).rejects.toThrow();
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('prints with the page and the options of the original workbench', async () => {
    const file = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    printed.outputPdf.mockResolvedValue(file);
    const laidOut = document.createElement('main');
    expect(await printDocument(laidOut)).toBe(file);
    expect(printed.set).toHaveBeenCalledWith({
      margin: [10, 10, 10, 10],
      html2canvas: { scale: 2, useCORS: true },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
    });
    expect(printed.from).toHaveBeenCalledWith(laidOut);
    expect(printed.outputPdf).toHaveBeenCalledWith('blob');
  });
});
