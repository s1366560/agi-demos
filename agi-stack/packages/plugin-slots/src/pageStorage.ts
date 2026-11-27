// Small state a signed page keeps between its loads, in the storage of the host workbench.
// A page reaches it as its own localStorage; nothing of another release, tenant or
// project does, and the guest script keeps the same bounds.
export const PAGE_STORAGE_KEY = /^[^\u0000-\u001f\u007f]{1,256}$/;
export const PAGE_STORAGE_VALUE_UNITS = 1_048_576;
export const PAGE_STORAGE_TOTAL_UNITS = 4_194_304;

export interface PageStorage {
  /** Everything the page stored, to hand to the page as it loads. */
  snapshot(): Record<string, string>;
  read(key: string): string | null;
  write(key: string, value: string): void;
  remove(key: string): void;
  clear(): void;
}

const OWNER = "memstack.page:";

/** The storage of the workbench document, when the document may use one. */
export function windowPageStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function createPageStorage(
  area: Storage | undefined,
  owner: string,
): PageStorage | undefined {
  if (!area) return undefined;
  const scope = OWNER + owner + ":";
  const entries = () => {
    const rows: [string, string][] = [];
    for (let index = 0; index < area.length; index++) {
      const full = area.key(index);
      if (full?.startsWith(scope)) {
        const value = area.getItem(full);
        if (value !== null) rows.push([full.slice(scope.length), value]);
      }
    }
    return rows;
  };
  return {
    snapshot: () => Object.fromEntries(entries()),
    read: (key) => area.getItem(scope + key),
    write(key, value) {
      if (
        !PAGE_STORAGE_KEY.test(key) ||
        value.length > PAGE_STORAGE_VALUE_UNITS
      )
        throw new Error("page_request_invalid");
      const others = entries().reduce(
        (sum, [name, text]) => sum + (name === key ? 0 : text.length),
        0,
      );
      if (others + value.length > PAGE_STORAGE_TOTAL_UNITS)
        throw new Error("page_storage_quota");
      area.setItem(scope + key, value);
    },
    remove: (key) => {
      if (PAGE_STORAGE_KEY.test(key)) area.removeItem(scope + key);
    },
    clear() {
      for (const [name] of entries()) area.removeItem(scope + name);
    },
  };
}
