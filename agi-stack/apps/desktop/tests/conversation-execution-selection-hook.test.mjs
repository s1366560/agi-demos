import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { test } from "node:test";
const require = createRequire(import.meta.url),
  ts = require("typescript");
const tick = () => new Promise(setImmediate);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
function harness(api, conversation) {
  let cursor = 0,
    effects = [],
    items = [],
    value;
  const slots = [];
  const equal = (a, b) =>
    a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useRef(v) {
      return (slots[cursor++] ??= { current: v });
    },
    useState(v) {
      const i = cursor++;
      slots[i] ??= { value: v };
      return [
        slots[i].value,
        (n) => {
          slots[i].value = typeof n === "function" ? n(slots[i].value) : n;
        },
      ];
    },
    useCallback(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn };
      return slots[i].value;
    },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, cleanup: fn() };
        });
    },
  };
  const cache = new Map();
  function load(path) {
    if (cache.has(path)) return cache.get(path);
    const module = { exports: {} };
    cache.set(path, module.exports);
    const code = ts.transpileModule(readFileSync(path, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText;
    new Function("require", "module", "exports", code)(
      (name) =>
        name === "react" ? react : load(resolve(dirname(path), `${name}.ts`)),
      module,
      module.exports,
    );
    return module.exports;
  }
  const model = load(
    new URL(
      "../src/features/chat/useConversationExecutionSelection.ts",
      import.meta.url,
    ).pathname,
  );
  const onResolved = (next) => {
    items = model.mergeExecutionSelectionItems(items, next);
  };
  let props = { api, conversation, enabled: true, sending: false, onResolved };
  function render(change = {}) {
    props = { ...props, ...change };
    cursor = 0;
    effects = [];
    value = model.useConversationExecutionSelection(props);
    for (const effect of effects) effect();
    return value;
  }
  return {
    render,
    get value() {
      return value;
    },
    get items() {
      return items;
    },
    async flush() {
      await tick();
      render();
      await tick();
      render();
    },
    dispose() {
      for (const slot of slots) slot?.cleanup?.();
    },
  };
}
const conversation = (id = "one", skill = "saved-skill") => ({
  id,
  tenant_id: "tenant",
  project_id: "project",
  workspace_id: null,
  execution_selection: {
    agent_id: null,
    forced_skill_id: skill,
    subagent_id: null,
  },
});
const catalog = {
  listManagedAgents: async () => [],
  listManagedSkills: async () => [{ id: "saved-skill", name: "Saved skill" }],
  listManagedSubAgents: async () => [],
};
test("authoritative binding reloads; clear waits for success and failure retains the chip", async () => {
  let stored = conversation(),
    pending;
  const updates = [];
  const api = {
    ...catalog,
    readExecutionSelection: async () => stored,
    updateExecutionSelection: async (c, patch) => {
      updates.push(patch);
      pending = deferred();
      return pending.promise;
    },
  };
  const h = harness(api, stored);
  h.render();
  await h.flush();
  assert.equal(h.value.ready, true);
  assert.equal(h.items[0].label, "Saved skill");
  assert.equal(h.items[0].metadata.authoritative_selection, true);
  let clearing = h.value.remove(h.items[0]);
  h.render();
  assert.equal(h.value.pending, true);
  assert.equal(h.items.length, 1);
  pending.reject(new Error("active run"));
  assert.equal(await clearing, false);
  await h.flush();
  assert.equal(h.items.length, 1);
  assert.match(h.value.error, /active run/);
  clearing = h.value.remove(h.items[0]);
  assert.equal(h.items.length, 1);
  stored = conversation("one", null);
  pending.resolve(stored);
  assert.equal(await clearing, true);
  await h.flush();
  assert.equal(h.items.length, 0);
  assert.deepEqual(updates, [
    { forced_skill_id: null },
    { forced_skill_id: null },
  ]);
  h.dispose();
  const restarted = harness(api, stored);
  restarted.render();
  await restarted.flush();
  assert.equal(restarted.items.length, 0);
  assert.equal(restarted.value.ready, true);
  restarted.dispose();
});
test("late read from another conversation cannot replace the active binding", async () => {
  const first = deferred(),
    second = conversation("two", "second-skill");
  const api = {
    ...catalog,
    readExecutionSelection: async (c) =>
      c.id === "one" ? first.promise : second,
  };
  const h = harness(api, conversation());
  h.render();
  h.render({ conversation: second });
  await h.flush();
  assert.equal(h.items[0].resource_id, "second-skill");
  first.resolve(conversation());
  await h.flush();
  assert.equal(h.items[0].resource_id, "second-skill");
  h.dispose();
});
