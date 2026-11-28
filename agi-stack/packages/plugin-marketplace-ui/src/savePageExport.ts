// Keep download URLs and the native file bridge in the trusted host document.
export async function savePageExport(
  csv: string,
  signal: AbortSignal,
  locale: string,
  saveNative?: (blob: Blob) => Promise<unknown>,
) {
  signal.throwIfAborted();
  const blob = new Blob([csv], { type: 'text/csv' });
  if (blob.size > 1_048_576) throw new Error('page_export_too_large');
  if (saveNative) {
    await saveNative(blob);
    return;
  }
  const dialog = document.createElement('dialog');
  const download = document.createElement('a');
  const cancel = document.createElement('button');
  const zh = locale.startsWith('zh');
  dialog.setAttribute('aria-label', zh ? '保存导出文件' : 'Save exported file');
  const url = URL.createObjectURL(blob);
  download.href = url;
  download.download = 'export.csv';
  download.textContent = zh ? '下载 CSV' : 'Download CSV';
  cancel.textContent = zh ? '取消' : 'Cancel';
  dialog.append(download, cancel);
  document.body.append(dialog);
  try {
    await new Promise<void>((resolve, reject) => {
      const abort = () => reject(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      dialog.onclose = () => {
        signal.removeEventListener('abort', abort);
        resolve();
      };
      cancel.onclick = () => dialog.close();
      download.onclick = () => dialog.close();
      dialog.showModal();
    });
  } finally {
    dialog.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
