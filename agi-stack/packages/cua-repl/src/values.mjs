export function unwrap(value) {
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return value; }
  }
  if (value?.error) {
    const error = new Error(typeof value.error === 'string' ? value.error : value.error.message);
    error.code = value.error.code ?? value.error;
    throw error;
  }
  return value;
}

export function index(value, nullable = false) {
  if (nullable && value === null) return null;
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError('element index must be a non-negative safe integer');
  return value;
}

export function point(value) {
  if (!value || !Number.isFinite(value.x) || !Number.isFinite(value.y)) throw new TypeError('point requires finite x and y');
  return { x: value.x, y: value.y };
}

export function target(value) {
  return typeof value === 'number' ? { element_index: index(value) } : point(value);
}

export function duration(value, platform) {
  if (value === undefined) return {};
  if (platform === 'win32') throw new Error('held input is unavailable on Windows');
  if (!Number.isSafeInteger(value) || value < 0 || value > 30_000) throw new TypeError('durationMs must be an integer from 0 to 30000');
  return { duration_ms: value };
}

export function imageBytes(value) {
  if (!value) return undefined;
  const data = value.dataBase64 ?? value.data;
  if (typeof data !== 'string') throw new Error('host did not provide authorized screenshot bytes');
  return Uint8Array.from(Buffer.from(data, 'base64'));
}

export function serializable(value) {
  if (Object.prototype.toString.call(value) === '[object Date]') return value.toISOString();
  if (typeof value === 'function') return { function: value.toString() };
  if (Object.prototype.toString.call(value) === '[object RegExp]') return { regex: value.source, flags: value.flags };
  if (Array.isArray(value)) return value.map(serializable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, serializable(item)]));
  return value;
}
