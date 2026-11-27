// Keep the layout of printed page documents in the trusted host document.
import { savePageFile, type PageFileSaver } from "./savePageExport";

/** The printer of a host: what it makes of a document that was laid out. */
export type PagePrinter = (document: HTMLElement) => Promise<Blob>;

// A page is kept in frames of its own, which is what a printer needs to reach
// across. The document it hands over is therefore laid out here, inside a frame
// that runs no script, and that reaches no address.
const FRAME_STYLE =
  "position:fixed;left:-9999px;top:0;width:794px;height:1123px;border:0;visibility:hidden";
const DOCUMENT =
  '<!doctype html><html><head><meta charset="utf-8">' +
  "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">" +
  "<style>body{margin:0;font:12pt/1.5 system-ui;color:#111}</style></head><body>";

/** Print an HTML document of a page to a PDF file, offered to the user under its name. */
export async function printPagePdf(
  name: string,
  html: string,
  signal: AbortSignal,
  locale: string,
  saveNative: PageFileSaver | undefined,
  print: PagePrinter,
) {
  signal.throwIfAborted();
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-same-origin");
  frame.setAttribute("aria-hidden", "true");
  frame.tabIndex = -1;
  frame.style.cssText = FRAME_STYLE;
  document.body.append(frame);
  try {
    await new Promise<void>((resolve, reject) => {
      const abort = () => reject(signal.reason);
      signal.addEventListener("abort", abort, { once: true });
      frame.onload = () => {
        signal.removeEventListener("abort", abort);
        resolve();
      };
      frame.srcdoc = DOCUMENT + html + "</body></html>";
    });
    signal.throwIfAborted();
    // The host prints the document of the page, and nothing else of the workbench.
    const laidOut = frame.contentDocument?.body;
    if (!laidOut) throw new Error("page_export_unavailable");
    const file = await print(laidOut);
    await savePageFile(
      name,
      file,
      "application/pdf",
      signal,
      locale,
      saveNative,
    );
  } finally {
    frame.remove();
  }
}
