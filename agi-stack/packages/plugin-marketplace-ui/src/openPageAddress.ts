// Keep the new tab and its fallback link in the trusted host document.
/**
 * Open an address of the web for a page. The page asked through a port, so the
 * browser may not count it as the user's own click: a tab it refuses is offered
 * as a link to click instead. A native window has opened the system browser
 * already, and needs no link.
 */
export async function openPageAddress(
  url: string,
  signal: AbortSignal,
  locale: string,
  target: "web" | "desktop-renderer",
) {
  signal.throwIfAborted();
  if (target !== "web") return;
  // The tab is cut off from this window by hand: asked for that way, the browser
  // reports none, and a refused tab could not be told from an opened one.
  const opened = window.open(url, "_blank");
  if (opened) {
    opened.opener = null;
    return;
  }
  const dialog = document.createElement("dialog");
  const open = document.createElement("a");
  const cancel = document.createElement("button");
  const zh = locale.startsWith("zh");
  dialog.setAttribute("aria-label", zh ? "打开链接" : "Open link");
  open.href = url;
  open.target = "_blank";
  open.rel = "noopener noreferrer";
  open.textContent = zh ? "在新标签页中打开" : "Open in a new tab";
  open.style.wordBreak = "break-all";
  cancel.textContent = zh ? "取消" : "Cancel";
  dialog.append(open, cancel);
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
      open.onclick = () => dialog.close();
      dialog.showModal();
    });
  } finally {
    dialog.remove();
  }
}
