export function formatStorage(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  const sizeLabel = sizes[unitIndex] ?? 'TB';
  const value = Number.parseFloat((bytes / Math.pow(k, unitIndex)).toFixed(1));
  return `${String(value)} ${sizeLabel}`;
}
