const DEFAULT_DB_NAME = "agistack-core";
const DEFAULT_STORE_NAME = "snapshots";
const DEFAULT_KEY = "default";
const DEFAULT_DB_VERSION = 1;
const SNAPSHOT_VERSION = 1;

export function openIndexedDbSnapshotStore(options = {}) {
  const {
    dbName = DEFAULT_DB_NAME,
    storeName = DEFAULT_STORE_NAME,
    key = DEFAULT_KEY,
    dbVersion = DEFAULT_DB_VERSION,
    indexedDB: indexedDb = globalThis.indexedDB,
  } = options;

  if (!indexedDb) {
    throw new Error("IndexedDB is unavailable in this JS host");
  }

  const dbPromise = openDatabase(indexedDb, dbName, dbVersion, storeName);

  return {
    async load() {
      const db = await dbPromise;
      return readSnapshot(db, storeName, key);
    },

    async save(snapshotJson) {
      const version = validateSnapshotJson(snapshotJson);
      const db = await dbPromise;
      await writeSnapshot(db, storeName, {
        id: key,
        version,
        snapshotJson,
        updatedAt: new Date().toISOString(),
      });
      return snapshotJson;
    },

    async clear() {
      const db = await dbPromise;
      await deleteSnapshot(db, storeName, key);
    },

    async close() {
      const db = await dbPromise;
      db.close();
    },
  };
}

export function createMemorySnapshotStore(initialSnapshotJson = null) {
  let snapshotJson = initialSnapshotJson;
  if (snapshotJson !== null) {
    validateSnapshotJson(snapshotJson);
  }

  return {
    async load() {
      return snapshotJson;
    },

    async save(nextSnapshotJson) {
      validateSnapshotJson(nextSnapshotJson);
      snapshotJson = nextSnapshotJson;
      return snapshotJson;
    },

    async clear() {
      snapshotJson = null;
    },
  };
}

export async function saveCoreSnapshot(core, store) {
  if (!core || typeof core.exportSnapshot !== "function") {
    throw new TypeError("core must expose exportSnapshot()");
  }
  if (!store || typeof store.save !== "function") {
    throw new TypeError("store must expose save(snapshotJson)");
  }

  const snapshotJson = core.exportSnapshot();
  await store.save(snapshotJson);
  return snapshotJson;
}

export async function restoreCoreSnapshot(core, store) {
  if (!core || typeof core.importSnapshot !== "function") {
    throw new TypeError("core must expose importSnapshot(snapshotJson)");
  }
  if (!store || typeof store.load !== "function") {
    throw new TypeError("store must expose load()");
  }

  const snapshotJson = await store.load();
  if (snapshotJson === null || snapshotJson === undefined) {
    return false;
  }
  validateSnapshotJson(snapshotJson);
  await core.importSnapshot(snapshotJson);
  return true;
}

export async function createPersistentAgistackCore(AgistackCore, store, options = {}) {
  if (typeof AgistackCore !== "function") {
    throw new TypeError("AgistackCore must be a constructor");
  }
  const snapshotStore = store ?? openIndexedDbSnapshotStore();
  const autosave = options.autosave !== false;
  const core = new AgistackCore();
  const restored = await restoreCoreSnapshot(core, snapshotStore);

  async function save() {
    return saveCoreSnapshot(core, snapshotStore);
  }

  return {
    core,
    restored,

    async ingest(projectId, authorId, content) {
      const result = await core.ingest(projectId, authorId, content);
      if (autosave) {
        await save();
      }
      return result;
    },

    search(projectId, query, limit) {
      return core.search(projectId, query, limit);
    },

    semanticSearch(projectId, query, limit) {
      return core.semanticSearch(projectId, query, limit);
    },

    exportSnapshot() {
      return core.exportSnapshot();
    },

    async importSnapshot(snapshotJson) {
      validateSnapshotJson(snapshotJson);
      await core.importSnapshot(snapshotJson);
      if (autosave) {
        await snapshotStore.save(snapshotJson);
      }
    },

    save,

    clearSnapshot() {
      return snapshotStore.clear();
    },
  };
}

function validateSnapshotJson(snapshotJson) {
  if (typeof snapshotJson !== "string") {
    throw new TypeError("snapshotJson must be a JSON string");
  }

  const snapshot = JSON.parse(snapshotJson);
  if (snapshot.version !== SNAPSHOT_VERSION) {
    throw new Error(`unsupported WASM snapshot version: ${snapshot.version}`);
  }
  if (!Array.isArray(snapshot.memories)) {
    throw new Error("WASM snapshot must contain a memories array");
  }
  return snapshot.version;
}

function openDatabase(indexedDb, dbName, dbVersion, storeName) {
  return new Promise((resolve, reject) => {
    const request =
      dbVersion === undefined ? indexedDb.open(dbName) : indexedDb.open(dbName, dbVersion);

    request.onupgradeneeded = () => {
      ensureStore(request.result, storeName);
    };

    request.onerror = () => {
      if (request.error?.name === "VersionError" && dbVersion !== undefined) {
        openDatabase(indexedDb, dbName, undefined, storeName).then(resolve, reject);
        return;
      }
      reject(request.error);
    };
    request.onsuccess = () => {
      const db = request.result;
      if (db.objectStoreNames.contains(storeName)) {
        resolve(db);
        return;
      }

      const nextVersion = db.version + 1;
      db.close();
      openDatabase(indexedDb, dbName, nextVersion, storeName).then(resolve, reject);
    };
  });
}

function ensureStore(db, storeName) {
  if (!db.objectStoreNames.contains(storeName)) {
    db.createObjectStore(storeName, { keyPath: "id" });
  }
}

async function readSnapshot(db, storeName, key) {
  const transaction = db.transaction(storeName, "readonly");
  const record = await idbRequest(transaction.objectStore(storeName).get(key));
  await transactionDone(transaction);
  return record?.snapshotJson ?? null;
}

async function writeSnapshot(db, storeName, record) {
  const transaction = db.transaction(storeName, "readwrite");
  await idbRequest(transaction.objectStore(storeName).put(record));
  await transactionDone(transaction);
}

async function deleteSnapshot(db, storeName, key) {
  const transaction = db.transaction(storeName, "readwrite");
  await idbRequest(transaction.objectStore(storeName).delete(key));
  await transactionDone(transaction);
}

function idbRequest(request) {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.onabort = () => reject(transaction.error);
    transaction.onerror = () => reject(transaction.error);
    transaction.oncomplete = () => resolve();
  });
}
