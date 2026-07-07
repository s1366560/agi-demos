// Node smoke test for the WASM web binding: proves the *same* portable core runs
// in a JS runtime (core-as-guest) with a real round-trip — ingest, then keyword
// and semantic search — using the wasm-pack `nodejs` package. Run:
//   wasm-pack build crates/bindings-wasm --release --target nodejs --out-dir pkg
//   node crates/bindings-wasm/smoke.cjs
const assert = require("node:assert");
const { AgistackCore } = require("./pkg/agistack_bindings_wasm.js");
const wasmPackage = require("./pkg/package.json");

async function main() {
  const {
    createMemorySnapshotStore,
    createPersistentAgistackCore,
    openIndexedDbSnapshotStore,
    restoreCoreSnapshot,
    saveCoreSnapshot,
  } = await import("./web-persistence.mjs");
  assert.ok(
    wasmPackage.files.includes("web-persistence.mjs"),
    "published WASM package includes host persistence helper"
  );
  const core = new AgistackCore();
  const project = "p1";

  // Ingest two episodes; each returns the created Memory as JSON.
  const m1 = JSON.parse(
    await core.ingest(project, "u1", "Local-first apps store data on device using sqlite")
  );
  assert.ok(m1.id, "ingest returns a memory with an id");
  assert.ok(Array.isArray(m1.embedding) && m1.embedding.length === 32, "32-dim embedding");
  await core.ingest(project, "u1", "A recipe for garlic bread with butter and herbs");

  // Keyword search hits the sqlite memory, misses the unrelated term.
  const hits = JSON.parse(await core.search(project, "sqlite", 10));
  assert.strictEqual(hits.length, 1, "keyword search finds exactly one match");
  const miss = JSON.parse(await core.search(project, "postgres", 10));
  assert.strictEqual(miss.length, 0, "keyword search misses unrelated term");

  // Semantic search over the in-memory vector index returns ranked results.
  const sem = JSON.parse(await core.semanticSearch(project, "on-device storage", 2));
  assert.ok(sem.length >= 1, "semantic search returns at least one hit");

  // The browser shell can persist this JSON in IndexedDB and restore it after
  // reload without changing the runtime-agnostic Rust core.
  const snapshot = JSON.parse(core.exportSnapshot());
  assert.strictEqual(snapshot.version, 1, "snapshot version is stable");
  assert.strictEqual(snapshot.memories.length, 2, "snapshot carries all memories");

  const restored = new AgistackCore();
  await restored.importSnapshot(JSON.stringify(snapshot));
  const restoredHits = JSON.parse(await restored.search(project, "sqlite", 10));
  assert.strictEqual(restoredHits.length, 1, "restored snapshot preserves keyword search");
  const restoredSem = JSON.parse(await restored.semanticSearch(project, "on-device storage", 2));
  assert.ok(restoredSem.length >= 1, "restored snapshot rebuilds semantic index");

  const memoryStore = createMemorySnapshotStore();
  await saveCoreSnapshot(core, memoryStore);
  const restoredFromStore = new AgistackCore();
  assert.strictEqual(
    await restoreCoreSnapshot(restoredFromStore, memoryStore),
    true,
    "host store restores an existing snapshot"
  );
  const storeHits = JSON.parse(await restoredFromStore.search(project, "sqlite", 10));
  assert.strictEqual(storeHits.length, 1, "host store preserves keyword search");

  const indexedDbStore = openIndexedDbSnapshotStore({ indexedDB: createFakeIndexedDB() });
  await saveCoreSnapshot(core, indexedDbStore);
  const restoredFromIndexedDb = new AgistackCore();
  assert.strictEqual(
    await restoreCoreSnapshot(restoredFromIndexedDb, indexedDbStore),
    true,
    "IndexedDB host store restores an existing snapshot"
  );
  const indexedDbHits = JSON.parse(await restoredFromIndexedDb.search(project, "sqlite", 10));
  assert.strictEqual(indexedDbHits.length, 1, "IndexedDB host store preserves keyword search");
  await indexedDbStore.clear();
  assert.strictEqual(
    await restoreCoreSnapshot(new AgistackCore(), indexedDbStore),
    false,
    "cleared IndexedDB host store reports no restore"
  );
  await indexedDbStore.close();

  const upgradeIndexedDB = createFakeIndexedDB();
  upgradeIndexedDB.seedDatabaseWithoutStores("agistack-upgrade", 1);
  const upgradeStore = openIndexedDbSnapshotStore({
    indexedDB: upgradeIndexedDB,
    dbName: "agistack-upgrade",
  });
  await saveCoreSnapshot(core, upgradeStore);
  assert.strictEqual(
    upgradeIndexedDB.databaseVersion("agistack-upgrade"),
    2,
    "IndexedDB host store upgrades existing databases that are missing the snapshot store"
  );
  const restoredAfterUpgrade = new AgistackCore();
  assert.strictEqual(
    await restoreCoreSnapshot(restoredAfterUpgrade, upgradeStore),
    true,
    "upgraded IndexedDB host store restores the saved snapshot"
  );
  const upgradedHits = JSON.parse(await restoredAfterUpgrade.search(project, "sqlite", 10));
  assert.strictEqual(upgradedHits.length, 1, "upgraded IndexedDB store preserves keyword search");
  await upgradeStore.close();

  const offlineStore = openIndexedDbSnapshotStore({
    indexedDB: createFailingIndexedDB(new Error("offline IndexedDB unavailable")),
  });
  await assert.rejects(
    () => offlineStore.load(),
    /offline IndexedDB unavailable/,
    "IndexedDB host store propagates open failures for offline/error states"
  );

  const emptyStore = createMemorySnapshotStore();
  const emptyCore = new AgistackCore();
  assert.strictEqual(
    await restoreCoreSnapshot(emptyCore, emptyStore),
    false,
    "empty host store reports no restore"
  );

  const persisted = await createPersistentAgistackCore(AgistackCore, createMemorySnapshotStore());
  assert.strictEqual(persisted.restored, false, "new persistent core starts without a snapshot");
  await persisted.ingest(project, "u1", "Durable browser state writes through a host snapshot store");
  const persistedHits = JSON.parse(await persisted.search(project, "durable", 10));
  assert.strictEqual(persistedHits.length, 1, "persistent core delegates search to WASM core");

  console.log(
    "SMOKE_OK",
    JSON.stringify({
      keyword: hits.length,
      semantic: sem.length,
      restoredKeyword: restoredHits.length,
      restoredSemantic: restoredSem.length,
      hostStoreKeyword: storeHits.length,
      indexedDbKeyword: indexedDbHits.length,
      upgradedIndexedDbKeyword: upgradedHits.length,
      persistentKeyword: persistedHits.length,
    })
  );
}

function createFakeIndexedDB() {
  const databases = new Map();

  return {
    seedDatabaseWithoutStores(name, version) {
      databases.set(name, { version, stores: new Map() });
    },

    databaseVersion(name) {
      return databases.get(name)?.version ?? null;
    },

    open(name, version) {
      const request = {};
      queueMicrotask(() => {
        let database = databases.get(name);
        const needsUpgrade = !database || version > database.version;
        if (!database) {
          database = { version, stores: new Map() };
          databases.set(name, database);
        }
        if (needsUpgrade) {
          database.version = version;
        }

        request.result = createFakeDatabase(database);
        if (needsUpgrade) {
          request.onupgradeneeded?.();
        }
        request.onsuccess?.();
      });
      return request;
    },
  };
}

function createFailingIndexedDB(error) {
  return {
    open() {
      const request = { error };
      queueMicrotask(() => {
        request.onerror?.();
      });
      return request;
    },
  };
}

function createFakeDatabase(database) {
  return {
    get version() {
      return database.version;
    },

    objectStoreNames: {
      contains(name) {
        return database.stores.has(name);
      },
    },

    createObjectStore(name) {
      if (!database.stores.has(name)) {
        database.stores.set(name, new Map());
      }
      return createFakeObjectStore(database.stores.get(name), null);
    },

    transaction(storeName) {
      const transaction = {
        objectStore(name) {
          assert.strictEqual(name, storeName, "fake IndexedDB only opens one store per transaction");
          const store = database.stores.get(name);
          if (!store) {
            throw new Error(`missing fake IndexedDB store: ${name}`);
          }
          return createFakeObjectStore(store, transaction);
        },
      };
      return transaction;
    },

    close() {},
  };
}

function createFakeObjectStore(store, transaction) {
  return {
    get(key) {
      return finishFakeRequest(transaction, cloneJson(store.get(key)));
    },

    put(record) {
      store.set(record.id, cloneJson(record));
      return finishFakeRequest(transaction, record.id);
    },

    delete(key) {
      store.delete(key);
      return finishFakeRequest(transaction, undefined);
    },
  };
}

function finishFakeRequest(transaction, result) {
  const request = {};
  queueMicrotask(() => {
    request.result = result;
    request.onsuccess?.();
    queueMicrotask(() => transaction?.oncomplete?.());
  });
  return request;
}

function cloneJson(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

main().catch((e) => {
  console.error("SMOKE_FAIL", e);
  process.exit(1);
});
