// Final values are previews. The persistent kernel retains the original value.
// Keep this budget below the JSONL control-frame limit, including JSON escaping.
export function resultPreview(value) {
  let remaining = 256 * 1024;
  const seen = new WeakSet();
  const visit = (item, depth) => {
    if (remaining <= 0) return { truncated: true };
    remaining -= 8;
    if (item === null || item === undefined || typeof item === 'boolean' || typeof item === 'number') return item;
    if (typeof item === 'bigint') return `${item}n`;
    if (typeof item === 'string') {
      const maximum = Math.max(0, Math.min(4096, Math.floor(remaining / 6)));
      remaining -= Math.min(item.length, maximum) * 6;
      return item.length <= maximum ? item : { type: 'string', length: item.length, preview: item.slice(0, maximum), truncated: true };
    }
    if (typeof item !== 'object') return visit(String(item), depth);
    if (seen.has(item)) return '[Circular]';
    if (depth >= 8 || remaining <= 0) return { truncated: true };
    seen.add(item);
    if (ArrayBuffer.isView(item) || Object.prototype.toString.call(item) === '[object ArrayBuffer]') {
      const bytes = ArrayBuffer.isView(item) ? Buffer.from(item.buffer, item.byteOffset, item.byteLength) : Buffer.from(item);
      remaining -= 128;
      return { type: item.constructor.name, byteLength: bytes.length, previewBase64: bytes.subarray(0, 64).toString('base64'), truncated: bytes.length > 64 };
    }
    if (Object.prototype.toString.call(item) === '[object Date]') return item.toISOString();
    if (Array.isArray(item)) {
      const values = item.slice(0, 100).map(child => visit(child, depth + 1));
      if (item.length > values.length) values.push({ truncated: true, omittedItems: item.length - values.length });
      return values;
    }
    const entries = Object.entries(item);
    const result = {};
    for (const [name, child] of entries.slice(0, 100)) {
      if (name.length > 4096 || remaining < name.length * 6) { result.previewTruncated = true; break; }
      remaining -= name.length * 6;
      Object.defineProperty(result, name, { value: visit(child, depth + 1), enumerable: true, writable: true, configurable: true });
    }
    if (entries.length > 100) result.previewTruncated = true;
    return result;
  };
  return visit(value, 0);
}
