// Keep download URLs and the native file bridge in the trusted host document.
export async function savePageExport(
  csv: string,
  signal: AbortSignal,
  locale: string,
  saveNative?: PageFileSaver,
) {
  return savePageFile(
    "export.csv",
    csv,
    "text/csv",
    signal,
    locale,
    saveNative,
  );
}

export type PageFileSaver = (
  blob: Blob,
  name: string,
  mimeType: string,
) => Promise<unknown>;

/**
 * Offer a file of a page to the user under its name. The workbench window lets the
 * user click the download; a native window saves through its own dialog.
 */
export async function savePageFile(
  name: string,
  content: string | Blob,
  mimeType: string,
  signal: AbortSignal,
  locale: string,
  saveNative?: PageFileSaver,
) {
  signal.throwIfAborted();
  const blob =
    typeof content === "string"
      ? new Blob([content], { type: mimeType })
      : content;
  if (blob.size > 12 * 1024 * 1024) throw new Error("page_export_too_large");
  if (saveNative) {
    await saveNative(blob, name, mimeType);
    return;
  }
  const dialog = document.createElement("dialog");
  const download = document.createElement("a");
  const cancel = document.createElement("button");
  const zh = locale.startsWith("zh");
  dialog.setAttribute("aria-label", zh ? "保存文件" : "Save file");
  const url = URL.createObjectURL(blob);
  download.href = url;
  download.download = name;
  download.textContent = `${zh ? "下载" : "Download"} ${name}`;
  cancel.textContent = zh ? "取消" : "Cancel";
  dialog.append(download, cancel);
  document.body.append(dialog);
  try {
    await new Promise<void>((resolve, reject) => {
      const abort = () => reject(signal.reason);
      signal.addEventListener("abort", abort, { once: true });
      dialog.onclose = () => {
        signal.removeEventListener("abort", abort);
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
