import { describe, expect, it, vi } from 'vitest';
import {
  createWebRendererDefinitionsV2,
  digestV2,
  RendererPluginRuntimeV2,
} from '@agistack/plugin-runtime';
import {
  parseWebPublicViewV2,
  WebPublicViewReconcilerV2,
} from '../../../../agi-stack/packages/plugin-runtime/src/webPublicView';
import bootstrap from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';
async function view(generation = 1) {
  const refs = new Set(createWebRendererDefinitionsV2().map((definition) => definition.moduleRef));
  const snapshot = structuredClone(bootstrap);
  snapshot.profile_id = 'web-public-view-v2';
  snapshot.generation = generation;
  snapshot.entries = snapshot.entries.filter((entry) => refs.has(entry.module_ref));
  snapshot.manifests = snapshot.manifests
    .map((manifest) => ({
      ...manifest,
      modules: manifest.modules.filter((module) => refs.has(module.module_ref)),
    }))
    .filter((manifest) => manifest.modules.length > 0);
  await redigest(snapshot);
  return { schema_version: 2, target: 'web', view_id: `public-${generation}`, snapshot };
}
async function redigest(snapshot: typeof bootstrap) {
  const { digest: _digest, ...unsigned } = snapshot;
  snapshot.digest = await digestV2(unsigned);
}
function setup() {
  const runtime = new RendererPluginRuntimeV2('web', createWebRendererDefinitionsV2());
  return { runtime, reconciler: new WebPublicViewReconcilerV2(runtime) };
}
describe('Web public view', () => {
  it('applies six real Web entries as a baseline without workload ACK', async () => {
    const { runtime, reconciler } = setup();
    const payload = await view();
    expect(payload.snapshot.entries).toHaveLength(6);
    const workloadApply = vi.spyOn(runtime, 'apply');
    expect(await reconciler.apply(payload)).toBeUndefined();
    expect(runtime.getSnapshot()?.snapshot.digest).toBe(payload.snapshot.digest);
    expect(workloadApply).not.toHaveBeenCalled();
    await reconciler.close();
  });
  it.each(['envelope', 'nonce', 'extra'])('rejects wrapper %s', async (field) => {
    await expect(
      parseWebPublicViewV2({ ...(await view()), [field]: 'not-public' })
    ).rejects.toMatchObject({ code: 'web_public_view_invalid' });
  });
  it('rejects tampering and correctly digested foreign modules or tenant entries', async () => {
    const tampered = await view();
    tampered.snapshot.generation += 1;
    await expect(parseWebPublicViewV2(tampered)).rejects.toMatchObject({ code: 'digest_mismatch' });
    const foreign = await view();
    foreign.snapshot.manifests.push(
      structuredClone(
        bootstrap.manifests.find((item) =>
          item.modules.some((module) => !module.targets.includes('web'))
        )!
      )
    );
    await redigest(foreign.snapshot);
    await expect(parseWebPublicViewV2(foreign)).rejects.toBeDefined();
    const scoped = await view();
    scoped.snapshot.entries[0]!.scope = {
      kind: 'tenant',
      tenant_id: 'other',
    } as (typeof scoped.snapshot.entries)[number]['scope'];
    await redigest(scoped.snapshot);
    await expect(parseWebPublicViewV2(scoped)).rejects.toBeDefined();
  });
  it('retains the old generation after real duplicate contribution rejection', async () => {
    const { runtime, reconciler } = setup();
    await reconciler.apply(await view());
    const previous = runtime.getSnapshot();
    const bad = await view(2);
    const contribution = bad.snapshot.entries.find(
      (entry) => entry.module_ref === 'builtin://memstack/web/renderer-contribution'
    )!;
    bad.snapshot.entries.push({
      ...structuredClone(contribution),
      entry_id: 'duplicate-public-contribution',
    });
    await redigest(bad.snapshot);
    await expect(reconciler.apply(bad)).rejects.toBeDefined();
    expect(runtime.getSnapshot()).toBe(previous);
    await reconciler.close();
  });
  it('skips unchanged views and re-applies a changed identity', async () => {
    const { runtime, reconciler } = setup();
    const payload = await view();
    await reconciler.apply(payload);
    const first = runtime.getSnapshot();
    await reconciler.apply(payload);
    expect(runtime.getSnapshot()).toBe(first);
    await reconciler.apply({ ...payload, view_id: 'changed-authority' });
    expect(runtime.getSnapshot()).not.toBe(first);
    await reconciler.close();
  });
  it('serializes apply and close and reopens after retirement', async () => {
    const { runtime, reconciler } = setup();
    const first = await view();
    const second = await view(2);
    const applying = reconciler.apply(first);
    const next = reconciler.apply(second);
    const closing = reconciler.close();
    expect(reconciler.close()).toBe(closing);
    await Promise.all([applying, next, closing]);
    expect(runtime.getSnapshot()).toBeUndefined();
    await reconciler.apply(first);
    expect(runtime.getSnapshot()?.snapshot.digest).toBe(first.snapshot.digest);
    await reconciler.close();
  });
});
