import { describe, expect, it } from 'vitest';
import { parsePluginManifestV2 } from '../../../../agi-stack/packages/plugin-runtime/src/contract';
import bootstrap from '../../../../shared/profiles/memstack-default-bootstrap.v2.json';

function manifestWithFlag(flag: unknown, present = true) {
  const manifest = structuredClone(bootstrap.manifests[0]!);
  const module = manifest.modules.find((item) => item.contract.services.requires.length > 0)!;
  const requirement = module.contract.services.requires[0]! as Record<string, unknown>;
  if (present) requirement.contributes = flag;
  else delete requirement.contributes;
  return { manifest, moduleRef: module.module_ref };
}

describe('service contribution declaration', () => {
  it.each([true, false, undefined])('preserves optional boolean %s', (flag) => {
    const { manifest, moduleRef } = manifestWithFlag(flag, flag !== undefined);
    const parsed = parsePluginManifestV2(manifest, 0);
    const requirement = parsed.modules.find((item) => item.module_ref === moduleRef)!
      .contract.services.requires[0]!;
    expect(requirement.contributes).toBe(flag);
    expect(Object.hasOwn(requirement, 'contributes')).toBe(flag !== undefined);
  });
  it.each([null, 'true', 1, {}, []])('rejects non-boolean %s', (flag) => {
    const { manifest } = manifestWithFlag(flag);
    expect(() => parsePluginManifestV2(manifest, 0)).toThrow('must be boolean');
  });
});
