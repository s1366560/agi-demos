/**
 * Download a JSON payload as a file in the browser.
 *
 * Shared helper replacing the repeated Blob/createObjectURL boilerplate
 * across export features. Objects are serialized with 2-space indentation;
 * string payloads are written as-is.
 */
export function downloadJson(filename: string, data: unknown): void {
  const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
