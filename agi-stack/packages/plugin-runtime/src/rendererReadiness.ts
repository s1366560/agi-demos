import { RuntimeV2Error } from './errors';
import {
  DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
  type RegisteredRendererContributionV2,
  type RendererContributionSetValidatorV2,
  type RendererContributionTargetV2,
} from './rendererContributions';
import type { CandidateReadinessV2 } from './runtime';
import { DESKTOP_RENDERER_HOST_SERVICE_V2, WEB_RENDERER_HOST_SERVICE_V2 } from './targetModules';

/** Check the complete staged renderer service protocol before local publication. */
export function createRendererCandidateReadinessV2(
  target: RendererContributionTargetV2,
  validateContributions?: RendererContributionSetValidatorV2
): CandidateReadinessV2 {
  return (generation) => {
    // Removing every target entry is a valid generation publication.
    if (generation.fibers.length === 0) return;
    const hostService =
      target === 'web' ? WEB_RENDERER_HOST_SERVICE_V2 : DESKTOP_RENDERER_HOST_SERVICE_V2;
    const registryService =
      target === 'web'
        ? WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2
        : DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2;
    const strategy =
      target === 'web' ? 'generation-renderer-host' : 'native-generation-renderer-host';
    const host = generation.resolve<unknown>(hostService, { kind: 'root' }, { version: '1.0.0' });
    if (!isRecord(host) || host.target !== target || host.strategy !== strategy) {
      throw new RuntimeV2Error(
        'renderer_host_not_ready',
        `renderer host protocol is invalid for ${target}`
      );
    }
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
