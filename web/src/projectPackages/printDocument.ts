// The options of the printer, as the export of the original workbench names them.
interface PrintOptions {
  margin: [number, number, number, number];
  html2canvas: Record<string, unknown>;
  jsPDF: { unit: string; format: string; orientation: 'portrait' | 'landscape' };
  pagebreak: { mode: string[] };
}

/**
 * Print a document that was laid out to a PDF file, with the printer of the
 * original workbench and the page it prints.
 */
export async function printDocument(document: HTMLElement): Promise<Blob> {
  const { default: html2pdf } = await import('html2pdf.js');
  const options: PrintOptions = {
    margin: [10, 10, 10, 10],
    html2canvas: { scale: 2, useCORS: true },
    jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
    pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
  };
  const file = (await html2pdf().set(options).from(document).outputPdf('blob')) as Blob;
  return file;
}
