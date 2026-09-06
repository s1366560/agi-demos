import { RuntimeV2Error } from './errors';
import {
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RegisteredRendererContributionV2,
  type RendererContributionSetValidatorV2,
  type RendererContributionTargetV2,
} from './rendererContributions';
import type { CandidateReadinessV2, RuntimeGenerationV2 } from './runtime';
import { DESKTOP_RENDERER_HOST_SERVICE_V2, WEB_RENDERER_HOST_SERVICE_V2 } from './targetModules';

/**
 * Check declared, unisolated root renderer services before local publication.
 * Other scopes retain their own service contracts and consumer requirements.
 */
export function createRendererCandidateReadinessV2(
  target: RendererContributionTargetV2,
  validateContributions?: RendererContributionSetValidatorV2
): CandidateReadinessV2 {
  return (generation) => {
    const declaredServices = declaredRootServices(generation);
    const hostService =
      target === 'web' ? WEB_RENDERER_HOST_SERVICE_V2 : DESKTOP_RENDERER_HOST_SERVICE_V2;
    const registryService =
      target === 'web'
        ? WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2
        : DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2;
    const strategy =
      target === 'web' ? 'generation-renderer-host' : 'native-generation-renderer-host';
    if (declaredServices.has(hostService)) {
      const host = generation.resolve<unknown>(hostService, { kind: 'root' }, { version: '1.0.0' });
      if (!isRecord(host) || host.target !== target || host.strategy !== strategy) {
        throw new RuntimeV2Error(
          'renderer_host_not_ready',
          `renderer host protocol is invalid for ${target}`
        );
      }
    }
    // Independent registry removal is valid; a declared provider must still
    // resolve successfully even when its apply omitted the promised service.
    if (!declaredServices.has(registryService)) return;
    const registry = generation.resolve<unknown>(
      registryService,
      { kind: 'root' },
      { version: '1.0.0' }
    );
    if (
      !isRecord(registry) ||
      registry.target !== target ||
      typeof registry.list !== 'function' ||
      typeof registry.register !== 'function'
    ) {
      throw new RuntimeV2Error(
        'renderer_registry_not_ready',
        `renderer registry protocol is invalid for ${target}`
      );
    }
    const contributions: unknown = registry.list();
    if (!Array.isArray(contributions) || !contributions.every(isContribution)) {
      throw new RuntimeV2Error(
        'renderer_contributions_not_ready',
        `renderer contribution list is invalid for ${target}`
      );
    }
    validateContributions?.(contributions);
  };
}

function declaredRootServices(generation: RuntimeGenerationV2): ReadonlySet<string> {
  const services = new Set<string>();
  for (const { entry } of generation.fibers) {
    if (entry.scope.kind !== 'root') continue;
    const manifest = generation.snapshot.manifests.find(
      (candidate) => candidate.plugin_id === entry.plugin_ref
    );
    const module = manifest?.modules.find((candidate) => candidate.module_ref === entry.module_ref);
    for (const provision of module?.contract.services.provides ?? []) {
      if (entry.isolate[provision.service] === undefined) services.add(provision.service);
    }
  }
  return services;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isContribution(value: unknown): value is RegisteredRendererContributionV2 {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.sourceEntryId === 'string' &&
    (value.kind === 'route' || value.kind === 'navigation' || value.kind === 'ui-slot') &&
    typeof value.order === 'number' &&
    Number.isFinite(value.order) &&
    isRecord(value.payload) &&
    !Array.isArray(value.payload)
  );
}
