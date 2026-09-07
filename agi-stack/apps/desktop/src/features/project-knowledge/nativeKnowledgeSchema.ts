/** Structural wire validators only; user decisions stay explicit command fields. */
export type NativeCheck = (value: unknown) => boolean;
export type NativeShape = Readonly<Record<string, NativeCheck>>;
export const plain: NativeCheck = (v) =>
  v !== null &&
  typeof v === 'object' &&
  (Object.getPrototypeOf(v) === Object.prototype || Object.getPrototypeOf(v) === null);
export const text: NativeCheck = (v) => typeof v === 'string';
export const identifier: NativeCheck = (v) =>
  typeof v === 'string' && v.length > 0 && v === v.trim() && [...v].length <= 512;
export const uuid: NativeCheck = (v) =>
  typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
export const bool: NativeCheck = (v) => typeof v === 'boolean';
export const integer =
  (min = 0, max = Number.MAX_SAFE_INTEGER): NativeCheck =>
  (v) =>
    typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max;
export const sequence = integer(1);
export const localRevision = integer(1, 4_294_967_295);
export const remoteRevision = integer(0, 2_147_483_647);
export const literal =
  (...allowed: readonly unknown[]): NativeCheck =>
  (v) =>
    allowed.includes(v);
export const nullable =
  (check: NativeCheck): NativeCheck =>
  (v) =>
    v === null || check(v);
export const array =
  (check: NativeCheck, max = Number.MAX_SAFE_INTEGER): NativeCheck =>
  (v) =>
    Array.isArray(v) && v.length <= max && v.every((item) => check(item));
export const object =
  (required: NativeShape, optional: NativeShape = {}, extensions = false): NativeCheck =>
  (v) => {
    if (!plain(v)) return false;
    const value = v as Record<string, unknown>;
    return (
      Object.entries(required).every(
        ([key, check]) => Object.hasOwn(value, key) && check(value[key]),
      ) &&
      Object.entries(optional).every(
        ([key, check]) => !Object.hasOwn(value, key) || check(value[key]),
      ) &&
      (extensions ||
        Object.keys(value).every(
          (key) => Object.hasOwn(required, key) || Object.hasOwn(optional, key),
        ))
    );
  };
export const sequenceList: NativeCheck = (v) =>
  array(sequence, 10_000)(v) && new Set(v as number[]).size === (v as number[]).length;
export const sortedSequences: NativeCheck = (v) =>
  sequenceList(v) && (v as number[]).every((n, i, values) => i === 0 || n > values[i - 1]!);
export const idempotencyKey: NativeCheck = (v) =>
  identifier(v) && typeof v === 'string' && v.length <= 512 && !/[^\x20-\x7e]/.test(v);

export function jsonValue(value: unknown, ancestors = new Set<object>(), depth = 0): boolean {
  if (depth > 64) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if ((!plain(value) && !Array.isArray(value)) || ancestors.has(value as object)) return false;
  ancestors.add(value as object);
  const valid = Object.values(value as object).every((nested) =>
    jsonValue(nested, ancestors, depth + 1),
  );
  ancestors.delete(value as object);
  return valid;
}
export const jsonObject: NativeCheck = (v) => plain(v) && jsonValue(v);
export function frozenClone<T>(value: T): T {
  const copy = structuredClone(value);
  const freeze = (nested: unknown): void => {
    if (nested !== null && typeof nested === 'object' && !Object.isFrozen(nested)) {
      Object.freeze(nested);
      Object.values(nested).forEach(freeze);
    }
  };
  freeze(copy);
  return copy;
}
