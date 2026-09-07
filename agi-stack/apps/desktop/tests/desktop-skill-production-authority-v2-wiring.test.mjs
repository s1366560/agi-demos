import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const methods = [
  'listManagedSkills', 'createManagedSkill', 'getManagedSkillContent',
  'updateManagedSkill', 'updateManagedSkillContent', 'setManagedSkillStatus',
  'deleteManagedSkill', 'importManagedSkillPackage', 'importManagedSkillZip',
  'listManagedSkillVersions', 'rollbackManagedSkill', 'exportManagedSkillPackage',
  'getManagedSkillVersion', 'getManagedSkillEvolution', 'runManagedSkillEvolution',
];

function find(node, predicate) {
  if (predicate(node)) return node;
  return ts.forEachChild(node, (child) => find(child, predicate));
}

function saveHarness() {
  const text = source('features/settings/useSkillManagement.ts');
  const tree = ts.createSourceFile('hook.ts', text, ts.ScriptTarget.Latest, true);
  const declaration = find(tree, (node) => ts.isVariableDeclaration(node)
    && node.name.getText(tree) === 'save');
  const callback = declaration.initializer.arguments[0];
  const code = ts.transpileModule(`return ${callback.getText(tree)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const calls = [];
  const contextKeyRef = { current: 'tenant-a/project-one' };
  const bindings = {
    dialog: { key: 'edit-one', skill: { id: 'skill-one', revision: 7 },
      loading: false, contentReady: true },
    contextKey: contextKeyRef.current, contextKeyRef,
    client: {
      async updateManagedSkill(...args) {
        calls.push(['metadata', ...args]);
        return { id: 'skill-one', revision: 8 };
      },
      async updateManagedSkillContent(...args) {
        calls.push(['content', ...args]);
        return { id: 'skill-one', revision: 9 };
      },
    },
    setBusy: () => {}, setError: (value) => { if (value) throw new Error(value); },
    setDialog: () => {}, onReload: async () => calls.push(['reload']),
    onSaved: (id) => calls.push(['saved', id]),
    errorMessage: (error) => error.message,
  };
  return { calls, bindings, run: new Function(...Object.keys(bindings), code)(...Object.values(bindings)) };
}

test('Skill metadata and content writes preserve the returned optimistic revision', async () => {
  const harness = saveHarness();
  await harness.run({ description: 'updated', full_content: '# Updated skill' });
  assert.deepEqual(harness.calls, [
    ['metadata', 'skill-one', { description: 'updated' }, 7],
    ['content', 'skill-one', '# Updated skill', 8],
    ['reload'], ['saved', 'skill-one'],
  ]);
});

test('all fifteen static Skill APIs and the legacy resource HTTP client are retired', () => {
  const text = source('api/client.ts');
  const tree = ts.createSourceFile('client.ts', text, ts.ScriptTarget.Latest, true);
  for (const method of methods) {
    assert.equal(Boolean(find(tree, (node) => ts.isMethodDeclaration(node)
      && node.name.getText(tree) === method)), false, method);
  }
  assert.equal(existsSync(new URL('../src/api/managedResourcesClient.ts', import.meta.url)), false);
  for (const path of ['features/settings/SettingsWindow.tsx',
    'features/settings/useSkillManagement.ts', 'features/settings/useSkillPackageManagement.ts',
    'features/settings-routes/skillsRouteClient.ts']) {
    assert.doesNotMatch(source(path), /new ManagedResourcesClient|api\/managedResourcesClient/u);
  }
});
