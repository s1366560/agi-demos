import type { CurrentUser, DesktopRuntimeConfig } from '../../types';
import { createChannelsRouteClient } from './channelsRouteClient';
import { createChannelsRouteController } from './channelsRouteController';
import type {
  ChannelsRouteBinding,
  ChannelsRouteContext,
} from './channelsRouteModule';
import { createEvolutionRouteClient } from './evolutionRouteClient';
import { createEvolutionRouteController } from './evolutionRouteController';
import type {
  EvolutionRouteBinding,
  EvolutionRouteContext,
} from './evolutionRouteModule';
import { createProfileRouteClient } from './profileRouteClient';
import { createProfileRouteController } from './profileRouteController';
import type { ProfileRouteBinding } from './profileRouteModule';
import { createTemplatesRouteClient } from './templatesRouteClient';
import { createTemplatesRouteController } from './templatesRouteController';
import type {
  TemplatesRouteBinding,
  TemplatesRouteContext,
} from './templatesRouteModule';

export function createEvolutionRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: EvolutionRouteContext,
): EvolutionRouteBinding {
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  return Object.freeze({
    controller: createEvolutionRouteController({
      client: createEvolutionRouteClient(config),
      initialScope: scope,
    }),
    scope,
  });
}

export function createChannelsRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: ChannelsRouteContext,
): ChannelsRouteBinding {
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
    projectId: context.projectId,
  });
  return Object.freeze({
    controller: createChannelsRouteController({
      client: createChannelsRouteClient(config),
      initialScope: scope,
    }),
    scope,
  });
}

export function createTemplatesRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  context: TemplatesRouteContext,
): TemplatesRouteBinding {
  const scope = Object.freeze({
    authority: config.mode,
    tenantId: context.tenantId,
  });
  return Object.freeze({
    controller: createTemplatesRouteController({
      client: createTemplatesRouteClient(config),
      initialScope: scope,
    }),
    scope,
  });
}

export function createProfileRouteBindingForRuntime(
  config: DesktopRuntimeConfig,
  onUserObserved?: (user: CurrentUser) => void,
): ProfileRouteBinding {
  const scope = Object.freeze({ authority: config.mode });
  const source = createProfileRouteClient(config);
  const client = Object.freeze({
    ...source,
    async observe(currentScope: typeof scope, signal?: AbortSignal) {
      const observation = await source.observe(currentScope, signal);
      onUserObserved?.(observation.user);
      return observation;
    },
    async update(
      currentScope: typeof scope,
      input: Parameters<typeof source.update>[1],
      signal?: AbortSignal,
    ) {
      const user = await source.update(currentScope, input, signal);
      onUserObserved?.(user);
      return user;
    },
  });
  return Object.freeze({
    controller: createProfileRouteController({
      client,
      initialScope: scope,
    }),
    scope,
  });
}
